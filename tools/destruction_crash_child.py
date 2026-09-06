"""Owned disposable destruction process. No oracle or expected state is accepted."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from contextlib import closing
from pathlib import Path
from time import monotonic, sleep
from typing import Any

if __package__ in {None, ""}:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]

from moj_discovery.store import RunStore  # noqa: E402
from tools.destruction_support import (  # noqa: E402
    consumption,
    delete_backend,
    immutable_json,
    insert_consumption,
    inventory,
    owned_case,
    persist_intent,
    prepare_backend,
    read_actual,
    validate_consumed,
    validate_external,
    validate_plan,
    worker_read,
    write_proof,
)


def execute(case: Path, config: dict[str, Any], *, recover: bool) -> None:
    run_id = config["identity"]["run_id"]
    database = owned_case(case, run_id)
    plan = json.loads((case / "precommit.json").read_text())
    boundary = config["identity"]["checkpoint_id"]

    def checkpoint(name: str) -> None:
        if not recover and name == boundary:
            immutable_json(case / "checkpoint.json", {**config["identity"], "pid": os.getpid()})
            while True:
                signal.pause()

    validate_plan(plan)
    checkpoint("destroy_01_before_authority")
    if recover and boundary == "destroy_01_before_authority":
        return
    if not recover:
        actual = read_actual(case, config)
        if inventory(actual) != plan["export"]["inventory"]:
            raise ValueError("E_DESTRUCTION_INVENTORY_HASH")
        with closing(RunStore(database).connect()) as connection, connection:
            insert_consumption(connection, consumption(plan))
    validate_consumed(case, plan)
    if database.exists():
        with closing(RunStore(database).connect()) as connection:
            committed = dict(
                connection.execute("SELECT * FROM authorization_consumptions").fetchone()
            )
        immutable_json(case / "consumed-external.json", committed)
    checkpoint("destroy_01a_after_consumption_before_intent")
    persist_intent(case, plan)
    checkpoint("destroy_02_after_intent_before_deletion")
    if boundary == "destroy_04_after_backend_deletion":
        delete_backend(case, plan)
        checkpoint("destroy_04_after_backend_deletion")
        validate_external(case, plan)
        worker_read(config, "destruction-delete")
    else:
        validate_external(case, plan)
        worker_read(config, "destruction-delete")
        checkpoint("destroy_03_after_extension_deletion")
        delete_backend(case, plan)
    checkpoint("destroy_05_after_both_deletions_before_proof")
    write_proof(case, config, plan)
    checkpoint("destroy_06_after_proof")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("setup", "run", "recover", "read", "validate"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--start", required=True, type=Path)
    args = parser.parse_args()
    args.start.with_suffix(".ready").write_text(str(os.getpid()))
    deadline = monotonic() + 15
    while not args.start.is_file():
        if monotonic() > deadline:
            raise ValueError("E_DESTRUCTION_START_TIMEOUT")
        sleep(0.01)
    config = json.loads(args.input.read_text())
    case = args.input.parent
    result: Any
    if args.mode == "validate":
        try:
            validate_plan(config)
        except ValueError as error:
            result = {"observed_error": str(error)}
        else:
            result = {"observed_error": None}
    elif args.mode == "setup":
        result = prepare_backend(case, config["observation"])
    elif args.mode == "read":
        if set(config) != {"identity", "options", "socket"}:
            raise ValueError("E_DESTRUCTION_READER_INPUT")
        result = read_actual(case, config)
    else:
        execute(case, config, recover=args.mode == "recover")
        result = {"completed": True}
    print(json.dumps({"pid": os.getpid(), "result": result}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(json.dumps({"pid": os.getpid(), "result": {"observed_error": str(error)}}))
        raise SystemExit(1) from error
