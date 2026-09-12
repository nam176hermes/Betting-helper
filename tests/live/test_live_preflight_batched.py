import copy
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from moj_discovery import live_preflight_batched as gate
from moj_discovery.live_config import LiveConfig, load_live_config
from moj_discovery.live_preflight_batched import EvidenceIndex, evaluate_live_readiness


def test_synthetic_and_truthy_claims_never_admit_live_with_key_present() -> None:
    config = load_live_config(Path("config/live-batched.example.json"))
    synthetic = EvidenceIndex(
        {
            "provider": {"source_kind": "MOCK", "PROBE_RESULT": "PASS"},
            "platform": {"status": "PASS"},
            "security": {"independent": True},
        }
    )
    result = evaluate_live_readiness(config, synthetic, key_present=True)
    assert result.live_read_only_ready is False
    assert "REQUIRES_REAL_PROVIDER_EVIDENCE" in result.missing_inputs
    assert result.key_status == "PRESENT_NOT_AUTHENTICATED"


def test_pure_verified_snapshot_scope_and_expiry() -> None:
    # Synthetic test seam only. No host receipt, runtime admission or provider I/O is produced.
    raw = load_live_config(Path("config/live-batched.example.json")).public
    raw["enabled"] = True
    raw["provider"].update(fixture_ids=[101], league_id=999, season=2026)
    config = LiveConfig(raw, "a" * 64)
    verified = EvidenceIndex(
        {},
        frozenset(gate.REQUIRED),
        config.sha256,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        _proof=gate._SEAL,
        _pid=os.getpid(),
        config_binding=gate.digest(raw),
    )
    result = evaluate_live_readiness(config, verified, True)
    assert result.live_read_only_ready and result.key_status == "PRESENT_NOT_AUTHENTICATED"
    assert result.independent_review == "VERIFIED_HOST_RECEIPT"
    for changed in [
        replace(verified, _proof=None),
        replace(verified, _pid=-1),
        replace(verified, expires_at=datetime.now(UTC) - timedelta(seconds=1)),
        replace(verified, config_sha256="b" * 64),
    ]:
        assert not evaluate_live_readiness(config, changed, True).live_read_only_ready
    mutation = copy.deepcopy(raw)
    mutation["provider"]["fixture_ids"] = [102]
    assert not evaluate_live_readiness(
        LiveConfig(mutation, config.sha256), verified, True
    ).live_read_only_ready
    assert not evaluate_live_readiness(config, verified, False).live_read_only_ready
    unknown = evaluate_live_readiness(config, verified, None)
    assert not unknown.live_read_only_ready and unknown.key_status == "NOT_CHECKED"
    with pytest.raises(ValueError):
        evaluate_live_readiness(config, verified, 1)  # type: ignore[arg-type]


def test_missing_and_symlink_evidence_is_pending_without_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import socket

    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("preflight must not open network sockets")

    monkeypatch.setattr(socket, "socket", denied)
    config = load_live_config(Path("config/live-batched.example.json"))
    raw = config.public
    raw["gates"]["provider_feasibility_path"] = ".local/part-b/provider.json"
    raw["gates"]["security_review_path"] = ".local/part-b/review.json"
    private = tmp_path / ".local/part-b"
    private.mkdir(parents=True)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/synthetic.py").write_text("# TEST_ONLY source binding\n")
    (private / "review.json").write_text(json.dumps({"review_kind": "SELF_ONLY", "PASS": True}))
    # The target must never be read, even if it contains a PASS-looking record.
    external = tmp_path / "unapproved.json"
    external.write_text('{"PROBE_RESULT":"PASS"}')
    (private / "provider.json").symlink_to(external)
    index = gate.load_evidence(LiveConfig(raw, "c" * 64), root=tmp_path)
    result = evaluate_live_readiness(LiveConfig(raw, "c" * 64), index, True)
    assert "provider" not in index.artifacts
    assert not result.live_read_only_ready and result.independent_review == "SELF_ONLY"
    assert set(gate.REQUIRED.values()) <= set(result.missing_inputs)


def test_review_reuse_rehashes_bytes_scope_clock_and_revocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import time

    from tools import issue_review_launch_authorization as launch

    evidence = tmp_path / "TEST_ONLY.json"
    evidence.write_bytes(b'{"value":1}')
    stamp = evidence.stat()
    context = {"snapshots": {str(evidence): hashlib.sha256(evidence.read_bytes()).hexdigest()}}
    bundle, scope = {"authorization": {}}, {"TEST_ONLY": True}
    now = datetime.now(UTC)
    verified = gate._VerifiedExternalReview(
        gate.digest({"bundle": bundle, "scope": scope}),
        tmp_path,
        context,
        {},
        "test-trust",
        now + timedelta(minutes=1),
        time.monotonic() + 60,
        gate._SEAL,
        os.getpid(),
    )
    monkeypatch.setattr(gate, "_host_trust_binding", lambda root: "test-trust")
    monkeypatch.setattr(launch, "validate_review_authority_state", lambda *args: None)
    gate.recheck_external_review(verified, bundle, scope, tmp_path, now)
    for changed in (
        replace(verified, _proof=None),
        replace(verified, _pid=-1),
        replace(verified, deadline_mono=time.monotonic() - 1),
    ):
        with pytest.raises(ValueError):
            gate.recheck_external_review(changed, bundle, scope, tmp_path, now)
    with pytest.raises(ValueError):
        gate.recheck_external_review(verified, bundle, {"TEST_ONLY": False}, tmp_path, now)
    evidence.write_bytes(b'{"value":2}')
    os.utime(evidence, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(ValueError):
        gate.recheck_external_review(verified, bundle, scope, tmp_path, now)
    evidence.write_bytes(b'{"value":1}')

    def revoked(*args: object) -> None:
        raise ValueError("TEST_ONLY_REVOKED")

    monkeypatch.setattr(launch, "validate_review_authority_state", revoked)
    with pytest.raises(ValueError, match="REVOKED"):
        gate.recheck_external_review(verified, bundle, scope, tmp_path, now)


def test_provider_scope_allows_gate_publication_but_not_poll_or_quota_drift() -> None:
    config = load_live_config(Path("config/live-batched.example.json"))
    raw = config.public
    raw["enabled"] = True
    raw["gates"]["provider_feasibility_path"] = ".local/part-b/real-result.json"
    assert gate.provider_config_scope(config) == gate.provider_config_scope(
        LiveConfig(raw, "a" * 64)
    )
    raw["provider"]["live_poll_seconds"] = 30
    assert gate.provider_config_scope(config) != gate.provider_config_scope(
        LiveConfig(raw, "a" * 64)
    )


def test_readonly_cli_reports_pending_without_credential_lookup(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    from tools.live_preflight_batched import main

    assert main(["--config", "config/live-batched.example.json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["live_read_only_ready"] is False
    assert result["key_status"] == "NOT_CHECKED"
    assert result["model_enabled"] is False and result["money_ready"] is False


def test_admission_composition_pins_receiver_and_streams_in_synthetic_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib
    import io
    import shutil
    from typing import Any

    from moj_discovery import live_intent
    from moj_discovery.operator_profile import ExtractionProfile
    from tests.live.test_live_store import binding
    from tests.live.test_operator_profile import profile, sample
    from tests.live.test_run_intents import make_intent

    intent, old_config, _, value = make_intent(tmp_path)
    (tmp_path / "extension").mkdir()
    shutil.copy2("extension/manifest.live.json", tmp_path / "extension/manifest.live.json")
    raw = old_config.public
    raw["enabled"] = True
    b = binding()
    raw["operator"]["allowed_fixture_bindings"] = [b["binding_id"]]
    config = LiveConfig(raw, "d" * 64)
    source = live_intent.source_tree_hash(tmp_path)
    value.update(
        stage="LIVE_READ_ONLY",
        config_sha256=config.sha256,
        source_tree_sha256=source,
        operator_urls=[b["operator_match_url"]],
        max_duration_seconds=120,
        max_http_attempts=20,
    )
    intent = replace(intent, _data=value)
    monkeypatch.setattr(
        live_intent, "controlling_tty", lambda: contextlib.nullcontext(io.StringIO())
    )
    receipt = live_intent.consume_user_intent(intent, config, "START READ ONLY")
    p = profile()
    markets = sample(p)["markets"]
    extracted = ExtractionProfile(p, {}, {b["operator_fixture_id"]: markets}, "a" * 64, True)
    index = EvidenceIndex(
        {},
        frozenset(gate.REQUIRED),
        config.sha256,
        source,
        tmp_path,
        profile=extracted,
        bindings=(b,),
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
        _proof=gate._SEAL,
        _pid=os.getpid(),
        config_binding=gate.digest(raw),
    )
    # This seam exercises composition only; it does not mint or verify an external receipt.
    monkeypatch.setattr(
        gate, "load_evidence", lambda _config: pytest.fail("full verify after consent")
    )
    monkeypatch.setattr(gate, "recheck_live_evidence", lambda _config, _index: None)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "_host_trust_binding", lambda _root: "")
    monkeypatch.setattr(gate, "_check_live_review_authority", lambda _index: None)
    admitted = gate.admit_live_run(config, receipt, verified=index)
    context: dict[str, Any] = dict(
        run_id=admitted.run_id,
        allowed_extension_origin=admitted.extension_origin,
        deadline_mono=admitted.deadline_mono,
        source_kind=admitted.source_kind,
        capture_streams=copy.deepcopy(admitted.capture_streams),
        authority=admitted.security_evidence,
    )
    gate.verify_receiver_authority(context)
    context["allowed_extension_origin"] = "chrome-extension://" + "b" * 32
    with pytest.raises(ValueError, match="AUTHORITY"):
        gate.verify_receiver_authority(context)
    first = next(iter(admitted.capture_streams.values()))
    first["generation"] = "1"
    with pytest.raises(ValueError, match="BINDING"):
        gate.verify_run_admission(config, admitted)
    assert not (tmp_path / ".local/part-b/live-one").exists()
