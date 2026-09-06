from pathlib import Path

from moj_discovery.vendor import pack_root
from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


def test_sql_transaction_is_all_or_none_after_sigkill(tmp_path: Path) -> None:
    result = run_sqlite_crash_matrix(PACK, tmp_path)
    assert result["result"] == "PASS"
    assert result["killed_child_count"] == 7
    assert result["executed_vector_ids"][-1] == "SQL-07-AFTER-COMMIT-BEFORE-ACK-SEND"
