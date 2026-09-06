from pathlib import Path

from moj_discovery.vendor import pack_root
from tools.run_clock_vector_qualification import run_clock_vector_qualification

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


def test_cross_language_drift_and_mutation_survivors_are_zero() -> None:
    result = run_clock_vector_qualification(PACK, ROOT)
    assert result["result"] == "HOLD"
    assert result["cross_language_drift"] == result["mutation_survivors"] == 0
    assert result["mutation_executions"] == len(result["mutation_records"]) > 0
    assert [row["case_id"] for row in result["records"]] == result["required_vector_ids"]
    assert result["required_id_set_complete"] is True
    assert result["covered_vector_count"] == sum(
        row["status"] == "PASS" for row in result["records"]
    ) < len(result["required_vector_ids"])
    assert any(row["status"] == "NOT_IMPLEMENTED" for row in result["records"])
