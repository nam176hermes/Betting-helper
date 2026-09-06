"""Execute registered generation/coherence operations on the governed SQLite schema."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import signal
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from time import sleep
from typing import Any

if __package__ in {None, ""}:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]

from moj_discovery.canonical import (  # noqa: E402
    canonical_content_hash,
    verify_canonical_content_hash,
)
from moj_discovery.generation import GenerationController  # noqa: E402
from moj_discovery.ingest import Ingestor  # noqa: E402
from moj_discovery.schema_registry import validate_artifact  # noqa: E402
from moj_discovery.store import VENDOR, RunStore, read_journal  # noqa: E402
from tools.gap_state_reader import read_gap_state  # noqa: E402
from tools.loopback_ack_crash_child import (  # noqa: E402
    BEFORE_STATEMENT,
    CheckpointStore,
    apply_result,
    provision,
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


def _checkpoint(
    args: argparse.Namespace,
    connection: sqlite3.Connection,
    operation: str,
    *,
    hold: bool,
) -> None:
    identity = _identity(args)
    boundary = {
        "identity": identity,
        "operation": operation,
        "in_transaction": connection.in_transaction,
        "tables": read_journal(connection),
    }
    args.ready.with_name("boundary.json").write_text(json.dumps(boundary, sort_keys=True))
    temporary = args.ready.with_suffix(".tmp")
    temporary.write_text(json.dumps(identity, sort_keys=True))
    temporary.replace(args.ready)
    if hold:
        while True:
            signal.pause()
    release = args.ready.with_name("continue.json")
    while not release.is_file():
        sleep(0.02)


def _mapping(connection: sqlite3.Connection, run_id: str, suffix: str = "0") -> str:
    mapping = f"mapping:{suffix}"
    connection.execute(
        "INSERT INTO clock_mappings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mapping,
            run_id,
            f"source:{suffix}",
            f"source-boot:{suffix}",
            "EXTENSION_SERVICE_WORKER",
            f"target:{suffix}",
            f"target-boot:{suffix}",
            "BACKEND_PROCESS",
            "MICROSECOND",
            8,
            0,
            0,
            2,
            1,
            1,
            0,
            100,
            0,
            10,
            "OPEN",
            0,
        ),
    )
    return mapping


def _close_mapping(connection: sqlite3.Connection, mapping: str) -> None:
    connection.execute(
        "INSERT INTO clock_mapping_closures VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "mapping-close:" + mapping,
            mapping,
            "SLEEP_RESUME",
            "source:0",
            "source-boot:0",
            5,
            1,
            0,
            5,
        ),
    )


def _shock_close(
    connection: sqlite3.Connection,
    run_id: str,
    suffix: str = "0",
    shock_type: str = "MAPPING_CLOSURE",
) -> None:
    controller = connection.execute(
        "SELECT * FROM coherence_controllers WHERE run_id=?", (run_id,)
    ).fetchone()
    shock, transition = f"shock:{suffix}", f"shock-transition:{suffix}"
    connection.execute(
        "INSERT INTO shock_observations VALUES (?,?,?,?,?,?,?,?)",
        (shock, run_id, "fixture:test", shock_type, 6, 6, f"{int(suffix) + 1:064x}", 6),
    )
    connection.execute(
        "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            transition,
            controller["coherence_controller_id"],
            controller["fixture_id"],
            controller["controller_state"],
            "SHOCKED_CLOSED",
            controller["current_epoch_id"],
            None,
            shock,
            None,
            None,
            1,
            "SHOCK_ATOMIC_CLOSE",
            6,
        ),
    )
    connection.execute(
        "UPDATE coherence_controllers SET controller_state='SHOCKED_CLOSED',"
        "active_shock_observation_id=?,controller_revision=controller_revision+1,updated_at_us=6 "
        "WHERE coherence_controller_id=?",
        (shock, controller["coherence_controller_id"]),
    )


def _waiting(connection: sqlite3.Connection, run_id: str) -> None:
    controller = connection.execute(
        "SELECT * FROM coherence_controllers WHERE run_id=?", (run_id,)
    ).fetchone()
    connection.execute(
        "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "close-recorded",
            controller["coherence_controller_id"],
            controller["fixture_id"],
            "SHOCKED_CLOSED",
            "WAITING_FOR_RESNAPSHOT",
            controller["current_epoch_id"],
            None,
            controller["active_shock_observation_id"],
            None,
            None,
            1,
            "CLOSE_RECORDED",
            7,
        ),
    )
    connection.execute(
        "UPDATE coherence_controllers SET controller_state='WAITING_FOR_RESNAPSHOT',"
        "controller_revision=controller_revision+1,updated_at_us=7 WHERE run_id=?",
        (run_id,),
    )


def _pending(connection: sqlite3.Connection, scenario: dict[str, Any]) -> None:
    run_id = scenario["run_id"]
    controller = connection.execute(
        "SELECT * FROM coherence_controllers WHERE run_id=?", (run_id,)
    ).fetchone()
    mappings = tuple(_mapping(connection, run_id, str(index + 1)) for index in range(3))
    freshness, proof, candidate = "freshness:1", "proof:1", "epoch:1"
    connection.execute(
        "INSERT INTO input_freshness_vectors VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            freshness,
            run_id,
            "fixture:test",
            "FRESH",
            "FRESH",
            "FRESH",
            "FRESH",
            "FRESH",
            "FRESH",
            "FRESH",
            "a" * 64,
            8,
        ),
    )
    connection.execute(
        "INSERT INTO coherence_epochs VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            candidate,
            run_id,
            "fixture:test",
            1,
            controller["current_epoch_id"],
            "OPEN",
            freshness,
            proof,
            8,
            1,
        ),
    )
    cursor = connection.execute(
        "SELECT reducer_cursor_id FROM reducer_cursors WHERE generation=1 LIMIT 1"
    ).fetchone()
    if cursor is None:
        raise ValueError("E_EPOCH_CURSOR_PREREQUISITE")
    connection.execute(
        "INSERT INTO authoritative_resnapshot_proofs VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            proof,
            run_id,
            "fixture:test",
            controller["current_epoch_id"],
            candidate,
            controller["active_shock_observation_id"],
            "OBSERVED",
            "capability:test",
            freshness,
            *mappings,
            "b" * 64,
            cursor[0],
            "c" * 64,
            1,
            1,
            1,
            "SATISFIED",
            "d" * 64,
            8,
        ),
    )
    connection.execute(
        "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "candidate-accepted",
            controller["coherence_controller_id"],
            "fixture:test",
            "WAITING_FOR_RESNAPSHOT",
            "NEW_EPOCH_PENDING",
            controller["current_epoch_id"],
            candidate,
            controller["active_shock_observation_id"],
            freshness,
            proof,
            1,
            "RESNAPSHOT_CANDIDATE_ACCEPTED",
            8,
        ),
    )
    connection.execute(
        "UPDATE coherence_controllers SET controller_state='NEW_EPOCH_PENDING',"
        "candidate_epoch_id=?,predecessor_epoch_id=current_epoch_id,"
        "controller_revision=controller_revision+1,updated_at_us=8 "
        "WHERE run_id=?",
        (candidate, run_id),
    )


def _seed_epoch_continuity(store: RunStore, scenario: dict[str, Any]) -> None:
    """Create an independent generation-1 cursor used only by the epoch proof."""
    observation = copy.deepcopy(scenario["observation"])
    observation.update(
        raw_observation_id="observation:" + "9" * 64,
        stream_id="00000000-0000-4000-8000-000000000099",
        generation="1",
        sequence="1",
    )
    observation["content_hash"] = canonical_content_hash(
        "RawObservation",
        observation,
        registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
    )
    with closing(store.connect()) as connection, connection:
        controller = connection.execute(
            "SELECT * FROM coherence_controllers WHERE run_id=?", (scenario["run_id"],)
        ).fetchone()
        transition = connection.execute(
            "SELECT * FROM coherence_transitions WHERE coherence_controller_id=? "
            "AND to_state='SHOCKED_CLOSED' ORDER BY transitioned_at_us DESC LIMIT 1",
            (controller["coherence_controller_id"],),
        ).fetchone()
        if transition is None or controller["controller_state"] != "SHOCKED_CLOSED":
            raise ValueError("E_EPOCH_CONTINUITY_CLOSURE")
        key = (
            scenario["run_id"],
            observation["context"]["browser_run_id"],
            observation["clock_context"]["clock_domain_id"],
            observation["stream_id"],
        )
        connection.execute(
            "INSERT INTO stream_generations VALUES (?,?,?,?,?,0,NULL,'ACTIVE',0,NULL,NULL)",
            ("epoch-proof-generation:0", *key),
        )
        connection.execute(
            "INSERT INTO gap_records VALUES (?,?,?,?,?,0,1,1,1,2,'MISSING_SEQUENCE','OPEN',0,2)",
            ("epoch-proof-gap", *key),
        )
        connection.execute(
            "INSERT INTO gap_epoch_bindings VALUES "
            "(?,?,?,?,?,?,'AFFECTED_EPOCH_PERMANENTLY_CLOSED',2)",
            (
                "epoch-proof-binding",
                "epoch-proof-gap",
                controller["current_epoch_id"],
                controller["coherence_controller_id"],
                controller["active_shock_observation_id"],
                transition["coherence_transition_id"],
            ),
        )
        connection.execute(
            "UPDATE stream_generations SET generation_state='QUARANTINED_GAP',closed_at_us=2,"
            "close_reason='MISSING_SEQUENCE' WHERE generation_id='epoch-proof-generation:0'"
        )
        connection.execute(
            "INSERT INTO generation_transitions VALUES (?,?,?,?,?,?,0,1,'GAP',2)",
            ("epoch-proof-generation-transition", "epoch-proof-gap", *key),
        )
        connection.execute(
            "INSERT INTO stream_generations VALUES (?,?,?,?,?,1,0,'ACTIVE',2,NULL,NULL)",
            ("epoch-proof-generation:1", *key),
        )
    Ingestor(store).apply(observation)


def _release(connection: sqlite3.Connection, run_id: str) -> None:
    controller = connection.execute(
        "SELECT * FROM coherence_controllers WHERE run_id=?", (run_id,)
    ).fetchone()
    connection.execute(
        "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "epoch-release",
            controller["coherence_controller_id"],
            "fixture:test",
            "NEW_EPOCH_PENDING",
            "NEW_EPOCH_OPEN",
            controller["current_epoch_id"],
            controller["candidate_epoch_id"],
            controller["active_shock_observation_id"],
            "freshness:1",
            "proof:1",
            1,
            "RELEASE_PREDICATE_SATISFIED",
            9,
        ),
    )
    connection.execute(
        "UPDATE coherence_controllers SET controller_state='NEW_EPOCH_OPEN',"
        "current_epoch_id=candidate_epoch_id,candidate_epoch_id=NULL,"
        "controller_revision=controller_revision+1,updated_at_us=9 WHERE run_id=?",
        (run_id,),
    )


def _new_shock_pending(connection: sqlite3.Connection, run_id: str) -> None:
    controller = connection.execute(
        "SELECT * FROM coherence_controllers WHERE run_id=?", (run_id,)
    ).fetchone()
    shock = "shock:1"
    connection.execute(
        "INSERT INTO shock_observations VALUES (?,?,?,?,?,?,?,?)",
        (shock, run_id, "fixture:test", "GOAL", 10, 10, "e" * 64, 10),
    )
    connection.execute(
        "INSERT INTO coherence_epochs VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "epoch:2",
            run_id,
            "fixture:test",
            2,
            controller["candidate_epoch_id"],
            "OPEN",
            "freshness:1",
            "proof:1",
            10,
            1,
        ),
    )
    connection.execute(
        "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "pending-new-shock",
            controller["coherence_controller_id"],
            "fixture:test",
            "NEW_EPOCH_PENDING",
            "WAITING_FOR_RESNAPSHOT",
            controller["current_epoch_id"],
            controller["candidate_epoch_id"],
            shock,
            "freshness:1",
            "proof:1",
            1,
            "NEW_SHOCK_CLOSED_CANDIDATE",
            10,
        ),
    )
    connection.execute(
        "UPDATE coherence_controllers SET controller_state='WAITING_FOR_RESNAPSHOT',"
        "candidate_epoch_id=NULL,active_shock_observation_id=?,"
        "controller_revision=controller_revision+1,updated_at_us=10 "
        "WHERE run_id=?",
        (shock, run_id),
    )


def _bootstrap(scenario: dict[str, Any], database: Path) -> RunStore:
    store = provision(database.parent.parent, scenario["observation"])
    for value in scenario.get("setup_deliveries", []):
        result = apply_result(store, value)
        if "error" in result and result["error"] not in {
            "E_INGEST_GAP",
            "E_INGEST_CONFLICT",
            "E_INGEST_GENERATION_CLOSED",
        }:
            raise ValueError("E_GAP_SETUP")
    return store


def _recover(case: Path) -> None:
    (case / "recovery-process.json").write_text(
        json.dumps(
            {
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
            sort_keys=True,
        )
    )
    scenario = json.loads((case / "scenario.json").read_text())
    store = RunStore(case / scenario["run_id"] / "run.sqlite3")
    with closing(store.connect()) as connection:
        tables = read_journal(connection)
        controller = tables["coherence_controllers"][0]["controller_state"]
        if scenario["operation"] == "GAP" and not tables["gap_records"]:
            apply_result(store, scenario["delivery"])
        elif scenario["operation"] == "CLOCK":
            closure = connection.execute("SELECT 1 FROM clock_mapping_closures LIMIT 1").fetchone()
            if closure is None:
                with connection:
                    mapping = connection.execute(
                        "SELECT clock_mapping_id FROM clock_mappings"
                    ).fetchone()[0]
                    _close_mapping(connection, mapping)
            shock = connection.execute("SELECT 1 FROM shock_observations LIMIT 1").fetchone()
            if shock is None:
                with connection:
                    _shock_close(connection, scenario["run_id"])
        elif scenario["operation"] == "EPOCH":
            with connection:
                if controller == "OPEN":
                    _shock_close(
                        connection,
                        scenario["run_id"],
                        shock_type="EQUIVALENT_UNKNOWN_SHOCK",
                    )
                    controller = "SHOCKED_CLOSED"
                if controller == "SHOCKED_CLOSED":
                    _waiting(connection, scenario["run_id"])
                    controller = "WAITING_FOR_RESNAPSHOT"
                if (
                    controller == "WAITING_FOR_RESNAPSHOT"
                    and scenario.get("candidate")
                    and scenario.get("epoch_step") != "new_shock"
                ):
                    _pending(connection, scenario)
                    controller = "NEW_EPOCH_PENDING"
                if controller == "NEW_EPOCH_PENDING" and scenario.get("release"):
                    _release(connection, scenario["run_id"])


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
    parser.add_argument("--launch-ready", type=Path)
    args = parser.parse_args()
    if args.recover:
        _recover(args.recover)
        return
    if not args.hold or not args.ready:
        raise ValueError("E_GAP_SCENARIO")
    case = args.ready.parent
    scenario = json.loads((case / "scenario.json").read_text())
    database = case / scenario["run_id"] / "run.sqlite3"
    store = RunStore(database) if database.is_file() else _bootstrap(scenario, database)
    if args.launch_ready:
        args.launch_ready.write_text(json.dumps(_identity(args), sort_keys=True))
        release = args.launch_ready.with_name("launch-continue.json")
        while not release.is_file():
            sleep(0.02)
    validate_artifact(
        scenario["delivery"], "raw-observation.schema.json", bootstrap_only=True, vendor=VENDOR
    )
    verify_canonical_content_hash(
        "RawObservation",
        scenario["delivery"],
        scenario["delivery"]["content_hash"],
        registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
    )
    phase, operation = scenario["phase"], scenario["operation"]
    fresh_case = not (case / "baseline-state.json").is_file()
    if fresh_case and scenario.get("prepare_successor"):
        _seed_epoch_continuity(store, scenario)
        with closing(store.connect()) as connection, connection:
            _waiting(connection, scenario["run_id"])
            _pending(connection, scenario)
            _release(connection, scenario["run_id"])
    elif fresh_case and (scenario.get("prepare_waiting") or scenario.get("prepare_pending")):
        with closing(store.connect()) as connection, connection:
            _shock_close(
                connection,
                scenario["run_id"],
                shock_type="EQUIVALENT_UNKNOWN_SHOCK",
            )
        if scenario.get("candidate"):
            _seed_epoch_continuity(store, scenario)
        with closing(store.connect()) as connection, connection:
            _waiting(connection, scenario["run_id"])
            if scenario.get("prepare_pending"):
                _pending(connection, scenario)
    if fresh_case:
        (case / "baseline-state.json").write_text(
            json.dumps(read_gap_state(store.db_path.parent), sort_keys=True)
        )
        if scenario.get("spool_append"):
            (case / "spool-events.jsonl").write_text(
                json.dumps(
                    {
                        "raw_observation_id": scenario["delivery"]["raw_observation_id"],
                        "status": "UNACKNOWLEDGED",
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    def pause(connection: sqlite3.Connection) -> None:
        _checkpoint(args, connection, phase, hold=True)

    if phase in BEFORE_STATEMENT:
        store = CheckpointStore(store.db_path, phase, pause)
    if scenario.get("during_commit") and os.environ.get("BH_GAP_COMMIT_REEXEC") != "1":
        if not args.commit_shim or not args.commit_shim.is_file():
            raise ValueError("E_GAP_COMMIT_SHIM")
        environment = dict(os.environ)
        environment.update(
            LD_PRELOAD=str(args.commit_shim.resolve()),
            BH_GAP_COMMIT_REEXEC="1",
            BH_SQL_COMMIT_ARMED="0",
            BH_SQL_COMMIT_READY=str(args.ready),
            BH_SQL_COMMIT_BOUNDARY=str(args.ready.with_name("boundary.json")),
            BH_SQL_COMMIT_IDENTITY=json.dumps(_identity(args), sort_keys=True),
            BH_SQL_DATABASE_SUFFIX="run.sqlite3",
        )
        os.execve(  # noqa: S606 -- fixed current interpreter and owned test child
            sys.executable,
            [sys.executable, "-I", str(Path(__file__).resolve()), *sys.argv[1:]],
            environment,
        )
    if scenario.get("during_commit"):
        original = store.connect

        def armed_connect() -> sqlite3.Connection:
            connection = original()
            connection.set_trace_callback(
                lambda statement: (
                    os.environ.__setitem__("BH_SQL_COMMIT_ARMED", "1")
                    if statement == "COMMIT"
                    else None
                )
            )
            return connection

        store.connect = armed_connect  # type: ignore[method-assign]
    if operation == "GAP":
        if phase == "after_late_rejection":
            Ingestor(store).store_late_repair(scenario["delivery"])
            with closing(store.connect()) as connection, connection:
                _waiting(connection, scenario["run_id"])
        else:
            apply_result(store, scenario["delivery"])
        if scenario.get("during_commit"):
            raise RuntimeError("E_GAP_COMMIT_BOUNDARY")
        if phase not in BEFORE_STATEMENT:
            with closing(store.connect()) as connection:
                _checkpoint(args, connection, phase, hold=not scenario["no_kill"])
    else:
        with closing(store.connect()) as connection:
            if operation == "CAPACITY":
                decision = GenerationController().capacity_decision(
                    used=7, incoming=1, normal_limit=7, terminal_reserve=1
                )
                (case / "capacity-decision.json").write_text(
                    json.dumps(
                        {
                            **decision,
                            "normal_limit": 7,
                            "terminal_reserve": 1,
                            "used": 7,
                            "incoming": 1,
                            "unacknowledged_rows": read_gap_state(store.db_path.parent)["spool"][
                                "count"
                            ],
                        },
                        sort_keys=True,
                    )
                )
                if decision["accepted"]:
                    raise ValueError("E_CAPACITY_EXPECTED_STOP")
                current = connection.execute("SELECT * FROM stream_generations").fetchone()
                connection.execute("BEGIN IMMEDIATE")
                Ingestor._gap(connection, current, 0, 2, "f" * 64, 10, "STORAGE_SAFETY_STOP")
                connection.commit()
            elif operation == "CLOCK":
                if not connection.execute("SELECT 1 FROM clock_mappings").fetchone():
                    with connection:
                        mapping = _mapping(connection, scenario["run_id"])
                else:
                    mapping = connection.execute(
                        "SELECT clock_mapping_id FROM clock_mappings"
                    ).fetchone()[0]
                connection.execute("BEGIN IMMEDIATE")
                _close_mapping(connection, mapping)
                if phase == "after_mapping_closure_insert":
                    _checkpoint(args, connection, phase, hold=True)
                connection.commit()
            elif operation == "EPOCH":
                connection.execute("BEGIN IMMEDIATE")
                if scenario["epoch_step"] == "shock":
                    _shock_close(
                        connection,
                        scenario["run_id"],
                        shock_type="EQUIVALENT_UNKNOWN_SHOCK",
                    )
                elif scenario["epoch_step"] == "pending":
                    _pending(connection, scenario)
                elif scenario["epoch_step"] == "release":
                    _release(connection, scenario["run_id"])
                elif scenario["epoch_step"] == "new_shock":
                    _new_shock_pending(connection, scenario["run_id"])
                if scenario.get("checkpoint_before_commit"):
                    _checkpoint(args, connection, phase, hold=True)
                connection.commit()
            _checkpoint(args, connection, phase, hold=not scenario["no_kill"])


if __name__ == "__main__":
    main()
