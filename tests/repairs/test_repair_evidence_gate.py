"""Repair acceptance consumes executions and current bytes, never inventory counts."""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.durability_release import validate_full_durability_release
from tools import run_clock_vector_qualification as clock

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"


def gate() -> Any:
    assert (ROOT / "tools/verify_repair_evidence.py").is_file(), "R08 evidence gate missing"
    return importlib.import_module("tools.verify_repair_evidence")


@pytest.fixture(scope="module")
def clock_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return clock.run_clock_vector_qualification(
        PACK, ROOT, evidence_dir=tmp_path_factory.mktemp("r08-clock"),
    )


def test_full_inventory_keeps_actual_clock_and_durability_holds(
    clock_report: dict[str, Any],
) -> None:
    from tools.run_loopback_ack_crash_matrix import run_family

    module = gate()
    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    rows = [row for family in {e["harness"] for e in registry["entries"]}
            for row in run_family(PACK, Path("unused-no-launch"), family, None)["records"]]
    result = module.aggregate_repair_evidence(
        module.full_required_ids(), [*rows, *clock_report["records"]],
    )
    assert result["result"] == "HOLD"
    assert result["qualification_scope"] == "FULL"
    assert result["required_id_set_complete"] is True
    assert result["status_counts"] == {"PASS": 17, "NOT_IMPLEMENTED": 94}
    assert result["errors"] == []
    assert result["security_review"] == "NOT_REVIEWED"
    assert result["production_authority"] == result["live_authority"] == "NONE"
    assert result["money_authority"] == "NONE"


def test_complete_subset_is_explicitly_not_full(clock_report: dict[str, Any]) -> None:
    row = next(row for row in clock_report["records"] if row["status"] == "PASS")
    result = gate().aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "PASS"
    assert result["qualification_scope"] == "SUBSET"
    assert result["legacy_full_qualification"] == "HOLD"


@pytest.mark.parametrize("damage", [
    "missing", "duplicate", "extra", "commit", "source", "vendor", "lock",
    "environment", "binding_missing", "artifact_missing", "artifact_stale",
    "environment_only", "wrong_comparator", "wrong_exit", "oracle_in_actual",
    "status", "unexecuted_pass", "missing_source_binding",
])
def test_negative_evidence_cannot_qualify(
    clock_report: dict[str, Any], tmp_path: Path, damage: str,
) -> None:
    module = gate()
    row = copy.deepcopy(next(row for row in clock_report["records"] if row["status"] == "PASS"))
    required = [row["case_id"]]
    rows = [row]
    if damage == "missing":
        rows = []
    elif damage == "duplicate":
        rows.append(copy.deepcopy(row))
    elif damage == "extra":
        rows.append({**row, "case_id": "UNREGISTERED"})
    elif damage in {"commit", "source", "vendor", "lock", "environment"}:
        key = {"commit": "revision", "source": "source_sha256", "vendor": "vendor_sha256",
               "lock": "lock_sha256", "environment": "environment"}[damage]
        row["evidence_binding"][key] = "wrong"
    elif damage == "missing_source_binding":
        row["evidence_binding"]["source_sha256"] = {}
    elif damage == "binding_missing":
        row.pop("evidence_binding")
    elif damage.startswith("artifact_"):
        artifact = tmp_path / "actual.json"
        if damage == "artifact_stale":
            artifact.write_text("{}")
        row["actual_artifact"]["path"] = str(artifact)
    elif damage == "environment_only":
        row["execution_kind"] = "CHROME_ENVIRONMENT_SENTINEL"
    elif damage == "wrong_comparator":
        row["comparison"]["matched"] = False
    elif damage == "wrong_exit":
        row["command_exit"]["typescript"] = 1
    elif damage == "oracle_in_actual":
        row["actual"]["expected"] = row["expected"]
    elif damage == "status":
        row["status"] = "SKIP"
    else:
        row["executed"] = False
    result = module.aggregate_repair_evidence(required, rows)
    assert result["result"] == "FAIL", damage
    assert result["errors"], damage


def test_absent_prerequisite_and_unimplemented_are_distinct() -> None:
    rows = [
        {"case_id": "browser", "status": "BLOCKED_ENVIRONMENT", "executed": False,
         "prerequisite": {"name": "extension-origin browser", "available": False},
         "reason": "E_EXTENSION_TARGET_UNAVAILABLE"},
        {"case_id": "spool", "status": "NOT_IMPLEMENTED", "executed": False,
         "reason": "R05 dependency missing"},
        {"case_id": "later", "status": "NOT_EXECUTED", "executed": False,
         "reason": "not attempted"},
    ]
    result = gate().aggregate_repair_evidence([r["case_id"] for r in rows], rows)
    assert result["result"] == "HOLD"
    assert result["status_counts"] == {
        "BLOCKED_ENVIRONMENT": 1, "NOT_IMPLEMENTED": 1, "NOT_EXECUTED": 1,
    }
    rows[0]["executed"] = True
    assert gate().aggregate_repair_evidence([r["case_id"] for r in rows], rows)["result"] == "FAIL"


def test_missing_db_readback_cannot_be_full_crash_pass() -> None:
    module = gate()
    case = next(case for case in module.full_required_ids() if case.startswith("SQL-"))
    row = {"case_id": case, "status": "PASS", "executed": True,
           "execution_kind": "BACKEND_ONLY_PROCESS_CRASH",
           "evidence_binding": module.capture_binding(),
           "actual_state_artifact": "/absent/readback.json"}
    assert module.aggregate_repair_evidence([case], [row])["result"] == "FAIL"


def test_empty_or_duplicate_required_set_cannot_pass() -> None:
    module = gate()
    assert module.aggregate_repair_evidence([], [])["result"] == "FAIL"
    assert module.aggregate_repair_evidence(["a", "a"], [])["result"] == "FAIL"


def test_count_only_durability_release_is_rejected() -> None:
    with pytest.raises(ValueError, match="E_DURABILITY_EVIDENCE_REQUIRED"):
        validate_full_durability_release(["invented"], ["invented"], mutation_survivors=0)


def test_supplemental_backend_claims_require_separate_reporting() -> None:
    row = {"vector_id": "SQL-01", "status": "NOT_IMPLEMENTED", "reason": "full owner absent",
           "scoped_result": "PASS", "scoped_evidence": {"actual_state_artifact": "missing"}}
    result = gate().aggregate_repair_evidence(["SQL-01"], [row])
    assert result["result"] == "FAIL"
    assert result["errors"][0]["error"] == "E_REPAIR_SUPPLEMENTAL_MUST_BE_SEPARATE"


def test_release_does_not_accept_subset_or_fabricated_summary() -> None:
    with pytest.raises(ValueError, match="E_DURABILITY_EVIDENCE_NOT_QUALIFIED"):
        validate_full_durability_release(["invented"], ["invented"], mutation_survivors=0,
                                         evidence=[{"case_id": "invented", "status": "PASS"}])
