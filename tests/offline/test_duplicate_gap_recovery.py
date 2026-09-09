import pytest

from tools.offline_harness import SliceHarness
from tools.offline_oracle import assert_case


@pytest.mark.parametrize("case_id", ["OFF-02", "OFF-13", "OFF-14"])
def test_real_duplicate_gap_conflict(slice_harness: SliceHarness, case_id: str) -> None:
    execution = slice_harness.run_case(case_id)
    assert assert_case(case_id, execution.run_dir)["oracle_passed"] is True
