import copy
import multiprocessing
import os
import signal
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import rfc8785

from moj_discovery.live_contracts import event_hash
from moj_discovery.live_store import LiveStore
from tests.live.test_provider_normalization import normalize

RUN_ID = "11111111-1111-4111-8111-111111111119"
CONTROL = "22222222-2222-4222-8222-222222222229"
PROVIDER = "33333333-3333-4333-8333-333333333339"
OPERATOR = "44444444-4444-4444-8444-444444444449"


def metadata() -> Any:
    return dict(
        run_id=RUN_ID,
        source_tree_hash="a" * 64,
        config_hash="b" * 64,
        started_utc="2026-09-09T18:00:00Z",
        max_matches=3,
    )


def binding() -> Any:
    return {
        "binding_id": "11111111-1111-4111-8111-111111111111",
        "revision": "1",
        "provider_fixture_id": 101,
        "league_id": 999,
        "season": 2026,
        "kickoff_utc": "2026-09-09T18:00:00Z",
        "home_id": 201,
        "away_id": 202,
        "home_name": "SYNTHETIC HOME",
        "away_name": "SYNTHETIC AWAY",
        "operator_fixture_id": "SYNTHETIC-101",
        "operator_home_id": "SYNTHETIC-H",
        "operator_away_id": "SYNTHETIC-A",
        "operator_match_url": "https://example.invalid/match/101",
        "livescore_match_url": None,
        "orientation_status": "UNVERIFIED",
        "evidence_hashes": [],
    }


def envelope(
    kind: Any, payload: Any, sequence: Any = 1, previous: Any = "0" * 64, stream: Any = None
) -> Any:
    source, default_stream = {
        "BindingChange": ("CONTROL", CONTROL),
        "HealthChange": ("CONTROL", CONTROL),
        "ProviderState": ("PROVIDER", PROVIDER),
        "MarketBook": ("OPERATOR", OPERATOR),
    }[kind]
    event = {
        "protocol": "BH_LIVE_READONLY_V1",
        "run_id": RUN_ID,
        "source_kind": source,
        "stream_id": stream or default_stream,
        "generation": "0",
        "sequence": str(sequence),
        "observation_id": str(uuid4()),
        "observed_at_utc": payload.get("observed_at_utc", "2026-09-09T18:10:00Z"),
        "received_mono_us": "1000000",
        "payload_type": kind,
        "payload": payload,
        "previous_hash": previous,
        "content_hash": "0" * 64,
    }
    event["content_hash"] = event_hash(event)
    return event


def register(store: Any, value: Any = None) -> Any:
    return store.append(
        envelope(
            "BindingChange",
            {
                "before_revision": None,
                "after": value or binding(),
                "reason": "SYNTHETIC_REGISTRATION",
            },
        )
    )


def read_counts(path: Any) -> Any:
    with sqlite3.connect(path) as db:
        return [
            db.execute("SELECT count(*) FROM " + table).fetchone()[0]  # noqa: S608 - fixed tables
            for table in ("live_events", "stream_cursors", "projection_versions", "request_links")
        ]


def test_commit_payload_projection_cursor_then_idempotent_receipt(
    tmp_path: Any, synthetic_provider_response: Any
) -> None:
    path = tmp_path / "run" / "live.sqlite3"
    with LiveStore(path, **metadata()) as store:
        register(store)
        event = envelope("ProviderState", normalize(synthetic_provider_response).states[101])
        receipt = store.append(event)
        assert store.append(copy.deepcopy(event)) == receipt
        assert receipt.receive_index == 2
        assert read_counts(path) == [2, 2, 2, 1]
        with sqlite3.connect(path) as observer:
            row = observer.execute(
                "SELECT payload_canonical FROM live_events WHERE receive_index=2"
            ).fetchone()
        assert bytes(row[0]) == rfc8785.dumps(event)
        assert store.read_projection(binding()["binding_id"])["provider"]["score_current"] == {
            "home": 0,
            "away": 0,
        }
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_binding_is_required_and_exact(
    tmp_path: Any, synthetic_book: Any, synthetic_provider_response: Any
) -> None:
    with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata()) as store:
        with pytest.raises(ValueError, match="BINDING"):
            store.append(envelope("MarketBook", synthetic_book))
        register(store)
        for key, val in [("binding_revision", "2"), ("operator_fixture_id", "WRONG")]:
            bad = {**synthetic_book, key: val}
            with pytest.raises(ValueError, match="BINDING"):
                store.append(envelope("MarketBook", bad))
        bad_provider = normalize(synthetic_provider_response).states[101]
        bad_provider["home_id"] = 999
        with pytest.raises(ValueError, match="BINDING"):
            store.append(envelope("ProviderState", bad_provider))
        assert read_counts(store.path) == [1, 1, 1, 0]


def test_conflict_freezes_source_and_records_control(tmp_path: Any, synthetic_book: Any) -> None:
    with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata()) as store:
        register(store)
        good = envelope("MarketBook", synthetic_book)
        store.append(good)
        conflict = copy.deepcopy(good)
        conflict["payload"]["selections"]["HOME"]["decimal_odds"] = "9.00"
        conflict["content_hash"] = event_hash(conflict)
        with pytest.raises(ValueError, match="CONFLICT"):
            store.append(conflict)
        with pytest.raises(ValueError, match="FROZEN"):
            store.append(envelope("MarketBook", synthetic_book, 2, good["content_hash"]))
        view = store.read_projection(binding()["binding_id"])
        assert view["health"]["state"] == "PAUSED"
        assert view["health"]["reason"] == "STREAM_CONFLICT"
        assert read_counts(store.path)[0] == 3


def test_gap_no_ack_and_missing_exact_frame_can_resume(tmp_path: Any, synthetic_book: Any) -> None:
    with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata()) as store:
        register(store)
        first = envelope("MarketBook", synthetic_book)
        second = envelope(
            "MarketBook", {**synthetic_book, "capture_revision": "2"}, 2, first["content_hash"]
        )
        with pytest.raises(ValueError, match="GAP"):
            store.append(second)
        assert store.read_projection(binding()["binding_id"])["health"]["state"] == "GAP"
        store.append(first)
        store.append(second)
        assert (
            store.read_projection(binding()["binding_id"])["books"]["FT"]["capture_revision"] == "2"
        )


def test_hash_run_and_stream_role_reject(tmp_path: Any, synthetic_book: Any) -> None:
    with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata()) as store:
        register(store)
        good = envelope("MarketBook", synthetic_book)
        for key, value in [("content_hash", "f" * 64), ("run_id", str(uuid4()))]:
            bad = {**good, key: value}
            with pytest.raises(ValueError):
                store.append(bad)
        bad = {**good, "stream_id": CONTROL}
        bad["content_hash"] = event_hash(bad)
        with pytest.raises(ValueError):
            store.append(bad)
        assert read_counts(store.path)[0] == 1


def test_generation_requires_binding_review_and_document_context(
    tmp_path: Any, synthetic_book: Any
) -> None:
    with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata()) as store:
        register(store)
        store.append(envelope("MarketBook", synthetic_book))
        next_document = {**synthetic_book, "document_epoch": str(uuid4())}
        change = envelope("MarketBook", next_document)
        change["generation"] = "1"
        change["content_hash"] = event_hash(change)
        with pytest.raises(ValueError, match="GENERATION"):
            store.append(change)


def test_reopen_preserves_history_and_metadata_is_immutable(tmp_path: Any) -> None:
    path = tmp_path / "run" / "live.sqlite3"
    with LiveStore(path, **metadata()) as store:
        register(store)
    with pytest.raises(ValueError, match="RUN_META"):
        LiveStore(path, **{**metadata(), "config_hash": "c" * 64})
    with LiveStore(path, **metadata()) as store:
        assert store.read_projection(binding()["binding_id"])["binding"] == binding()
        store.close_run("2026-09-09T18:30:00Z", "USER_STOP")
        with pytest.raises(ValueError, match="CLOSED"):
            store.append(
                envelope(
                    "HealthChange",
                    dict(
                        binding_id=None,
                        reason="STOP",
                        state="STOPPED",
                        epoch="1",
                        evidence_hashes=[],
                    ),
                )
            )
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM run_meta")


def _crash_writer(path: Any, event: Any, stage: Any, pipe: Any) -> Any:
    with LiveStore(Path(path), **metadata()) as store:
        if stage == "before":

            def trace(sql: Any) -> Any:
                if sql == "COMMIT":
                    pipe.send("BEFORE_COMMIT")
                    pipe.recv()

            store.db.set_trace_callback(trace)
        receipt = store.append(event)
        pipe.send(receipt.receive_index)
        pipe.recv()


@pytest.mark.parametrize("stage,counts", [("before", [1, 1, 1, 0]), ("after", [2, 2, 2, 0])])
def test_process_kill_at_commit_boundary(
    tmp_path: Any, synthetic_book: Any, stage: Any, counts: Any
) -> None:
    path = tmp_path / "run" / "live.sqlite3"
    with LiveStore(path, **metadata()) as store:
        register(store)
    parent, child = multiprocessing.Pipe()
    worker = multiprocessing.Process(
        target=_crash_writer, args=(str(path), envelope("MarketBook", synthetic_book), stage, child)
    )
    worker.start()
    try:
        assert parent.poll(5)
        observed = parent.recv()
        assert observed == ("BEFORE_COMMIT" if stage == "before" else 2)
    finally:
        assert worker.pid is not None
        os.kill(worker.pid, signal.SIGKILL)
        worker.join(5)
    assert worker.exitcode == -signal.SIGKILL
    with LiveStore(path, **metadata()):
        assert read_counts(path) == counts


def test_size_cap_stops_without_false_receipt(tmp_path: Any, synthetic_book: Any) -> None:
    with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata(), max_bytes=256 * 1024) as store:
        register(store)
        previous = "0" * 64
        accepted = 0
        for sequence in range(1, 201):
            event = envelope(
                "MarketBook",
                {**synthetic_book, "capture_revision": str(sequence)},
                sequence,
                previous,
            )
            try:
                store.append(event)
            except ValueError as error:
                assert str(error) == "E_LIVE_STORE_CAP"
                break
            accepted += 1
            previous = event["content_hash"]
        else:
            pytest.fail("cap did not bound intake")
        assert read_counts(store.path)[0] == accepted + 1


def test_single_writer_and_symlink_rejection(tmp_path: Any) -> None:
    path = tmp_path / "run" / "live.sqlite3"
    with LiveStore(path, **metadata()), pytest.raises(ValueError, match="LOCK"):
        LiveStore(path, **metadata())
    link = tmp_path / "link"
    link.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="PATH"):
        LiveStore(link / "live.sqlite3", **metadata())


def test_duplicate_never_acks_missing_durable_cursor(tmp_path: Any, synthetic_book: Any) -> None:
    path = tmp_path / "run" / "live.sqlite3"
    event = envelope("MarketBook", synthetic_book)
    with LiveStore(path, **metadata()) as store:
        register(store)
        store.append(event)
    with sqlite3.connect(path) as db:
        trigger = db.execute(
            "SELECT sql FROM sqlite_schema WHERE name='immutable_stream_cursors_delete'"
        ).fetchone()[0]
        db.execute("DROP TRIGGER immutable_stream_cursors_delete")
        db.execute("DELETE FROM stream_cursors WHERE receive_index=2")
        db.execute(trigger)
    with (
        LiveStore(path, **metadata()) as store,
        pytest.raises(ValueError, match="POSTCOMMIT_CURSOR"),
    ):
        store.append(event)
