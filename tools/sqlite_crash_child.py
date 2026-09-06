"""Killable SQLite transaction child for durability vectors."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from time import sleep


TABLES = ("raw_commits", "application_records", "derived_revisions", "reducer_cursors", "ack_outbox")


def contract_not_implemented() -> None:
    raise RuntimeError("E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vector-id", required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    if args.database is None:
        print(json.dumps({"vector_id": args.vector_id}, sort_keys=True))
        return
    connection = sqlite3.connect(args.database)
    try:
        for table in TABLES:
            connection.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY)")
        connection.execute("BEGIN")
        for table in TABLES:
            connection.execute(f"INSERT INTO {table} VALUES (?)", (args.vector_id,))
        if args.vector_id == "SQL-07-AFTER-COMMIT-BEFORE-ACK-SEND":
            connection.commit()
        if args.ready is not None:
            args.ready.write_text(json.dumps({"vector_id": args.vector_id}))
        if args.hold:
            while True:
                sleep(1)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
