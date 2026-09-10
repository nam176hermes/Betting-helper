import json
import sqlite3
from typing import Any

import pytest

from moj_discovery.live_replay import verify_live_replay
from moj_discovery.live_store import LiveStore
from tests.live.test_live_store import envelope, metadata, register
from tests.live.test_provider_normalization import normalize


def frozen_run(tmp_path: Any, synthetic_book: Any, synthetic_provider_response: Any) -> Any:
    run = tmp_path / "observed"
    with LiveStore(run / "live.sqlite3", **metadata()) as store:
        register(store)
        store.append(envelope("ProviderState", normalize(synthetic_provider_response).states[101]))
        store.append(envelope("MarketBook", synthetic_book))
        store.close_run("2026-09-09T18:30:00Z", "USER_STOP")
    return run


def test_fresh_sqlite_replays_observed_rows_twice(
    tmp_path: Any, synthetic_book: Any, synthetic_provider_response: Any
) -> None:
    run = frozen_run(tmp_path, synthetic_book, synthetic_provider_response)
    a = verify_live_replay(run, tmp_path / "replay-a")
    b = verify_live_replay(run, tmp_path / "replay-b")
    assert a.equal and b.equal and a.events == 3
    assert a.logical_sha256 == b.logical_sha256
    assert (tmp_path / "replay-a" / "live.sqlite3").is_file()
    with pytest.raises(ValueError):
        verify_live_replay(run, tmp_path / "replay-a")


@pytest.mark.parametrize("mutation", ["raw", "missing", "reorder", "quote", "binding", "derived"])
def test_actual_observation_and_projection_tamper_detected(
    tmp_path: Any, synthetic_book: Any, synthetic_provider_response: Any, mutation: Any
) -> None:
    run = frozen_run(tmp_path, synthetic_book, synthetic_provider_response)
    path = run / "live.sqlite3"
    # Isolated corrupt copies are evidence of rejection, never imported as acceptance inputs.
    with sqlite3.connect(path) as db:
        trigger_sql = db.execute(
            "SELECT name,sql FROM sqlite_schema WHERE type='trigger'"
        ).fetchall()
        for name, _ in trigger_sql:
            db.execute('DROP TRIGGER "' + name + '"')
        if mutation == "missing":
            db.execute("DELETE FROM live_events WHERE receive_index=2")
        elif mutation == "reorder":
            db.execute("UPDATE live_events SET receive_index=receive_index+10")
        elif mutation == "derived":
            db.execute(
                "UPDATE projection_versions SET canonical_view=x'7b7d' WHERE projection_id=3"
            )
        else:
            index = 1 if mutation == "binding" else 3
            event = json.loads(
                db.execute(
                    "SELECT payload_canonical FROM live_events WHERE receive_index=?", (index,)
                ).fetchone()[0]
            )
            if mutation == "binding":
                event["payload"]["after"]["home_id"] = 999
            elif mutation == "quote":
                event["payload"]["selections"]["HOME"]["decimal_odds"] = "9.00"
            else:
                event["received_mono_us"] = "9000000"
            db.execute(
                "UPDATE live_events SET payload_canonical=? WHERE receive_index=?",
                (json.dumps(event).encode(), index),
            )
        for _, sql in trigger_sql:
            db.execute(sql)
    with pytest.raises(ValueError):
        verify_live_replay(run, tmp_path / "replay")


def test_open_run_cannot_be_frozen(tmp_path: Any) -> None:
    run = tmp_path / "observed"
    with LiveStore(run / "live.sqlite3", **metadata()) as store:
        register(store)
        with pytest.raises(ValueError):
            verify_live_replay(run, tmp_path / "replay")
    with pytest.raises(ValueError, match="NOT_CLOSED"):
        verify_live_replay(run, tmp_path / "replay-closed")
