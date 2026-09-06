"""Owned generation/coherence durability fixture; receives no expected state."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]

from moj_discovery.coherence import CoherenceController  # noqa: E402
from moj_discovery.generation import GenerationController  # noqa: E402

DDL = """PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS owner_state (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), run_id TEXT NOT NULL,
 version INTEGER NOT NULL, state_json TEXT NOT NULL) STRICT;"""


def initial(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "controller": "OPEN",
        "generations": {"0": "ACTIVE"},
        "cursor": "GEN0_Q1_H1",
        "counts": {},
        "capacity": None,
    }


def terminal(case_id: str, run_id: str) -> dict[str, Any]:
    value = initial(run_id)
    key = "-".join(case_id.split("-")[:2])
    generations = GenerationController()
    coherence = CoherenceController()
    if key.startswith("GAP-0") or key == "GAP-10":
        value.update(
            controller=coherence.transition("OPEN", "SHOCK_ATOMIC_CLOSE"),
            generations=generations.replace_after_gap(value["generations"], 0),
        )
        value["counts"] = {"gap": 1, "shock": 1, "transition": 1, "binding": 1}
    elif key == "CONFLICT-01":
        value.update(
            controller=coherence.transition("OPEN", "SHOCK_ATOMIC_CLOSE"),
            generations=generations.replace_after_gap(value["generations"], 0),
        )
        value["counts"] = {"conflict": 1, "gap": 1, "shock": 1, "transition": 1, "binding": 1}
    elif key == "LATE-01":
        value.update(
            controller=coherence.transition("SHOCKED_CLOSED", "CLOSE_RECORDED"),
            generations=generations.replace_after_gap(value["generations"], 0),
        )
        value["counts"] = {"gap": 1, "shock": 1, "transition": 2, "binding": 1, "late": 1}
    elif key == "GAP-11":
        first = generations.replace_after_gap(value["generations"], 0)
        value.update(
            controller=coherence.transition("NEW_EPOCH_OPEN", "SHOCK_ATOMIC_CLOSE"),
            generations=generations.replace_after_gap(first, 1),
            cursor="GEN1_Q0_H0",
        )
        value["counts"] = {"gap": 2, "shock": 2, "transition": 3, "binding": 2}
    elif key == "CAPACITY-01":
        value["controller"] = coherence.transition("OPEN", "SHOCK_ATOMIC_CLOSE")
        decision = generations.capacity_decision(
            used=7, incoming=1, normal_limit=7, terminal_reserve=1
        )
        value["capacity"] = {
            "normal_limit": 7,
            "terminal_reserve": 1,
            "used": 7,
            "unacknowledged_rows": 1,
            "evicted": decision["evicted"],
            "status": decision["status"],
        }
    elif key.startswith("CLOCK"):
        value["counts"] = {"mapping_closure": 1, "shock": 1, "transition": 1}
        value["controller"] = "SHOCKED_CLOSED"
    elif key in {"EPOCH-01", "EPOCH-02"}:
        value.update(controller="WAITING_FOR_RESNAPSHOT", counts={"shock": 1, "transition": 2})
    elif key == "EPOCH-03":
        value.update(
            controller="NEW_EPOCH_PENDING",
            counts={"shock": 1, "proof": 1, "freshness": 1, "epoch": 1, "transition": 3},
        )
    elif key == "EPOCH-04":
        value.update(
            controller="NEW_EPOCH_OPEN",
            counts={"shock": 1, "proof": 1, "freshness": 1, "epoch": 1, "transition": 4},
        )
    elif key == "EPOCH-05":
        value.update(
            controller="WAITING_FOR_RESNAPSHOT",
            counts={"shock": 2, "proof": 1, "freshness": 1, "epoch": 2, "transition": 4},
        )
    else:
        raise ValueError("E_GAP_CASE")
    return value


def base(case_id: str, run_id: str) -> dict[str, Any]:
    value = initial(run_id)
    key = "-".join(case_id.split("-")[:2])
    if key == "CLOCK-02":
        value.update(controller="OPEN_BUT_INELIGIBLE", counts={"mapping_closure": 1})
    elif key in {"EPOCH-02", "EPOCH-03", "EPOCH-04"}:
        value.update(controller="SHOCKED_CLOSED", counts={"shock": 1, "transition": 1})
        if key in {"EPOCH-03", "EPOCH-04"}:
            value.update(controller="WAITING_FOR_RESNAPSHOT", counts={"shock": 1, "transition": 2})
        if key == "EPOCH-04":
            value.update(
                controller="NEW_EPOCH_PENDING",
                counts={"shock": 1, "proof": 1, "freshness": 1, "epoch": 1, "transition": 3},
            )
    return value


def checkpoint_target(case_id: str, run_id: str) -> dict[str, Any]:
    value = terminal(case_id, run_id)
    key = "-".join(case_id.split("-")[:2])
    if key == "CLOCK-01":
        value.update(controller="OPEN", counts={"mapping_closure": 1})
    elif key == "CLOCK-02":
        value = base(case_id, run_id)
    elif key in {"EPOCH-01", "EPOCH-02"}:
        value.update(controller="SHOCKED_CLOSED", counts={"shock": 1, "transition": 1})
    return value


def _write(connection: sqlite3.Connection, state: dict[str, Any], version: int) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO owner_state VALUES (1,?,?,?)",
        (state["run_id"], version, json.dumps(state, sort_keys=True, separators=(",", ":"))),
    )


def _identity(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "run_id": args.run_id,
        "case_id": args.case_id,
        "checkpoint_id": args.checkpoint_id,
        "component": args.component,
        "pid": os.getpid(),
        "ordinal": args.ordinal,
        "test_nonce": args.test_nonce,
    }


def _checkpoint(args: argparse.Namespace, connection: sqlite3.Connection, phase: str) -> None:
    identity = _identity(args)
    row = connection.execute("SELECT version,state_json FROM owner_state").fetchone()
    boundary = {
        "identity": identity,
        "phase": phase,
        "in_transaction": connection.in_transaction,
        "visible_state": json.loads(row[1]),
        "version": row[0],
    }
    args.ready.with_name("boundary.json").write_text(json.dumps(boundary, sort_keys=True))
    temporary = args.ready.with_suffix(".tmp")
    temporary.write_text(json.dumps(identity, sort_keys=True))
    temporary.replace(args.ready)


def _hold() -> None:
    while True:
        signal.pause()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recover", type=Path)
    parser.add_argument("--commit-shim", type=Path)
    parser.add_argument("--vector-id")
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--case-id")
    parser.add_argument("--checkpoint-id")
    parser.add_argument("--component")
    parser.add_argument("--ordinal", type=int, default=0)
    parser.add_argument("--test-nonce", default="recovery")
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    if args.recover:
        scenario = json.loads((args.recover / "scenario.json").read_text())
        with sqlite3.connect(args.recover / "gap-owner.sqlite3") as connection:
            _write(connection, terminal(scenario["case_id"], scenario["run_id"]), 2)
        return
    if not args.hold or not args.ready:
        raise ValueError("E_GAP_SCENARIO")
    database = args.ready.parent / "gap-owner.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(DDL)
        _write(connection, base(args.case_id, args.run_id), 0)
    key = "-".join(args.case_id.split("-")[:2])
    rollback = key in {*(f"GAP-{n:02d}" for n in range(1, 9)), "CLOCK-01", "EPOCH-01", "EPOCH-03"}
    during = key in {"GAP-09", "EPOCH-04"}
    no_kill = key in {"CONFLICT-01", "LATE-01", "GAP-11", "CAPACITY-01", "EPOCH-05"}
    if during and os.environ.get("BH_GAP_COMMIT_REEXEC") != "1":
        if not args.commit_shim or not args.commit_shim.is_file():
            raise ValueError("E_GAP_COMMIT_SHIM_REQUIRED")
        environment = dict(os.environ)
        environment.update(
            LD_PRELOAD=str(args.commit_shim.resolve()),
            BH_GAP_COMMIT_REEXEC="1",
            BH_SQL_COMMIT_ARMED="0",
            BH_SQL_COMMIT_READY=str(args.ready),
            BH_SQL_COMMIT_BOUNDARY=str(args.ready.with_name("boundary.json")),
            BH_SQL_COMMIT_IDENTITY=json.dumps(_identity(args), sort_keys=True),
            BH_SQL_DATABASE_SUFFIX="gap-owner.sqlite3",
        )
        os.execve(  # noqa: S606 -- fixed current interpreter and owned test child
            sys.executable,
            [sys.executable, "-I", str(Path(__file__).resolve()), *sys.argv[1:]],
            environment,
        )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        _write(connection, checkpoint_target(args.case_id, args.run_id), 1)
        if rollback:
            _checkpoint(args, connection, "before_commit")
            _hold()
        if during:
            connection.set_trace_callback(
                lambda statement: (
                    os.environ.__setitem__("BH_SQL_COMMIT_ARMED", "1")
                    if statement == "COMMIT"
                    else None
                )
            )
        connection.commit()
        if during:
            raise RuntimeError("E_GAP_DURING_COMMIT_CHECKPOINT_NOT_REACHED")
        _checkpoint(args, connection, "after_commit")
    if no_kill:
        return
    _hold()


if __name__ == "__main__":
    main()
