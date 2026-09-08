import json
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, cast

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
                "cwd": "/tmp/review-b",  # noqa: S108 - inert executor fixture, never accessed.
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


def test_current_source_b_keeps_exact_sec14_and_no_descendant_execution() -> None:
    from tests.release.test_descendant_repository_qualification import SOURCE_CONFIG
    from tools.prepare_review_workspace import _registered_leaf_commands

    source = SOURCE_CONFIG.parents[2]
    config = json.loads((source / "docs/configs/review-b.v2.json").read_bytes())
    path = source / "docs/registries/cybersecurity-command-registry.v1.json"
    raw = path.read_bytes()
    assert (
        sha256(raw).hexdigest()
        == "c2009100f4df8cd3e8d1daa4abb901641dd0c1fc5b83162f78188342a541fa5d"
    )
    registry = json.loads(raw)
    config["command_registry_path"] = str(path)
    calls = []

    def execute(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=b"TEST_ONLY_EXECUTOR", stderr=b"")

    result = cast(dict[str, Any], run_review_b_checks(config, registry, execute=execute))
    assert len(calls) == 14
    assert [row["command_id"] for row in result["commands"]] == list(EXPECTED_IDS)
    authorization: dict[str, object] = {"command_registry_sha256": sha256(raw).hexdigest()}
    assert len(_registered_leaf_commands(config, authorization)) == 14
    config["mechanical_command_ids"].append("A_CHECK_DESCENDANT")
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        _registered_leaf_commands(config, authorization)
    assert path.read_bytes() == raw
