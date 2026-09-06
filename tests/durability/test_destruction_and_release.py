from pathlib import Path

from moj_discovery.durability_release import validate_full_durability_release
from moj_discovery.vendor import pack_root
from tools.run_destruction_crash_matrix import run_destruction_crash_matrix

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


def test_declared_equals_executed_and_mutation_survivors_zero(tmp_path: Path) -> None:
    result = run_destruction_crash_matrix(PACK, tmp_path)
    receipt = validate_full_durability_release(
        result["declared_vector_ids"], result["executed_vector_ids"], mutation_survivors=0
    )
    assert result["result"] == "PASS"
    assert result["killed_child_count"] == 7
    assert receipt == {"result": "PASS", "declared_count": 7, "mutation_survivors": 0}
