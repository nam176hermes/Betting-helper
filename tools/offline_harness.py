"""Actual isolated processes and storage readers. No expected state enters this module."""

import hashlib
import json
import os
import secrets
import selectors
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Any, cast
from uuid import uuid4

from moj_discovery.canonical import canonical_content_hash
from moj_discovery.offline_run import create_offline_run
from moj_discovery.replay import verify_replay_equivalence
from moj_discovery.synthetic_source import load_synthetic_observations
from tools.offline_browser import ROOT, OfflineBrowser, prepare_offline_extension
from tools.offline_wire import run_wire_case


def process_group_sample(group: int) -> dict[str, Any]:
    ticks = resident = count = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            values = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(values[2]) == group:
                ticks += int(values[11]) + int(values[12])
                resident += int(values[21]) * os.sysconf("SC_PAGE_SIZE")
                count += 1
        except (OSError, ValueError):
            continue
    return {
        "sampled_processes": count,
        "cpu_seconds": ticks / os.sysconf("SC_CLK_TCK"),
        "summed_resident_bytes": resident,
        "measurement": "POINT_SAMPLE_NOT_PEAK_SHARED_PAGES_MAY_REPEAT",
    }


def source_hashes() -> dict[str, str]:
    paths = subprocess.check_output(  # noqa: S603 -- local read-only source inventory
        ["/usr/bin/git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(set(paths))
        if (ROOT / name).is_file() and not name.startswith("extension/.test-build/")
    }


class Backend:
    def __init__(self, run_dir: Path, output: Path, fault: str | None = None):
        self.output = output
        self.process = subprocess.Popen(  # noqa: S603 -- same provisioned interpreter, fixed local entrypoint
            [
                sys.executable,
                str(ROOT / "tools/run_offline_receiver.py"),
                "--run-dir",
                str(run_dir),
                *([] if fault is None else ["--fault", fault]),
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.observed: list[dict[str, Any]] = []
        try:
            ready = self.read()
            if ready != {"status": "LISTENING", "pid": self.process.pid}:
                raise RuntimeError("E_OFFLINE_BACKEND_IDENTITY")
        except BaseException:
            self.close()
            raise

    def read(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(10):
                raise RuntimeError("E_OFFLINE_BACKEND_TIMEOUT")
        value = json.loads(self.process.stdout.readline())
        self.observed.append(value)
        return cast(dict[str, Any], value)

    def register(self, count: int = 4) -> list[dict[str, Any]]:
        assert self.process.stdin is not None
        credentials = []
        for _ in range(count):
            sid, key = str(uuid4()), secrets.token_bytes(32)
            self.process.stdin.write(
                json.dumps(
                    {"operation": "REGISTER_SESSION", "session_id": sid, "key_hex": key.hex()}
                ).encode()
                + b"\n"
            )
            self.process.stdin.flush()
            if self.read() != {"status": "REGISTERED"}:
                raise RuntimeError("E_OFFLINE_BACKEND_REGISTER")
            credentials.append({"sessionId": sid, "key": list(key)})
        return credentials

    def close(self) -> None:
        if self.process.poll() is None:
            assert self.process.stdin is not None
            self.process.stdin.write(b'{"operation":"STOP"}\n')
            self.process.stdin.flush()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.output.write_text(
            json.dumps(
                {
                    "pid": self.process.pid,
                    "exit": self.process.returncode,
                    "observed": self.observed,
                },
                indent=2,
            )
        )

    def kill_at_checkpoint(self, run_dir: Path) -> dict[str, Any]:
        deadline = monotonic() + 10
        while not (run_dir / "checkpoint.json").is_file():
            if self.process.poll() is not None or monotonic() > deadline:
                raise RuntimeError("E_OFFLINE_CHECKPOINT_TIMEOUT")
            sleep(0.02)
        checkpoint = json.loads((run_dir / "checkpoint.json").read_text())
        if (
            checkpoint["pid"] != self.process.pid
            or os.getpgid(self.process.pid) != self.process.pid
        ):
            raise ValueError("E_OFFLINE_PROCESS_OWNERSHIP")
        self.process.kill()
        self.process.wait(timeout=10)
        if self.process.returncode != -signal.SIGKILL:
            raise ValueError("E_OFFLINE_PROCESS_NOT_KILLED")
        self.close()
        return cast(dict[str, Any], checkpoint)


@dataclass
class CaseExecution:
    run_dir: Path
    raw_hashes: list[str]
    actual_artifacts: list[dict[str, str]]
    command_exits: list[int]
    status: str


class SliceHarness:
    def __init__(self, workspace: Path, browser_binary: Path = Path("/opt/google/chrome/chrome")):
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.browser_binary = browser_binary

    def run_case(self, case_id: str, *, fault: str | None = None) -> CaseExecution:
        supported = {
            "OFF-01",
            "OFF-02",
            "OFF-03",
            "OFF-04",
            "OFF-05",
            "OFF-06",
            "OFF-07",
            "OFF-08",
            "OFF-09",
            "OFF-10",
            "OFF-23",
            "OFF-11",
            "OFF-12",
            "OFF-13",
            "OFF-14",
            "OFF-15",
            "OFF-16",
            "OFF-17",
            "OFF-18",
            "OFF-19",
            "OFF-24",
            "OFF-26",
            "OFF-27",
        }
        if case_id not in supported or fault is not None:
            raise ValueError("E_OFFLINE_CASE_NOT_IMPLEMENTED")
        case_started = monotonic()
        count = (
            1000
            if case_id == "OFF-19"
            else (
                1
                if case_id in {"OFF-03", "OFF-04", "OFF-05", "OFF-06", "OFF-07", "OFF-15", "OFF-24"}
                else 3
            )
        )
        directory = self.workspace / case_id
        directory.mkdir()
        before = source_hashes()
        extension, identity = prepare_offline_extension(directory)
        context: dict[str, Any] = {
            "schema_version": "offline-run-context/v1",
            "source_kind": "SYNTHETIC_TEST",
            **{
                name: str(uuid4())
                for name in ("run_id", "browser_run_id", "producer_id", "stream_id")
            },
            "generation": "0",
            "backend_url": "ws://127.0.0.1:8765/offline",
            "allowed_extension_origin": "chrome-extension://" + identity,
            "max_duration_seconds": 600,
            "max_frame_bytes": 262144,
            "max_raw_bytes": 65536,
            "max_batch_records": 32,
            "normal_spool_limit_bytes": "4096" if case_id == "OFF-18" else "133169152",
            "code_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
            "vendor_sha256": hashlib.sha256(
                (ROOT / "vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json").read_bytes()
            ).hexdigest(),
            "schema_lock_sha256": hashlib.sha256(
                (ROOT / "schema-lock.json").read_bytes()
            ).hexdigest(),
            "scenario_sha256": hashlib.sha256(
                f"offline-synthetic-accounting:{count}".encode()
            ).hexdigest(),
            "live_authority": False,
            "provider_authority": False,
            "money_authority": False,
        }
        store = create_offline_run(directory / "run", context)
        scenario = directory / "scenario.json"
        scenario.write_text(
            json.dumps(
                {
                    "schema_version": "offline-scenario/v1",
                    "source_kind": "SYNTHETIC_TEST",
                    "context": context,
                    "record_count": count,
                }
            )
        )
        rows = load_synthetic_observations(scenario)
        backend_fault = {
            "OFF-03": "DROP_ACK",
            "OFF-04": "AFTER_APPLY",
            "OFF-24": "AFTER_RECEIVED",
            "OFF-15": "FAKE_ACK",
            "OFF-27": "SQLITE_DENY_THIRD",
        }.get(case_id)
        backend = Backend(store.db_path.parent, directory / "backend.json", backend_fault)
        browser = None
        try:
            credentials = backend.register()
            browser = OfflineBrowser(
                directory / "browser",
                extension,
                context["allowed_extension_origin"],
                self.browser_binary,
            )
            observations: list[dict[str, Any]] = []

            def command(operation: str, **values: Any) -> dict[str, Any]:
                assert browser is not None
                observed = browser.command({"operation": operation, **values})
                observations.append({"operation": operation, **observed})
                return observed

            if (
                command(
                    "INIT",
                    context=context,
                    credentials=credentials,
                    batchSize=32 if case_id == "OFF-19" else 1,
                )["status"]
                != "OK"
            ):
                raise RuntimeError("E_OFFLINE_COMPONENT_REJECTED")
            started = monotonic()
            if case_id in {"OFF-08", "OFF-09", "OFF-10", "OFF-23"}:
                result = run_wire_case(case_id, context, backend.register(5), rows)
                (directory / "wire-observed.json").write_text(json.dumps(result, indent=2))
            elif case_id == "OFF-05":
                pending = browser.submit(
                    {"operation": "APPEND_PRECOMMIT", "observations": rows, "context": context}
                )
                deadline = monotonic() + 10
                while True:
                    checkpoint = command("READ_CHECKPOINTS")
                    if checkpoint.get("checkpoints"):
                        break
                    if monotonic() > deadline:
                        raise RuntimeError("E_OFFLINE_CHECKPOINT_TIMEOUT")
                    sleep(0.02)
                command("RESTART_WORKER")
                observations.append(browser.collect(pending))
                command("INIT", context=context, credentials=backend.register())
            elif case_id in {"OFF-11", "OFF-12", "OFF-26"}:
                poisoned = dict(rows[0])
                if case_id == "OFF-12":
                    poisoned["discovery_run_id"] = str(uuid4())
                else:
                    poisoned["unknown_command"] = secrets.token_hex(32)
                command("FORGED" if case_id == "OFF-26" else "APPEND", observations=[poisoned])
            elif case_id in {"OFF-02", "OFF-13", "OFF-14"}:
                command("APPEND", observations=rows[:1])
                command("FLUSH")
                next_row = rows[2] if case_id == "OFF-13" else rows[0]
                if case_id == "OFF-14":
                    next_row = {**rows[0], "facts": {**rows[0]["facts"], "observation_count": "2"}}
                    next_row["content_hash"] = canonical_content_hash("RawObservation", next_row)
                command(
                    "WIRE",
                    context=context,
                    credentials=backend.register(1),
                    observations=[next_row],
                )
                if case_id == "OFF-02":
                    command("APPEND", observations=rows[1:])
                    command("FLUSH")
            elif case_id == "OFF-27":
                command("WIRE", context=context, credentials=backend.register(1), observations=rows)
            else:
                command("PIPELINE" if case_id == "OFF-19" else "APPEND", observations=rows)
                if case_id in {"OFF-04", "OFF-24"}:
                    pending = browser.submit({"operation": "FLUSH"})
                    observations.append(backend.kill_at_checkpoint(store.db_path.parent))
                    command("RESTART_WORKER")
                    observations.append(browser.collect(pending))
                    backend = Backend(store.db_path.parent, directory / "backend-restarted.json")
                    command("INIT", context=context, credentials=backend.register())
                if case_id == "OFF-06":
                    command("RESTART_WORKER")
                    command("INIT", context=context, credentials=backend.register())
                if case_id == "OFF-07":
                    browser.close()
                    browser = None
                    browser = OfflineBrowser(
                        directory / "browser-resumed",
                        extension,
                        context["allowed_extension_origin"],
                        self.browser_binary,
                        profile=directory / "browser/profile",
                    )
                    command("INIT", context=context, credentials=backend.register())
                if case_id != "OFF-18":
                    command("FLUSH")
                if case_id == "OFF-19":
                    command(
                        "WIRE",
                        context=context,
                        credentials=backend.register(1),
                        observations=rows[:1],
                    )
            (directory / "resources.json").write_text(
                json.dumps(
                    {
                        "browser_group": process_group_sample(browser.owner.pid),
                        "backend_group": process_group_sample(backend.process.pid),
                    },
                    indent=2,
                )
            )
            browser.close()
            browser = None
            browser = OfflineBrowser(
                directory / "reader",
                extension,
                context["allowed_extension_origin"],
                self.browser_binary,
                profile=directory / "browser/profile",
            )
            reopened = browser.command({"operation": "INIT", "context": context, "credentials": []})
            elapsed = monotonic() - started
            (directory / "readback.json").write_text(
                json.dumps(
                    {"writer": observations, "reader": reopened, "elapsed_seconds": elapsed},
                    indent=2,
                )
            )
        finally:
            if browser is not None:
                browser.close()
            backend.close()
        if case_id == "OFF-16":
            retained = store.db_path.parent / "raw" / (rows[0]["content_hash"] + ".json")
            retained.rename(retained.with_suffix(".removed-by-negative-control"))
        workload_finished = monotonic()
        readback = json.loads((directory / "readback.json").read_text())
        readback["elapsed_seconds"] = workload_finished - started
        (directory / "readback.json").write_text(json.dumps(readback, indent=2))
        replay_started = monotonic()
        if case_id == "OFF-16":
            try:
                verify_replay_equivalence(store.db_path.parent, directory / "replay")
            except (ValueError, OSError):
                (directory / "replay-rejected.json").write_text('{"rejected":true}')
            else:
                raise ValueError("E_OFFLINE_NEGATIVE_CONTROL_ACCEPTED")
        else:
            verify_replay_equivalence(store.db_path.parent, directory / "replay")
        finished = monotonic()
        (directory / "timings.json").write_text(
            json.dumps(
                {
                    "setup_seconds": started - case_started,
                    "workload_and_cold_readback_seconds": workload_finished - started,
                    "replay_verification_seconds": finished - replay_started,
                    "execution_and_replay_seconds": finished - case_started,
                    "target_scope": "INITIALIZED_WORKLOAD_THROUGH_COLD_READBACK_AND_OWNED_SHUTDOWN",
                    "replay_verification_is_mandatory": True,
                },
                indent=2,
            )
        )
        after = source_hashes()
        if before != after:
            raise ValueError("E_OFFLINE_SOURCE_DRIFT")
        (directory / "sources.json").write_text(json.dumps(before, indent=2))
        artifacts = [
            {
                "path": str(p.relative_to(self.workspace)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(directory.rglob("*"))
            if p.is_file() and "profile" not in p.parts and "offline-extension" not in p.parts
        ]
        return CaseExecution(
            store.db_path.parent,
            [row["content_hash"] for row in rows],
            artifacts,
            [backend.process.returncode],
            "EXECUTED",
        )
