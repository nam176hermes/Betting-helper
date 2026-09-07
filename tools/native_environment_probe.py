"""Native Windows test controller: real RunStore, owned handles, no ingest oracle."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.request import urlopen


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> dict[str, str]:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return {"path": str(path), "sha256": sha(path)}


def observe(child: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Query the live process through the exact owned native handle, not its label."""
    if child.poll() is not None:
        raise RuntimeError("E_ENV_NATIVE_HANDLE")
    return observe_handle(child.pid, int(child._handle), child.args)  # type: ignore[attr-defined]


def observe_handle(pid: int, handle: int, argv: Any) -> dict[str, Any]:
    """Read an already owned handle; the controller verifies its parent chain."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    query.restype = ctypes.c_int
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.c_ulong(len(buffer))
    if not query(handle, 0, buffer, ctypes.byref(size)):
        raise RuntimeError("E_ENV_NATIVE_HANDLE")
    command = subprocess.run(  # noqa: S603 -- read-only exact PID observation.
        [
            "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | "
            "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate | "
            "ConvertTo-Json -Compress",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    return {
        "pid": pid,
        "handle": handle,
        "executable": buffer.value,
        "sha256": sha(Path(buffer.value)),
        "argv": argv,
        "cim": json.loads(command.stdout),
        "cim_raw": command.stdout.decode().strip(),
    }


def component(mode: str, config: dict[str, Any]) -> None:
    gate = Path(config["ready"]).parent
    save(gate / f"{mode}.started.json", {"pid": os.getpid(), "mode": mode})
    deadline = time.monotonic() + 20
    while not (gate / f"{mode}.start").is_file():
        if time.monotonic() > deadline:
            raise RuntimeError("E_ENV_NATIVE_CONTROLLER_MISSING")
        time.sleep(0.02)
    sys.path[:0] = [str(Path(config["root"]) / "src"), config["root"], config["dependency_root"]]
    from moj_discovery.store import RunStore
    from tools.restart_state_reader import read_restart_state

    run_dir = Path(config["run_dir"])
    store = RunStore(run_dir / "run.sqlite3")
    if mode == "setup":
        run_dir.mkdir()
        store.bootstrap_v1()
        with closing(store.connect()) as connection, connection:
            connection.execute(
                "INSERT INTO run_meta VALUES (?,1,'OPEN','test-only:offline',?,?,0,NULL)",
                (run_dir.name, "a" * 64, "b" * 64),
            )
    elif mode == "write":
        with closing(store.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE run_meta SET run_status='CLOSED',closed_at_us=1")
            if config["phase"] == "after_commit":
                connection.commit()
            save(
                Path(config["ready"]),
                {
                    "pid": os.getpid(),
                    "run_id": run_dir.name,
                    "phase": config["phase"],
                    "in_transaction": connection.in_transaction,
                    "tables": {
                        "run_meta": [
                            dict(row) for row in connection.execute("SELECT * FROM run_meta")
                        ]
                    },
                },
            )
            while True:
                time.sleep(1)
    elif mode == "reopen":
        with closing(store.connect()):
            pass
    elif mode != "read":
        raise ValueError("E_ENV_NATIVE_MODE")
    print(json.dumps({"pid": os.getpid(), "state": read_restart_state(run_dir)}, sort_keys=True))


def storage(config: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(config["workspace"])
    cases = []
    script = str(Path(__file__).resolve())
    for phase in ("before_commit", "after_commit"):
        case = workspace / phase
        case.mkdir()
        cfg = {
            "root": config["root"],
            "dependency_root": config["dependency_root"],
            "run_dir": str(case / config["run_id"]),
            "phase": phase,
            "ready": str(case / "checkpoint.json"),
        }
        input_file = case / "input.json"
        save(input_file, cfg)
        processes: list[dict[str, Any]] = []

        def launch(
            mode: str,
            held: bool = False,
            *,
            case: Path = case,
            input_file: Path = input_file,
            processes: list[dict[str, Any]] = processes,
        ) -> tuple[Any, dict[str, Any]]:
            command = [sys.executable, "-I", script, mode, str(input_file)]
            with (
                (case / f"{mode}.stdout").open("wb") as stdout,
                (case / f"{mode}.stderr").open("wb") as stderr,
            ):
                child = subprocess.Popen(command, stdout=stdout, stderr=stderr)  # noqa: S603
            deadline = time.monotonic() + 15
            started = case / f"{mode}.started.json"
            while not started.is_file() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if json.loads(started.read_text())["pid"] != child.pid:
                child.kill()
                child.wait(timeout=10)
                raise RuntimeError("E_ENV_NATIVE_START_IDENTITY")
            observation = observe(child)
            (case / f"{mode}.start").touch(exist_ok=False)
            if held:
                return child, observation
            code = child.wait(timeout=20)
            out = (case / f"{mode}.stdout").read_bytes()
            err = (case / f"{mode}.stderr").read_bytes()
            if code or err:
                raise RuntimeError(f"E_ENV_NATIVE_CHILD:{mode}:{code}:{err.decode()}")
            value = json.loads(out)
            if value["pid"] != child.pid:
                raise RuntimeError("E_ENV_NATIVE_READER_PID")
            processes.append(
                {
                    "mode": mode,
                    "pid": child.pid,
                    "argv": command,
                    "exit": code,
                    "observed": observation,
                    "stdout": {
                        "path": str(case / f"{mode}.stdout"),
                        "sha256": sha(case / f"{mode}.stdout"),
                    },
                    "stderr": {
                        "path": str(case / f"{mode}.stderr"),
                        "sha256": sha(case / f"{mode}.stderr"),
                    },
                }
            )
            return value, processes[-1]

        baseline, _ = launch("setup")
        writer, writer_start = launch("write", True)
        try:
            deadline = time.monotonic() + 15
            while (
                not Path(cfg["ready"]).is_file()
                and writer.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            checkpoint = json.loads(Path(cfg["ready"]).read_text())
            observed = observe(writer)
            if checkpoint["pid"] != writer.pid or checkpoint["phase"] != phase:
                raise RuntimeError("E_ENV_NATIVE_CHECKPOINT")
            writer.kill()  # Windows Popen uses TerminateProcess on its retained owned handle.
            code = writer.wait(timeout=10)
            if code != 1:
                raise RuntimeError("E_ENV_NATIVE_TERMINATION")
        finally:
            if writer.poll() is None:
                writer.kill()
                writer.wait(timeout=10)
        reopened, _ = launch("reopen")
        after, _ = launch("read")
        cases.append(
            {
                "phase": phase,
                "input": {"path": str(input_file), "sha256": sha(input_file)},
                "before": baseline["state"],
                "after": after["state"],
                "reopened": reopened["state"],
                "checkpoint": checkpoint,
                "writer": observed,
                "writer_start": writer_start,
                "processes": processes,
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
                },
            }
        )
    runtime = Path(sys.executable).parent
    return {
        "result": "PASS",
        "cases": cases,
        "system": platform.system(),
        "platform": platform.platform(),
        "python_version": sys.version,
        "sqlite_version": sqlite3.sqlite_version,
        "pid": os.getpid(),
        "executable": str(Path(sys.executable)),
        "runtime_files": [
            {"path": str(path), "sha256": sha(path)}
            for path in [
                Path(sys.executable),
                runtime / "python312.dll",
                runtime / "DLLs/_sqlite3.pyd",
                runtime / "DLLs/sqlite3.dll",
            ]
        ],
        "physical_power_loss": "HOLD_NOT_EXECUTED",
        "native_ingestor": "HOLD_MISSING_NATIVE_SCHEMA_DEPENDENCIES",
    }


def browser_leader(config: dict[str, Any]) -> None:
    """The leader owns the sole job handle; its death kills inherited Chrome members."""
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("minimum", ctypes.c_size_t),
            ("maximum", ctypes.c_size_t),
            ("active", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (
        not job
        or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
        or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())
    ):
        raise RuntimeError("E_ENV_WINDOWS_JOB")
    if config.get("transport") == "pipe":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tools.qualify_chrome_indexeddb import _pipe_node_environment

        case = Path(config["workspace"])
        with (case / "node.stdout").open("wb") as out, (case / "node.stderr").open("wb") as err:
            child = subprocess.Popen(  # noqa: S603 -- exact retained pipe program, owned job.
                [config["node"], config["script"], config["input_path"]],
                stdout=out,
                stderr=err,
                env=_pipe_node_environment(),
            )
        save(
            case / "node-ready.json",
            {
                "leader_pid": os.getpid(),
                "job_handle": int(job),
                "job_kill_on_close": True,
                "node": observe(child),
            },
        )
        while child.poll() is None:
            time.sleep(0.05)
        raise RuntimeError("E_ENV_PIPE_OWNER_EXIT")
    with (Path(config["workspace"]) / "chrome.log").open("wb") as log:
        child = subprocess.Popen(config["command"], stdout=log, stderr=log)  # noqa: S603 -- fixed approved browser command.
    save(
        Path(config["workspace"]) / "browser-ready.json",
        {
            "leader_pid": os.getpid(),
            "job_handle": int(job),
            "job_kill_on_close": True,
            "browser": observe(child),
        },
    )
    while True:
        time.sleep(1)


def browser(config: dict[str, Any], input_path: Path) -> dict[str, Any]:
    if config.get("transport") == "pipe":
        return pipe_browser(config, input_path)
    case = Path(config["workspace"])
    with (case / "leader.stdout").open("wb") as out, (case / "leader.stderr").open("wb") as err:
        leader = subprocess.Popen(  # noqa: S603 -- fixed native leader and owned input.
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "browser-leader",
                str(input_path),
            ],
            stdout=out,
            stderr=err,
        )  # noqa: S603
    pages: list[dict[str, Any]] = []
    try:
        deadline = time.monotonic() + 20
        ready = case / "browser-ready.json"
        while not ready.is_file() and leader.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        raw = json.loads(ready.read_text())
        observed = observe(leader)
        if raw["leader_pid"] != leader.pid:
            raise RuntimeError("E_ENV_BROWSER_LEADER")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{config['port']}/json/list", timeout=1) as response:
                    pages = json.loads(response.read())
            except OSError:
                time.sleep(0.1)
                continue
            if any(page.get("url") == config["origin"] + "/repair-probe.html" for page in pages):
                break
            time.sleep(0.1)
        matched = any(page.get("url") == config["origin"] + "/repair-probe.html" for page in pages)
        document = None
        if matched:
            target = next(
                page for page in pages if page.get("url") == config["origin"] + "/repair-probe.html"
            )
            evaluation = subprocess.run(  # noqa: S603 -- bound local CDP program.
                [
                    config["node"],
                    "-e",
                    config["cdp_script"],
                    target["webSocketDebuggerUrl"],
                    "({origin:location.origin,protocol:location.protocol,"
                    "probe:Boolean(globalThis.repairProbe),"
                    "extensionId:globalThis.chrome?.runtime?.id ?? null})",
                ],
                capture_output=True,
                check=True,
                timeout=15,
            )  # noqa: S603 -- bound fixed local CDP program.
            document = json.loads(evaluation.stdout)
            save(case / "document-observation.json", document)
            matched = (
                document["origin"] == config["origin"]
                and document["protocol"] == "chrome-extension:"
                and document["probe"]
                and document["extensionId"] == config["origin"].split("://")[1]
            )
        enumeration = subprocess.run(  # noqa: S603 -- read only the owned descendant tree.
            [
                "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$queue=[System.Collections.Generic.Queue[int]]::new(); "
                f"$queue.Enqueue({leader.pid}); $rows=@(); "
                "while($queue.Count){$taskpid=$queue.Dequeue(); "
                '$children=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$taskpid"); '
                "foreach($child in $children){$rows += $child | "
                "Select-Object ProcessId,ParentProcessId,ExecutablePath,CreationDate; "
                "$queue.Enqueue($child.ProcessId)}}; "
                "ConvertTo-Json -InputObject @($rows) -Compress",
            ],
            capture_output=True,
            check=True,
            timeout=20,
        )  # noqa: S603 -- observe this owned job tree only.
        descendants = json.loads(enumeration.stdout)
        if raw["browser"]["pid"] not in {item["ProcessId"] for item in descendants}:
            raise RuntimeError("E_ENV_BROWSER_DESCENDANTS")
    finally:
        if leader.poll() is None:
            leader.kill()
        code = leader.wait(timeout=10)
    browser_pid = raw["browser"]["pid"]
    # A terminated job must not leave the named browser process alive.
    owned_ids = [item["ProcessId"] for item in descendants]
    pid_filter = " OR ".join(f"ProcessId={pid}" for pid in owned_ids)
    check = subprocess.run(  # noqa: S603 -- exact observed descendant PID set, read only.
        [
            "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"@(Get-CimInstance Win32_Process -Filter '{pid_filter}').Count",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )  # noqa: S603
    if code != 1 or check.stdout.strip() != b"0":
        raise RuntimeError("E_ENV_BROWSER_JOB_SURVIVOR")
    return {
        "result": "PASS" if matched else "HOLD",
        "observed_error": None if matched else "E_EXTENSION_TARGET_UNAVAILABLE",
        "origin": config["origin"],
        "pages": pages,
        "document": document,
        "leader": observed,
        "descendants_before": descendants,
        "descendants_raw": enumeration.stdout.decode().strip(),
        "descendant_cleanup_raw": check.stdout.decode().strip(),
        **raw,
        "termination": {
            "mechanism": "WINDOWS_JOB_KILL_ON_CONTROLLER_TERMINATION",
            "leader_exit": code,
            "browser_pid": browser_pid,
            "remaining_named_browser_processes": 0,
            "observed_descendant_pids": owned_ids,
            "remaining_observed_descendants": 0,
        },
        "scope": "UNPACKED_EXTENSION_TARGET_AVAILABILITY_ONLY",
        "physical_power_loss": "HOLD_NOT_EXECUTED",
    }


def pipe_browser(config: dict[str, Any], input_path: Path) -> dict[str, Any]:
    """Force the first owned job down, then run the independent successor reader."""
    from ctypes import wintypes

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.qualify_chrome_indexeddb import _pipe_work

    phases = []
    for phase in ("before", "after"):
        case = Path(config["workspace"]) / phase
        case.mkdir()
        request = dict(config["requests"][phase])
        phase_cfg = {
            key: config[key]
            for key in ("transport", "command", "extension", "origin", "node", "script")
        }
        phase_cfg.update(workspace=str(case), input_path=str(case / "input.json"))
        save(case / "input.json", phase_cfg)
        invocation = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "browser-leader",
            str(case / "input.json"),
        ]
        with (case / "leader.stdout").open("wb") as out, (case / "leader.stderr").open("wb") as err:
            leader = subprocess.Popen(invocation, stdout=out, stderr=err)  # noqa: S603
        try:
            deadline = time.monotonic() + 30
            while not all(
                (case / name).is_file() for name in ("node-ready.json", "pipe-ready.json")
            ):
                if leader.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("E_ENV_PIPE_READY")
                time.sleep(0.02)
            observed = observe(leader)
            ready = json.loads((case / "node-ready.json").read_text())
            pipe_ready = json.loads((case / "pipe-ready.json").read_text())
            if pipe_ready["node_pid"] != ready["node"]["pid"]:
                raise RuntimeError("E_ENV_PIPE_PARENT")
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000 | 0x100000, False, pipe_ready["pid"])
            if not handle:
                raise RuntimeError("E_ENV_PIPE_CHROME_HANDLE")
            try:
                chrome = observe_handle(pipe_ready["pid"], int(handle), config["command"])
            finally:
                kernel.CloseHandle(handle)
            if chrome["cim"]["ParentProcessId"] != ready["node"]["pid"]:
                raise RuntimeError("E_ENV_PIPE_CHROME_PARENT")
            request["identity"] = {
                "run_id": config["profile_id"],
                "pid": chrome["pid"],
                "phase": phase,
            }
            work = _pipe_work(config["profile_id"], phase, config["worker_ids"][phase], request)
            save(case / "start.json", work)
            deadline = time.monotonic() + 35
            while not (case / "pipe-result.json").is_file():
                if (case / "pipe-error.json").is_file():
                    raise RuntimeError(
                        "E_ENV_PIPE_EXECUTION:" + (case / "pipe-error.json").read_text()
                    )
                if leader.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("E_ENV_PIPE_RESULT")
                time.sleep(0.02)
            result = json.loads((case / "pipe-result.json").read_text())
            enumeration = subprocess.run(  # noqa: S603 -- only owned descendants, read-only.
                [
                    "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "function Desc([int]$taskpid){$children=@(Get-CimInstance "
                    "Win32_Process -Filter "
                    '"ParentProcessId=$taskpid");foreach($c in $children){$c | Select-Object '
                    "ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine;"
                    "Desc $c.ProcessId}};"
                    f"ConvertTo-Json -InputObject @(Desc {leader.pid}) -Compress",
                ],
                capture_output=True,
                check=True,
                timeout=15,
            )
            descendants = json.loads(enumeration.stdout)
        finally:
            if leader.poll() is None:
                leader.kill()  # Owned leader handle; inherited job kills Node/Chrome.
            code = leader.wait(timeout=10)
        ids = [row["ProcessId"] for row in descendants]
        cleanup = subprocess.run(  # noqa: S603 -- read-only exact observed identity set.
            [
                "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter '"
                + " OR ".join(f"ProcessId={pid}" for pid in ids)
                + "' | Select-Object ProcessId,ParentProcessId,CreationDate,"
                "ExecutablePath,CommandLine) -Compress",
            ],
            capture_output=True,
            check=True,
            timeout=15,
        )
        survivors = [old for old in descendants if old in json.loads(cleanup.stdout)]
        if code != 1 or survivors:
            raise RuntimeError("E_ENV_PIPE_JOB_SURVIVOR")
        phases.append(
            {
                "phase": phase,
                "config": phase_cfg,
                "leader": observed,
                **ready,
                "browser": chrome,
                "result": result,
                "work": work,
                "descendants": descendants,
                "descendants_raw": enumeration.stdout.decode(),
                "cleanup_raw": cleanup.stdout.decode(),
                "cleanup_command": cleanup.args,
                "termination": {
                    "mechanism": "WINDOWS_JOB_KILL_ON_CONTROLLER_TERMINATION",
                    "leader_exit": code,
                    "remaining_observed_descendants": 0,
                    "graceful": False,
                },
            }
        )
    return {
        "phases": phases,
        "input_path": str(input_path),
        "controller": observe_handle(
            os.getpid(),
            -1,
            [sys.executable, "-I", str(Path(__file__).resolve()), "browser", str(input_path)],
        ),
    }


if __name__ == "__main__":
    if os.name != "nt":
        raise RuntimeError("E_ENV_NATIVE_WINDOWS_REQUIRED")
    configuration = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    if sys.argv[1] == "storage":
        print(json.dumps(storage(configuration), sort_keys=True))
    elif sys.argv[1] == "browser":
        print(json.dumps(browser(configuration, Path(sys.argv[2])), sort_keys=True))
    elif sys.argv[1] == "browser-leader":
        browser_leader(configuration)
    else:
        component(sys.argv[1], configuration)
