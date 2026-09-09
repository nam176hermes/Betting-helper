"""Parent-only expectations. Never imported by browser, receiver, or storage readers."""

import json
from pathlib import Path
from typing import Any

from moj_discovery.input_journal import InputJournal
from moj_discovery.offline_projection import semantic_projection


def assert_case(case_id: str, run_dir: Path) -> dict[str, Any]:
    if not __debug__:
        raise RuntimeError("E_OFFLINE_OPTIMIZED_EXECUTION")
    directory = run_dir.parent
    observed = json.loads((directory / "readback.json").read_text())
    reader = observed["reader"]
    assert reader["status"] == "OK"
    actual = semantic_projection(run_dir / "run.sqlite3")
    count = len(actual["raw_commits"])
    expected = {
        "OFF-08": 1,
        "OFF-09": 0,
        "OFF-10": 0,
        "OFF-23": 1,
        "OFF-01": 3,
        "OFF-02": 3,
        "OFF-03": 1,
        "OFF-04": 1,
        "OFF-05": 0,
        "OFF-06": 1,
        "OFF-07": 1,
        "OFF-11": 0,
        "OFF-12": 0,
        "OFF-13": 1,
        "OFF-14": 1,
        "OFF-15": 1,
        "OFF-16": 3,
        "OFF-17": 3,
        "OFF-18": 0,
        "OFF-19": 1000,
        "OFF-24": 1,
        "OFF-26": 0,
        "OFF-27": 2,
    }
    assert count == expected[case_id]
    ack = int(reader["state"]["ackSequence"])
    expected_ack = (
        0
        if case_id
        in {
            "OFF-05",
            "OFF-08",
            "OFF-09",
            "OFF-10",
            "OFF-23",
            "OFF-11",
            "OFF-12",
            "OFF-15",
            "OFF-18",
            "OFF-26",
            "OFF-27",
        }
        else count
    )
    assert ack == expected_ack
    writer = observed["writer"]
    if case_id in {"OFF-08", "OFF-09", "OFF-10", "OFF-23"}:
        wire = json.loads((directory / "wire-observed.json").read_text())["observed"]
        assert sum("rejected" in item for item in wire) == (
            4 if case_id == "OFF-23" else (2 if case_id == "OFF-10" else 1)
        )
        if case_id == "OFF-10":
            assert all(
                item.get("rejected") == "HTTP" and item.get("status") == 403 for item in wire
            )
        elif case_id in {"OFF-08", "OFF-09"}:
            assert all(item.get("after_ready") is True for item in wire if "rejected" in item)
        else:
            assert all(item.get("after_ready") is False for item in wire if "rejected" in item)
    if case_id in {"OFF-11", "OFF-12", "OFF-15", "OFF-18", "OFF-26"}:
        code = {
            "OFF-11": "E_OFFLINE_SCHEMA",
            "OFF-12": "E_OFFLINE_SOURCE_BINDING",
            "OFF-15": "E_SPOOL_ACK",
            "OFF-18": "E_SPOOL_CAPACITY",
            "OFF-26": "E_SPOOL_SCHEMA",
        }[case_id]
        assert any(item.get("status") == "REJECTED" and item.get("code") == code for item in writer)
    if case_id == "OFF-18":
        assert 0 < len(reader["retained"]) < 3
        assert int(reader["state"]["nextSequence"]) == len(reader["retained"]) + 1
    if case_id in {"OFF-13", "OFF-14"}:
        assert actual["stream_generations"][0]["generation_state"] != "ACTIVE"
        assert actual["gap_records"]
        frames = [frame for item in writer for frame in item.get("frames", [])]
        assert frames[-1]["message_type"] == "NACK"
        assert frames[-1]["body"]["code"] == ("GAP" if case_id == "OFF-13" else "CONFLICT")
    if case_id == "OFF-05":
        checkpoints = [point for item in writer for point in item.get("checkpoints", [])]
        assert checkpoints[-1]["stage"] == "BEFORE_IDB_COMMIT"
        assert checkpoints[-1]["workerId"] != reader["workerId"]
        assert reader["retained"] == [] and reader["state"]["nextSequence"] == "1"
    if case_id in {"OFF-04", "OFF-24"}:
        checkpoint = json.loads((run_dir / "checkpoint.json").read_text())
        killed = json.loads((directory / "backend.json").read_text())
        restarted = json.loads((directory / "backend-restarted.json").read_text())
        assert checkpoint["pid"] == killed["pid"] != restarted["pid"] and killed["exit"] == -9
        assert checkpoint["run_id"] == InputJournal(run_dir).context["run_id"]
        assert checkpoint["stage"] == ("AFTER_APPLY" if case_id == "OFF-04" else "AFTER_RECEIVED")
    if case_id == "OFF-27":
        frames = [frame for item in writer for frame in item.get("frames", [])]
        assert [frame["message_type"] for frame in frames] == ["ACK", "NACK"]
        assert frames[0]["body"]["highest_contiguous_sequence"] == "2"
        assert frames[1]["body"]["code"] == "STORAGE_FAILED"
        assert (run_dir / "sqlite-faults.jsonl").is_file()
    if case_id == "OFF-16":
        assert json.loads((directory / "replay-rejected.json").read_text()) == {"rejected": True}
    else:
        replay = json.loads((directory / "replay/replay-result.json").read_text())
        assert replay["equal"] is True
        if case_id in {"OFF-02", "OFF-03"}:
            assert replay["deliveries"] == count + 1
        if case_id == "OFF-17":
            before = (directory / "readback.json").read_bytes()
            try:
                assert count == 999999
            except AssertionError:
                pass
            else:
                raise AssertionError("E_OFFLINE_ORACLE_CONTROL")
            assert (directory / "readback.json").read_bytes() == before
    if case_id == "OFF-19":
        assert replay["deliveries"] == 1001
        assert [
            row["sequence"]
            for row in sorted(actual["raw_commits"], key=lambda row: row["sequence"])
        ] == list(range(1, 1001))
        assert reader["state"]["pendingCount"] == 0
        assert observed["elapsed_seconds"] <= 120
    else:
        assert observed["elapsed_seconds"] <= 30
    return {
        "case_id": case_id,
        "actual_count": count,
        "ack": ack,
        "oracle_passed": True,
        "highest_sequence": max((row["sequence"] for row in actual["raw_commits"]), default=0),
        "gap_count": len(actual["gap_records"]),
        "replay": "EXPECTED_REJECTION" if case_id == "OFF-16" else "EQUAL",
    }
