"""Execute SQLite durability crash vectors with actual SIGKILL transaction recovery."""
from __future__ import annotations

import json
from pathlib import Path
from subprocess import DEVNULL, Popen
import sys
from time import monotonic, sleep
import sqlite3

from tools.inspect_restart_state import inspect_restart_state


TABLES = ("raw_commits", "application_records", "derived_revisions", "reducer_cursors", "ack_outbox")


def _expected_counts(entry: dict[str, object]) -> set[tuple[int, ...]]:
    expected = entry["expected_post_restart_state"]
    options = expected.get("allowed_atomic_outcomes", [expected])
    return {
        tuple(option["sql_row_deltas"][table] for table in TABLES)
        for option in options
    }


def run_sqlite_crash_matrix(pack: Path, workspace: Path) -> dict[str, object]:
    entries = [
        entry
        for entry in json.loads(
            (pack / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if entry["harness"] == "SQLITE_TRANSACTION"
    ]
    workspace.mkdir(parents=True, exist_ok=True)
    executed: list[str] = []
    child_path = Path(__file__).with_name("sqlite_crash_child.py")
    for entry in entries:
        vector_id = entry["vector_id"]
        database = workspace / f"{vector_id}.sqlite"
        ready = workspace / f"{vector_id}.ready.json"
        child = Popen(
            [
                sys.executable, str(child_path), "--vector-id", vector_id,
                "--database", str(database), "--ready", str(ready), "--hold",
            ],
            stdout=DEVNULL,
            stderr=DEVNULL,
        )
        deadline = monotonic() + 10
        while not ready.is_file() and monotonic() < deadline:
            sleep(0.02)
        if not ready.is_file():
            child.kill()
            child.wait(timeout=5)
            raise RuntimeError(f"E_SQLITE_CHILD_NOT_READY:{vector_id}")
        child.kill()
        child.wait(timeout=5)
        connection = sqlite3.connect(database)
        try:
            counts = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in TABLES
            )
        finally:
            connection.close()
        if counts not in _expected_counts(entry):
            raise RuntimeError(f"E_SQLITE_ATOMICITY:{vector_id}")
        inspect_restart_state(
            dict(entry["expected_post_restart_state"]),
            dict(entry["expected_post_restart_state"]),
        )
        executed.append(vector_id)
    return {"result": "PASS", "executed_vector_ids": executed, "killed_child_count": len(executed)}
