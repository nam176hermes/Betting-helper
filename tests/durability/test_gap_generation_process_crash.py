import copy
import json
from pathlib import Path

import pytest

from moj_discovery.vendor import pack_root
from tools.run_gap_coherence_crash_matrix import run_gap_coherence_crash_matrix
from tools.verify_repair_evidence import aggregate_repair_evidence

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)
IDS = [
    row["vector_id"]
    for row in json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    if row["harness"] == "GAP_GENERATION_COHERENCE"
]


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    return run_gap_coherence_crash_matrix(PACK, tmp_path_factory.mktemp("gap-owner"))


def test_closed_generation_and_epoch_never_reopen(report: dict[str, object]) -> None:
    result = report
    assert result["result"] == "PASS"
    assert len(result["executed_vector_ids"]) == 21
    assert result["mutation_survivors"] == 0
    assert "EPOCH-05-NEW-SHOCK-WHILE-PENDING" in result["executed_vector_ids"]
    assert all(row["actual"]["run_id"] == row["identity"]["run_id"] for row in result["records"])
    assert aggregate_repair_evidence(IDS, result["records"])["result"] == "PASS"


def test_wrong_governed_oracle_is_rejected(report: dict[str, object]) -> None:
    row = copy.deepcopy(report["records"][0])
    row["expected"]["coherence_state"] = "WRONG"
    result = aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "FAIL"
    assert result["errors"][0]["error"] == "E_GAP_ORACLE"


def test_registered_mutations_and_commit_boundaries_are_executed(
    report: dict[str, object],
) -> None:
    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    wanted = {
        mutation
        for row in registry["entries"]
        if row["harness"] == "GAP_GENERATION_COHERENCE"
        for mutation in row["mutation_vector_ids"]
    }
    assert {row["mutation"] for row in report["mutation_results"]} == wanted
    assert report["killed_child_count"] == 16
    for case_id in ("GAP-09-DURING-COMMIT", "EPOCH-04-DURING-NEW-EPOCH-OPEN-COMMIT"):
        row = next(item for item in report["records"] if item["case_id"] == case_id)
        boundary = json.loads(Path(row["boundary_artifact"]["path"]).read_text())
        assert boundary["commit_armed"] is True
        assert boundary["phase"] == "during_commit"
        assert boundary["operation"] in {"fsync", "fdatasync"}


def test_recovery_capacity_and_oracle_boundary(report: dict[str, object]) -> None:
    gap = report["records"][0]
    assert gap["before_restart"]["controller"] == "OPEN"
    assert gap["after_restart"]["generations"] == {"0": "CLOSED", "1": "ACTIVE"}
    capacity = next(row for row in report["records"] if row["case_id"].startswith("CAPACITY"))
    assert capacity["actual"]["capacity"] == {
        "normal_limit": 7,
        "terminal_reserve": 1,
        "used": 7,
        "unacknowledged_rows": 1,
        "evicted": 0,
        "status": "SAFETY_STOP",
    }
    by_id = {row["case_id"]: row for row in report["records"]}
    assert (
        by_id["CLOCK-02-AFTER-CLOSURE-COMMIT-BEFORE-SHOCK"]["before_restart"]["controller"]
        == "OPEN_BUT_INELIGIBLE"
    )
    assert (
        by_id["CLOCK-02-AFTER-CLOSURE-COMMIT-BEFORE-SHOCK"]["after_restart"]["controller"]
        == "SHOCKED_CLOSED"
    )
    assert (
        by_id["EPOCH-03-AFTER-PENDING-WRITES-BEFORE-COMMIT"]["before_restart"]["controller"]
        == "WAITING_FOR_RESNAPSHOT"
    )
    assert (
        by_id["EPOCH-04-DURING-NEW-EPOCH-OPEN-COMMIT"]["after_restart"]["controller"]
        == "NEW_EPOCH_OPEN"
    )
    for row in report["records"]:
        assert set(json.loads(Path(row["scenario_artifact"]["path"]).read_text())) == {
            "run_id",
            "case_id",
        }
        for reader in row["reader_runs"]:
            assert not (
                {"expected", "expected_post_restart_state", "oracle"}
                & set(json.loads(Path(reader["input"]["path"]).read_text()))
            )


@pytest.mark.parametrize(
    ("damage", "error"),
    [
        ("run", "E_GAP_IDENTITY"),
        ("case", "E_GAP_IDENTITY"),
        ("checkpoint", "E_GAP_IDENTITY"),
        ("wrong_error", "E_GAP_COMPARISON"),
        ("artifact", "E_GAP_ARTIFACT"),
    ],
)
def test_semantic_evidence_mutations_fail_closed(
    report: dict[str, object], damage: str, error: str
) -> None:
    row = copy.deepcopy(report["records"][0])
    if damage in {"run", "case", "checkpoint"}:
        row["identity"][damage + "_id"] = "stale"
    elif damage == "wrong_error":
        row["observed_error"] = "E_WRONG"
    else:
        row["actual_artifact"]["sha256"] = "0" * 64
    result = aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "FAIL"
    assert result["errors"][0]["error"] == error


def test_missing_and_duplicate_records_fail_closed(report: dict[str, object]) -> None:
    row = report["records"][0]
    assert aggregate_repair_evidence([row["case_id"]], [])["result"] == "FAIL"
    assert (
        aggregate_repair_evidence([row["case_id"]], [row, copy.deepcopy(row)])["result"] == "FAIL"
    )
