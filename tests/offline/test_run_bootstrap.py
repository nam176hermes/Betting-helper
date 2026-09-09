from contextlib import closing
from pathlib import Path

import pytest

from moj_discovery.offline_run import create_offline_run
from moj_discovery.store import read_journal
from tests.offline.test_synthetic_source import context


def test_fresh_run_contains_only_legitimate_seed_rows(tmp_path: Path) -> None:
    ctx = context()
    store = create_offline_run(tmp_path / "run", ctx)
    with closing(store.connect()) as connection:
        tables = read_journal(connection)
    assert len(tables["run_meta"]) == len(tables["stream_generations"]) == 1
    assert tables["raw_commits"] == tables["application_records"] == tables["ack_outbox"] == []
    assert tables["run_meta"][0]["run_id"] == ctx["run_id"]
    with pytest.raises(FileExistsError):
        create_offline_run(tmp_path / "run", ctx)
