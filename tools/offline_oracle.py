"""Parent-only expectations. Never imported by browser, receiver, or storage readers."""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import rfc8785

from moj_discovery.canonical import canonical_content_hash
from moj_discovery.input_journal import InputJournal
from moj_discovery.offline_projection import semantic_projection
from moj_discovery.store import VENDOR
from moj_discovery.synthetic_source import load_synthetic_observations
from tools.offline_harness import poison_inputs


def assert_case(case_id: str, run_dir: Path) -> dict[str, Any]:
    if not __debug__:
        raise RuntimeError("E_OFFLINE_OPTIMIZED_EXECUTION")
    directory = run_dir.parent
    timing = json.loads((directory / "timings.json").read_text())
    assert timing["execution_and_replay_seconds"] <= (120 if case_id == "OFF-19" else 30)
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
    if case_id == "OFF-11":
        rejected = [r for r in writer if r.get("status") == "REJECTED"]
        assert len(rejected) == 5 and all(r["code"] == "E_OFFLINE_SCHEMA" for r in rejected)
        assert reader["retained"] == [] and reader["state"]["nextSequence"] == "1"
        raw = load_synthetic_observations(directory / "scenario.json")[0]
        needles: set[bytes] = set()
        for poisoned in poison_inputs(raw):
            key = next(key for key in poisoned if key not in raw)
            value = poisoned[key].encode()
            needles.update(
                [
                    value,
                    base64.b64encode(value),
                    value.hex().encode(),
                    hashlib.sha256(value).hexdigest().encode(),
                ]
            )
            for data in [
                rfc8785.dumps(poisoned),
                json.dumps(poisoned, separators=(",", ":")).encode(),
            ]:
                needles.add(hashlib.sha256(data).hexdigest().encode())
            needles.add(
                canonical_content_hash(
                    "RawObservation",
                    poisoned,
                    registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
                ).encode()
            )
        overlap = max(map(len, needles)) - 1
        for path in directory.rglob("*"):
            if path.is_file():
                with path.open("rb") as stream:
                    tail = b""
                    while chunk := stream.read(1048576):
                        block = tail + chunk
                        assert not any(needle in block for needle in needles), (
                            "E_OFFLINE_POISON_LEAK"
                        )
                        tail = block[-overlap:]
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
    if case_id == "OFF-06":
        restarts = [r for r in writer if r.get("operation") == "RESTART_WORKER"]
        assert len(restarts) == 2 and all(r["status"] == "WORKER_TERMINATED" for r in restarts)
        initializations = [r for r in writer if r.get("operation") == "INIT"]
        assert len(initializations) == 3
        assert len({r["workerId"] for r in initializations}) == 3
        for resumed in initializations[1:]:
            assert resumed["state"]["nextSequence"] == "2"
            assert resumed["state"]["ackSequence"] == "0"
            assert resumed["state"]["pendingCount"] == 1
        points = [
            p
            for r in writer
            for p in r.get("checkpoints", [])
            if p.get("stage") == "AFTER_ACK_BEFORE_LOCAL_PERSIST"
        ]
        assert points and points[-1]["workerId"] == initializations[1]["workerId"]
        assert points[-1]["sequence"] == "1"
        assert points[-1]["cursorHash"] == actual["ack_outbox"][0]["cursor_hash"]
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
        if case_id in {"OFF-02", "OFF-03", "OFF-06"}:
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
