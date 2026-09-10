"""Actual SQLite observations remain distinct from synthetic expected assertions."""

import asyncio
import copy
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.live_contracts import event_hash
from moj_discovery.live_state import capture_observation_id
from tests.live.test_live_replay import frozen_run
from tests.live.test_live_service import make_service
from tests.live.test_live_store import envelope
from tools.qualify_live_readonly import _verify_manual_checks, qualify_recorded_run


def test_journal_without_run_authority_never_becomes_live_pass(
    tmp_path: Path,
    synthetic_book: Any,
    synthetic_provider_response: Any,
) -> None:
    run = frozen_run(tmp_path, synthetic_book, synthetic_provider_response)
    result = qualify_recorded_run(run)
    assert result["LIVE_READ_ONLY_PASS"] is False
    assert result["replay"]["equal"] is True
    assert result["status"] == "HOLD"
    assert "RUN_ARTIFACTS_MISSING" in result["missing_inputs"]
    assert result["model_enabled"] is False and result["money_ready"] is False


def test_missing_or_active_journal_cannot_qualify(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        qualify_recorded_run(tmp_path)


def test_terminal_check_binds_committed_book_and_preserves_mock_label(
    tmp_path: Any,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    service, http, book, stream = make_service(
        tmp_path,
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )
    monkeypatch.setattr("moj_discovery.secrets_local.controlling_tty", nullcontext)

    async def scenario() -> None:
        await service.start()
        await service.tick()
        challenge = await service.request_capture(book["binding_id"])
        event = envelope("MarketBook", book, stream=stream)
        event.update(
            run_id=service.admitted.run_id, observation_id=capture_observation_id(challenge, "FT")
        )
        event["content_hash"] = event_hash(event)
        service.store.append(event)
        await service.capture_received(event)
        prices = tuple(book["selections"][s]["decimal_odds"] for s in ("HOME", "DRAW", "AWAY"))
        with pytest.raises(ValueError):
            service.record_manual_ft_check(101, ("99", "99", "99"))
        service.record_manual_ft_check(101, prices)
        with pytest.raises(ValueError):
            service.record_manual_ft_check(101, prices)
        await service.close()

    asyncio.run(scenario())
    rows = [
        json.loads(r)
        for r in (service.directory / "manual-ft-checks.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1 and rows[0]["source_kind"] == "MOCK"
    requests = (service.directory / "requests.jsonl").read_text().splitlines()
    assert len(requests) == len(http.paths) == 2
    result = json.loads((service.directory / "result.json").read_text())
    assert result["real_http_attempts"] == 0 and result["http_attempts"] == 2
    for name in (
        "intent.json",
        "config-public.json",
        "source-bindings.json",
        "requests.jsonl",
        "result.json",
    ):
        assert "TEST_ONLY_SERVICE_KEY" not in (service.directory / name).read_text()
    qualified = qualify_recorded_run(service.directory)
    assert qualified["replay"]["equal"] and not qualified["LIVE_READ_ONLY_PASS"]


def test_manual_comparison_requires_three_distinct_time_bound_books(synthetic_book: Any) -> None:
    # Test data only. The observation validator is not the live authority gate.
    books, rows = [], []
    binding = synthetic_book["binding_id"]
    start = datetime(2026, 9, 9, 18, tzinfo=UTC)
    for i in range(3):
        book = copy.deepcopy(synthetic_book)
        book["observed_at_utc"] = (start + timedelta(seconds=i * 31)).isoformat()
        event = envelope("MarketBook", book)
        books.append(event)
        rows.append(
            dict(
                confirmation_kind="LOCAL_TTY_USER_CHECK",
                source_kind="OBSERVED_REAL",
                run_id=event["run_id"],
                binding_id=binding,
                capture_event_hash=event["content_hash"],
                checked_at_utc=book["observed_at_utc"],
                selections=book["selections"],
                market_id=book["market_id"],
            )
        )
    meta = (books[0]["run_id"], None, None, start.isoformat())
    closure = (None, (start + timedelta(minutes=5)).isoformat())
    assert _verify_manual_checks(rows, books, {binding: {}}, meta, closure) == {binding: 3}
    for bad in (
        rows + [rows[0]],
        [dict(rows[0], source_kind="MOCK")],
        [dict(rows[0], checked_at_utc=(start + timedelta(seconds=31)).isoformat())],
    ):
        with pytest.raises(ValueError):
            _verify_manual_checks(bad, books, {binding: {}}, meta, closure)
