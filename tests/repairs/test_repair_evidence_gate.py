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
from tools import run_indexeddb_crash_matrix as indexeddb

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


@pytest.fixture(scope="module")
def indexeddb_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return indexeddb.run_indexeddb_crash_matrix(
        PACK, tmp_path_factory.mktemp("r08-indexeddb"),
    )


def _crash_rows() -> list[dict[str, Any]]:
    from tools.run_loopback_ack_crash_matrix import run_family

    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    families = dict.fromkeys(entry["harness"] for entry in registry["entries"])
    by_id = {
        row["vector_id"]: row
        for family in families
        for row in run_family(PACK, Path("unused-no-launch"), family, None)["records"]
    }
    return [by_id[entry["vector_id"]] for entry in registry["entries"]]


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


def test_full_inventory_consumes_four_actual_indexeddb_rows(
    clock_report: dict[str, Any], indexeddb_report: dict[str, Any],
) -> None:
    module = gate()
    actual = {row["vector_id"]: row for row in indexeddb_report["records"]}
    crash = [actual.get(row["vector_id"], row) for row in _crash_rows()]
    result = module.aggregate_repair_evidence(
        module.full_required_ids(), [*crash, *clock_report["records"]],
    )
    assert result["result"] == "HOLD"
    assert result["qualification_scope"] == "FULL"
    assert result["status_counts"] == {"PASS": 21, "NOT_IMPLEMENTED": 90}
    assert result["errors"] == []
    assert result["production_authority"] == result["live_authority"] == "NONE"
    assert result["money_authority"] == "NONE"


def test_full_aggregate_runner_replaces_only_indexeddb_holds(tmp_path: Path) -> None:
    workspace = tmp_path / "full"
    result = indexeddb.run_full_repair_evidence(PACK, ROOT, workspace)
    ids = [row.get("case_id", row.get("vector_id")) for row in result["records"]]
    assert ids == gate().full_required_ids()
    assert len(ids) == len(set(ids)) == 111
    assert result["result"] == "HOLD"
    assert result["status_counts"] == {"PASS": 21, "NOT_IMPLEMENTED": 90}
    assert result["errors"] == []
    assert result["security_review"] == "NOT_REVIEWED"
    assert result["production_authority"] == result["live_authority"] == "NONE"
    assert result["money_authority"] == "NONE"
    assert json.loads((workspace / "current-aggregate.json").read_text()) == result


def test_indexeddb_pass_does_not_use_clock_verifier(
    indexeddb_report: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(clock, "verify_record", lambda row: pytest.fail("clock verifier called"))
    row = indexeddb_report["records"][0]
    result = gate().aggregate_repair_evidence([row["vector_id"]], [row])
    assert result["result"] == "PASS"


def test_indexeddb_worker_and_reader_never_receive_expected_state(
    indexeddb_report: dict[str, Any],
) -> None:
    for row in indexeddb_report["records"]:
        for name in ("worker_input_artifact", "reader_input_artifact"):
            payload = json.loads(Path(row[name]["path"]).read_text())
            assert "expected" not in payload
            assert "expected_post_restart_state" not in payload


@pytest.mark.parametrize(
    ("damage", "error"),
    [
        ("revision", "E_REPAIR_STALE_BINDING"),
        ("source", "E_REPAIR_STALE_BINDING"),
        ("environment", "E_INDEXEDDB_ENVIRONMENT"),
        ("artifact", "E_INDEXEDDB_ARTIFACT"),
        ("missing_readback", "E_INDEXEDDB_READBACK"),
        ("expected", "E_INDEXEDDB_EXPECTED"),
        ("oracle_in_actual", "E_INDEXEDDB_ACTUAL_ORACLE"),
        ("command_exit", "E_INDEXEDDB_COMMAND"),
    ],
)
def test_indexeddb_evidence_damage_fails(
    indexeddb_report: dict[str, Any], tmp_path: Path, damage: str, error: str,
) -> None:
    row = copy.deepcopy(indexeddb_report["records"][0])
    if damage in {"revision", "source"}:
        key = "revision" if damage == "revision" else "source_sha256"
        row["evidence_binding"][key] = "wrong"
    elif damage == "environment":
        row["environment"] = {"system": "wrong", "release": "wrong"}
    elif damage == "artifact":
        row["actual_artifact"]["sha256"] = "0" * 64
    elif damage in {"missing_readback", "oracle_in_actual"}:
        actual = copy.deepcopy(row["actual"])
        if damage == "missing_readback":
            actual.pop("entries")
        else:
            actual["expected"] = row["expected"]
        path = tmp_path / f"{damage}.json"
        path.write_text(json.dumps(actual, sort_keys=True, separators=(",", ":")))
        row["actual"] = actual
        row["actual_artifact"] = {
            "path": str(path), "sha256": module_sha256(path),
        }
    elif damage == "expected":
        row["expected"] = {**row["expected"], "indexeddb_spool_delta": 999}
    else:
        row["command_exit"]["reader"] = 1
    result = gate().aggregate_repair_evidence([row["vector_id"]], [row])
    assert result["result"] == "FAIL"
    assert error in result["errors"][0]["error"]


@pytest.mark.parametrize("artifact_name", ["actual_artifact", "worker_input_artifact"])
def test_indexeddb_renamed_oracle_cannot_qualify(
    indexeddb_report: dict[str, Any], tmp_path: Path, artifact_name: str,
) -> None:
    row = copy.deepcopy(indexeddb_report["records"][0])
    payload = copy.deepcopy(
        row["actual"]
        if artifact_name == "actual_artifact"
        else json.loads(Path(row[artifact_name]["path"]).read_text())
    )
    payload["oracle"] = row["expected"]
    path = tmp_path / f"{artifact_name}.json"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    row[artifact_name] = {"path": str(path), "sha256": module_sha256(path)}
    if artifact_name == "actual_artifact":
        row["actual"] = payload
    else:
        row["input_sha256"] = row[artifact_name]["sha256"]

    result = gate().aggregate_repair_evidence([row["vector_id"]], [row])
    assert result["result"] == "FAIL"
    assert "E_INDEXEDDB_" in result["errors"][0]["error"]


def test_indexeddb_nested_worker_options_oracle_cannot_qualify(
    indexeddb_report: dict[str, Any], tmp_path: Path,
) -> None:
    row = copy.deepcopy(indexeddb_report["records"][0])
    for artifact_name in ("worker_input_artifact", "reader_input_artifact"):
        payload = json.loads(Path(row[artifact_name]["path"]).read_text())
        payload["options"]["oracle"] = row["expected"]
        path = tmp_path / f"nested-{artifact_name}.json"
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        row[artifact_name] = {"path": str(path), "sha256": module_sha256(path)}
    row["input_sha256"] = row["worker_input_artifact"]["sha256"]

    result = gate().aggregate_repair_evidence([row["vector_id"]], [row])
    assert result["result"] == "FAIL"
    assert "E_INDEXEDDB_INPUT" in result["errors"][0]["error"]


def module_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


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
         "launch_attempted": False,
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


@pytest.mark.parametrize("status", ["NOT_IMPLEMENTED", "NOT_EXECUTED", "BLOCKED_ENVIRONMENT"])
def test_executed_failure_cannot_be_relabelled_as_unexecuted(
    clock_report: dict[str, Any], status: str,
) -> None:
    trial = copy.deepcopy(clock_report["mutation_records"][0]["actual"]["trial"])
    assert trial["status"] == "FAIL" and trial["executed"] is True
    assert clock.verify_record(trial)
    trial.update(status=status, executed=False, reason="claimed missing prerequisite",
                 implementation_marker="claimed stub", launch_attempted=False,
                 prerequisite={"name": "claimed browser", "available": False})
    result = gate().aggregate_repair_evidence([trial["case_id"]], [trial])
    assert result["result"] == "FAIL"
    assert result["errors"]


@pytest.mark.parametrize("field", ["actual", "actual_artifact", "command_exit", "comparison",
                                   "cross_language_drift", "detected", "mutation_survivors"])
def test_unexecuted_row_cannot_carry_execution_fields(field: str) -> None:
    row = {"case_id": "later", "status": "NOT_EXECUTED", "executed": False,
           "reason": "not attempted", field: None}
    assert gate().aggregate_repair_evidence(["later"], [row])["result"] == "FAIL"


def test_clock_prerequisite_block_occurs_before_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_execute(case: dict[str, Any]) -> dict[str, Any]:
        pytest.fail("missing compiled prerequisite must prevent Python evaluation")

    monkeypatch.setattr(clock, "_python", must_not_execute)
    case = {"case_id": "blocked", "family": "RAW_SAMPLE", "handler": "raw", "section": "test",
            "input": {}, "expected": {}, "evaluator_refs": []}
    row = clock._execute(case, tmp_path, tmp_path / "evidence", {})
    assert row["status"] == "BLOCKED_ENVIRONMENT"
    assert row["executed"] is row["launch_attempted"] is False
    assert not {"actual", "actual_artifact", "comparison", "command_exit"}.intersection(row)
