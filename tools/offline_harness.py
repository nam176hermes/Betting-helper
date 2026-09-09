"""Actual isolated processes and storage readers. No expected state enters this module."""

import hashlib
import json
import secrets
import selectors
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from moj_discovery.offline_run import create_offline_run
from moj_discovery.synthetic_source import load_synthetic_observations
from tools.offline_browser import ROOT, OfflineBrowser, prepare_offline_extension


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
    def __init__(self, run_dir: Path, output: Path):
        self.output = output
        self.process = subprocess.Popen(  # noqa: S603 -- same provisioned interpreter, fixed local entrypoint
            [
                sys.executable,
                str(ROOT / "tools/run_offline_receiver.py"),
                "--run-dir",
                str(run_dir),
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
        self.workspace.mkdir(parents=True, exist_ok=False)
        self.browser_binary = browser_binary

    def run_case(self, case_id: str, *, fault: str | None = None) -> CaseExecution:
        if case_id != "OFF-01" or fault is not None:
            raise ValueError("E_OFFLINE_CASE_NOT_IMPLEMENTED")
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
            "normal_spool_limit_bytes": "133169152",
            "code_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
            "vendor_sha256": hashlib.sha256(
                (ROOT / "vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json").read_bytes()
            ).hexdigest(),
            "schema_lock_sha256": hashlib.sha256(
                (ROOT / "schema-lock.json").read_bytes()
            ).hexdigest(),
            "scenario_sha256": hashlib.sha256(b"offline-synthetic-accounting:3").hexdigest(),
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
                    "record_count": 3,
                }
            )
        )
        rows = load_synthetic_observations(scenario)
        backend = Backend(store.db_path.parent, directory / "backend.json")
        browser = None
        try:
            credentials = backend.register()
            browser = OfflineBrowser(
                directory / "browser",
                extension,
                context["allowed_extension_origin"],
                self.browser_binary,
            )
            observations = []
            requests: list[dict[str, Any]] = [
                {"operation": "INIT", "context": context, "credentials": credentials},
                {"operation": "APPEND", "observations": rows},
                {"operation": "FLUSH"},
            ]
            for request in requests:
                observed = browser.command(request)
                observations.append(observed)
                if observed["status"] != "OK":
                    raise RuntimeError("E_OFFLINE_COMPONENT_REJECTED")
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
            (directory / "readback.json").write_text(
                json.dumps({"writer": observations, "reader": reopened}, indent=2)
            )
        finally:
            if browser is not None:
                browser.close()
            backend.close()
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
