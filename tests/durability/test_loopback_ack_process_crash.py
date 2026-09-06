from pathlib import Path

from moj_discovery.vendor import pack_root
from tools.run_loopback_ack_crash_matrix import run_loopback_ack_crash_matrix

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


def test_ack_never_crosses_uncommitted_or_gapped_position(tmp_path: Path) -> None:
    result = run_loopback_ack_crash_matrix(PACK, tmp_path)
    assert result["result"] == "PASS"
    assert result["killed_child_count"] == 7
    assert result["executed_vector_ids"][0] == "SEND-01-AFTER-SEND-BEFORE-BACKEND-BEGIN"
    assert result["executed_vector_ids"][-1] == "ACK-06-DUPLICATE-IDENTICAL"
