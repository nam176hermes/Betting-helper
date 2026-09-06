from pathlib import Path
from typing import Any, cast

import pytest

import tools.run_command_registry as registry_runner


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
