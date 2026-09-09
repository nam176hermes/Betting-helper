import json
from contextlib import closing
from pathlib import Path

import pytest

from moj_discovery.store import RunStore
from tools.offline_browser import OfflineBrowser
from tools.offline_harness import SliceHarness


def test_real_owned_process_and_reopened_storage(slice_harness: SliceHarness) -> None:
    execution = slice_harness.run_case("OFF-01")
    assert execution.command_exits == [0]
    directory = execution.run_dir.parent
    readback = json.loads((directory / "readback.json").read_text())
    assert readback["reader"]["status"] == "OK"
    assert readback["reader"]["state"]["ackSequence"] == "3"
    assert len(readback["reader"]["retained"]) == 3
    writer = json.loads((directory / "browser/identity.json").read_text())
    reader = json.loads((directory / "reader/identity.json").read_text())
    assert writer["pid"] != reader["pid"]
    assert writer["document"]["origin"] == reader["document"]["origin"]
    assert writer["document"]["origin"].startswith("chrome-extension://")
    assert json.loads((directory / "browser/termination.json").read_text())["graceful"] is False
    with closing(RunStore(execution.run_dir / "run.sqlite3").connect()) as db:
        assert len(db.execute("SELECT * FROM raw_commits").fetchall()) == 3


def test_unowned_existing_profile_is_rejected_before_launch(tmp_path: Path) -> None:
    profile = tmp_path / "unrelated-profile"
    profile.mkdir()
    with pytest.raises(ValueError, match="E_OFFLINE_PROFILE_OWNERSHIP"):
        OfflineBrowser(
            tmp_path / "attempt",
            tmp_path / "offline-extension",
            "chrome-extension://" + "a" * 32,
            profile=profile,
        )
