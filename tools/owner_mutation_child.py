"""Isolated ordinary SQL/browser owner entrypoints; never receives an oracle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from time import monotonic, sleep

if __package__ in {None, ""}:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]

from moj_discovery.ingest import Ingestor  # noqa: E402
from moj_discovery.store import RunStore  # noqa: E402
from tools.loopback_ack_crash_child import provision  # noqa: E402
from tools.restart_state_reader import read_restart_state  # noqa: E402
from tools.run_indexeddb_crash_matrix import PACK, run_indexeddb_case  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("case", "sql-setup", "sql-input", "sql-read"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--start", required=True, type=Path)
    args = parser.parse_args()
    args.start.with_suffix(".ready").write_text(str(os.getpid()))
    deadline = monotonic() + 20
    while not args.start.exists():
        if monotonic() > deadline:
            raise ValueError("E_OWNER_MUTATION_START")
        sleep(0.01)
    request = json.loads(args.input.read_text())
    case = args.input.parent
    if args.mode == "case":
        entry = next(
            item
            for item in json.loads(
                (PACK / "docs/registries/crash-harness-registry.v1.json").read_text()
            )["entries"]
            if item["vector_id"] == request["case_id"]
        )
        if entry["harness"] == "SQLITE_TRANSACTION":
            from tools.owner_mutation_evidence import run_sql_input
            from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix

            result = (
                run_sql_input(entry, case / "execution")
                if request["kind"] == "INPUT"
                else run_sqlite_crash_matrix(
                    PACK, case / "execution", entries=[entry], include_mutations=False
                )["records"][0]
            )
        else:
            result = run_indexeddb_case(
                entry,
                case / "execution",
                full=True,
                operation="crash" if entry["harness"] == "CHROME_INDEXEDDB" else "deliver",
                input_rejection=request["kind"] == "INPUT",
            )
    elif args.mode == "sql-setup":
        provision(case, request["observation"])
        result = {"completed": True}
    elif args.mode == "sql-read":
        result = read_restart_state(case / request["run_id"])
    else:
        result = Ingestor(RunStore(case / request["run_id"] / "run.sqlite3")).apply(
            request["observation"]
        )
    print(json.dumps({"pid": os.getpid(), "result": result}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(json.dumps({"pid": os.getpid(), "result": {"observed_error": str(error)}}))
        raise SystemExit(1) from error
