import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

from moj_discovery.governance import validate_durability_vectors


def _row_counts(connection: sqlite3.Connection) -> list[int]:
    queries = (
        "SELECT count(*) FROM raw_commits",
        "SELECT count(*) FROM application_records",
        "SELECT count(*) FROM derived_revisions",
        "SELECT count(*) FROM reducer_cursors",
        "SELECT count(*) FROM ack_outbox",
    )
    return [connection.execute(query).fetchone()[0] for query in queries]


def test_real_sigkill_rolls_back_each_statement_boundary(tmp_path: Path) -> None:
    ddl = Path("vendor/hybrid-discovery-v6.3.6/sql/discovery-store-v1.sql")
    for boundary in ("1", "2", "3", "4", "5", "commit"):
        database = tmp_path / f"crash-{boundary}.sqlite"
        child = subprocess.Popen(  # noqa: S603 - fixed local harness argv
            [sys.executable, "-u", "tools/sql_crash_child.py", str(database), str(ddl), boundary],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert child.stdout is not None and child.stdout.readline().strip() == "READY"
        os.kill(child.pid, signal.SIGKILL)
        child.wait()
        with sqlite3.connect(database) as connection:
            assert _row_counts(connection) == [0] * 5
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    database = tmp_path / "committed.sqlite"
    subprocess.run(  # noqa: S603 - fixed local harness argv
        [sys.executable, "tools/sql_crash_child.py", str(database), str(ddl), "after"], check=True
    )
    with sqlite3.connect(database) as connection:
        assert _row_counts(connection) == [1] * 5


def test_all_46_restart_contracts_have_executable_exact_post_restart_state() -> None:
    validate_durability_vectors()
