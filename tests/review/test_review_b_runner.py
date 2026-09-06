from types import SimpleNamespace

import pytest

from tools.run_review_b_checks import EXPECTED_IDS, run_review_b_checks


def _config() -> dict[str, object]:
    return {
        "role": "CYBERSECURITY_REVIEWER",
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
                "cwd": "/tmp/review-b",
                "expected_exit": 0,
                "kind": "review-leaf",
                "network": "DENY",
                "authenticated_operator_access": "DENY",
                "provider_access": "DENY",
            }
            for command_id in EXPECTED_IDS
        ]
    }


def test_review_b_runner_rejects_missing_or_skipped_security_area() -> None:
    calls: list[list[str]] = []

    def execute(argv: list[str], **_: object) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")

    result = run_review_b_checks(_config(), _registry(), execute=execute)
    assert calls == [["runner", command_id] for command_id in EXPECTED_IDS]
    assert result["result"] == "PASS"
    incomplete = _registry()
    incomplete["commands"].pop()
    with pytest.raises(ValueError, match="E_REVIEW_B_REGISTRY"):
        run_review_b_checks(_config(), incomplete, execute=execute)
