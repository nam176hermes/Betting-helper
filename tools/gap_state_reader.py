"""Independent read-only reader for governed generation/coherence SQLite facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]

from moj_discovery.store import verified_ddl  # noqa: E402
from tools.restart_state_reader import read_restart_state  # noqa: E402

EXTRA_TABLES = (
    "clock_mappings",
    "clock_mapping_closures",
    "input_freshness_vectors",
    "authoritative_resnapshot_proofs",
)


def read_gap_state(run_dir: Path) -> dict[str, Any]:
    state = read_restart_state(run_dir)
    path = run_dir / "run.sqlite3"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        extras = {
            table: sorted(
                (dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')),  # noqa: S608
                key=lambda row: json.dumps(row, sort_keys=True),
            )
            for table in EXTRA_TABLES
        }
    spool_path = run_dir.parent / "spool-events.jsonl"
    spool_rows = (
        [json.loads(line) for line in spool_path.read_text().splitlines() if line]
        if spool_path.is_file()
        else []
    )
    capacity_path = run_dir.parent / "capacity-decision.json"
    capacity = json.loads(capacity_path.read_text()) if capacity_path.is_file() else None
    return {
        **state,
        "ddl_sha256": hashlib.sha256(verified_ddl().encode()).hexdigest(),
        "tables": {**state["tables"], **extras},
        "spool": {"count": len(spool_rows), "rows": spool_rows},
        "capacity": capacity,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    args = parser.parse_args()
    identity = json.loads(args.identity.read_text())
    state = read_gap_state(args.run_dir)
    if state["run_id"] != identity.get("run_id"):
        raise ValueError("E_GAP_READER_IDENTITY")
    print(
        json.dumps(
            {
                "identity": identity,
                "state": state,
                "process": {
                    "pid": os.getpid(),
                    "ppid": os.getppid(),
                    "pgid": os.getpgid(0),
                    "start_ticks": Path("/proc/self/stat").read_text().split()[21],
                    "executable": str(Path(sys.executable).resolve()),
                    "executable_sha256": hashlib.sha256(
                        Path(sys.executable).resolve().read_bytes()
                    ).hexdigest(),
                    "argv": sys.argv,
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
