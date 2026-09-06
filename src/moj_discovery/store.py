"""Offline SQLite storage using the unmodified governed bootstrap schema."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .canonical import canonical_content_hash
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


TABLES = (
    "run_meta",
    "raw_commits",
    "raw_conflicts",
    "application_records",
    "derived_revisions",
    "reducer_cursors",
    "ack_outbox",
    "ack_cursors",
    "stream_generations",
    "gap_records",
    "gap_epoch_bindings",
    "generation_transitions",
    "coherence_epochs",
    "coherence_controllers",
    "coherence_transitions",
    "shock_observations",
)
KEY = ("run_id", "browser_run_id", "producer_id", "stream_id", "generation")


def validate_journal(tables: dict[str, list[dict[str, Any]]]) -> None:
    # ponytail: quadratic scan for bounded offline runs; index by position if runs grow.
    schema = json.loads((VENDOR / "schemas/durability-records.schema.json").read_text())
    h0 = schema["$defs"]["CursorChainContract"]["properties"]["seed_hash_h0"]["const"]
    applied = [row for row in tables["raw_commits"] if row["disposition"] == "APPLIED"]
    chains: dict[tuple[Any, ...], tuple[int, str]] = {}
    linked_tables = ("application_records", "derived_revisions", "reducer_cursors", "ack_outbox")
    if any(len(tables[name]) != len(applied) for name in linked_tables):
        raise ValueError("E_STORE_DURABLE_CHAIN")
    for raw in sorted(applied, key=lambda row: tuple(row[field] for field in (*KEY, "sequence"))):
        key = tuple(raw[field] for field in KEY)
        sequence, prior = chains.get(key, (0, h0))
        digest = canonical_content_hash(
            "CursorStep",
            {
                "schema_version": "cursor-step/v1",
                "discovery_run_id": raw["run_id"],
                "browser_run_id": raw["browser_run_id"],
                "producer_id": raw["producer_id"],
                "stream_id": raw["stream_id"],
                "generation": str(raw["generation"]),
                "sequence": str(raw["sequence"]),
                "raw_observation_hash": raw["raw_observation_content_hash"],
                "previous_cursor_hash": prior,
            },
            registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
        )
        if (raw["sequence"], raw["previous_cursor_hash"], raw["cursor_hash"]) != (
            sequence + 1,
            prior,
            digest,
        ):
            raise ValueError("E_STORE_DURABLE_CHAIN")
        records: dict[str, dict[str, Any]] = {}
        for name in linked_tables:
            matches = [
                row
                for row in tables[name]
                if tuple(row[field] for field in KEY) == key
                and row.get("sequence", row.get("highest_contiguous_sequence")) == sequence + 1
            ]
            if len(matches) != 1:
                raise ValueError("E_STORE_DURABLE_CHAIN")
            records[name] = matches[0]
        app, revision, cursor, ack = (records[name] for name in linked_tables)
        if not (
            app["raw_commit_id"]
            == revision["raw_commit_id"]
            == ack["raw_commit_id"]
            == raw["raw_commit_id"]
            and revision["application_id"] == ack["application_id"] == app["application_id"]
            and cursor["derived_revision_id"]
            == ack["derived_revision_id"]
            == revision["derived_revision_id"]
            and ack["reducer_cursor_id"] == cursor["reducer_cursor_id"]
            and app["input_cursor_hash"] == cursor["previous_cursor_hash"] == prior
            and app["raw_observation_content_hash"]
            == cursor["raw_observation_content_hash"]
            == raw["raw_observation_content_hash"]
            and cursor["cursor_hash"] == ack["cursor_hash"] == revision["revision_hash"] == digest
            and revision["revision"] == sequence + 1
            and revision["previous_revision_hash"] == (None if sequence == 0 else prior)
        ):
            raise ValueError("E_STORE_DURABLE_CHAIN")
        chains[key] = (sequence + 1, digest)
    histories: dict[tuple[Any, ...], dict[str, Any]] = {}
    for ack in sorted(
        tables["ack_cursors"],
        key=lambda row: tuple(
            row[field] for field in (*KEY, "owner", "highest_contiguous_sequence")
        ),
    ):
        key = tuple(ack[field] for field in KEY)
        owner_key = (*key, ack["owner"])
        previous = histories.get(owner_key)
        required_binding = {"BACKEND": "BACKEND_DURABLE_CHAIN", "EXTENSION": "LOCAL_SPOOL_CHAIN"}
        if ack["verified_against"] != required_binding.get(ack["owner"]):
            raise ValueError("E_STORE_ACK_CHAIN")
        if ack["highest_contiguous_sequence"] == 0:
            valid = (
                previous is None
                and ack["previous_ack_cursor_id"] is None
                and ack["cursor_hash"] == h0
            )
        else:
            valid = (
                ack["previous_ack_cursor_id"]
                == (None if previous is None else previous["ack_cursor_id"])
                and (
                    previous is None
                    or previous["highest_contiguous_sequence"] < ack["highest_contiguous_sequence"]
                )
                and any(
                    tuple(row[field] for field in KEY) == key
                    and row["highest_contiguous_sequence"] == ack["highest_contiguous_sequence"]
                    and row["cursor_hash"] == ack["cursor_hash"]
                    for row in tables["ack_outbox"]
                )
            )
        if not valid:
            raise ValueError("E_STORE_ACK_CHAIN")
        histories[owner_key] = ack


def read_journal(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        table: sorted(
            (dict(row) for row in connection.execute(f"SELECT * FROM {table}")),  # noqa: S608 -- fixed allowlist
            key=lambda row: json.dumps(row, sort_keys=True),
        )
        for table in TABLES
    }
