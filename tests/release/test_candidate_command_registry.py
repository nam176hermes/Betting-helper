from pathlib import Path
from typing import Any, cast

import pytest

import tools.run_command_registry as registry_runner
from tools.full_verifier_config import load_controller_config


def test_candidate_mode_runs_every_required_command_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = Path("task-command-registry.json")
    registry = registry_runner.validate_registry(registry_path)
    expected = [command["command_id"] for command in registry_runner.candidate_commands(registry)]
    seen: list[str] = []
    monkeypatch.setattr(
        registry_runner,
        "collect_candidate_file_tree",
        lambda _root: {"entries": [], "schema_version": "repo0-independent-file-tree/v1"},
    )

    def evaluate(command: dict[str, object], **_kwargs: Any) -> dict[str, object]:
        seen.append(cast(str, command["command_id"]))
        return {
            "command_id": command["command_id"],
            "argv": command["argv"],
            "cwd": command["cwd"],
            "exit_code": command["expected_exit"],
            "expected_exit": command["expected_exit"],
            "passed": True,
            "stdout_sha256": "0" * 64,
            "stdout_size_bytes": "0",
            "stderr_sha256": "0" * 64,
            "stderr_size_bytes": "0",
        }

    monkeypatch.setattr(registry_runner, "evaluate_invocation", evaluate)
    registry_runner.run_registry(registry_path)

    assert seen == expected
    assert len(seen) == 45


def test_configured_candidate_uses_clean_git_identity_and_effective_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = Path("task-command-registry.json")
    config = load_controller_config(
        Path("vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json")
    )
    identities: list[Path] = []
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        registry_runner,
        "_git_source_identity",
        lambda root: identities.append(root) or {"head": "1" * 40, "tree": "2" * 40},
    )

    def evaluate(command: dict[str, object], **_kwargs: Any) -> dict[str, object]:
        seen.append(command)
        return {
            "command_id": command["command_id"],
            "argv": command["argv"],
            "cwd": command["cwd"],
            "exit_code": command["expected_exit"],
            "expected_exit": command["expected_exit"],
            "passed": True,
            "stdout_sha256": "0" * 64,
            "stdout_size_bytes": "0",
            "stderr_sha256": "0" * 64,
            "stderr_size_bytes": "0",
        }

    monkeypatch.setattr(registry_runner, "evaluate_invocation", evaluate)
    report = registry_runner.run_registry(registry_path, config)

    assert identities == [Path.cwd(), Path.cwd()]
    assert len(seen) == 45
    assert {Path(cast(str, row["cwd"])) for row in seen} == {Path.cwd()}
    assert report["controller_binding"] == config.binding()
