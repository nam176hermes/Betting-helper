"""Atomic forward-GAP boundaries through the real offline ingest owner."""

import json
from pathlib import Path

import pytest

from moj_discovery.generation import GenerationController
from tests.repairs.test_loopback_actual_crashes import PACK, entry, runner
from tests.repairs.test_shared_ingest_persistence import observation


def test_generation_owner_opens_only_exact_successor_and_never_evicts() -> None:
    owner = GenerationController()
    assert owner.replace_after_gap({"0": "ACTIVE"}, 0) == {"0": "CLOSED", "1": "ACTIVE"}
    assert owner.capacity_decision(used=7, incoming=1, normal_limit=7, terminal_reserve=1) == {
        "accepted": False,
        "status": "SAFETY_STOP",
        "evicted": 0,
    }


@pytest.mark.parametrize("prefix", [f"GAP-{number:02d}-" for number in (*range(1, 9), 10)])
def test_forward_gap_atomic_boundaries(tmp_path: Path, prefix: str) -> None:
    result = runner().run_backend_case(entry(prefix), observation(), tmp_path)
    case = Path(result["records"][0]["case_directory"])
    actual = json.loads((case / "actual-state.json").read_text())["tables"]
    committed = prefix == "GAP-10-"
    assert len(actual["gap_records"]) == int(committed)
    assert len(actual["stream_generations"]) == 1 + int(committed)
    assert len(actual["raw_commits"]) == len(actual["ack_outbox"]) == 1
    assert actual["coherence_controllers"][0]["controller_state"] == (
        "SHOCKED_CLOSED" if committed else "OPEN"
    )


def test_late_arrival_rejection_is_scoped_not_history_repair(tmp_path: Path) -> None:
    result = runner().run_backend_case(entry("LATE-01"), observation(), tmp_path)
    case = Path(result["records"][0]["case_directory"])
    recovery = json.loads((case / "recovery.json").read_text())
    assert recovery["replay"] == {"error": "E_INGEST_GENERATION_CLOSED"}
    assert len(recovery["after"]["tables"]["raw_commits"]) == 1
    assert (
        recovery["after"]["tables"]["coherence_controllers"][0]["controller_state"]
        == "SHOCKED_CLOSED"
    )


def test_missing_full_process_and_coherence_contracts_remain_visible(tmp_path: Path) -> None:
    from tools.run_gap_coherence_crash_matrix import run_gap_coherence_crash_matrix

    result = run_gap_coherence_crash_matrix(PACK, tmp_path, observation_input=observation())
    assert result["result"] == "HOLD"
    assert len(result["records"]) == 21
    for row in result["records"]:
        assert row["status"] == "NOT_IMPLEMENTED"
    conflict = next(row for row in result["records"] if row["vector_id"].startswith("CONFLICT"))
    assert conflict["reason"] == "FULL_CONFLICT_PROCESS_EVIDENCE_NOT_IMPLEMENTED"
