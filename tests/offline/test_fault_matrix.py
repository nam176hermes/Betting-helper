import pytest

from tools.offline_harness import SliceHarness
from tools.offline_oracle import assert_case


@pytest.mark.parametrize(
    "case_id",
    [
        "OFF-08",
        "OFF-09",
        "OFF-10",
        "OFF-23",
        "OFF-03",
        "OFF-04",
        "OFF-05",
        "OFF-06",
        "OFF-07",
        "OFF-11",
        "OFF-12",
        "OFF-15",
        "OFF-16",
        "OFF-17",
        "OFF-24",
        "OFF-26",
        "OFF-27",
    ],
)
def test_real_fault_case(slice_harness: SliceHarness, case_id: str) -> None:
    execution = slice_harness.run_case(case_id)
    assert assert_case(case_id, execution.run_dir)["oracle_passed"] is True
