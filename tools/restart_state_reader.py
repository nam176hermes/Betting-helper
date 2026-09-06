"""Read actual offline run storage. Receives no oracle, scenario or expected state."""

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]

from moj_discovery.store import read_journal, validate_journal, verified_ddl, verify_database


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
            tables = read_journal(connection)
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
            validate_journal(tables)
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
    parser.add_argument("--identity", type=Path)
    args = parser.parse_args()
    state = read_restart_state(args.run_dir)
    if args.identity is None:
        print(json.dumps(state, sort_keys=True))
        return
    identity = json.loads(args.identity.read_text())
    if (
        not isinstance(identity, dict)
        or set(identity)
        != {"run_dir", "run_id", "case_id", "checkpoint_id", "phase"}
        or identity["run_dir"] != str(args.run_dir.resolve())
        or identity["run_id"] != state["run_id"]
        or not isinstance(identity["case_id"], str)
        or not identity["case_id"]
        or not isinstance(identity["checkpoint_id"], str)
        or not identity["checkpoint_id"]
        or identity["phase"] not in {"before", "after"}
    ):
        raise ValueError("E_RESTART_READER_IDENTITY")
    print(json.dumps({"identity": identity, "state": state}, sort_keys=True))


if __name__ == "__main__":
    main()
