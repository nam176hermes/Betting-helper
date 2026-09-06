"""Qualification must compare actual executions, including same-wrong parity."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tools import run_clock_vector_qualification as runner

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"
VECTORS = "docs/vectors/inherited/clock-coherence-v6.2.json"
COVERAGE = "docs/registries/clock-vector-coverage.v1.json"


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
    assert result["result"] == "HOLD"
    rows = result["records"]
    assert result["covered_vector_count"] == sum(row["status"] == "PASS" for row in rows) == 17
    assert result["skipped_vectors"] == sum(not row["executed"] for row in rows) == 48
    assert result["mutation_executions"] == len(result["mutation_records"]) == 6
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


def test_same_wrong_evaluators_fail_independent_numeric_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runner._python

    def wrong(case: dict[str, Any]) -> dict[str, Any]:
        actual = original(case)
        actual["network_rtt_us"] = 0
        return actual

    monkeypatch.setattr(runner, "_python", wrong)
    monkeypatch.setattr(runner, "_typescript", lambda case, runtime: wrong(case))
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
    artifact = Path(rows[0]["actual_artifact"]["path"])
    artifact.write_text("{}")
    assert not runner.verify_record(rows[0])
    assert runner.summarize(result["required_vector_ids"], rows)["result"] == "FAIL"
