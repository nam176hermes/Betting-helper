import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
import rfc8785

from moj_discovery.input_journal import InputJournal
from moj_discovery.replay import verify_replay_equivalence
from tests.offline.test_input_journal import prepared


@pytest.mark.parametrize("mutation", ["missing-raw", "changed-raw", "receive-order", "db-cursor"])
def test_replay_rejects_changed_actuals(tmp_path: Path, mutation: str) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    for row in rows:
        outcome = journal.apply(rfc8785.dumps(row), str(uuid4()))
        ack = outcome["ack"]
        journal.record_ack_confirmation(
            "0", str(ack["highest_contiguous_sequence"]), ack["cursor_hash"]
        )
    raw_path = journal.root / "raw" / (rows[0]["content_hash"] + ".json")
    if mutation == "missing-raw":
        raw_path.rename(raw_path.with_suffix(".retained-test-original"))
    elif mutation == "changed-raw":
        raw_path.write_bytes(b"{}")
    elif mutation == "receive-order":
        lines = journal.path.read_bytes().splitlines(keepends=True)
        lines[0], lines[3] = lines[3], lines[0]
        journal.path.write_bytes(b"".join(lines))
    else:
        # Deliberate on-disk corruption in this disposable DB, preserving the final DDL.
        with closing(sqlite3.connect(store.db_path)) as db, db:
            trigger = db.execute(
                "SELECT sql FROM sqlite_schema WHERE name='ack_cursors_no_update'"
            ).fetchone()[0]
            db.execute("DROP TRIGGER ack_cursors_no_update")
            db.execute("UPDATE ack_cursors SET cursor_hash=?", ("0" * 64,))
            db.execute(trigger)
    with pytest.raises((ValueError, OSError)):
        verify_replay_equivalence(journal.root, tmp_path / "replay")


def test_parent_wrong_expectation_does_not_change_actual_replay(tmp_path: Path) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    journal.apply(rfc8785.dumps(rows[0]), str(uuid4()))
    actual = verify_replay_equivalence(journal.root, tmp_path / "replay")
    before = (tmp_path / "replay/replay-result.json").read_bytes()
    with pytest.raises(AssertionError):
        assert actual["deliveries"] == 999999
    assert (tmp_path / "replay/replay-result.json").read_bytes() == before
    assert json.loads(before)["deliveries"] == 1
