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
from tests.repairs.test_shared_ingest_persistence import RUN, observation, prepared_store


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
        ("cursor", "E_RESTART_DURABLE_CHAIN"),
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
