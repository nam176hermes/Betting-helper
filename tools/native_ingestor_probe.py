"""Disposable native Ingestor owner; no expected state, TCP or commit-I/O claim."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PREPARATION_SHA256 = "9c28ee8811c2bce507717958606257d6ee3a74cabb723f264b7a761e68ade2c1"
PHASES = ("NATIVE-INGEST-OUTBOX-PRECOMMIT", "NATIVE-INGEST-COMMITTED-PRE-OWNER-ACK")
COMMIT_PHASE = "NATIVE-WINDOWS-SQL06-COMMIT-IO"
MODULES = {
    "jsonschema": "jsonschema",
    "jsonschema-specifications": "jsonschema_specifications",
    "referencing": "referencing",
    "rpds-py": "rpds",
    "attrs": "attrs",
    "typing-extensions": "typing_extensions",
    "rfc8785": "rfc8785",
}


def loaded_dependencies(root: Path) -> dict[str, Any]:
    def descriptor(module: str) -> dict[str, str]:
        filename = importlib.import_module(module).__file__
        if filename is None:
            raise ValueError("E_NATIVE_DEPENDENCY_IMPORT")
        path = Path(filename).resolve()
        if not path.is_relative_to(root / "site-packages"):
            raise ValueError("E_NATIVE_DEPENDENCY_IMPORT")
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    return {
        "modules": {
            name: {**descriptor(module), "version": importlib.metadata.version(name)}
            for name, module in MODULES.items()
        },
        "native_rpds": descriptor("rpds.rpds"),
    }


def dependency_payload(root: Path) -> dict[str, str]:
    """Pinned preparation is authority for these exact previously approved bytes."""
    raw = (root / "preparation.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != PREPARATION_SHA256:
        raise ValueError("E_NATIVE_DEPENDENCY_PREPARATION")
    prepared = json.loads(raw)
    payload = root / "site-packages"
    files = {
        path.relative_to(payload).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in payload.rglob("*")
        if path.is_file()
    }
    if any(path.is_symlink() for path in payload.rglob("*")) or files != prepared["file_sha256"]:
        raise ValueError("E_NATIVE_DEPENDENCY_PAYLOAD")
    return files


def component(mode: str, config: dict[str, Any]) -> None:
    from tools.native_environment_probe import save

    required = {"root", "dependency_root", "run_dir", "identity"}
    if mode in {"setup", "write", "replay", "replay-again"}:
        required.add("delivery")
    if mode == "write" and config.get("identity", {}).get("case_id") == COMMIT_PHASE:
        required.add("commit_io")
    if set(config) != required or set(config["identity"]) != {"run_id", "case_id", "checkpoint_id"}:
        raise ValueError("E_NATIVE_INGESTOR_INPUT")
    identity = config["identity"]
    run_dir = Path(config["run_dir"])
    if (
        Path(config["root"]) != ROOT
        or run_dir.name != identity["run_id"]
        or identity["case_id"] not in (*PHASES, COMMIT_PHASE)
        or identity["checkpoint_id"] != identity["case_id"]
    ):
        raise ValueError("E_NATIVE_INGESTOR_IDENTITY")
    dependency_payload(Path(config["dependency_root"]))
    case = run_dir.parent
    save(case / f"{mode}.started.json", {"pid": os.getpid(), "identity": identity})
    deadline = time.monotonic() + 20
    while not (case / f"{mode}.start").is_file():
        if time.monotonic() > deadline:
            raise ValueError("E_NATIVE_INGESTOR_CONTROLLER")
        time.sleep(0.02)
    sys.path[:0] = [str(ROOT / "src"), str(Path(config["dependency_root"]) / "site-packages")]
    from moj_discovery.ingest import Ingestor
    from moj_discovery.store import RunStore, read_journal
    from tools.loopback_ack_crash_child import CheckpointStore, provision
    from tools.restart_state_reader import read_restart_state

    loaded = loaded_dependencies(Path(config["dependency_root"]))
    ack = None
    if mode == "setup":
        store = provision(case, config["delivery"])
    else:
        if not (run_dir / "run.sqlite3").is_file():
            raise ValueError("E_RESTART_MISSING_DATABASE")
        store = RunStore(run_dir / "run.sqlite3")
    if mode == "write":

        def snapshot(connection: Any) -> dict[str, Any]:
            return {
                "identity": {**identity, "pid": os.getpid()},
                "in_transaction": connection.in_transaction,
                "tables": read_journal(connection),
                "ingest_ack": ack,
                "owner_ack_published": False,
                "loaded_dependencies": loaded,
            }

        def pause(connection: Any) -> None:
            save(case / "checkpoint.json", snapshot(connection))
            while True:
                time.sleep(1)

        if identity["case_id"] == COMMIT_PHASE:
            from tools.native_sqlite_commit_io import CommitIoHook

            hook = CommitIoHook(store.db_path, case, config["commit_io"])

            class IoStore(RunStore):
                def connect(self) -> Any:
                    connection = super().connect()

                    def trace(statement: str) -> None:
                        if statement == "COMMIT":
                            connection.set_trace_callback(None)
                            hook.arm(connection, snapshot(connection))

                    connection.set_trace_callback(trace)
                    return connection

            ack = Ingestor(IoStore(store.db_path)).apply(config["delivery"])
            with closing(store.connect()) as connection:
                hook.fallback(snapshot(connection))
        if identity["case_id"] == PHASES[0]:
            store = CheckpointStore(store.db_path, "after_outbox_insert", pause)
        ack = Ingestor(store).apply(config["delivery"])
        with closing(store.connect()) as connection:
            pause(connection)
    elif mode in {"replay", "replay-again"}:
        ack = Ingestor(store).apply(config["delivery"])
    elif mode == "reopen":
        with closing(store.connect()):
            pass
    elif mode not in {"setup", "read", "final-read"}:
        raise ValueError("E_NATIVE_INGESTOR_MODE")
    print(
        json.dumps(
            {
                "pid": os.getpid(),
                "identity": identity,
                "state": read_restart_state(run_dir),
                "ack": ack,
                "loaded_dependencies": loaded,
            },
            sort_keys=True,
        )
    )


def owner(config: dict[str, Any], input_path: Path) -> dict[str, Any]:
    from tools.native_environment_probe import observe, observe_handle, save, sha

    extra = {"commit_io"} if "commit_io" in config else set()
    if set(config) != {"workspace", "root", "dependency_root", "delivery"} | extra:
        raise ValueError("E_NATIVE_INGESTOR_INPUT")
    if extra and config["commit_io"] not in {"armed", "bypass", "unarmed", "postcommit"}:
        raise ValueError("E_NATIVE_COMMIT_IO_MODE")
    dependency_payload(Path(config["dependency_root"]))
    workspace = Path(config["workspace"])
    cases = []
    for phase in (COMMIT_PHASE,) if extra else PHASES:
        case = workspace / phase
        case.mkdir()
        identity = {
            "run_id": config["delivery"]["discovery_run_id"],
            "case_id": phase,
            "checkpoint_id": phase,
        }
        base = {
            "root": config["root"],
            "dependency_root": config["dependency_root"],
            "run_dir": str(case / identity["run_id"]),
            "identity": identity,
        }
        inputs: dict[str, Any] = {}
        processes: list[dict[str, Any]] = []

        def launch(
            mode: str,
            held: bool = False,
            *,
            base: dict[str, Any] = base,
            case: Path = case,
            inputs: dict[str, Any] = inputs,
            identity: dict[str, Any] = identity,
            processes: list[dict[str, Any]] = processes,
            phase: str = phase,
        ) -> tuple[Any, dict[str, Any]]:
            cfg = {
                **base,
                **(
                    {"delivery": config["delivery"]}
                    if mode in {"setup", "write", "replay", "replay-again"}
                    else {}
                ),
            }
            if phase == COMMIT_PHASE and mode == "write":
                cfg["commit_io"] = config["commit_io"]
            input_file = case / f"{mode}.input.json"
            inputs[mode] = {"value": cfg, "artifact": save(input_file, cfg)}
            command = [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).resolve()),
                mode,
                str(input_file),
            ]
            with (
                (case / f"{mode}.stdout").open("wb") as out,
                (case / f"{mode}.stderr").open("wb") as err,
            ):
                child = subprocess.Popen(command, stdout=out, stderr=err)  # noqa: S603
            try:
                started = case / f"{mode}.started.json"
                deadline = time.monotonic() + 20
                while (
                    not started.is_file() and child.poll() is None and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                if json.loads(started.read_text()) != {"pid": child.pid, "identity": identity}:
                    raise ValueError("E_NATIVE_INGESTOR_STARTED")
                observed = observe(child)
                (case / f"{mode}.start").touch(exist_ok=False)
                if held:
                    return child, observed
                code = child.wait(timeout=25)
                output = (case / f"{mode}.stdout").read_bytes()
                if code or (case / f"{mode}.stderr").read_bytes():
                    raise ValueError("E_NATIVE_INGESTOR_CHILD:" + mode)
                value = json.loads(output)
                if value["pid"] != child.pid or value["identity"] != identity:
                    raise ValueError("E_NATIVE_INGESTOR_READER")
                process = {
                    "mode": mode,
                    "observed": observed,
                    "exit": code,
                    "value": value,
                    "stdout": {
                        "path": str(case / f"{mode}.stdout"),
                        "sha256": sha(case / f"{mode}.stdout"),
                    },
                    "stderr": {
                        "path": str(case / f"{mode}.stderr"),
                        "sha256": sha(case / f"{mode}.stderr"),
                    },
                }
                processes.append(process)
                return value, process
            finally:
                if not held or sys.exc_info()[0] is not None:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=10)

        before, _ = launch("setup")
        writer, initial = launch("write", True)
        try:
            ready = case / "checkpoint.json"
            deadline = time.monotonic() + 20
            while not ready.is_file() and writer.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            code = writer.poll()
            if code is not None or not ready.is_file():
                diagnostic = (
                    "E_NATIVE_INGESTOR_CHECKPOINT_TIMEOUT"
                    if code is None
                    else "E_NATIVE_INGESTOR_WRITER_EXIT"
                    if code
                    else "E_NATIVE_INGESTOR_CHECKPOINT_MISSING"
                )
                if code is None:
                    writer.kill()
                    code = writer.wait(timeout=10)
                stderr = case / "write.stderr"
                lines = stderr.read_text(errors="replace").splitlines()
                allowed = {
                    "ValueError: HOLD_NATIVE_COMMIT_IO_" + suffix
                    for suffix in ("DLL", "LOADED_DLL", "VFS", "SYSCALL", "INSTALL")
                }
                if code and lines and lines[-1] in allowed:
                    diagnostic = lines[-1].removeprefix("ValueError: ")
                failure = save(
                    case / "writer-failure.json",
                    {
                        "diagnostic": diagnostic,
                        "exit": code,
                        "writer": initial,
                        "checkpoint_present": ready.is_file(),
                        "stdout": {
                            "path": str(case / "write.stdout"),
                            "sha256": sha(case / "write.stdout"),
                        },
                        "stderr": {"path": str(stderr), "sha256": sha(stderr)},
                    },
                )
                raise ValueError(diagnostic + ":" + json.dumps(failure, sort_keys=True))
            checkpoint = json.loads(ready.read_text())
            observed = observe(writer)
            if checkpoint["identity"] != {**identity, "pid": writer.pid}:
                raise ValueError("E_NATIVE_INGESTOR_CHECKPOINT")
            journal = None
            if extra and checkpoint["commit_io"]["handle"]:
                from tools.native_sqlite_commit_io import duplicate_journal

                journal = duplicate_journal(writer, checkpoint["commit_io"]["handle"])
            writer.kill()
            code = writer.wait(timeout=10)
            if code != 1:
                raise ValueError("E_NATIVE_INGESTOR_TERMINATION")
        finally:
            if writer.poll() is None:
                writer.kill()
                writer.wait(timeout=10)
        reopened, _ = launch("reopen")
        after, _ = launch("read")
        replayed, _ = launch("replay")
        again, _ = launch("replay-again")
        final, _ = launch("final-read")
        cases.append(
            {
                "case_id": phase,
                **(
                    {
                        "journal_observation": journal,
                        "commit_io_events": {
                            "path": str(case / "commit-io-events.json"),
                            "sha256": sha(case / "commit-io-events.json"),
                        },
                    }
                    if extra
                    else {}
                ),
                "inputs": inputs,
                "processes": processes,
                "before": before["state"],
                "reopened": reopened["state"],
                "after": after["state"],
                "replayed": replayed["state"],
                "replayed_again": again["state"],
                "final": final["state"],
                "checkpoint": checkpoint,
                "checkpoint_artifact": {"path": str(ready), "sha256": sha(ready)},
                "writer": observed,
                "writer_start": initial,
                "writer_stdout": {
                    "path": str(case / "write.stdout"),
                    "sha256": sha(case / "write.stdout"),
                },
                "writer_stderr": {
                    "path": str(case / "write.stderr"),
                    "sha256": sha(case / "write.stderr"),
                },
                "termination": {
                    "mechanism": "WINDOWS_TERMINATE_PROCESS_OWNED_HANDLE",
                    "exit": code,
                    "pid": writer.pid,
                    "graceful": False,
                },
            }
        )
    return {
        "cases": cases,
        "system": os.name,
        "python_version": sys.version,
        "runtime_files": [
            {"path": str(path), "sha256": sha(path)}
            for path in [
                Path(sys.executable),
                Path(sys.executable).parent / "python312.dll",
                Path(sys.executable).parent / "DLLs/_sqlite3.pyd",
                Path(sys.executable).parent / "DLLs/sqlite3.dll",
            ]
        ],
        "controller": observe_handle(
            os.getpid(),
            -1,
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "owner", str(input_path)],
        ),
    }


if __name__ == "__main__":
    if os.name != "nt":
        raise ValueError("E_NATIVE_INGESTOR_WINDOWS_REQUIRED")
    sys.path.insert(0, str(ROOT))
    source = Path(sys.argv[2])
    config = json.loads(source.read_text())
    if sys.argv[1] == "owner":
        print(json.dumps(owner(config, source), sort_keys=True))
    else:
        component(sys.argv[1], config)
