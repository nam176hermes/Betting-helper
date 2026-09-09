"""Explicit offline-only SQLite denial, retaining the actual authorization decision."""

import os
import sqlite3
from pathlib import Path
from typing import Any

import rfc8785

from .store import RunStore, _runtime_authorizer


class WriteDeniedStore(RunStore):
    def __init__(self, db_path: Path, event_path: Path):
        super().__init__(db_path)
        self.event_path = event_path

    def connect(self) -> sqlite3.Connection:
        db = super().connect()
        committed = db.execute(
            "SELECT raw_observation_content_hash FROM raw_commits ORDER BY sequence"
        ).fetchall()
        if len(committed) == 2:

            def authorize(
                action: int,
                table: str | None,
                column: str | None,
                database: str | None,
                trigger: str | None,
            ) -> int:
                if action == sqlite3.SQLITE_INSERT and table == "raw_commits":
                    event: dict[str, Any] = {
                        "operation": "SQLITE_DENY",
                        "action": action,
                        "table": table,
                        "committed_hashes": [row[0] for row in committed],
                    }
                    descriptor = os.open(
                        self.event_path,
                        os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                        0o600,
                    )
                    with os.fdopen(descriptor, "ab") as output:
                        output.write(rfc8785.dumps(event) + b"\n")
                        output.flush()
                        os.fsync(output.fileno())
                    return sqlite3.SQLITE_DENY
                return _runtime_authorizer(action, table, column, database, trigger)

            db.set_authorizer(authorize)
        return db
