from pathlib import Path
from uuid import uuid4

import pytest
import rfc8785

from moj_discovery.canonical import canonical_content_hash
from moj_discovery.input_journal import InputJournal
from moj_discovery.replay import verify_replay_equivalence
from tests.offline.test_input_journal import prepared


@pytest.mark.parametrize("order", [(0, 1, 2), (0, 0, 1, 2), (0, 2)])
def test_replay_actual_delivery_order(tmp_path: Path, order: tuple[int, ...]) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    for index in order:
        outcome = journal.apply(rfc8785.dumps(rows[index]), str(uuid4()))
        if outcome["status"] == "APPLIED":
            ack = outcome["ack"]
            journal.record_ack_confirmation(
                "0", str(ack["highest_contiguous_sequence"]), ack["cursor_hash"]
            )
    result = verify_replay_equivalence(store.db_path.parent, tmp_path / "replayed")
    assert result["equal"] is True
    assert result["deliveries"] == len(order)
    assert (tmp_path / "replayed/run.sqlite3").is_file()


def test_replay_conflicting_duplicate(tmp_path: Path) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    journal.apply(rfc8785.dumps(rows[0]), str(uuid4()))
    changed = {**rows[0], "facts": {**rows[0]["facts"], "observation_count": "2"}}
    changed["content_hash"] = canonical_content_hash("RawObservation", changed)
    assert journal.apply(rfc8785.dumps(changed), str(uuid4())) == {
        "status": "REJECTED",
        "code": "CONFLICT",
    }
    assert verify_replay_equivalence(journal.root, tmp_path / "replay")["equal"] is True
