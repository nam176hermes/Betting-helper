from pathlib import Path

import pytest

from tools.offline_harness import SliceHarness


@pytest.fixture
def slice_harness(tmp_path: Path) -> SliceHarness:
    return SliceHarness(tmp_path / "campaign")
