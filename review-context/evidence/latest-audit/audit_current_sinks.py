"""Local diagnostic only; not a registered host proof or independent review."""

import copy
import hashlib
import json
import logging
from pathlib import Path
from unittest.mock import patch

from moj_discovery import live_store
from moj_discovery.live_contracts import validate_live_record
from tests.live.conftest import synthetic_book
from tests.live.test_live_store import envelope, metadata, register


def main():
    root = Path(__file__).resolve().parent
    book = synthetic_book.__wrapped__()
    event = envelope("MarketBook", book)
    observations = []
    messages = []

    class LogProbe(logging.Handler):
        def emit(self, record):
            messages.append(record)

    handler = LogProbe()
    logger = logging.getLogger()
    logger.addHandler(handler)
    try:
        with live_store.LiveStore(root / "sink-diagnostic" / "live.sqlite3", **metadata()) as store:
            register(store)
            sql = []
            store.db.set_trace_callback(sql.append)
            with patch.object(live_store, "event_hash", wraps=live_store.event_hash) as hashing:
                store.append(event)
                assert hashing.call_count > 0
                assert any(s.startswith("INSERT INTO live_events") for s in sql)
                allowed = {"hash_sink_observed": True, "sqlite_insert_observed": True}
                for field in ("cookie", "token", "raw_response", "authorization"):
                    for depth in ("event", "payload", "selection"):
                        invalid = copy.deepcopy(event)
                        target = invalid if depth == "event" else invalid["payload"]
                        if depth == "selection":
                            target = target["selections"]["HOME"]
                        target[field] = "TEST_ONLY_FORBIDDEN_SENTINEL"
                        hashing.reset_mock()
                        sql.clear()
                        messages.clear()
                        before = hashlib.sha256(store.path.read_bytes()).hexdigest()
                        for admission in (
                            lambda value: validate_live_record(value, "LiveEvent"),
                            store.append,
                        ):
                            try:
                                admission(invalid)
                            except ValueError as error:
                                assert str(error) == "E_LIVE_RECORD"
                            else:
                                raise AssertionError("unexpected admission")
                        assert hashing.call_count == 0 and sql == [] and messages == []
                        assert hashlib.sha256(store.path.read_bytes()).hexdigest() == before
                        observations.append({"field": field, "depth": depth, "rejection": "E_LIVE_RECORD",
                                             "hash_calls": 0, "sql_calls": 0, "logs": 0,
                                             "database_bytes_unchanged": True})
            store.db.set_trace_callback(None)
    finally:
        logger.removeHandler(handler)
    result = {"status": "LOCAL_DIAGNOSTIC_PASS", "allowed_control": allowed,
              "denied_cases": observations, "source_kind": "SYNTHETIC",
              "limitations": ["Not controller-executed", "No independent review",
                              "No guard-disabled proof-invalidating mutation",
                              "No browser or IndexedDB observations in this diagnostic"]}
    (root / "sink-diagnostic.json").write_text(json.dumps(result, indent=2) + "\n")
    print("LOCAL_DIAGNOSTIC_PASS: 1 allowed control, 12 rejected field/depth cases; no denied hash/log/SQL effects")


if __name__ == "__main__":
    main()
