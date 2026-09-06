from pathlib import Path

from moj_discovery.vendor import pack_root
from tools.run_clock_vector_qualification import run_clock_vector_qualification

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


def test_cross_language_drift_and_mutation_survivors_are_zero() -> None:
    result = run_clock_vector_qualification(PACK, ROOT)
    assert result == {
        "result": "PASS",
        "covered_vector_count": 65,
        "cross_language_drift": 0,
        "mutation_survivors": 0,
        "skipped_vectors": 0,
    }
