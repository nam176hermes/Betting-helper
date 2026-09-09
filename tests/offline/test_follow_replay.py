from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest
import rfc8785

from moj_discovery.input_journal import InputJournal
from moj_discovery.replay import verify_replay_equivalence
from tests.offline.test_input_journal import prepared


@pytest.mark.parametrize("tamper", [False, True])
def test_replay_follows_actual_deliveries_and_rechecks_closed_source(
    tmp_path: Path, tamper: bool
) -> None:
    store, rows = prepared(tmp_path)
    done = tmp_path / "writer-closed"
    replay_dir = tmp_path / "replay"
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(
            verify_replay_equivalence, store.db_path.parent, replay_dir, writer_closed=done
        )
        try:
            journal = InputJournal(store.db_path.parent)
            journal.apply(rfc8785.dumps(rows[0]), str(uuid4()))
            deadline = monotonic() + 10
            while not (replay_dir / "run.sqlite3").exists():
                if result.done():
                    result.result()
                assert monotonic() < deadline
                sleep(0.02)
            if tamper:
                (store.db_path.parent / "raw" / (rows[0]["content_hash"] + ".json")).write_bytes(
                    b"{}"
                )
        finally:
            done.touch()
        if tamper:
            with pytest.raises(ValueError):
                result.result(timeout=10)
        else:
            assert result.result(timeout=10)["deliveries"] == 1
