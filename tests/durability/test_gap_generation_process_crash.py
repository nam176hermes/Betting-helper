from pathlib import Path

from moj_discovery.vendor import pack_root
from tools.run_gap_coherence_crash_matrix import run_gap_coherence_crash_matrix

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


def test_closed_generation_and_epoch_never_reopen(tmp_path: Path) -> None:
    result = run_gap_coherence_crash_matrix(PACK, tmp_path)
    assert result["result"] == "PASS"
    assert result["killed_child_count"] == 21
    assert "EPOCH-05-NEW-SHOCK-WHILE-PENDING" in result["executed_vector_ids"]
