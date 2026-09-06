"""Registered SQLite child; SQL-06 re-execs under the test-only commit I/O hook."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def contract_not_implemented() -> None:
    raise RuntimeError("E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04")


def main() -> None:
    arguments = sys.argv[1:]
    shim_index = arguments.index("--commit-shim") if "--commit-shim" in arguments else -1
    shim = Path(arguments[shim_index + 1]).resolve() if shim_index >= 0 else None
    if shim_index >= 0:
        del arguments[shim_index : shim_index + 2]
    values = dict(zip(arguments[::2], arguments[1::2], strict=False))
    if (
        values.get("--vector-id") == "SQL-06-DURING-COMMIT"
        and os.environ.get("BH_SQL_COMMIT_REEXEC") != "1"
    ):
        if shim is None or not shim.is_file():
            raise ValueError("E_SQL_COMMIT_SHIM_REQUIRED")
        ready = Path(values["--ready"]).resolve()
        identity = {
            "run_id": values["--run-id"],
            "case_id": values["--case-id"],
            "checkpoint_id": values["--checkpoint-id"],
            "component": values["--component"],
            "pid": os.getpid(),
            "ordinal": int(values["--ordinal"]),
            "test_nonce": values["--test-nonce"],
        }
        environment = dict(os.environ)
        environment.update(
            {
                "LD_PRELOAD": str(shim),
                "BH_SQL_COMMIT_REEXEC": "1",
                "BH_SQL_COMMIT_ARMED": "0",
                "BH_SQL_COMMIT_READY": str(ready),
                "BH_SQL_COMMIT_BOUNDARY": str(ready.with_name("boundary.json")),
                "BH_SQL_COMMIT_IDENTITY": json.dumps(identity, sort_keys=True),
                "BH_SQL_DATABASE_SUFFIX": "run.sqlite3",
            }
        )
        os.execve(  # noqa: S606 -- fixed current venv interpreter and owned test child
            sys.executable,
            [sys.executable, "-I", str(Path(__file__).resolve()), *arguments],
            environment,
        )
    sys.argv[1:] = arguments
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]
    from tools.loopback_ack_crash_child import main as ingest_crash_main

    ingest_crash_main()


if __name__ == "__main__":
    main()
