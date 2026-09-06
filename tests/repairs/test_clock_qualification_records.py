"""Qualification must compare actual executions, including same-wrong parity."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from shutil import which
from subprocess import run
from typing import Any

import pytest

from tools import run_clock_vector_qualification as runner
from tools import verify_repair_evidence as evidence_gate

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"
VECTORS = "docs/vectors/inherited/clock-coherence-v6.2.json"
COVERAGE = "docs/registries/clock-vector-coverage.v1.json"

MUTATION_IDS = {
    "wrong_expected_error", "inverse_eligibility", "raw_timestamp",
    "missing_result", "duplicate_result", "same_wrong_result",
    "hash_field_removal", "drift_input_change", "midpoint_corruption",
    "selection_candidate_order", "post_close_selection",
    "candidate_proof_corruption", "release_mapping_close",
}


def changed_pack(tmp_path: Path, field: str, value: object) -> Path:
    pack = tmp_path / "pack"
    for relative in (VECTORS, COVERAGE):
        target = pack / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads((PACK / relative).read_text())
        if relative == VECTORS:
            data["mapping_negative_vectors"][0][field] = value
        target.write_text(json.dumps(data))
    return pack


@pytest.mark.parametrize(("field", "value"), [
    ("expected_error", "E_WRONG_EXPECTATION"), ("mapping_eligible", True),
])
def test_wrong_expectation_cannot_pass_even_when_languages_agree(
    tmp_path: Path, field: str, value: object,
) -> None:
    result = runner.run_clock_vector_qualification(changed_pack(tmp_path, field, value), ROOT)
    assert result["result"] == "FAIL"
    row = next(row for row in result["records"] if row["case_id"] == "MAP-NEG-01-TARGET-ORDER")
    assert row["status"] == "FAIL"
    assert row["comparison"]["diff"]
    assert row["cross_language_drift"] is False


def test_actual_artifacts_and_mutations_have_recomputable_counters(tmp_path: Path) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    assert result["result"] == "PASS"
    rows = result["records"]
    assert result["covered_vector_count"] == sum(row["status"] == "PASS" for row in rows) == 65
    assert result["skipped_vectors"] == sum(not row["executed"] for row in rows) == 0
    assert result["mutation_executions"] == len(result["mutation_records"]) == 13
    assert {row["case_id"] for row in result["mutation_records"]} == MUTATION_IDS
    assert result["mutation_survivors"] == sum(
        not row["detected"] for row in result["mutation_records"]
    ) == 0
    for row in [*rows, *result["mutation_records"]]:
        assert runner.verify_record(row)
        assert row["environment"]["python"]
        assert row["code"]["revision"]
        assert row["input_sha256"] and row["expected_sha256"]
    unknown = next(row for row in rows if row["case_id"] == "MAP-NEG-16-UNMAPPED-CDP")
    assert unknown["actual"]["python"]["source_age"] == "UNKNOWN"
    assert unknown["actual"]["python"]["accepted"] is False
    assert unknown["status"] == "PASS"


def test_primitive_rows_bind_real_cross_language_and_sql_artifacts(tmp_path: Path) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    primitive_rows = [
        row for row in result["records"]
        if row["case_id"].startswith(("CLOCK-HASH-", "DRIFT-", "MIDPOINT-"))
    ]
    assert len(primitive_rows) == 10
    for row in primitive_rows:
        assert row["status"] == "PASS"
        assert row["executed"] is True
        assert row["cross_language_drift"] is False
        assert set(row["evaluator_artifacts"]) == {"python", "typescript"}
        assert all(key != "id" and not key.startswith("expected") for key in row["input"])
        assert runner.verify_record(row)
    for row in primitive_rows:
        if row["case_id"].startswith("MIDPOINT-"):
            assert row["sql_observation"]["ddl_sha256"]
            assert row["sql_observation_artifact"]["sha256"]


def test_three_clock_primitive_mutations_are_executed_and_detected(tmp_path: Path) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    rows = {row["case_id"]: row for row in result["mutation_records"]}
    for name in ("hash_field_removal", "drift_input_change", "midpoint_corruption"):
        assert rows[name]["executed"] is True
        assert rows[name]["detected"] is True
        assert runner.verify_record(rows[name])


def test_selection_and_closure_rows_bind_real_cross_language_artifacts(tmp_path: Path) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    rows = [
        row for row in result["records"]
        if row["case_id"].startswith(("SELECT-", "CLOSE-"))
    ]
    assert len(rows) == 14
    for row in rows:
        assert row["status"] == "PASS"
        assert row["executed"] is True
        assert row["cross_language_drift"] is False
        assert set(row["evaluator_artifacts"]) == {"python", "typescript"}
        assert all(key != "id" and not key.startswith("expected") for key in row["input"])
        assert runner.verify_record(row)


def test_post_close_mutation_is_executed_and_detected(tmp_path: Path) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    rows = {row["case_id"]: row for row in result["mutation_records"]}
    mutation = rows["post_close_selection"]
    assert mutation["executed"] is True
    assert mutation["detected"] is True
    assert runner.verify_record(mutation)
    control = mutation["actual"]["control"]
    trial = mutation["actual"]["trial"]
    assert "close_before_select" not in control["input"]
    assert "close_before_select" not in trial["input"]
    for row in (control, trial):
        for language in ("python", "typescript"):
            assert row["actual"][language]["closure_executed"] is True
    assert control["actual"]["python"]["history"][0]["mapping_id"] == "MAP:" + "c" * 64
    assert trial["actual"]["python"]["history"][0]["mapping_id"].endswith("-MUTATED")
    assert trial["actual"]["python"]["accepted"] is True


def test_selection_order_mutation_executes_real_selection_without_metadata_detection(
    tmp_path: Path,
) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    mutation = next(
        row for row in result["mutation_records"]
        if row["case_id"] == "selection_candidate_order"
    )
    assert mutation["executed"] is True
    assert mutation["detected"] is True
    assert runner.verify_record(mutation)
    control = mutation["actual"]["control"]
    trial = mutation["actual"]["trial"]
    for row in (control, trial):
        assert row["executed"] is True
        assert set(row["evaluator_artifacts"]) == {"python", "typescript"}
        assert "operation_metadata" not in row
    assert control["actual"]["python"]["mapping_id"] != trial["actual"]["python"]["mapping_id"]
    assert trial["status"] == "FAIL"


def test_candidate_proof_and_release_mapping_mutations_execute_real_operations(
    tmp_path: Path,
) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    rows = {row["case_id"]: row for row in result["mutation_records"]}
    for name in ("candidate_proof_corruption", "release_mapping_close"):
        assert rows[name]["executed"] is True
        assert rows[name]["detected"] is True
        assert runner.verify_record(rows[name])
    candidate = rows["candidate_proof_corruption"]["actual"]
    assert candidate["control"]["actual"]["python"]["accepted"] is True
    assert candidate["trial"]["actual"]["python"]["error"] == "E_RESNAPSHOT_CANDIDATE_BINDING"
    release = rows["release_mapping_close"]["actual"]
    for phase in ("control", "trial"):
        for language in ("python", "typescript"):
            assert "mapping_close_executed" not in release[phase]["actual"][language]
            assert release[phase]["operation_metadata"][language][
                "mapping_close_executed"
            ] is True
    assert release["control"]["actual"]["python"]["accepted"] is True
    assert release["trial"]["actual"]["python"]["error"] == "E_MAPPING_CLOSED"


def test_release_mapping_guard_bypass_makes_mutation_survive_and_fail_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runner._mutations

    def bypass(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return original(*args, **kwargs, bypass_release_mapping_guard=True)

    monkeypatch.setattr(runner, "_mutations", bypass)
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    mutation = next(
        row for row in result["mutation_records"] if row["case_id"] == "release_mapping_close"
    )
    assert mutation["executed"] is True
    assert mutation["detected"] is False
    assert mutation["actual"]["trial"]["status"] == "PASS"
    assert result["mutation_survivors"] == 1
    assert result["result"] == "FAIL"


@pytest.mark.parametrize("damage", ["tamper", "remove"])
def test_imported_coherence_javascript_is_bound_and_damage_fails_evidence(
    tmp_path: Path, damage: str,
) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    row = next(item for item in result["records"] if item["case_id"] == "RELEASE-POS-01")
    executable = ROOT / "extension/.test-build/src/contracts/clock-coherence.js"
    key = "extension/.test-build/src/contracts/clock-coherence.js"
    assert key in row["evidence_binding"]["source_sha256"]
    assert str(executable.resolve()) in row["code"]["sha256"]
    original = executable.read_bytes()
    try:
        if damage == "tamper":
            executable.write_bytes(original + b"\n// tampered\n")
        else:
            executable.unlink()
        checked = evidence_gate.aggregate_repair_evidence([row["case_id"]], [row])
        assert checked["result"] == "FAIL"
        assert any("E_REPAIR_STALE_BINDING" in error["error"]
                   or "E_REPAIR_SOURCE" in error["error"] for error in checked["errors"])
    finally:
        executable.write_bytes(original)


def test_same_wrong_evaluators_fail_independent_numeric_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runner._python

    def wrong(case: dict[str, Any], **_kwargs: object) -> dict[str, Any]:
        actual = original(case)
        actual["network_rtt_us"] = 0
        return actual

    monkeypatch.setattr(runner, "_python", wrong)
    monkeypatch.setattr(runner, "_typescript", lambda case, runtime, **kwargs: wrong(case))
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    golden = next(row for row in result["records"] if row["case_id"].startswith("CLOCK-GOLDEN"))
    assert golden["status"] == "FAIL"
    assert golden["cross_language_drift"] is False
    assert golden["comparison"]["diff"]["python"]["network_rtt_us"] == {
        "expected": 400, "actual": 0,
    }


def test_missing_duplicate_and_tampered_artifacts_fail(tmp_path: Path) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    rows = result["records"]
    for changed in (rows[1:], [*rows, copy.deepcopy(rows[0])]):
        assert runner.summarize(result["required_vector_ids"], changed)["result"] == "FAIL"
    executed = next(row for row in rows if row["executed"])
    artifact = Path(executed["actual_artifact"]["path"])
    artifact.write_text("{}")
    assert not runner.verify_record(executed)
    assert runner.summarize(result["required_vector_ids"], rows)["result"] == "FAIL"


@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_damaged_mutation_evidence_fails_without_erasing_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str,
) -> None:
    original = runner._mutations

    def damaged(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        rows = original(*args, **kwargs)
        artifact = Path(rows[0]["actual"]["trial"]["actual_artifact"]["path"])
        if damage == "missing":
            artifact.unlink()
        else:
            artifact.write_text("{}")
        return rows

    monkeypatch.setattr(runner, "_mutations", damaged)
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    assert result["result"] == "FAIL"
    assert result["mutation_attempts"] == result["mutation_executions"] == 13
    assert result["mutation_verified_executions"] == 12
    assert result["mutation_survivors"] is None
    assert result["mutation_evidence_errors"] == [{
        "case_id": "wrong_expected_error", "error": "E_CLOCK_MUTATION_EVIDENCE",
    }]
    assert len(result["mutation_records"]) == 13
    assert result["covered_vector_count"] == 65


def test_recursive_artifact_and_stale_binding_damage_fail(tmp_path: Path) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)

    nested = copy.deepcopy(result["mutation_records"][0])
    nested["actual"]["trial"]["evidence_binding"]["revision"] = "stale"
    assert runner.verify_record(nested) is False

    evaluator = copy.deepcopy(result["records"][0])
    Path(evaluator["evaluator_artifacts"]["python"]["path"]).unlink()
    assert runner.verify_record(evaluator) is False


def test_retained_typescript_graph_verifies_after_clean_generated_restore(
    tmp_path: Path,
) -> None:
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    generated = {
        relative: ROOT / "extension/.test-build/src" / relative
        for relative in (
            "contracts/clock-vectors.js", "contracts/clock-coherence.js",
            "canonical.js", "schema-registry.js", "errors.js",
        )
    }
    compiled = {relative: path.read_bytes() for relative, path in generated.items()}
    try:
        git = which("git")
        assert git is not None
        tracked = run(  # noqa: S603 -- fixed local git and tracked path
            [git, "show", "HEAD:extension/.test-build/src/contracts/clock-vectors.js"],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout
        generated["contracts/clock-vectors.js"].write_bytes(tracked)
        generated["contracts/clock-coherence.js"].unlink()

        assert runner.summarize(result["required_vector_ids"], result["records"])[
            "result"
        ] == "PASS"
        assert all(runner.verify_record(row) for row in result["mutation_records"])

        row = result["records"][0]
        assert all("/.test-build/" not in path for path in row["code"]["sha256"])
        assert all(
            not path.startswith("extension/.test-build/")
            for path in row["evidence_binding"]["source_sha256"]
        )
        retained = row["typescript_executable_artifacts"]
        retained_path = Path(retained["contracts/clock-vectors.js"]["path"])
        retained_content = retained_path.read_bytes()
        retained_path.write_bytes(retained_content + b"\n// tampered\n")
        assert runner.summarize(result["required_vector_ids"], result["records"])[
            "result"
        ] == "FAIL"
        assert not runner.verify_record(result["mutation_records"][0])
        retained_path.write_bytes(retained_content)
        retained_path.unlink()
        assert runner.summarize(result["required_vector_ids"], result["records"])[
            "result"
        ] == "FAIL"
        assert not runner.verify_record(result["mutation_records"][0])
    finally:
        for relative, content in compiled.items():
            generated[relative].parent.mkdir(parents=True, exist_ok=True)
            generated[relative].write_bytes(content)


@pytest.mark.parametrize("damage", ["remove", "duplicate"])
def test_missing_or_duplicate_mutation_row_fails_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str,
) -> None:
    original = runner._mutations

    def damaged(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        rows = original(*args, **kwargs)
        return rows[1:] if damage == "remove" else [*rows, copy.deepcopy(rows[0])]

    monkeypatch.setattr(runner, "_mutations", damaged)
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    assert result["mutation_id_set_complete"] is False
    assert result["result"] == "FAIL"


def test_cli_rejects_missing_evidence_directory() -> None:
    completed = run(  # noqa: S603 -- fixed local Python and script path
        [sys.executable, str(ROOT / "tools/run_clock_vector_qualification.py")],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "--evidence-dir" in completed.stderr
