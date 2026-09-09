import json
from pathlib import Path

from tests.repairs.test_shared_ingest_persistence import (
    BROWSER,
    PRODUCER,
    REGISTRY,
    STREAM,
    observation,
)
from tools.offline_browser import run_worker_probe


def test_real_spool_payloads_are_retained_copies(tmp_path: Path) -> None:
    rows = [observation(i) for i in range(1, 4)]
    request = {
        "identity": {},
        "operation": "offline-spool",
        "options": {
            "browser_run_id": BROWSER,
            "producer_id": PRODUCER,
            "stream_id": STREAM,
            "generation": "0",
            "registry": json.loads(REGISTRY.read_text()),
        },
        "observations": [json.dumps(row) for row in rows],
    }
    result = run_worker_probe(tmp_path / "browser", request)
    actual = result["worker"]
    assert [json.loads(value) for value in actual["payloads"]] == rows
    assert [json.loads(value) for value in actual["retained"]] == rows
    assert actual["verified"]["nextSequence"] == "4"
    assert actual["verified"]["ackSequence"] == "1"
    assert actual["verified"]["pendingCount"] == 2
    assert len(actual["entries"]) == 3


def test_real_capacity_rejection_keeps_prior_rows(tmp_path: Path) -> None:
    rows = [observation(i) for i in range(1, 4)]
    encoded = [json.dumps(row) for row in rows]
    limit = len(encoded[0].encode()) + len(encoded[1].encode())
    request = {
        "identity": {},
        "operation": "offline-spool",
        "normal_byte_limit": str(limit),
        "options": {
            "browser_run_id": BROWSER,
            "producer_id": PRODUCER,
            "stream_id": STREAM,
            "generation": "0",
            "registry": json.loads(REGISTRY.read_text()),
        },
        "observations": encoded,
    }
    actual = run_worker_probe(tmp_path / "browser", request)["worker"]
    assert actual["appendErrors"] == ["E_SPOOL_CAPACITY"]
    assert len(actual["entries"]) == 2
    assert actual["verified"]["nextSequence"] == "3"
    assert [json.loads(value) for value in actual["retained"]] == rows[:2]
