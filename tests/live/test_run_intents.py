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


def make_discovery_intent(tmp_path: Path, monkeypatch: Any) -> Any:
    """SYNTHETIC admission fixture; never an independent host review."""
    from moj_discovery import operator_profile
    from tests.live.test_operator_profile import profile

    _, config, path, value = make_intent(tmp_path)
    (tmp_path / "extension").mkdir()
    (tmp_path / "extension/manifest.live.json").write_bytes(
        Path("extension/manifest.live.json").read_bytes()
    )
    value.update(
        stage="OPERATOR_DISCOVERY",
        max_http_attempts=0,
        max_duration_seconds=5,
        operator_urls=["https://miseojeuplus.espacejeux.com/sports/TEST_ONLY/101"],
        source_tree_sha256=live_intent.source_tree_hash(tmp_path),
    )
    path.write_text(json.dumps(value))
    monkeypatch.setattr(operator_profile, "capture_source_hash", lambda root: "a" * 64)
    intent = live_intent.load_run_intent(path, config, "OPERATOR_DISCOVERY", root=tmp_path)
    selectors = profile()["selectors"]
    expiry = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
    scope = live_intent.discovery_review_scope(
        intent, config, selectors, "TEST_ONLY_PROFILE", expiry
    )
    return intent, config, selectors, scope


def test_discovery_scope_needs_no_accepted_profile_but_review_precedes_io(
    tmp_path: Any, monkeypatch: Any
) -> None:
    import asyncio

    from moj_discovery import live_preflight_batched

    intent, config, selectors, scope = make_discovery_intent(tmp_path, monkeypatch)
    assert scope["kind"] == "OPERATOR_DISCOVERY_TOOL" and scope["max_http_attempts"] == 0
    assert "sample_refs" not in scope and not config.enabled
    for bad in (
        {**selectors, "account": "#balance"},
        {**selectors, "home_odds": "input"},
        {**selectors, "match_root": "body"},
    ):
        with pytest.raises(ValueError):
            live_intent.discovery_field_map(bad)
    partial = {k: None if k != "match_root" else v for k, v in selectors.items()}
    assert live_intent.discovery_field_map(partial) == partial
    monkeypatch.setattr(live_intent, "controlling_tty", contextlib.nullcontext)
    receipt = live_intent.consume_user_intent(intent, config, "ALLOW OPERATOR OBSERVATION")

    def deny(*args: Any) -> None:
        raise ValueError("TEST_ONLY_MISSING_REAL_REVIEW")

    monkeypatch.setattr(live_preflight_batched, "verify_external_review", deny)
    output = tmp_path / ".local/part-b/discovery/result.json"
    with pytest.raises(ValueError, match="MISSING_REAL_REVIEW"):
        asyncio.run(
            live_intent.serve_operator_discovery(
                receipt, selectors, "TEST_ONLY_PROFILE", {"scope": scope}, output
            )
        )
    assert not output.exists() and not receipt._claimed


@pytest.mark.parametrize(
    ("tamper", "write_failure"), [(False, False), (True, False), (False, True)]
)
def test_discovery_loopback_exchange_and_tamper_with_synthetic_review_seam(
    tmp_path: Any, monkeypatch: Any, tamper: bool, write_failure: bool
) -> None:
    """Real loopback I/O, SYNTHETIC review/DOM; does not prove operator or host review."""
    import asyncio
    import base64
    import hmac

    from websockets.asyncio.client import connect

    from moj_discovery import live_preflight_batched
    from tools.qualify_chrome_indexeddb import _extension_id

    intent, config, selectors, scope = make_discovery_intent(tmp_path, monkeypatch)
    monkeypatch.setattr(live_intent, "controlling_tty", contextlib.nullcontext)
    monkeypatch.setattr(live_preflight_batched, "verify_external_review", lambda *args: None)
    receipt = live_intent.consume_user_intent(intent, config, "ALLOW OPERATOR OBSERVATION")
    output = tmp_path / ".local/part-b/discovery/result.json"
    if write_failure:

        def fail_fsync(fd: int) -> None:
            raise OSError("TEST_ONLY_DISK_FAILURE")

        monkeypatch.setattr(live_intent.os, "fsync", fail_fsync)

    async def run() -> Any:
        ready = asyncio.Event()
        tickets = []

        def printed(value: str, **kwargs: Any) -> None:
            assert value.startswith("LOCAL_DISCOVERY_PAIRING_TICKET: ")
            tickets.append(json.loads(value.split(": ", 1)[1]))
            ready.set()

        monkeypatch.setattr("builtins.print", printed)
        task = asyncio.create_task(
            live_intent.serve_operator_discovery(
                receipt, selectors, "TEST_ONLY_PROFILE", {"scope": scope}, output
            )
        )
        try:
            await asyncio.wait_for(ready.wait(), 3)
            ticket = tickets[0]
            key = base64.urlsafe_b64decode(ticket["key"] + "=")
            manifest = json.loads(Path("extension/manifest.live.json").read_text())
            async with connect(
                "ws://127.0.0.1:8765/operator-discovery",
                origin="chrome-extension://" + _extension_id(manifest["key"]),
            ) as ws:
                greeting = json.loads(await ws.recv())
                nonce = greeting["nonce"]
                auth = live_intent.discovery_mac(key, "AUTH", receipt.run_id, nonce)
                assert auth != live_intent.discovery_mac(key, "PLAN", receipt.run_id, nonce)
                await ws.send(json.dumps({"mac": auth}))
                frame = json.loads(await ws.recv())
                assert hmac.compare_digest(
                    frame["mac"],
                    live_intent.discovery_mac(key, "PLAN", receipt.run_id, nonce, frame["payload"]),
                )
                plan = json.loads(frame["payload"])
                sample = dict(
                    status="UNADMITTED_SAMPLE",
                    source_kind="OBSERVED_REAL",
                    exact_url=scope["exact_url"],
                    field_map_hash=plan["fieldMapHash"],
                    tab_id=7,
                    document_id="TEST_ONLY_DOCUMENT",
                    document_epoch=str(uuid4()),
                    fields={k: None for k in selectors if k != "match_root"},
                    observed_at_utc=datetime.now(UTC).isoformat(),
                    browser_mono_us="1000000",
                    profile_accepted=False,
                    binding_verified=False,
                )
                for bad in (
                    {**sample, "profile_accepted": True},
                    {**sample, "binding_verified": True},
                    {**sample, "fields": {"account": "TEST_ONLY_FORBIDDEN"}},
                ):
                    with pytest.raises(ValueError):
                        live_intent.validate_discovery_sample(bad, plan)
                payload = json.dumps(sample)
                signature = live_intent.discovery_mac(key, "SAMPLE", receipt.run_id, nonce, payload)
                await ws.send(
                    json.dumps({"payload": payload, "mac": "0" * 64 if tamper else signature})
                )
                if not tamper and not write_failure:
                    ack = json.loads(await ws.recv())
                    assert ack["mac"] == live_intent.discovery_mac(
                        key, "ACK", receipt.run_id, nonce, ack["payload"]
                    )
            result = await asyncio.wait_for(task, 3)
            assert key.hex() not in json.dumps(result) and ticket["key"] not in json.dumps(result)
            return result
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    result = asyncio.run(run())
    assert result["status"] == (
        "DISCOVERY_REJECTED" if tamper or write_failure else "UNADMITTED_SAMPLE_SAVED"
    )
    assert output.exists() is (not tamper)
    if not tamper:
        assert json.loads(output.read_text())["profile_accepted"] is False


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


def test_date_lookup_has_empty_exact_scope_and_cannot_become_live(tmp_path: Any) -> None:
    from moj_discovery.live_config import LiveConfig

    _, config, path, value = make_intent(tmp_path)
    cfg = config.public
    cfg["provider"]["fixture_ids"] = []
    config = LiveConfig(cfg, config.sha256)
    value.update(fixture_ids=[], lookup_date="2026-09-10")
    path.write_text(json.dumps(value))
    intent = live_intent.load_run_intent(path, config, "PROVIDER_PROBE", root=tmp_path)
    assert intent.public["lookup_date"] == "2026-09-10"
    for mutation in (
        {"stage": "LIVE_READ_ONLY"},
        {"lookup_date": "2026-02-30"},
        {"fixture_ids": [101]},
        {"lookup_date": None},
    ):
        path.write_text(json.dumps(value | mutation))
        with pytest.raises(ValueError):
            live_intent.load_run_intent(path, config, "PROVIDER_PROBE", root=tmp_path)


def test_lookup_confirmation_only_authorizes_status_and_chosen_date(
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    from moj_discovery.live_config import LiveConfig
    from moj_discovery.provider_protocol import ProviderScope

    _, config, path, value = make_intent(tmp_path)
    cfg = config.public
    cfg["provider"]["fixture_ids"] = []
    config = LiveConfig(cfg, config.sha256)
    value.update(fixture_ids=[], lookup_date="2026-09-10")
    path.write_text(json.dumps(value))
    intent = live_intent.load_run_intent(path, config, "PROVIDER_PROBE", root=tmp_path)
    monkeypatch.setattr(live_intent, "controlling_tty", contextlib.nullcontext)
    receipt = live_intent.consume_user_intent(intent, config, "ALLOW PROVIDER PROBE")
    monkeypatch.setattr(live_intent, "ROOT", tmp_path)
    live_intent.claim_receipt(receipt, "PROVIDER_PROBE")
    scope = ProviderScope(
        receipt.run_id,
        (),
        999,
        2026,
        receipt.deadline_mono,
        source_kind="OBSERVED_REAL",
        config_sha256=config.sha256,
        source_tree_sha256=value["source_tree_sha256"],
        receipt=receipt,
        lookup_date=value["lookup_date"],
    )
    for purpose in ("STATUS", "LOOKUP"):
        live_intent.verify_provider_receipt(receipt, scope, purpose)
    for purpose in ("COVERAGE", "BUNDLE", "EVENTS_FALLBACK"):
        with pytest.raises(ValueError):
            live_intent.verify_provider_receipt(receipt, scope, purpose)
    from dataclasses import replace

    with pytest.raises(ValueError):
        live_intent.verify_provider_receipt(
            receipt, replace(scope, lookup_date="2026-09-11"), "LOOKUP"
        )


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
