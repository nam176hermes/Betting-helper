from pathlib import Path

from moj_discovery.vendor import pack_root
from tools.run_indexeddb_crash_matrix import run_indexeddb_crash_matrix

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


def test_all_indexeddb_vectors_match_expected_restart_state(tmp_path: Path) -> None:
    result = run_indexeddb_crash_matrix(PACK, tmp_path)
    assert result["result"] == "PASS"
    assert result["executed_vector_ids"] == [
        "IDB-01-BEFORE-TRANSACTION",
        "IDB-02-DURING-SEQUENCE-ALLOCATION",
        "IDB-03-DURING-ROW-PUT",
        "IDB-04-AFTER-COMMIT",
    ]
    assert result["killed_child_count"] == 4
