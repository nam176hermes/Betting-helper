"""Read actual offline run storage. Receives no oracle, scenario or expected state."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from moj_discovery.canonical import canonical_content_hash
from moj_discovery.store import VENDOR, verified_ddl, verify_database

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


def _check_journal(tables: dict[str, list[dict[str, Any]]]) -> None:
    # ponytail: quadratic scan for bounded offline runs; index by position if runs grow.
    schema = json.loads((VENDOR / "schemas/durability-records.schema.json").read_text())
    h0 = schema["$defs"]["CursorChainContract"]["properties"]["seed_hash_h0"]["const"]
    applied = [row for row in tables["raw_commits"] if row["disposition"] == "APPLIED"]
    chains: dict[tuple[Any, ...], tuple[int, str]] = {}
    linked_tables = ("application_records", "derived_revisions", "reducer_cursors", "ack_outbox")
    if any(len(tables[name]) != len(applied) for name in linked_tables):
        raise ValueError("E_RESTART_DURABLE_CHAIN")
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
            raise ValueError("E_RESTART_DURABLE_CHAIN")
        records: dict[str, dict[str, Any]] = {}
        for name in linked_tables:
            matches = [
                row
                for row in tables[name]
                if tuple(row[field] for field in KEY) == key
                and row.get("sequence", row.get("highest_contiguous_sequence")) == sequence + 1
            ]
            if len(matches) != 1:
                raise ValueError("E_RESTART_DURABLE_CHAIN")
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
            raise ValueError("E_RESTART_DURABLE_CHAIN")
        chains[key] = (sequence + 1, digest)
    for ack in tables["ack_cursors"]:
        key = tuple(ack[field] for field in KEY)
        if ack["highest_contiguous_sequence"] == 0:
            valid = ack["cursor_hash"] == h0
        else:
            valid = any(
                tuple(row[field] for field in KEY) == key
                and row["highest_contiguous_sequence"] == ack["highest_contiguous_sequence"]
                and row["cursor_hash"] == ack["cursor_hash"]
                for row in tables["ack_outbox"]
            )
        if not valid:
            raise ValueError("E_RESTART_DURABLE_CHAIN")


def read_restart_state(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run.sqlite3"
    if run_dir.is_symlink() or not path.is_file() or path.is_symlink():
        raise ValueError("E_RESTART_MISSING_DATABASE")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("BEGIN")
            verify_database(connection)
            tables = {
                table: sorted(
                    (dict(row) for row in connection.execute(f"SELECT * FROM {table}")),  # noqa: S608 -- fixed allowlist
                    key=lambda row: json.dumps(row, sort_keys=True),
                )
                for table in TABLES
            }
            meta = tables["run_meta"]
            if len(meta) != 1 or meta[0]["run_id"] != run_dir.name:
                raise ValueError("E_RESTART_RUN_IDENTITY")
            run_id = meta[0]["run_id"]
            if any(
                row["run_id"] != run_id
                for rows in tables.values()
                for row in rows
                if "run_id" in row
            ):
                raise ValueError("E_RESTART_RUN_IDENTITY")
            _check_journal(tables)
            return {
                "schema_version": 1,
                "run_id": run_id,
                "ddl_sha256": hashlib.sha256(verified_ddl().encode()).hexdigest(),
                "tables": tables,
            }
    except sqlite3.DatabaseError as error:
        raise ValueError("E_RESTART_DATABASE") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(read_restart_state(args.run_dir), sort_keys=True))


if __name__ == "__main__":
    main()
