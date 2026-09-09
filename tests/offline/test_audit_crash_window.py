import json

import pytest

from tools.offline_harness import SliceHarness
from tools.offline_oracle import assert_case


def test_ack_delivery_before_local_persistence_crash(slice_harness: SliceHarness) -> None:
    execution = slice_harness.run_case("OFF-06")
    directory = execution.run_dir.parent
    path = directory / "readback.json"
    observed = json.loads(path.read_text())
    points = [p for row in observed["writer"] for p in row.get("checkpoints", [])]
    assert any(p["stage"] == "AFTER_ACK_BEFORE_LOCAL_PERSIST" for p in points)
    assert assert_case("OFF-06", execution.run_dir)["oracle_passed"]
    observed["writer"] = [r for r in observed["writer"] if r.get("operation") != "RESTART_WORKER"]
    path.write_text(json.dumps(observed))
    with pytest.raises(AssertionError):
        assert_case("OFF-06", execution.run_dir)
