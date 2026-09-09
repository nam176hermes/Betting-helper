import json

import pytest

from tools.offline_harness import SliceHarness
from tools.offline_oracle import assert_case


def test_sensitive_variants_rejected_and_persisted_leak_detected(
    slice_harness: SliceHarness,
) -> None:
    execution = slice_harness.run_case("OFF-11")
    directory = execution.run_dir.parent
    actual = json.loads((directory / "readback.json").read_text())
    rejected = [r for r in actual["writer"] if r.get("status") == "REJECTED"]
    assert len(rejected) == 5
    assert assert_case("OFF-11", execution.run_dir)["oracle_passed"]
    context = json.loads((execution.run_dir / "context.json").read_text())
    (directory / "leaked.log").write_text("synthetic-poison-" + context["run_id"] + "-token")
    with pytest.raises(AssertionError):
        assert_case("OFF-11", execution.run_dir)
