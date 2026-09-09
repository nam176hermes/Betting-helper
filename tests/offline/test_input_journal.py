import os
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import rfc8785

from moj_discovery.canonical import canonical_content_hash
from moj_discovery.ingest import Ingestor
from moj_discovery.input_journal import InputJournal
from moj_discovery.offline_run import create_offline_run
from moj_discovery.store import RunStore
from moj_discovery.synthetic_source import load_synthetic_observations
from tests.offline.test_synthetic_source import context, scenario


def prepared(tmp_path: Path) -> tuple[RunStore, list[dict[str, Any]]]:
    ctx = context()
    store = create_offline_run(tmp_path / "run", ctx)
    rows = load_synthetic_observations(scenario(tmp_path / "scenario.json", ctx))
    return store, rows


def test_committed_input_is_available_after_restart(tmp_path: Path) -> None:
    store, rows = prepared(tmp_path)
    raw = rows[0]
    journal = InputJournal(store.db_path.parent)
    result = journal.apply(rfc8785.dumps(raw), str(uuid4()))
    retained = store.db_path.parent / "raw" / (raw["content_hash"] + ".json")
    assert retained.read_bytes() == rfc8785.dumps(raw)
    assert result["status"] == "APPLIED"
    operations = list(InputJournal(store.db_path.parent).iter_operations())
    assert operations[0]["raw"] == raw
    assert operations[1]["outcome"] == result


@pytest.mark.parametrize("after_commit", [False, True])
def test_pending_input_reconciles_actual_database(tmp_path: Path, after_commit: bool) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    journal.record_received(rfc8785.dumps(rows[0]), str(uuid4()))
    if after_commit:
        Ingestor(store).apply(rows[0])
    assert InputJournal(store.db_path.parent).reconcile(store) == {"reconciled_operations": 1}
    with closing(store.connect()) as connection:
        assert len(connection.execute("SELECT * FROM raw_commits").fetchall()) == 1
    assert list(journal.iter_operations())[-1]["outcome"]["status"] == "APPLIED"


@pytest.mark.parametrize("mutation", ["missing", "changed", "symlink", "hardlink"])
def test_raw_substitution_rejected(tmp_path: Path, mutation: str) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    journal.apply(rfc8785.dumps(rows[0]), str(uuid4()))
    raw = store.db_path.parent / "raw" / (rows[0]["content_hash"] + ".json")
    if mutation == "missing":
        raw.unlink()
    elif mutation == "changed":
        raw.write_bytes(b"{}")
    elif mutation == "symlink":
        other = tmp_path / "replacement"
        other.write_bytes(raw.read_bytes())
        raw.unlink()
        raw.symlink_to(other)
    else:
        os.link(raw, tmp_path / "linked")
    with pytest.raises((ValueError, OSError)):
        list(journal.iter_operations())


def test_poison_creates_no_journal_or_raw_file(tmp_path: Path) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    with pytest.raises(ValueError, match="E_OFFLINE_SCHEMA"):
        journal.apply(rfc8785.dumps({**rows[0], "cookie": "synthetic-poison"}), str(uuid4()))
    assert not journal.path.exists()
    assert list((store.db_path.parent / "raw").iterdir()) == []


def test_partial_tail_is_preserved_before_recovery(tmp_path: Path) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    journal.record_received(rfc8785.dumps(rows[0]), str(uuid4()))
    with journal.path.open("ab") as output:
        output.write(b'{"row_index":2')
    before = journal.path.read_bytes()
    with pytest.raises(ValueError, match="PARTIAL_TAIL"):
        list(journal.iter_operations())
    journal.reconcile(store)
    tails = list(store.db_path.parent.glob("partial-tail-*.jsonl"))
    assert len(tails) == 1 and tails[0].read_bytes() == before
    assert list(journal.iter_operations())[-1]["outcome"]["status"] == "APPLIED"


def test_committed_gap_without_outcome_recovers_same_rejection(tmp_path: Path) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    journal.apply(rfc8785.dumps(rows[0]), str(uuid4()))
    journal.record_received(rfc8785.dumps(rows[2]), str(uuid4()))
    with pytest.raises(ValueError, match="E_INGEST_GAP"):
        Ingestor(store).apply(rows[2])
    journal.reconcile(store)
    assert list(journal.iter_operations())[-1]["outcome"] == {"status": "REJECTED", "code": "GAP"}


def test_existing_ack_cannot_confirm_different_payload(tmp_path: Path) -> None:
    store, rows = prepared(tmp_path)
    journal = InputJournal(store.db_path.parent)
    first = journal.apply(rfc8785.dumps(rows[0]), str(uuid4()))
    changed = {**rows[0], "facts": {**rows[0]["facts"], "observation_count": "2"}}
    changed["content_hash"] = canonical_content_hash("RawObservation", changed)
    index = journal.record_received(rfc8785.dumps(changed), str(uuid4()))
    with pytest.raises(ValueError, match="E_OFFLINE_OUTCOME_BINDING"):
        journal.record_outcome(index, first)
