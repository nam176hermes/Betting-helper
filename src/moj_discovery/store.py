"""Offline SQLite storage using the unmodified governed bootstrap schema."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .errors import ContractNotImplementedError

VENDOR = Path(__file__).resolve().parents[2] / "vendor/hybrid-discovery-v6.3.6"


def verified_ddl() -> str:
    relative = "sql/discovery-store-v1.sql"
    lock = json.loads((VENDOR.parents[1] / "schema-lock.json").read_text())
    content = (VENDOR / relative).read_bytes()
    matches = [item for item in lock["files"] if item["path"] == relative]
    if len(matches) != 1 or hashlib.sha256(content).hexdigest() != matches[0]["sha256"]:
        raise ValueError("E_STORE_DDL_HASH")
    return content.decode("utf-8")


def verify_database(connection: sqlite3.Connection) -> None:
    """Compare complete schema objects, including constraints and all triggers."""
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("E_STORE_USER_VERSION")
    if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
        raise ValueError("E_STORE_INTEGRITY")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("E_STORE_FOREIGN_KEY")
    query = "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.executescript(verified_ddl())
        expected = reference.execute(query).fetchall()
    if [tuple(row) for row in connection.execute(query)] != expected:
        raise ValueError("E_STORE_SCHEMA")


def _runtime_authorizer(
    action: int, first: str | None, second: str | None, _db: str | None, _trigger: str | None
) -> int:
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_SAVEPOINT,
        sqlite3.SQLITE_RECURSIVE,
    }
    if action in allowed:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_UPDATE and first in {
        "run_meta",
        "stream_generations",
        "coherence_controllers",
    }:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and second in {
        "max",
        "coalesce",
        "length",
        "glob",
        "raise",
    }:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class RunStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        if self._db_path is None:
            raise ContractNotImplementedError("F0A-T04")
        return self._db_path

    def bootstrap_v1(self) -> None:
        ddl = verified_ddl()
        path = self.db_path
        if path.exists():
            with closing(self.connect()):
                return
        # Exclusive creation never overwrites an existing run or adopts a symlink.
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(ddl)
            verify_database(connection)

    def connect(self) -> sqlite3.Connection:
        path = self.db_path
        if not path.is_file() or path.is_symlink():
            raise ValueError("E_STORE_MISSING_DATABASE")
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA temp_store=MEMORY")
            if connection.execute("PRAGMA max_page_count=32768").fetchone()[0] != 32768:
                raise ValueError("E_STORE_CAPACITY")
            verify_database(connection)
            connection.row_factory = sqlite3.Row
            connection.set_authorizer(_runtime_authorizer)
            return connection
        except BaseException:
            connection.close()
            raise
