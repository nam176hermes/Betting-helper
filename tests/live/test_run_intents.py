import contextlib
import copy
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from moj_discovery import live_intent
from moj_discovery.live_config import load_live_config
from moj_discovery.live_intent import validate_intent_window


def test_intent_window_is_finite_and_utc() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    validate_intent_window(now, now + timedelta(minutes=15), now)
    for issued, expiry, current in [
        (now, now + timedelta(minutes=16), now),
        (now, now + timedelta(minutes=15), now + timedelta(minutes=15)),
        (now, now + timedelta(minutes=15), now - timedelta(seconds=1)),
    ]:
        with pytest.raises(ValueError):
            validate_intent_window(issued, expiry, current)


def make_intent(tmp_path: Path) -> Any:
    source = tmp_path / "src/moj_discovery/owned.py"
    source.parent.mkdir(parents=True)
    source.write_text("# SYNTHETIC intent test source\n")
    config = json.loads(Path("config/live-batched.example.json").read_text())
    config["provider"].update(league_id=999, season=2026, fixture_ids=[101])
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    loaded = load_live_config(config_path)
    now = datetime.now(UTC)
    value = dict(
        schema_version="part-b-run-intent/v1",
        intent_id=str(uuid4()),
        stage="PROVIDER_PROBE",
        config_sha256=loaded.sha256,
        source_tree_sha256=live_intent.source_tree_hash(tmp_path),
        fixture_ids=[101],
        operator_urls=[],
        max_duration_seconds=300,
        max_http_attempts=20,
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=15)).isoformat(),
        user_confirmation_required=True,
        money_authority=False,
    )
    target = tmp_path / ".local/part-b/intents/probe.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(value))
    intent = live_intent.load_run_intent(target, loaded, "PROVIDER_PROBE", root=tmp_path)
    assert intent.sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    return intent, loaded, target, value


def test_consumption_burns_intent_and_claim_once_even_after_reload(
    tmp_path: Any, monkeypatch: Any
) -> None:
    intent, config, path, _ = make_intent(tmp_path)
    monkeypatch.setattr(
        live_intent, "controlling_tty", lambda: contextlib.nullcontext(io.StringIO())
    )
    with pytest.raises(ValueError, match="DECLINED"):
        live_intent.consume_user_intent(intent, config, "NO")
    receipt = live_intent.consume_user_intent(intent, config, "ALLOW PROVIDER PROBE")
    live_intent.claim_receipt(receipt, "PROVIDER_PROBE")
    assert receipt.confirmation_kind == "LOCAL_TTY_USER_CONFIRMATION"
    with pytest.raises(ValueError, match="REPLAY"):
        live_intent.claim_receipt(receipt, "PROVIDER_PROBE")
    reloaded = live_intent.load_run_intent(path, config, "PROVIDER_PROBE", root=tmp_path)
    with pytest.raises(ValueError, match="CONSUMED"):
        live_intent.consume_user_intent(reloaded, config, "ALLOW PROVIDER PROBE")
    (tmp_path / "src/moj_discovery/owned.py").write_text("# DIFFERENT SYNTHETIC SOURCE\n")
    with pytest.raises(ValueError, match="RECEIPT"):
        live_intent.verify_receipt(receipt, "PROVIDER_PROBE")


def test_no_terminal_and_source_config_scope_mismatch_cannot_consume(
    tmp_path: Any, monkeypatch: Any
) -> None:
    intent, config, path, value = make_intent(tmp_path)

    def no_tty() -> Any:
        raise ValueError("E_SECRET_NO_TTY")

    monkeypatch.setattr(live_intent, "controlling_tty", no_tty)
    with pytest.raises(ValueError, match="NO_TTY"):
        live_intent.consume_user_intent(intent, config, "ALLOW PROVIDER PROBE")
    assert not (tmp_path / ".local/part-b/intent-consumptions.sqlite3").exists()
    for key, bad in [
        ("max_http_attempts", 21),
        ("fixture_ids", [102]),
        ("config_sha256", "a" * 64),
        ("source_tree_sha256", "b" * 64),
        ("money_authority", True),
        ("arbitrary", "value"),
    ]:
        changed = copy.deepcopy(value)
        changed[key] = bad
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match="LOAD"):
            live_intent.load_run_intent(path, config, "PROVIDER_PROBE", root=tmp_path)


def test_concurrent_consumers_only_commit_one_row(tmp_path: Any, monkeypatch: Any) -> None:
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor

    intent, config, _, _ = make_intent(tmp_path)
    monkeypatch.setattr(
        live_intent, "controlling_tty", lambda: contextlib.nullcontext(io.StringIO())
    )

    def consume() -> bool:
        try:
            live_intent.consume_user_intent(intent, config, "ALLOW PROVIDER PROBE")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(lambda _: consume(), range(2))) == [False, True]
    with sqlite3.connect(tmp_path / ".local/part-b/intent-consumptions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM intent_consumptions").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
            db.execute("DELETE FROM intent_consumptions")


def test_pairing_uses_only_user_terminal_and_never_provider_secret(
    tmp_path: Any, monkeypatch: Any, capsys: Any
) -> None:
    import time

    from moj_discovery.live_wire import PairingAuthority
    from tools import run_live_readonly

    terminal = io.StringIO()
    run_id = str(uuid4())
    service = type(
        "SyntheticService",
        (),
        {
            "admitted": type(
                "SyntheticAdmission",
                (),
                {"run_id": run_id, "deadline_mono": time.monotonic() + 120},
            )(),
            "pairing": PairingAuthority(run_id, time.monotonic() + 120),
        },
    )()
    monkeypatch.setattr(
        run_live_readonly, "controlling_tty", lambda: contextlib.nullcontext(terminal)
    )
    run_live_readonly.show_local_pairing(service)
    ticket = json.loads(terminal.getvalue().splitlines()[1])
    assert set(ticket) == {"version", "runId", "durationSeconds", "ui", "capture"}
    assert ticket["runId"] == run_id and ticket["ui"]["sessionId"] != ticket["capture"]["sessionId"]
    assert capsys.readouterr().out == ""
    assert "API_FOOTBALL_KEY" not in terminal.getvalue()
