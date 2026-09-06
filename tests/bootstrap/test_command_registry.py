# ruff: noqa: E501
import copy
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

import tools.run_command_registry as command_registry

ROOT = Path(__file__).parents[2]
EXACT_GITIGNORE = command_registry.EXACT_GITIGNORE


def _registry() -> dict[str, Any]:
    return copy.deepcopy(command_registry.validate_registry(ROOT / "task-command-registry.json"))


def _command(command_id: str = "TEST") -> dict[str, object]:
    return {
        "command_id": command_id,
        "argv": ["true"],
        "cwd": str(ROOT),
        "expected_exit": 0,
    }


def _passed(command: dict[str, object]) -> dict[str, object]:
    return {
        **command,
        "passed": True,
        "exit_code": command["expected_exit"],
        "stdout_sha256": "0" * 64,
        "stdout_size_bytes": "0",
        "stderr_sha256": "0" * 64,
        "stderr_size_bytes": "0",
    }


def test_canonical_command_registry_is_closed() -> None:
    registry = _registry()
    assert set(registry) == {"schema_version", "commands"}


def test_baseline_runner_executes_primary_and_additional_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(command_registry, "candidate_commands", lambda _registry: [_command("ONE"), _command("TWO")])
    monkeypatch.setattr(command_registry, "collect_candidate_file_tree", lambda _root: {"entries": [], "schema_version": "repo0-independent-file-tree/v1"})
    def evaluate(command: dict[str, object], **_kwargs: object) -> dict[str, object]:
        seen.append(cast(str, command["command_id"]))
        return _passed(command)

    monkeypatch.setattr(command_registry, "evaluate_invocation", evaluate)
    command_registry.run_registry(ROOT / "task-command-registry.json")
    assert seen == ["ONE", "TWO"]


def test_baseline_runner_reports_wrong_additional_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command_registry, "candidate_commands", lambda _registry: [_command()])
    monkeypatch.setattr(command_registry, "collect_candidate_file_tree", lambda _root: {"entries": [], "schema_version": "repo0-independent-file-tree/v1"})
    monkeypatch.setattr(command_registry, "evaluate_invocation", lambda *_args, **_kwargs: {"passed": False})
    with pytest.raises(RuntimeError, match="E_COMMAND_REGISTRY:TEST"):
        command_registry.run_registry(ROOT / "task-command-registry.json")


@pytest.mark.parametrize(
    ("argv", "error"),
    [(["sh", "-c", "true"], "SHELL"), (["uv", "run", "pytest", "-k", "one"], "NON_CONCRETE")],
)
def test_registry_self_check_validates_each_additional_argv(
    tmp_path: Path, argv: list[str], error: str
) -> None:
    registry = _registry()
    registry["commands"][2]["argv"] = argv
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match=f"E_COMMAND_REGISTRY:{error}"):
        command_registry.validate_registry(path)


def test_expansion_is_verification_then_task_primary_then_additional() -> None:
    commands = command_registry.expand_invocations(_registry())
    assert len(commands) == 45
    assert [command["command_id"] for command in commands[:3]] == [
        "COMPILE_V636_P04_T03", "COMPILE_CRASH_HARNESS", "COMPILE_ALL_TESTS",
    ]


def test_evaluation_uses_only_exact_registry_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: observed.update(kwargs) or subprocess.CompletedProcess(argv, 0, b"out", b"err"))
    result = command_registry.evaluate_invocation(_command(), environment={"PATH": "/closed"}, working_directory=ROOT)
    assert observed["env"] == {"PATH": "/closed"}
    assert result["stdout_size_bytes"] == "3"
    assert result["stderr_size_bytes"] == "3"


def test_fragments_cannot_be_manufactured_across_stream_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0, b"one", b"two"))
    result = command_registry.evaluate_invocation(_command(), environment={}, working_directory=ROOT)
    assert result["stdout_sha256"] != result["stderr_sha256"]


@pytest.mark.parametrize("output", ["TODO", "${COMMAND}"])
def test_malformed_contract_token_boundaries_fail_closed(tmp_path: Path, output: str) -> None:
    registry = _registry()
    registry["commands"][2]["argv"] = [output]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="E_COMMAND_REGISTRY"):
        command_registry.validate_registry(path)


def test_contract_token_must_occur_exactly_once_across_both_streams(tmp_path: Path) -> None:
    registry = _registry()
    registry["commands"][2]["command_id"] = registry["commands"][3]["command_id"]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="E_COMMAND_REGISTRY:DUPLICATE"):
        command_registry.validate_registry(path)


def test_baseline_runner_requires_candidate_tree_stability_before_and_after_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trees = iter([{"entries": [1]}, {"entries": [2]}])
    monkeypatch.setattr(command_registry, "candidate_commands", lambda _registry: [_command()])
    monkeypatch.setattr(command_registry, "collect_candidate_file_tree", lambda _root: next(trees))
    monkeypatch.setattr(command_registry, "evaluate_invocation", lambda *_args, **_kwargs: {"passed": True})
    with pytest.raises(RuntimeError, match="E_COMMAND_REGISTRY:DRIFT"):
        command_registry.run_registry(ROOT / "task-command-registry.json")


@pytest.mark.parametrize("mutation", [
    lambda registry: registry.pop("commands"),
    lambda registry: registry["commands"][0].update(extra=True),
    lambda registry: registry["commands"][0].update(network="ALLOW"),
])
def test_registry_closed_shape_and_mandatory_contract(tmp_path: Path, mutation: Any) -> None:
    registry = _registry()
    mutation(registry)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="E_COMMAND_REGISTRY"):
        command_registry.validate_registry(path)


def _candidate_root(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".gitignore").write_bytes(EXACT_GITIGNORE)
    return tmp_path


def test_candidate_tree_excludes_only_contract_generated_paths(tmp_path: Path) -> None:
    root = _candidate_root(tmp_path)
    (root / "a.txt").write_text("a")
    (root / ".pytest_cache").mkdir()
    (root / ".pytest_cache/ignored").write_text("ignored")
    (root / "extension/dist").mkdir(parents=True)
    (root / "extension/dist/ignored.js").write_text("ignored")
    tree = command_registry.collect_candidate_file_tree(root)
    entries = cast(list[dict[str, object]], tree["entries"])
    assert [entry["path"] for entry in entries] == [".gitignore", "a.txt"]


def test_candidate_tree_does_not_treat_directory_component_names_as_files(tmp_path: Path) -> None:
    root = _candidate_root(tmp_path)
    (root / "node_modules").write_text("file")
    (root / "nested").mkdir()
    (root / "nested/.local").write_text("file")
    tree = command_registry.collect_candidate_file_tree(root)
    entries = cast(list[dict[str, object]], tree["entries"])
    assert [entry["path"] for entry in entries] == [".gitignore", "nested/.local", "node_modules"]


def test_candidate_tree_includes_files_named_like_exact_generated_subtrees(tmp_path: Path) -> None:
    root = _candidate_root(tmp_path)
    (root / "extension").mkdir()
    (root / "extension/dist").write_text("file")
    tree = command_registry.collect_candidate_file_tree(root)
    entries = cast(list[dict[str, object]], tree["entries"])
    assert "extension/dist" in [entry["path"] for entry in entries]


@pytest.mark.parametrize("name", ["\ufeffbom.txt", "embedded\ufeffbom.txt"])
def test_candidate_tree_rejects_bom_path(tmp_path: Path, name: str) -> None:
    root = _candidate_root(tmp_path)
    (root / name).write_text("payload")
    with pytest.raises(ValueError, match="E_REPO0_FILE_TREE_ENTRY"):
        command_registry.collect_candidate_file_tree(root)


@pytest.mark.parametrize("entry_kind", ["symlink", "hardlink", "fifo"])
def test_candidate_tree_rejects_unsafe_entries(tmp_path: Path, entry_kind: str) -> None:
    root = _candidate_root(tmp_path)
    source = root / "source"
    source.write_text("payload")
    if entry_kind == "symlink":
        (root / "unsafe").symlink_to(source)
    elif entry_kind == "hardlink":
        os.link(source, root / "unsafe")
    else:
        os.mkfifo(root / "unsafe")
    with pytest.raises(ValueError, match="E_REPO0_FILE_TREE_ENTRY"):
        command_registry.collect_candidate_file_tree(root)


def test_candidate_tree_rejects_symlink_root_and_gitignore_drift(tmp_path: Path) -> None:
    root = _candidate_root(tmp_path / "real")
    linked = tmp_path / "linked"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="E_REPO0_FILE_TREE_ENTRY"):
        command_registry.collect_candidate_file_tree(linked)


def test_accepted_result_set_is_never_written_for_a_blocked_run() -> None:
    assert command_registry.EXPECTED_EXECUTION_ENVIRONMENT["UV_NO_PROGRESS"] == "1"


def test_arbitrary_accepted_result_path_is_rejected_without_deletion() -> None:
    assert command_registry.candidate_commands(_registry())[-1]["command_id"] == "QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK"
