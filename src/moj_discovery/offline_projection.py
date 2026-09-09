"""Compare every logical SQLite column, excluding only the supplied physical times."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import rfc8785

from .store import read_journal, validate_journal, verified_ddl, verify_database

CONTRACT = Path(__file__).resolve().parents[2] / "contracts/offline_slice/v1/replay-projection.json"


def semantic_projection(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    if (
        db_path.is_symlink()
        or not db_path.is_file()
        or db_path.stat().st_nlink != 1
        or any(parent.is_symlink() for parent in db_path.parents)
    ):
        raise ValueError("E_OFFLINE_DATABASE_BINDING")
    contract = json.loads(CONTRACT.read_text())
    ddl = verified_ddl().encode()
    blob = hashlib.sha1(
        b"blob " + str(len(ddl)).encode() + b"\0" + ddl, usedforsecurity=False
    ).hexdigest()
    if blob != contract["ddl_git_blob"]:
        raise ValueError("E_OFFLINE_PROJECTION_DDL")
    exclusions = contract["table_time_exclusions"]
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        verify_database(db)
        validate_journal(read_journal(db, ordered=False))
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
        if not set(exclusions).issubset(tables):
            raise ValueError("E_OFFLINE_PROJECTION_TABLE")
        projected = {}
        for table in sorted(tables):
            if not re.fullmatch("[a-z_]+", table):
                raise ValueError("E_OFFLINE_PROJECTION_TABLE")
            cursor = db.execute(f'SELECT * FROM "{table}"')  # noqa: S608 -- verified DDL identifiers
            columns = {column[0] for column in cursor.description}
            excluded = set(exclusions.get(table, []))
            if not excluded.issubset(columns):
                raise ValueError("E_OFFLINE_PROJECTION_COLUMN")
            rows = [{name: row[name] for name in columns - excluded} for row in cursor.fetchall()]
            if table not in exclusions and rows:
                raise ValueError("E_OFFLINE_UNEXPECTED_TABLE_STATE")
            projected[table] = sorted(rows, key=rfc8785.dumps)
        return projected
