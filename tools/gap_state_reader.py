"""Independent read-only reader for the generation/coherence owner store."""

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    args = parser.parse_args()
    identity = json.loads(args.identity.read_text())
    if args.database.is_symlink() or not args.database.is_file():
        raise ValueError("E_GAP_READER_DATABASE")
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("E_GAP_READER_INTEGRITY")
        rows = connection.execute("SELECT run_id,version,state_json FROM owner_state").fetchall()
    if len(rows) != 1 or rows[0][0] != identity["run_id"]:
        raise ValueError("E_GAP_READER_IDENTITY")
    print(
        json.dumps(
            {"identity": identity, "version": rows[0][1], "state": json.loads(rows[0][2])},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
