from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import run_command_registry, verify_local
from tools.full_verifier_config import load_controller_config

ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONFIG = (
    ROOT / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json"
)


def test_source_owned_controller_config_is_strict_and_fully_consumed() -> None:
    config = load_controller_config(SOURCE_CONFIG)
    assert config.current_checkout_root == ROOT
    assert config.production_authority == "NONE"
    assert (
        verify_local._validate_authoring_tests(
            config.external_authoring_tests, config.external_authoring_source_sha256
        )
        == config.external_authoring_source_sha256
    )
    with pytest.raises(ValueError, match="E_EXTERNAL_AUTHORING_TESTS"):
        verify_local._validate_authoring_tests(config.external_authoring_tests, "0" * 64)

    registry = run_command_registry.validate_registry()
    commands = run_command_registry.effective_candidate_commands(registry, config)
    assert {Path(str(command["cwd"])) for command in commands} == {ROOT}
    normative = next(
        command
        for command in commands
        if command["command_id"] == "QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS"
    )
    pack_index = normative["argv"].index("--pack") + 1
    runtime_index = normative["argv"].index("--runtime") + 1
    assert Path(normative["argv"][pack_index]) == config.governed_source_pack
    assert Path(normative["argv"][runtime_index]) == ROOT

    environment = run_command_registry.execution_environment(config)
    assert Path(environment["UV_CACHE_DIR"]) == config.uv_cache
    assert Path(environment["npm_config_store_dir"]) == config.pnpm_store
    assert Path(environment["BH_CHROME_BINARY"]) == config.chrome_path


def test_missing_or_extra_config_field_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(SOURCE_CONFIG.read_text())
    payload.pop("pnpm_store")
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(broken)

    payload = json.loads(SOURCE_CONFIG.read_text())
    payload["unexpected"] = True
    broken.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(broken)


def test_candidate_receipt_is_postcondition_not_preflight_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_controller_config(SOURCE_CONFIG)
    seen: list[Path] = []

    def configured(identifier: str, path: Path | None, *, directory: bool) -> dict[str, object]:
        assert path is not None
        seen.append(path)
        return {"prerequisite_id": identifier, "path": str(path), "status": "PASS"}

    monkeypatch.setattr(verify_local, "_configured_path", configured)
    monkeypatch.setattr(verify_local, "sync_pack_assets", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_local, "_validate_bootstrap_receipt", lambda *_a: None)
    monkeypatch.setattr(verify_local, "_validate_authoring_tests", lambda *_a: None)
    monkeypatch.setattr(verify_local, "_validate_cache", lambda *_a: None)
    monkeypatch.setattr(verify_local.os, "access", lambda *_a: True)
    monkeypatch.setattr(verify_local, "_sha256_file", lambda _path: config.chrome_sha256)

    prerequisites = verify_local._full_prerequisites(config)
    assert all(item["status"] == "PASS" for item in prerequisites)
    assert config.candidate_qualification_receipt not in seen
    assert config.candidate_command_evidence not in seen


def test_failed_controller_cannot_be_promoted_by_stale_candidate_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = load_controller_config(SOURCE_CONFIG)
    monkeypatch.setattr(
        verify_local,
        "_full_prerequisites",
        lambda _config: [{"prerequisite_id": "all", "status": "PASS", "path": None}],
    )
    monkeypatch.setattr(verify_local, "_delegate_controller", lambda _config: 7)
    monkeypatch.setattr(
        verify_local,
        "_validate_candidate_postcondition",
        lambda _config: (_ for _ in ()).throw(AssertionError("must not validate stale receipt")),
    )

    assert verify_local._run_full(config) == 7
    assert json.loads(capsys.readouterr().out.splitlines()[0])["status"] == "READY"
