"""Test-only local TCP receiver exercising RunStore/Ingestor; no oracle access."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    # Direct -I invocation ignores caller cwd/PYTHONPATH; load only this checkout.
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]

from moj_discovery.canonical import canonical_content_hash  # noqa: E402
from moj_discovery.ingest import Ingestor  # noqa: E402
from moj_discovery.store import VENDOR, RunStore, read_journal  # noqa: E402
from tools.restart_state_reader import read_restart_state  # noqa: E402

# SQLite traces a statement BEFORE executing it. Pause before the next statement,
# never pretend the COMMIT trace is a checkpoint inside SQLite's commit machinery.
BEFORE_STATEMENT = {
    "after_raw_insert": "INSERT INTO application_records",
    "after_application_insert": "INSERT INTO derived_revisions",
    "after_revision_insert": "INSERT INTO reducer_cursors",
    "after_cursor_insert": "INSERT INTO ack_outbox",
    "after_outbox_insert": "COMMIT",
    "after_gap_insert": "INSERT INTO shock_observations",
    "after_shock_insert": "INSERT INTO coherence_transitions",
    "after_coherence_transition": "UPDATE coherence_controllers",
    "after_controller_close": "INSERT INTO gap_epoch_bindings",
    "after_epoch_binding": "UPDATE stream_generations",
    "after_predecessor_close": "INSERT INTO generation_transitions",
    "after_generation_transition": "INSERT INTO stream_generations",
    "after_successor_insert": "COMMIT",
}


def contract_not_implemented() -> None:
    raise RuntimeError("E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04")


def position(base: dict[str, Any], sequence: int) -> dict[str, Any]:
    value = json.loads(json.dumps(base))
    value["sequence"] = str(sequence)
    value["raw_observation_id"] = "observation:" + f"{sequence:064x}"
    value["content_hash"] = canonical_content_hash(
        "RawObservation", value, registry_path=VENDOR / "registries/canonical-hash-domains.v1.json"
    )
    return dict(value)


def provision(case: Path, base: dict[str, Any]) -> RunStore:
    run_dir = case / base["discovery_run_id"]
    run_dir.mkdir()
    store = RunStore(run_dir / "run.sqlite3")
    store.bootstrap_v1()
    run, browser, producer, stream = (
        base["discovery_run_id"],
        base["context"]["browser_run_id"],
        base["clock_context"]["clock_domain_id"],
        base["stream_id"],
    )
    with closing(store.connect()) as connection, connection:
        connection.execute(
            "INSERT INTO run_meta VALUES (?,1,'OPEN','test-only:offline',?,?,0,NULL)",
            (run, base["pack_hash"], base["build_hash"]),
        )
        connection.execute(
            "INSERT INTO stream_generations VALUES ('generation:0',?,?,?,?,0,NULL,"
            "'ACTIVE',0,NULL,NULL)",
            (run, browser, producer, stream),
        )
        connection.execute(
            "INSERT INTO coherence_epochs VALUES ('epoch:0',?,'fixture:test',0,NULL,"
            "'OPEN',NULL,NULL,0,0)",
            (run,),
        )
        connection.execute(
            "INSERT INTO coherence_controllers VALUES ('controller:test',?,'fixture:test',"
            "'OPEN','epoch:0',NULL,NULL,NULL,0,0)",
            (run,),
        )
    return store


class CheckpointStore(RunStore):
    """Only this test child installs the observer; runtime transaction code is unchanged."""

    def __init__(self, path: Path, phase: str, pause: Callable[[sqlite3.Connection], None]) -> None:
        super().__init__(path)
        self.phase, self.pause = phase, pause

    def connect(self) -> sqlite3.Connection:
        connection = super().connect()

        def trace(statement: str) -> None:
            if statement.startswith(BEFORE_STATEMENT[self.phase]):
                connection.set_trace_callback(None)
                self.pause(connection)

        connection.set_trace_callback(trace)
        return connection


class CommitIoStore(RunStore):
    """Arm the test-only preload hook immediately before SQLite enters COMMIT."""

    def connect(self) -> sqlite3.Connection:
        connection = super().connect()

        def trace(statement: str) -> None:
            if statement == "COMMIT":
                connection.set_trace_callback(None)
                os.environ["BH_SQL_COMMIT_ARMED"] = "1"

        connection.set_trace_callback(trace)
        return connection


def apply_result(store: RunStore, value: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"ack": Ingestor(store).apply(value)}
    except ValueError as error:
        return {"error": str(error)}


def recover(case: Path, *, replay: bool = False) -> None:
    scenario = json.loads((case / "scenario.json").read_text())
    store = RunStore(case / scenario["observation"]["discovery_run_id"] / "run.sqlite3")
    # A read-write reopen performs SQLite's hot journal recovery before the
    # separate read-only inspector. Reopen must never bootstrap a missing store.
    with closing(store.connect()):
        pass
    if not replay:
        (case / "reopened.json").write_text(json.dumps({"pid": os.getpid()}))
        return
    result = apply_result(store, scenario["delivery"])
    after = read_restart_state(store.db_path.parent)
    (case / "recovery.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "replay": result,
                "after": after,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recover", type=Path)
    parser.add_argument("--browser-server", type=Path)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--vector-id")
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--case-id")
    parser.add_argument("--checkpoint-id")
    parser.add_argument("--component")
    parser.add_argument("--ordinal", type=int)
    parser.add_argument("--test-nonce")
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    if args.browser_server is not None:
        browser_server(args.browser_server)
        return
    if args.recover is not None:
        recover(args.recover, replay=args.replay)
        return
    if args.ready is None or not args.hold:
        raise ValueError("E_CRASH_SCENARIO_REQUIRED")
    case = args.ready.parent
    scenario = json.loads((case / "scenario.json").read_text())
    phase = scenario["phase"]
    store = provision(case, scenario["observation"])
    for value in scenario["setup_deliveries"]:
        result = apply_result(store, value)
        if "error" in result and result["error"] != "E_INGEST_GAP":
            raise ValueError("E_CRASH_SETUP_FAILED")
    identity = {
        "run_id": args.run_id,
        "case_id": args.case_id,
        "checkpoint_id": args.checkpoint_id,
        "component": args.component,
        "pid": os.getpid(),
        "ordinal": args.ordinal,
        "test_nonce": args.test_nonce,
    }
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        address = listener.getsockname()
        with socket.create_connection(address, timeout=5) as sender:
            sender.sendall(json.dumps(scenario["delivery"]).encode() + b"\n")
            receiver, _ = listener.accept()
            with receiver, receiver.makefile("rb") as incoming:
                received = json.loads(incoming.readline(65537))
                wire_ack: dict[str, Any] | None = None
                ingest_result: dict[str, Any] | None = None

                def pause(connection: sqlite3.Connection) -> None:
                    witness = {
                        "identity": identity,
                        "phase": phase,
                        "in_transaction": connection.in_transaction,
                        "tables": read_journal(connection),
                        "received_observation_hash": received["content_hash"],
                        "transport_address": address,
                        "wire_ack": wire_ack,
                        "ingest_result": ingest_result,
                    }
                    (case / "boundary.json").write_text(json.dumps(witness, sort_keys=True))
                    temporary = args.ready.with_suffix(".tmp")
                    temporary.write_text(json.dumps(identity, sort_keys=True))
                    temporary.replace(args.ready)
                    while True:
                        signal.pause()

                if phase == "after_receive_before_begin":
                    with closing(store.connect()) as connection:
                        pause(connection)
                if phase in BEFORE_STATEMENT:
                    store = CheckpointStore(store.db_path, phase, pause)
                elif phase == "during_commit":
                    store = CommitIoStore(store.db_path)
                result = apply_result(store, received)
                ingest_result = result
                if phase == "after_duplicate_ack":
                    receiver.sendall(json.dumps(result).encode() + b"\n")
                    with sender.makefile("rb") as outgoing:
                        wire_ack = json.loads(outgoing.readline(65537))
                if phase in {
                    "after_commit_before_send",
                    "after_gap_commit",
                    "after_duplicate_ack",
                    "after_late_rejection",
                }:
                    with closing(store.connect()) as connection:
                        pause(connection)
                raise RuntimeError("E_CRASH_BOUNDARY_NOT_REACHED")


def browser_server(input_path: Path) -> None:
    """Disposable loopback transport. Token authorizes this fixture only, never discovery."""
    config = json.loads(input_path.read_text())
    if set(config) != {"identity", "observation", "origin", "token", "restart"}:
        raise ValueError("E_ACK_SERVER_INPUT")
    case = input_path.parent
    identity = {**config["identity"], "pid": os.getpid()}
    base = config["observation"]
    store = (
        RunStore(case / base["discovery_run_id"] / "run.sqlite3")
        if config["restart"]
        else provision(case, base)
    )
    with closing(store.connect()):
        pass
    checkpoint = identity["checkpoint_id"] if not config["restart"] else ""
    serial = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            pass

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", config["origin"])
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.end_headers()

        def do_POST(self) -> None:
            nonlocal serial
            size = int(self.headers.get("Content-Length", "0"))
            (case / "request-metadata.json").write_text(
                json.dumps(
                    {
                        "origin": self.headers.get("Origin"),
                        "path": self.path,
                        "size": size,
                    }
                )
            )
            if (
                self.headers.get("Origin") != config["origin"]
                or not 0 < size < 65536
                or self.path not in {"/ingest", "/confirm"}
            ):
                self.send_error(403)
                return
            request = json.loads(self.rfile.read(size))
            if set(request) != {"token", "value"} or request["token"] != config["token"]:
                self.send_error(403)
                return
            serial += 1
            value = request["value"]

            def pause() -> None:
                with closing(store.connect()) as connection:
                    witness = {
                        "identity": identity,
                        "path": self.path,
                        "value": value,
                        "in_transaction": connection.in_transaction,
                        "tables": read_journal(connection),
                    }
                (case / "backend-boundary.json").write_text(json.dumps(witness, sort_keys=True))
                ready = case / "backend-checkpoint.json"
                temporary = ready.with_suffix(".tmp")
                temporary.write_text(json.dumps(identity, sort_keys=True))
                temporary.replace(ready)
                while True:
                    signal.pause()

            if self.path == "/ingest":
                if value != base:
                    raise ValueError("E_ACK_SERVER_OBSERVATION")
                if checkpoint == "send_01_after_send_before_backend_begin":
                    pause()
                result = {"ack": Ingestor(store).apply(value)}
            else:
                if checkpoint == "ack_04_before_backend_confirmation_commit":
                    pause()
                result = {"confirmation": Ingestor(store).confirm_ack(value)}
                if checkpoint == "ack_05_after_backend_confirmation_commit":
                    pause()
            record = {
                "identity": identity,
                "request": request,
                "path": self.path,
                "response": result,
                "serial": serial,
            }
            (case / f"wire-{int(config['restart'])}-{serial}.json").write_text(
                json.dumps(record, sort_keys=True)
            )
            data = json.dumps(result, sort_keys=True).encode()
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", config["origin"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        ready = {"identity": identity, "address": list(server.server_address)}
        (case / f"server-{int(config['restart'])}.json").write_text(json.dumps(ready))
        server.serve_forever(poll_interval=0.05)


if __name__ == "__main__":
    main()
