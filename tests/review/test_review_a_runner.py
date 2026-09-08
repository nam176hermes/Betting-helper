from types import SimpleNamespace
from typing import Any, cast

import pytest

from tools.run_review_a_checks import EXPECTED_IDS, run_review_a_checks


def _config() -> dict[str, object]:
    return {
        "role": "IMPLEMENTATION_READINESS_REVIEWER",
        "network": "DENY",
        "mechanical_command_ids": list(EXPECTED_IDS),
        "environment": {"UV_OFFLINE": "1"},
    }


def _registry() -> dict[str, object]:
    return {
        "commands": [
            {
                "command_id": command_id,
                "argv": ["runner", command_id],
                "cwd": "/tmp/review-a",  # noqa: S108 - inert executor fixture, never accessed.
                "expected_exit": 0,
                "kind": "review-leaf",
                "network": "DENY",
                "authenticated_operator_access": "DENY",
                "provider_access": "DENY",
            }
            for command_id in EXPECTED_IDS
        ]
    }


def test_review_a_runner_executes_only_registry_commands() -> None:
    calls: list[list[str]] = []

    def execute(argv: list[str], **_: object) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")

    result = run_review_a_checks(_config(), _registry(), execute=execute)
    assert calls == [["runner", command_id] for command_id in EXPECTED_IDS]
    assert result["result"] == "PASS"
    assert len(result["commands"]) == len(EXPECTED_IDS)
    changed = _config()
    changed["mechanical_command_ids"] = [*EXPECTED_IDS, "REVIEW_A_MECHANICAL"]
    with pytest.raises(ValueError, match="E_REVIEW_A_CONFIG"):
        run_review_a_checks(changed, _registry(), execute=execute)


def test_current_review_a_selects_descendant_without_running_legacy_leaf() -> None:
    config, registry = _config(), _registry()
    config["schema_version"] = "review-config/v2"
    config["mechanical_command_ids"] = ["A_CHECK_SOURCE", "A_CHECK_EVIDENCE", "A_CHECK_DESCENDANT"]
    registry["commands"][-1]["command_id"] = "A_CHECK_DESCENDANT"
    registry["commands"][-1]["argv"] = ["runner", "--check-only"]
    calls = []

    def execute(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    result = cast(dict[str, Any], run_review_a_checks(config, registry, execute=execute))
    assert [row["command_id"] for row in result["commands"]] == config["mechanical_command_ids"]
    assert calls[-1] == ["runner", "--check-only"]
