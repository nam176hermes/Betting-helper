"""Independent process readback of actual offline journal storage."""

import importlib
import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.ingest import Ingestor
from tests.repairs.test_shared_ingest_persistence import (
    BROWSER,
    H0,
    PRODUCER,
    RUN,
    STREAM,
    observation,
    prepared_store,
)


def read(run_dir: Path) -> dict[str, Any]:
    try:
        reader = importlib.import_module("tools.restart_state_reader")
    except ModuleNotFoundError:
        pytest.fail("BH-R02: actual restart reader not implemented")
    result: dict[str, Any] = reader.read_restart_state(run_dir)
    return result


def test_restart_reads_real_rows_in_separate_process_without_expected_input(tmp_path: Path) -> None:
    store = prepared_store(tmp_path)
    ack = Ingestor(store).apply(observation())
    state = read(store.db_path.parent)
    result = subprocess.run(  # noqa: S603 -- fixed local Python reader, synthetic path only
        [sys.executable, "-m", "tools.restart_state_reader", str(store.db_path.parent)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == state
    assert state["run_id"] == RUN
    assert state["tables"]["ack_outbox"] == [ack]
    assert len(state["tables"]["raw_commits"]) == 1
    assert (
        state["tables"]["raw_commits"][0]["raw_observation_id"]
        == observation()["raw_observation_id"]
    )
    # Read-only inspection creates no file or metadata inside the run directory.
    assert sorted(path.name for path in store.db_path.parent.iterdir()) == ["run.sqlite3"]


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN
    run_dir.mkdir()
    with pytest.raises(ValueError, match="E_RESTART_MISSING_DATABASE"):
        read(run_dir)
    assert list(run_dir.iterdir()) == []


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("version", "E_STORE_USER_VERSION"),
        ("schema", "E_STORE_SCHEMA"),
        ("integrity", "E_RESTART_DATABASE"),
        ("identity", "E_RESTART_RUN_IDENTITY"),
        ("cursor", "E_STORE_DURABLE_CHAIN"),
    ],
)
def test_reader_rejects_database_mutations(tmp_path: Path, mutation: str, error: str) -> None:
    store = prepared_store(tmp_path)
    Ingestor(store).apply(observation())
    if mutation == "integrity":
        store.db_path.write_bytes(b"not a SQLite database")
    elif mutation == "identity":
        other = tmp_path / "00000000-0000-4000-8000-000000000099"
        shutil.copytree(store.db_path.parent, other)
        with pytest.raises(ValueError, match=error):
            read(other)
        return
    else:
        # Deliberate corruption uses a separate test connection; never shared runtime code.
        with closing(sqlite3.connect(store.db_path)) as connection, connection:
            if mutation == "version":
                connection.execute("PRAGMA user_version=9")
            elif mutation == "schema":
                connection.execute("CREATE TABLE unrelated(x)")
            else:
                trigger = connection.execute(
                    "SELECT sql FROM sqlite_schema WHERE name='raw_commits_no_update'"
                ).fetchone()[0]
                connection.execute("DROP TRIGGER raw_commits_no_update")
                connection.execute("UPDATE raw_commits SET cursor_hash=?", ("f" * 64,))
                connection.execute(trigger)
    with pytest.raises(ValueError, match=error):
        read(store.db_path.parent)


def test_restart_shows_actual_gap_generations_and_closed_epoch(tmp_path: Path) -> None:
    store = prepared_store(tmp_path)
    Ingestor(store).apply(observation())
    with pytest.raises(ValueError, match="E_INGEST_GAP"):
        Ingestor(store).apply(observation(3))
    state = read(store.db_path.parent)
    generations = state["tables"]["stream_generations"]
    assert {(row["generation"], row["generation_state"]) for row in generations} == {
        (0, "QUARANTINED_GAP"),
        (1, "ACTIVE"),
    }
    assert state["tables"]["coherence_transitions"][0]["to_state"] == "SHOCKED_CLOSED"
    assert state["tables"]["ack_outbox"][0]["highest_contiguous_sequence"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "wrong_owner_binding",
        "zero_predecessor",
        "missing_predecessor",
        "skipped_predecessor",
        "cross_owner",
        "cycle",
        "wrong_hash",
    ],
)
def test_reader_enforces_complete_per_owner_ack_history(tmp_path: Path, mutation: str) -> None:
    store = prepared_store(tmp_path)
    acks = [Ingestor(store).apply(observation(seq)) for seq in (1, 2)]
    with closing(sqlite3.connect(store.db_path)) as connection, connection:
        for owner, verified in (
            ("BACKEND", "BACKEND_DURABLE_CHAIN"),
            ("EXTENSION", "LOCAL_SPOOL_CHAIN"),
        ):
            for sequence in (0, 1, 2):
                connection.execute(
                    "INSERT INTO ack_cursors VALUES (?,?,?,?,?,0,?,?,?,1,?,?,?)",
                    (
                        f"{owner}:{sequence}",
                        RUN,
                        BROWSER,
                        PRODUCER,
                        STREAM,
                        owner,
                        sequence,
                        H0 if sequence == 0 else acks[sequence - 1]["cursor_hash"],
                        verified,
                        None if sequence == 0 else f"{owner}:{sequence - 1}",
                        sequence,
                    ),
                )
        if mutation != "none":
            trigger = connection.execute(
                "SELECT sql FROM sqlite_schema WHERE name='ack_cursors_no_update'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER ack_cursors_no_update")
            changes = {
                "wrong_owner_binding": ("verified_against", "LOCAL_SPOOL_CHAIN", "BACKEND:1"),
                "zero_predecessor": ("previous_ack_cursor_id", "BACKEND:2", "BACKEND:0"),
                "missing_predecessor": ("previous_ack_cursor_id", None, "BACKEND:1"),
                "skipped_predecessor": ("previous_ack_cursor_id", "BACKEND:0", "BACKEND:2"),
                "cross_owner": ("previous_ack_cursor_id", "EXTENSION:1", "BACKEND:2"),
                "cycle": ("previous_ack_cursor_id", "BACKEND:2", "BACKEND:1"),
                "wrong_hash": ("cursor_hash", "f" * 64, "BACKEND:1"),
            }
            column, value, row_id = changes[mutation]
            connection.execute(
                f"UPDATE ack_cursors SET {column}=? WHERE ack_cursor_id=?",  # noqa: S608
                (value, row_id),
            )
            connection.execute(trigger)
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    if mutation == "none":
        assert len(read(store.db_path.parent)["tables"]["ack_cursors"]) == 6
    else:
        with pytest.raises(ValueError, match="^E_STORE_ACK_CHAIN$"):
            read(store.db_path.parent)
        before = store.db_path.read_bytes()
        with pytest.raises(ValueError, match="^E_STORE_ACK_CHAIN$"):
            Ingestor(store).apply(observation(3))
        assert store.db_path.read_bytes() == before
