"""Supplemental real environment experiments; never broad/physical qualification."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any
from uuid import uuid4

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from tools.run_indexeddb_crash_matrix import CHROME, PACK, ROOT, _observations
from tools.verify_repair_evidence import capture_binding

if TYPE_CHECKING:
    from tools.retained_artifact_io import RetainedArtifactIO

NATIVE = Path(
    "/mnt/c/Users/thenam/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
)
WINDOWS_PARENT = Path("/mnt/c/Users/thenam/Documents/BettingHelper-Repair-Chrome")


def artifact(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path: Path, value: Any) -> dict[str, str]:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return artifact(path)


def winpath(path: Path) -> str:
    resolved = path.resolve()
    # The qualified Windows C: workspace is not mounted into review namespaces.
    # Translate its identity without making the drive or original artifacts visible.
    if resolved.is_relative_to("/mnt/c"):
        return str(PureWindowsPath("C:/", *resolved.relative_to("/mnt/c").parts))
    return subprocess.run(  # noqa: S603 -- fixed path translation utility.
        ["/usr/bin/wslpath", "-w", str(resolved)], check=True, capture_output=True, text=True
    ).stdout.strip()  # noqa: S603


def localpath(path: str) -> Path:
    if path.startswith("/"):
        return Path(path)
    windows = PureWindowsPath(path)
    if windows.is_absolute() and windows.drive.casefold() == "c:":
        return Path("/mnt/c", *windows.parts[1:]).resolve()
    return Path(
        subprocess.run(  # noqa: S603 -- fixed path translation utility.
            ["/usr/bin/wslpath", "-u", path], check=True, capture_output=True, text=True
        ).stdout.strip()
    )  # noqa: S603


def checked(
    descriptor: dict[str, str],
    *,
    artifacts: RetainedArtifactIO | None = None,
    recorded_boundary: str | None = None,
) -> bytes:
    if artifacts is not None:
        if recorded_boundary is None:
            raise ValueError("E_ENV_ARTIFACT_BOUNDARY")
        data = artifacts.read_bytes(descriptor["path"], recorded_boundary=recorded_boundary)
    else:
        if recorded_boundary is not None:
            raise ValueError("E_ENV_ARTIFACT_BOUNDARY")
        data = localpath(descriptor["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
        raise ValueError("E_ENV_ARTIFACT_HASH")
    return data


def _browser_file_paths(case: Path, modules: dict[str, str], *, workers: bool) -> list[Path]:
    paths = [case / "test-extension" / name for name in sorted(modules)]
    paths.extend(case / "test-extension" / name for name in ("manifest.json", "repair-probe.html"))
    paths.append(case / "profile/environment-profile.json")
    if workers:
        paths.extend(case / f"{phase}-worker.json" for phase in ("before", "after"))
    return paths


def environment_retained_boundaries(report: dict[str, Any], workspace: Path) -> tuple[Path, ...]:
    """Only the controller workspace and explicitly owned per-run native stores."""
    roots = {workspace.resolve()}
    for name, value in report["reports"].items():
        if name in {"native_ingestor", "native_commit_io"}:
            owned = localpath(value["config"]["workspace"])
            prefix = "native-ingestor-"
        elif name in {"native", "windows_browser"}:
            owned = Path(value["owned_workspace"])
            prefix = "environment-" if name == "native" else "browser-environment-"
        else:
            continue
        if owned.parent != WINDOWS_PARENT or not owned.name.startswith(prefix):
            raise ValueError("E_ENV_ARTIFACT_BOUNDARY")
        roots.add(owned)
    return tuple(sorted(roots))


def environment_live_roots() -> tuple[Path, ...]:
    """Verified native prerequisites, never the parent containing disposable stores."""
    from tools.run_native_ingestor_qualification import DEPENDENCIES, dependency_binding

    dependency = dependency_binding()
    return (
        ROOT,
        NATIVE.parent.parent,
        CHROME,
        Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"),
        DEPENDENCIES,
        *(Path(row["path"]) for row in dependency["wheels"]),
    )


def run_native_storage(workspace: Path) -> dict[str, Any]:
    import rfc8785

    workspace.mkdir(parents=True, exist_ok=True)
    owned = WINDOWS_PARENT / f"environment-{uuid4()}"
    owned.mkdir(parents=True, exist_ok=False)
    dependency = owned / "dependencies"
    source = Path(rfc8785.__file__).parent
    shutil.copytree(source, dependency / "rfc8785", ignore=shutil.ignore_patterns("__pycache__"))
    closure = [
        {"source": artifact(path), "copy": artifact(dependency / "rfc8785" / path.name)}
        for path in sorted(source.iterdir())
        if path.is_file()
    ]
    configuration = {
        "workspace": winpath(owned),
        "root": winpath(ROOT),
        "dependency_root": winpath(dependency),
        "run_id": str(uuid4()),
    }
    input_file = workspace / "native-input.json"
    save(input_file, configuration)
    command = [
        str(NATIVE),
        "-I",
        winpath(ROOT / "tools/native_environment_probe.py"),
        "storage",
        winpath(input_file),
    ]
    completed = subprocess.run(command, capture_output=True, timeout=100)  # noqa: S603 -- fixed cached native runtime and test entrypoint.
    (workspace / "native.stdout").write_bytes(completed.stdout)
    (workspace / "native.stderr").write_bytes(completed.stderr)
    if completed.returncode or completed.stderr:
        raise RuntimeError(f"E_ENV_NATIVE_OWNER:{completed.returncode}:{completed.stderr.decode()}")
    result: dict[str, Any] = json.loads(completed.stdout)
    result.update(
        {
            "binding": capture_binding(),
            "dependency_closure": closure,
            "owner_command": command,
            "owner_exit": completed.returncode,
            "owner_input": artifact(input_file),
            "owner_stdout": artifact(workspace / "native.stdout"),
            "owner_stderr": artifact(workspace / "native.stderr"),
            "owned_workspace": str(owned),
            "entrypoint": artifact(ROOT / "tools/native_environment_probe.py"),
        }
    )
    verify_native_storage(result)
    save(workspace / "native-terminal.json", result)
    return result


def verify_native_storage(
    report: dict[str, Any], *, artifacts: RetainedArtifactIO | None = None
) -> None:
    from moj_discovery.store import validate_journal

    def retained(descriptor: dict[str, str]) -> bytes:
        boundary = artifacts.recorded_boundary(descriptor["path"]) if artifacts else None
        return checked(descriptor, artifacts=artifacts, recorded_boundary=boundary)

    try:
        if (
            report["result"] != "PASS"
            or report["system"] != "Windows"
            or len(report["cases"]) != 2
            or report["binding"] != capture_binding()
            or report["owner_exit"] != 0
            or report["physical_power_loss"] != "HOLD_NOT_EXECUTED"
            or report["native_ingestor"] != "HOLD_MISSING_NATIVE_SCHEMA_DEPENDENCIES"
        ):
            raise ValueError("header")
        raw = json.loads(retained(report["owner_stdout"]))
        if any(report[key] != value for key, value in raw.items()) or retained(
            report["owner_stderr"]
        ):
            raise ValueError("owner")
        for entry in report["dependency_closure"]:
            if checked(entry["source"]) != retained(entry["copy"]):
                raise ValueError("dependency")
        for item in report["runtime_files"]:
            checked(item)
        checked(report["entrypoint"])
        cfg = json.loads(retained(report["owner_input"]))
        if cfg["root"] != winpath(ROOT) or cfg["workspace"] != winpath(
            Path(report["owned_workspace"])
        ):
            raise ValueError("owner paths")
        if report["owner_command"] != [
            str(NATIVE),
            "-I",
            winpath(ROOT / "tools/native_environment_probe.py"),
            "storage",
            winpath(Path(report["owner_input"]["path"])),
        ]:
            raise ValueError("owner command")
        identities = set()
        for phase, state, row in zip(
            ("before_commit", "after_commit"), ("OPEN", "CLOSED"), report["cases"], strict=True
        ):
            if (
                row["phase"] != phase
                or row["before"]["tables"]["run_meta"][0]["run_status"] != "OPEN"
            ):
                raise ValueError("phase")
            if (
                row["after"]["tables"]["run_meta"][0]["run_status"] != state
                or row["after"] != row["reopened"]
            ):
                raise ValueError("durability")
            validate_journal(row["before"]["tables"])
            validate_journal(row["after"]["tables"])
            checkpoint = row["checkpoint"]
            writer = row["writer"]
            writer_identity = _verify_native_observation(
                writer,
                [
                    winpath(NATIVE),
                    "-I",
                    winpath(ROOT / "tools/native_environment_probe.py"),
                    "write",
                    row["input"]["path"],
                ],
                report["pid"],
            )
            if row["writer_start"] != writer:
                raise ValueError("writer replaced")
            if (
                checkpoint["pid"] != writer["pid"]
                or writer["pid"] != writer["cim"]["ProcessId"]
                or writer["cim"]["ParentProcessId"] != report["pid"]
                or checkpoint["in_transaction"] != (phase == "before_commit")
                or checkpoint["run_id"] != cfg["run_id"]
                or row["termination"]
                != {
                    "mechanism": "WINDOWS_TERMINATE_PROCESS_OWNED_HANDLE",
                    "pid": writer["pid"],
                    "exit": 1,
                }
                or retained(row["writer_stdout"])
                or retained(row["writer_stderr"])
            ):
                raise ValueError("process")
            if (
                json.loads(writer["cim_raw"]) != writer["cim"]
                or localpath(writer["executable"]) != NATIVE
            ):
                raise ValueError("observation")
            if hashlib.sha256(NATIVE.read_bytes()).hexdigest() != writer["sha256"]:
                raise ValueError("executable")
            child_input = json.loads(retained(row["input"]))
            if set(child_input) != {"root", "dependency_root", "run_dir", "phase", "ready"}:
                raise ValueError("oracle in child")
            if [p["mode"] for p in row["processes"]] != ["setup", "reopen", "read"]:
                raise ValueError("readers")
            for process in row["processes"]:
                expected_command = [
                    winpath(NATIVE),
                    "-I",
                    winpath(ROOT / "tools/native_environment_probe.py"),
                    process["mode"],
                    row["input"]["path"],
                ]
                process_identity = _verify_native_observation(
                    process["observed"], expected_command, report["pid"]
                )
                if (
                    process["argv"] != expected_command
                    or process["observed"]["pid"] != process["pid"]
                ):
                    raise ValueError("reader command")
                value = json.loads(retained(process["stdout"]))
                if (
                    process["exit"] != 0
                    or value["pid"] != process["pid"]
                    or retained(process["stderr"])
                ):
                    raise ValueError("reader")
                if value["state"] != (
                    row["before"] if process["mode"] == "setup" else row["after"]
                ):
                    raise ValueError("readback")
                identities.add(process_identity)
            identities.add(writer_identity)
        if len(identities) != 8:
            raise ValueError("independent processes")
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ValueError("E_ENV_NATIVE_EVIDENCE") from error


def _verify_native_observation(
    row: dict[str, Any],
    command: list[str],
    parent: int,
    *,
    wsl_entry: bool = False,
) -> tuple[int, int]:
    cim = row.get("cim")
    if not isinstance(cim, dict) or set(cim) != {
        "ProcessId",
        "ParentProcessId",
        "ExecutablePath",
        "CommandLine",
        "CreationDate",
    }:
        raise ValueError("E_ENV_NATIVE_OBSERVATION")
    creation = cim["CreationDate"]
    match = re.fullmatch(r"/Date\(([0-9]+)\)/", creation) if isinstance(creation, str) else None
    if match is None:
        raise ValueError("E_ENV_NATIVE_OBSERVATION")
    try:
        # Windows PowerShell ConvertTo-Json emits the observed UTC epoch milliseconds.
        datetime.fromtimestamp(int(match[1]) / 1000, UTC)
    except (ValueError, OverflowError, OSError) as error:
        raise ValueError("E_ENV_NATIVE_OBSERVATION") from error
    command_lines = [subprocess.list2cmdline(command)]
    if wsl_entry:
        command_lines.append(subprocess.list2cmdline(["python.exe", *command[1:]]))
    if (
        row["argv"] != command
        or row["cim"]["CommandLine"] not in command_lines
        or row["pid"] != row["cim"]["ProcessId"]
        or row["cim"]["ParentProcessId"] != parent
        or row["pid"] == parent
        or row["executable"] != row["cim"]["ExecutablePath"]
        or localpath(row["executable"]) != localpath(command[0])
        or row["sha256"] != artifact(localpath(command[0]))["sha256"]
        or json.loads(row["cim_raw"]) != row["cim"]
        or not row["handle"]
    ):
        raise ValueError("E_ENV_NATIVE_OBSERVATION")
    return row["pid"], int(match[1])


def run_filesystem_faults(workspace: Path) -> dict[str, Any]:
    from tools.owner_mutation_evidence import process
    from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix

    workspace.mkdir(parents=True, exist_ok=True)
    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    selected = [row for row in registry if row["vector_id"].startswith(("SQL-06-", "SQL-07-"))]
    control = run_sqlite_crash_matrix(
        PACK, workspace / "commit-io", entries=selected, include_mutations=False
    )
    original = (
        Path(control["records"][1]["case_directory"])
        / control["records"][1]["actual"]["after"]["run_id"]
    )
    faults = []
    for fault, error in (
        ("truncated_database", "E_RESTART_DATABASE"),
        ("corrupt_header", "E_RESTART_DATABASE"),
        ("schema_corruption", "E_STORE_SCHEMA"),
        ("missing_database", "E_RESTART_MISSING_DATABASE"),
    ):
        case = workspace / fault
        case.mkdir()
        run_dir = case / original.name
        shutil.copytree(original, run_dir)
        database = run_dir / "run.sqlite3"
        before, reader_before = process(
            case, "sql-read", {"run_id": original.name}, "reader-before"
        )
        shutil.copy2(database, case / "before.sqlite3")
        if fault == "truncated_database":
            with database.open("r+b") as stream:
                stream.truncate(128)
        elif fault == "corrupt_header":
            with database.open("r+b") as stream:
                stream.write(b"BROKEN SQLITE!!!")
        elif fault == "schema_corruption":
            connection = sqlite3.connect(database)
            connection.execute("DROP TRIGGER raw_commits_no_update")
            connection.commit()
            connection.close()
        else:
            database.rename(case / "removed.sqlite3")
        changed = artifact(database) if database.exists() else None
        rejection, reader_after = process(
            case, "sql-read", {"run_id": original.name}, "reader-after", rejection=True
        )
        if rejection != {"observed_error": error} or (
            fault == "missing_database" and database.exists()
        ):
            raise ValueError("E_ENV_CORRUPTION_NOT_REJECTED")
        faults.append(
            {
                "fault": fault,
                "case_directory": str(case),
                "run_id": original.name,
                "before": before,
                "before_copy": artifact(case / "before.sqlite3"),
                "after_file": changed,
                "reader_before": reader_before,
                "reader_after": reader_after,
                "observed_error": error,
                "removed_copy": artifact(case / "removed.sqlite3")
                if fault == "missing_database"
                else None,
            }
        )
    report = {
        "result": "PASS",
        "binding": capture_binding(),
        "faults": faults,
        "commit_io": control,
        "physical_power_loss": "HOLD_NOT_EXECUTED",
        "scope": "SOFTWARE_FAULT_INJECTION_ONLY",
    }
    verify_filesystem_faults(report)
    save(workspace / "filesystem-terminal.json", report)
    return report


def verify_filesystem_faults(
    report: dict[str, Any], *, artifacts: RetainedArtifactIO | None = None
) -> None:
    from tools.owner_mutation_evidence import verify_process
    from tools.verify_repair_evidence import _RETAINED_ARTIFACTS, aggregate_repair_evidence

    def retained(descriptor: dict[str, str]) -> bytes:
        boundary = artifacts.recorded_boundary(descriptor["path"]) if artifacts else None
        return checked(descriptor, artifacts=artifacts, recorded_boundary=boundary)

    if (
        report["binding"] != capture_binding()
        or report["physical_power_loss"] != "HOLD_NOT_EXECUTED"
    ):
        raise ValueError("E_ENV_FILESYSTEM_BINDING")
    controls = report["commit_io"]["records"]
    if (
        aggregate_repair_evidence(
            [row["vector_id"] for row in controls], controls, artifacts=artifacts
        )["result"]
        != "PASS"
    ):
        raise ValueError("E_ENV_FILESYSTEM_CONTROL")
    names = [
        ("truncated_database", "E_RESTART_DATABASE"),
        ("corrupt_header", "E_RESTART_DATABASE"),
        ("schema_corruption", "E_STORE_SCHEMA"),
        ("missing_database", "E_RESTART_MISSING_DATABASE"),
    ]
    token = _RETAINED_ARTIFACTS.set(artifacts)
    try:
        for (name, error), fault in zip(names, report["faults"], strict=True):
            case = Path(fault["case_directory"])
            request = {"run_id": fault["run_id"]}
            if fault["fault"] != name or fault["observed_error"] != error:
                raise ValueError("E_ENV_FILESYSTEM_FAULT")
            verify_process(
                fault["reader_before"],
                case,
                "sql-read",
                "reader-before",
                request,
                fault["before"],
            )
            verify_process(
                fault["reader_after"],
                case,
                "sql-read",
                "reader-after",
                request,
                {"observed_error": error},
                rejection=True,
            )
            before = retained(fault["before_copy"])
            if fault["before"] != controls[1]["actual"]["after"]:
                raise ValueError("E_ENV_FILESYSTEM_BASELINE")
            if name == "missing_database":
                if (
                    retained(fault["removed_copy"]) != before
                    or (case / fault["run_id"] / "run.sqlite3").exists()
                ):
                    raise ValueError("E_ENV_FILESYSTEM_ABSENCE")
            else:
                after = retained(fault["after_file"])
                if (
                    name == "truncated_database"
                    and after != before[:128]
                    or name == "corrupt_header"
                    and after != b"BROKEN SQLITE!!!" + before[16:]
                    or name == "schema_corruption"
                    and after == before
                ):
                    raise ValueError("E_ENV_FILESYSTEM_BYTES")
    finally:
        _RETAINED_ARTIFACTS.reset(token)


def run_browser_restart(workspace: Path) -> dict[str, Any]:
    from tools.qualify_chrome_indexeddb import (
        _browser_process_observation,
        _evaluate,
        _kill_owned_process_group,
        _prepare_test_extension,
        _start_chrome,
        _wait_for_probe,
    )
    from tools.run_indexeddb_crash_matrix import PRODUCER, REGISTRY, STREAM

    workspace.mkdir(parents=True, exist_ok=True)
    extension, extension_id, _ = _prepare_test_extension(ROOT, workspace)
    profile = workspace / "profile"
    profile.mkdir()
    profile_id = str(uuid4())
    save(profile / "environment-profile.json", {"id": profile_id})
    values = _observations(profile_id)
    origin = f"chrome-extension://{extension_id}"
    records = []
    processes = []
    launches = []
    requests = []
    terminations = []
    sentinels = []
    modules = {
        str(path.relative_to(extension)): artifact(path)["sha256"]
        for path in extension.rglob("*.js")
    }
    for phase in ("before", "after"):
        child, socket = _start_chrome(
            CHROME, profile, extension, origin + "/repair-probe.html", workspace / f"{phase}.log"
        )
        try:
            processes.append(_browser_process_observation(child))
            launches.append(child.args)
            _wait_for_probe(socket)
            sentinel_method = "writeSentinel" if phase == "before" else "readSentinel"
            args = (
                f"{json.dumps(profile_id)},{json.dumps(profile_id)}"
                if phase == "before"
                else json.dumps(profile_id)
            )
            sentinels.append(_evaluate(socket, f"globalThis.repairProbe.{sentinel_method}({args})"))
            worker_id = str(uuid4())
            request = {
                "operation": "exercise" if phase == "before" else "read",
                "identity": {"run_id": profile_id, "pid": child.pid, "phase": phase},
                "options": {
                    "browser_run_id": profile_id,
                    "producer_id": PRODUCER,
                    "stream_id": STREAM,
                    "generation": "0",
                    "registry": json.loads(REGISTRY.read_text()),
                },
                "observations": [
                    json.dumps(value, sort_keys=True, separators=(",", ":")) for value in values
                ]
                if phase == "before"
                else [],
            }
            reply = _evaluate(
                socket,
                f"globalThis.repairProbe.startWorker({json.dumps(worker_id)},{json.dumps(request)})",
            )
            requests.append(
                save(
                    workspace / f"{phase}-input.json", {"worker_id": worker_id, "request": request}
                )
            )
            records.append(reply)
            save(workspace / f"{phase}-worker.json", reply)
        finally:
            termination = _kill_owned_process_group(child)
        save(workspace / f"{phase}-termination.json", termination)
        terminations.append(termination)
    report = {
        "result": "PASS",
        "binding": capture_binding(),
        "before": records[0],
        "after": records[1],
        "processes": processes,
        "profile": str(profile),
        "profile_id": profile_id,
        "origin": origin,
        "case_directory": str(workspace.resolve()),
        "inputs": requests,
        "modules": modules,
        "sentinels": sentinels,
        "launches": launches,
        "terminations": terminations,
        "physical_power_loss": "HOLD_NOT_EXECUTED",
    }
    report["retained_browser_files"] = [
        artifact(path) for path in _browser_file_paths(workspace, modules, workers=True)
    ]
    verify_browser_restart(report)
    save(workspace / "browser-terminal.json", report)
    return report


def verify_browser_restart(
    report: dict[str, Any], *, artifacts: RetainedArtifactIO | None = None
) -> None:
    from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]

    from tools.qualify_chrome_indexeddb import _browser_command, _extension_id
    from tools.run_indexeddb_crash_matrix import (
        PRODUCER,
        REGISTRY,
        STREAM,
        compare_indexeddb_state,
    )

    def read_path(path: Path) -> bytes:
        recorded = str(path)
        return (
            artifacts.read_bytes(recorded, recorded_boundary=artifacts.recorded_boundary(recorded))
            if artifacts is not None
            else path.read_bytes()
        )

    def retained(descriptor: dict[str, str]) -> bytes:
        boundary = artifacts.recorded_boundary(descriptor["path"]) if artifacts else None
        return checked(descriptor, artifacts=artifacts, recorded_boundary=boundary)

    from tools.verify_repair_evidence import (
        _compiled_browser_module_hashes,
        _typescript_compile_binding,
    )

    try:
        current = capture_binding()
        case = Path(report["case_directory"])
        extension = case / "test-extension"
        profile = Path(report["profile"])
        modules = report["modules"]
        if report["binding"] != current or report["physical_power_loss"] != "HOLD_NOT_EXECUTED":
            raise ValueError("binding")
        if modules != _compiled_browser_module_hashes(_typescript_compile_binding(current)):
            raise ValueError("modules")
        expected_files = _browser_file_paths(case, modules, workers=True)
        files = report["retained_browser_files"]
        if [row["path"] for row in files] != [str(path) for path in expected_files]:
            raise ValueError("browser files")
        for row in files:
            retained(row)
        for name, digest in modules.items():
            if hashlib.sha256(read_path(extension / name)).hexdigest() != digest:
                raise ValueError("module bytes")
        for name, source in (
            ("manifest.json", "repair-manifest.json"),
            ("repair-probe.html", "repair-probe.html"),
        ):
            if (
                read_path(extension / name)
                != (ROOT / "extension/test-harness" / source).read_bytes()
            ):
                raise ValueError("asset")
        key = json.loads(read_path(extension / "manifest.json"))["key"]
        if report["origin"] != "chrome-extension://" + _extension_id(key):
            raise ValueError("origin")
        if json.loads(read_path(profile / "environment-profile.json")) != {
            "id": report["profile_id"]
        }:
            raise ValueError("profile")
        if report["processes"][0]["pid"] == report["processes"][1]["pid"]:
            raise ValueError("restart")
        observations = _observations(report["profile_id"])
        for phase, process, termination, descriptor, sentinel, argv in zip(
            ("before", "after"),
            report["processes"],
            report["terminations"],
            report["inputs"],
            report["sentinels"],
            report["launches"],
            strict=True,
        ):
            port = int(
                next(
                    arg.split("=", 1)[1]
                    for arg in argv
                    if arg.startswith("--remote-debugging-port=")
                )
            )
            headless = [
                " ".join(
                    [
                        *argv[:-1],
                        "--noerrdialogs",
                        "--ozone-platform=headless",
                        "--ozone-override-screen-size=800,600",
                        "--use-angle=swiftshader-webgl",
                        argv[-1],
                    ]
                )
            ]
            raw_argv = bytes.fromhex(process["proc_cmdline_hex"]).rstrip(b"\0").decode().split("\0")
            if (
                argv
                != _browser_command(
                    CHROME, profile, extension, report["origin"] + "/repair-probe.html", port
                )
                or raw_argv != process["argv"]
                or raw_argv not in (argv, headless)
                or process["pid"] != process["pgid"]
                or not process["proc_stat"].startswith(str(process["pid"]) + " ")
                or process["sha256"] != artifact(CHROME)["sha256"]
                or termination["returncode"] != -9
                or termination["method"] != "SIGKILL_PROCESS_GROUP"
            ):
                raise ValueError("process")
            value = json.loads(read_path(case / f"{phase}-worker.json"))
            request = json.loads(retained(descriptor))
            ordinary_request: dict[str, Any] = {
                "operation": "exercise" if phase == "before" else "read",
                "identity": {"run_id": report["profile_id"], "pid": process["pid"], "phase": phase},
                "options": {
                    "browser_run_id": report["profile_id"],
                    "producer_id": PRODUCER,
                    "stream_id": STREAM,
                    "generation": "0",
                    "registry": json.loads(REGISTRY.read_text()),
                },
                "observations": [
                    json.dumps(raw, sort_keys=True, separators=(",", ":")) for raw in observations
                ]
                if phase == "before"
                else [],
            }
            if (
                set(request) != {"worker_id", "request"}
                or request["request"] != ordinary_request
                or Path(descriptor["path"]) != case / f"{phase}-input.json"
            ):
                raise ValueError("ordinary input")
            if (
                value != report[phase]
                or value.get("error")
                or value["worker_id"] != request["worker_id"]
                or value["pid"] != process["pid"]
                or value["origin"] != report["origin"]
                or value["module_sha256"] != modules["src/spool.js"]
                or sentinel["sentinel"] != report["profile_id"]
                or sentinel["profileId"] != report["profile_id"]
                or sentinel["origin"] != report["origin"]
            ):
                raise ValueError("readback")
            if phase == "after" and request["request"]["observations"]:
                raise ValueError("reader input")
            # Only observations 1 and 2 survived; 3 was aborted. Validate the
            # actual envelopes, cursor chain, keys, ACK=1 and next sequence=3.
            compare_indexeddb_state(value, ordinary_request["identity"], observations, 2, ack=1)
        before = report["before"]
        first, second = [entry["spool_record"] for entry in before["entries"]]
        if (
            before["aborted"] is not True
            or before["first"] != first
            or before["second"] != second
            or before["duplicate"] != first
            or before["pending"] != [second]
            or before["invalid_ack"] != "Error: E_SPOOL_ACK"
            or any(
                report["before"][key] != report["after"][key]
                for key in ("entries", "states", "keys")
            )
        ):
            raise ValueError("state")
    except (KeyError, ValueError, TypeError, OSError, StopIteration, ValidationError) as error:
        raise ValueError("E_ENV_BROWSER_EVIDENCE") from error


def run_windows_browser(workspace: Path) -> dict[str, Any]:
    from tools.qualify_chrome_indexeddb import _pipe_browser_command, _prepare_test_extension
    from tools.run_indexeddb_crash_matrix import PRODUCER, REGISTRY, STREAM

    workspace.mkdir(parents=True, exist_ok=True)
    owned = WINDOWS_PARENT / f"browser-environment-{uuid4()}"
    owned.mkdir(parents=True, exist_ok=False)
    extension, extension_id, _ = _prepare_test_extension(ROOT, owned)
    profile = owned / "profile"
    profile.mkdir()
    profile_id = str(uuid4())
    save(profile / "environment-profile.json", {"id": profile_id})
    script = owned / "chrome_pipe.cjs"
    shutil.copy2(ROOT / "tools/chrome_pipe.cjs", script)
    browser = Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")
    command = _pipe_browser_command(browser, profile)
    command[0] = winpath(browser)
    command = [arg.replace(str(profile.resolve()), winpath(profile)) for arg in command]
    requests = {
        phase: {
            "operation": "exercise" if phase == "before" else "read",
            "options": {
                "browser_run_id": profile_id,
                "producer_id": PRODUCER,
                "stream_id": STREAM,
                "generation": "0",
                "registry": json.loads(REGISTRY.read_text()),
            },
            "observations": [
                json.dumps(value, sort_keys=True, separators=(",", ":"))
                for value in _observations(profile_id)
            ]
            if phase == "before"
            else [],
        }
        for phase in ("before", "after")
    }
    config = {
        "transport": "pipe",
        "workspace": winpath(owned),
        "command": command,
        "extension": winpath(extension),
        "origin": "chrome-extension://" + extension_id,
        "node": winpath(NATIVE.parent.parent / "node/bin/node.exe"),
        "script": winpath(script),
        "profile_id": profile_id,
        "requests": requests,
        "worker_ids": {phase: str(uuid4()) for phase in ("before", "after")},
    }
    input_file = workspace / "windows-browser-input.json"
    save(input_file, config)
    invocation = [
        str(NATIVE),
        "-I",
        winpath(ROOT / "tools/native_environment_probe.py"),
        "browser",
        winpath(input_file),
    ]
    completed = subprocess.run(invocation, capture_output=True, timeout=180)  # noqa: S603
    (workspace / "windows-browser.stdout").write_bytes(completed.stdout)
    (workspace / "windows-browser.stderr").write_bytes(completed.stderr)
    if completed.returncode or completed.stderr:
        raise RuntimeError(
            f"E_ENV_WINDOWS_BROWSER:{completed.returncode}:{completed.stderr.decode()}"
        )
    raw = json.loads(completed.stdout)
    for phase in raw["phases"]:
        case = owned / phase["phase"]
        for key, name in (
            ("transcript", "pipe.ndjson"),
            ("result_artifact", "pipe-result.json"),
            ("work_artifact", "start.json"),
            ("config_artifact", "input.json"),
            ("node_stderr", "node.stderr"),
            ("node_stdout", "node.stdout"),
            ("leader_stderr", "leader.stderr"),
            ("leader_stdout", "leader.stdout"),
            ("chrome_stdout", "chrome.stdout"),
            ("chrome_stderr", "chrome.stderr"),
        ):
            phase[key] = artifact(case / name)
    first = raw["phases"][0]
    report = {
        **raw,
        "result": "PASS",
        "restart_result": "PASS",
        "case_id": "WINDOWS-CHROME-PROCESS-RESTART",
        "binding": capture_binding(),
        "input": artifact(input_file),
        "owner_command": invocation,
        "stdout": artifact(workspace / "windows-browser.stdout"),
        "stderr": artifact(workspace / "windows-browser.stderr"),
        "owned_workspace": str(owned),
        "profile_id": profile_id,
        "origin": config["origin"],
        "script": artifact(script),
        "browser_binary": artifact(browser),
        "node_binary": artifact(NATIVE.parent.parent / "node/bin/node.exe"),
        "modules": {
            str(path.relative_to(extension)): artifact(path)["sha256"]
            for path in extension.rglob("*.js")
        },
        "before": first["result"]["worker"],
        "after": raw["phases"][1]["result"]["worker"],
        "browser": first["browser"],
        "document": first["result"]["document"],
        "termination": first["termination"],
        "observed_error": None,
        "physical_power_loss": "HOLD_NOT_EXECUTED",
    }
    report["retained_browser_files"] = [
        artifact(path) for path in _browser_file_paths(owned, report["modules"], workers=False)
    ]
    verify_windows_browser(report)
    save(workspace / "windows-browser-terminal.json", report)
    return report


def verify_windows_browser(
    report: dict[str, Any], *, artifacts: RetainedArtifactIO | None = None
) -> None:
    from tools.qualify_chrome_indexeddb import (
        _extension_id,
        _pipe_browser_command,
        _pipe_work,
        _verify_pipe_transcript,
    )
    from tools.run_indexeddb_crash_matrix import PRODUCER, REGISTRY, STREAM, compare_indexeddb_state
    from tools.verify_repair_evidence import (
        _compiled_browser_module_hashes,
        _typescript_compile_binding,
    )

    try:
        current = capture_binding()

        def retained(descriptor: dict[str, str]) -> bytes:
            boundary = artifacts.recorded_boundary(descriptor["path"]) if artifacts else None
            return checked(descriptor, artifacts=artifacts, recorded_boundary=boundary)

        def read_path(path: Path) -> bytes:
            recorded = str(path)
            return (
                artifacts.read_bytes(
                    recorded, recorded_boundary=artifacts.recorded_boundary(recorded)
                )
                if artifacts is not None
                else path.read_bytes()
            )

        cfg = json.loads(retained(report["input"]))
        raw = json.loads(retained(report["stdout"]))
        owned = Path(report["owned_workspace"])
        profile = owned / "profile"
        extension = owned / "test-extension"
        script = owned / "chrome_pipe.cjs"
        browser = Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")
        if (
            report["binding"] != current
            or retained(report["stderr"])
            or report["result"] != "PASS"
            or report["restart_result"] != "PASS"
            or report["case_id"] != "WINDOWS-CHROME-PROCESS-RESTART"
            or report["physical_power_loss"] != "HOLD_NOT_EXECUTED"
            or retained(report["script"]) != (ROOT / "tools/chrome_pipe.cjs").read_bytes()
            or Path(report["script"]["path"]) != script
            or localpath(report["browser_binary"]["path"]) != browser
        ):
            raise ValueError("binding")
        # Executables are live prerequisites, never retained-artifact substitutes.
        checked(report["browser_binary"])
        checked(report["node_binary"])
        expected_invocation = [
            str(NATIVE),
            "-I",
            winpath(ROOT / "tools/native_environment_probe.py"),
            "browser",
            winpath(Path(report["input"]["path"])),
        ]
        native_invocation = [winpath(NATIVE), *expected_invocation[1:]]
        if (
            report["owner_command"] != expected_invocation
            or owned.parent != WINDOWS_PARENT
            or raw["input_path"] != expected_invocation[-1]
            or report["controller"] != raw["controller"]
        ):
            raise ValueError("controller")
        _verify_native_observation(
            report["controller"],
            native_invocation,
            report["controller"]["cim"]["ParentProcessId"],
            wsl_entry=True,
        )
        for name, source in (
            ("manifest.json", "repair-manifest.json"),
            ("repair-probe.html", "repair-probe.html"),
        ):
            if (
                read_path(extension / name)
                != (ROOT / "extension/test-harness" / source).read_bytes()
            ):
                raise ValueError("asset")
        origin = "chrome-extension://" + _extension_id(
            json.loads(read_path(extension / "manifest.json"))["key"]
        )
        if report["origin"] != origin or json.loads(
            read_path(profile / "environment-profile.json")
        ) != {"id": report["profile_id"]}:
            raise ValueError("profile")
        modules = report["modules"]
        if modules != _compiled_browser_module_hashes(_typescript_compile_binding(current)):
            raise ValueError("compiled modules")
        expected_files = _browser_file_paths(owned, modules, workers=False)
        files = report["retained_browser_files"]
        if [row["path"] for row in files] != [str(path) for path in expected_files]:
            raise ValueError("browser files")
        for row in files:
            retained(row)
        if any(
            hashlib.sha256(read_path(extension / name)).hexdigest() != digest
            for name, digest in modules.items()
        ):
            raise ValueError("module bytes")
        command = _pipe_browser_command(browser, profile)
        command[0] = winpath(browser)
        command = [arg.replace(str(profile.resolve()), winpath(profile)) for arg in command]
        requests = {
            phase: {
                "operation": "exercise" if phase == "before" else "read",
                "options": {
                    "browser_run_id": report["profile_id"],
                    "producer_id": PRODUCER,
                    "stream_id": STREAM,
                    "generation": "0",
                    "registry": json.loads(REGISTRY.read_text()),
                },
                "observations": [
                    json.dumps(value, sort_keys=True, separators=(",", ":"))
                    for value in _observations(report["profile_id"])
                ]
                if phase == "before"
                else [],
            }
            for phase in ("before", "after")
        }
        expected_cfg = {
            "transport": "pipe",
            "workspace": winpath(owned),
            "command": command,
            "extension": winpath(extension),
            "origin": origin,
            "node": winpath(NATIVE.parent.parent / "node/bin/node.exe"),
            "script": winpath(script),
            "profile_id": report["profile_id"],
            "requests": requests,
            "worker_ids": cfg["worker_ids"],
        }
        if cfg != expected_cfg or set(cfg["worker_ids"]) != {"before", "after"}:
            raise ValueError("config")
        observed_identities: set[tuple[int, int]] = set()
        for phase, row, saved in zip(
            ("before", "after"), report["phases"], raw["phases"], strict=True
        ):
            if any(row.get(key) != value for key, value in saved.items()):
                raise ValueError("raw owner")
            case = owned / phase
            expected_phase_cfg = {
                key: cfg[key]
                for key in ("transport", "command", "extension", "origin", "node", "script")
            }
            expected_phase_cfg.update(
                workspace=winpath(case), input_path=winpath(case / "input.json")
            )
            if row["phase"] != phase or row["config"] != expected_phase_cfg:
                raise ValueError("phase config")
            for key, name in (
                ("transcript", "pipe.ndjson"),
                ("result_artifact", "pipe-result.json"),
                ("work_artifact", "start.json"),
                ("config_artifact", "input.json"),
                ("node_stderr", "node.stderr"),
                ("node_stdout", "node.stdout"),
                ("leader_stderr", "leader.stderr"),
                ("leader_stdout", "leader.stdout"),
                ("chrome_stdout", "chrome.stdout"),
                ("chrome_stderr", "chrome.stderr"),
            ):
                if Path(row[key]["path"]) != case / name:
                    raise ValueError("artifact path")
                content = retained(row[key])
                if (
                    key
                    in {
                        "node_stderr",
                        "node_stdout",
                        "leader_stderr",
                        "leader_stdout",
                        "chrome_stdout",
                    }
                    and content
                ):
                    raise ValueError("unexpected output")
            leader_command = [
                winpath(NATIVE),
                "-I",
                winpath(ROOT / "tools/native_environment_probe.py"),
                "browser-leader",
                winpath(case / "input.json"),
            ]
            leader_identity = _verify_native_observation(
                row["leader"], leader_command, report["controller"]["pid"]
            )
            node_identity = _verify_native_observation(
                row["node"],
                [cfg["node"], cfg["script"], winpath(case / "input.json")],
                row["leader_pid"],
            )
            browser_identity = _verify_native_observation(
                row["browser"], command, row["node"]["pid"]
            )
            if (
                row["leader"]["pid"] != row["leader_pid"]
                or not row["job_kill_on_close"]
                or not row["job_handle"]
            ):
                raise ValueError("job")
            pids = [row["leader_pid"], row["node"]["pid"], row["browser"]["pid"]]
            identities = {leader_identity, node_identity, browser_identity}
            if (
                len(set(pids)) != 3
                or report["controller"]["pid"] in pids
                or identities & observed_identities
            ):
                raise ValueError("restart process")
            observed_identities.update(identities)
            descendants = json.loads(row["descendants_raw"])
            cleanup = json.loads(row["cleanup_raw"])
            ids = [item["ProcessId"] for item in descendants]
            if (
                descendants != row["descendants"]
                or len(ids) != len(set(ids))
                or row["browser"]["pid"] not in ids
                or row["node"]["pid"] not in ids
                or any(
                    item["ParentProcessId"] not in {*ids, row["leader_pid"]} for item in descendants
                )
                or any(item in cleanup for item in descendants)
                or row["termination"]
                != {
                    "mechanism": "WINDOWS_JOB_KILL_ON_CONTROLLER_TERMINATION",
                    "leader_exit": 1,
                    "remaining_observed_descendants": 0,
                    "graceful": False,
                }
            ):
                raise ValueError("termination")
            for process in (row["node"], row["browser"]):
                if process["cim"] not in descendants:
                    raise ValueError("descendant identity")
            request: dict[str, Any] = {
                **requests[phase],
                "identity": {
                    "run_id": report["profile_id"],
                    "pid": row["browser"]["pid"],
                    "phase": phase,
                },
            }
            work = _pipe_work(report["profile_id"], phase, cfg["worker_ids"][phase], request)
            if (
                row["work"] != work
                or json.loads(retained(row["work_artifact"])) != work
                or json.loads(retained(row["config_artifact"])) != expected_phase_cfg
            ):
                raise ValueError("work")
            result = row["result"]
            if (
                json.loads(retained(row["result_artifact"])) != result
                or result["pid"] != row["browser"]["pid"]
                or result["node_pid"] != row["node"]["pid"]
            ):
                raise ValueError("result identity")
            _verify_pipe_transcript(retained(row["transcript"]), expected_phase_cfg, work, result)
            sentinel = result["sentinel"]
            if (
                sentinel["sentinel"] != report["profile_id"]
                or sentinel["profileId"] != report["profile_id"]
                or sentinel["origin"] != origin
                or sentinel["moduleSha256"] != modules["src/spool.js"]
            ):
                raise ValueError("sentinel")
            value = result["worker"]
            if (
                value != report[phase]
                or value["worker_id"] != work["worker_id"]
                or value["origin"] != origin
                or value["module_sha256"] != modules["src/spool.js"]
            ):
                raise ValueError("worker")
            compare_indexeddb_state(
                value, request["identity"], _observations(report["profile_id"]), 2, ack=1
            )
        before = report["before"]
        first, second = [entry["spool_record"] for entry in before["entries"]]
        if (
            before["aborted"] is not True
            or before["first"] != first
            or before["second"] != second
            or before["duplicate"] != first
            or before["pending"] != [second]
            or before["invalid_ack"] != "Error: E_SPOOL_ACK"
            or any(before[key] != report["after"][key] for key in ("entries", "states", "keys"))
            or report["browser"] != report["phases"][0]["browser"]
            or report["document"] != report["phases"][0]["result"]["document"]
            or report["termination"] != report["phases"][0]["termination"]
        ):
            raise ValueError("restart state")
    except (KeyError, ValueError, TypeError, OSError) as error:
        raise ValueError("E_ENV_WINDOWS_BROWSER_EVIDENCE") from error


def run_environment_qualification(workspace: Path) -> dict[str, Any]:
    """Keep every environment result separate from the historical full111 gate."""
    from tools.run_native_ingestor_qualification import (
        run_native_commit_io,
        run_native_ingestor,
        verify_native_commit_io,
        verify_native_ingestor,
    )

    workspace.mkdir(parents=True, exist_ok=False)
    native = run_native_storage(workspace / "native")
    filesystem = run_filesystem_faults(workspace / "filesystem")
    linux_browser = run_browser_restart(workspace / "linux-browser")
    windows_browser = run_windows_browser(workspace / "windows-browser")
    native_ingestor = run_native_ingestor(workspace / "native-ingestor")
    verify_native_ingestor(native_ingestor)
    native_commit_io = run_native_commit_io(workspace / "native-commit-io")
    verify_native_commit_io(native_commit_io)
    cases = (
        [
            {"case_id": "NATIVE-WIN-STORE-" + row["phase"].upper(), "result": "PASS"}
            for row in native["cases"]
        ]
        + [
            {
                "case_id": "SOFTWARE-FAULT-" + row["fault"].upper(),
                "result": "PASS",
                "observed_error": row["observed_error"],
            }
            for row in filesystem["faults"]
        ]
        + [
            {"case_id": row["vector_id"], "result": row["result"]}
            for row in filesystem["commit_io"]["records"]
        ]
        + [
            {"case_id": "LINUX-CHROME-PROCESS-RESTART", "result": linux_browser["result"]},
            {"case_id": "WINDOWS-CONTROLLER-JOB-TERMINATION", "result": "PASS"},
            {
                "case_id": "WINDOWS-CHROME-PROCESS-RESTART",
                "result": windows_browser["restart_result"],
            },
            {
                "case_id": "WINDOWS-CHROME-EXTENSION-TARGET",
                "result": windows_browser["result"],
                "observed_error": windows_browser["observed_error"],
            },
            {
                "case_id": "NATIVE-WINDOWS-INGESTOR",
                "result": native_ingestor["result"],
            },
            {
                "case_id": "NATIVE-WINDOWS-SQL06-COMMIT-IO",
                "result": native_commit_io["native_sql06"],
            },
            {
                "case_id": "PHYSICAL-POWER-LOSS",
                "result": "HOLD",
                "observed_error": "NOT_EXECUTED_NO_EXTERNAL_FACILITY",
            },
        ]
    )
    report = {
        "result": "PARTIAL_HOLD",
        "binding": capture_binding(),
        "cases": cases,
        "reports": {
            "native": native,
            "filesystem": filesystem,
            "linux_browser": linux_browser,
            "windows_browser": windows_browser,
            "native_ingestor": native_ingestor,
            "native_commit_io": native_commit_io,
        },
        "scope": "SUPPLEMENTAL_ENVIRONMENT_ONLY",
        "production_authority": "NONE",
        "live_authority": "NONE",
        "money_authority": "NONE",
        "full111": "NOT_RERUN_AT_THIS_SOURCE",
        "security_review": "NOT_REVIEWED",
    }
    report["terminal_files"] = [
        artifact(workspace / name / file)
        for name, file in [
            ("native", "native-terminal.json"),
            ("filesystem", "filesystem-terminal.json"),
            ("linux-browser", "browser-terminal.json"),
            ("windows-browser", "windows-browser-terminal.json"),
            ("native-ingestor", "native-ingestor-terminal.json"),
            ("native-commit-io", "native-ingestor-terminal.json"),
        ]
    ]
    cases.extend(
        {"case_id": row["case_id"], "result": native_ingestor["result"]}
        for row in native_ingestor["cases"]
    )
    save(workspace / "environment-aggregate.json", report)
    return report


def _environment_case_projection(reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    native = reports["native"]
    filesystem = reports["filesystem"]
    linux_browser = reports["linux_browser"]
    windows_browser = reports["windows_browser"]
    native_ingestor = reports["native_ingestor"]
    native_commit_io = reports["native_commit_io"]
    return (
        [
            {"case_id": "NATIVE-WIN-STORE-" + row["phase"].upper(), "result": "PASS"}
            for row in native["cases"]
        ]
        + [
            {
                "case_id": "SOFTWARE-FAULT-" + row["fault"].upper(),
                "result": "PASS",
                "observed_error": row["observed_error"],
            }
            for row in filesystem["faults"]
        ]
        + [
            {"case_id": row["vector_id"], "result": row["result"]}
            for row in filesystem["commit_io"]["records"]
        ]
        + [
            {"case_id": "LINUX-CHROME-PROCESS-RESTART", "result": linux_browser["result"]},
            {"case_id": "WINDOWS-CONTROLLER-JOB-TERMINATION", "result": "PASS"},
            {
                "case_id": "WINDOWS-CHROME-PROCESS-RESTART",
                "result": windows_browser["restart_result"],
            },
            {
                "case_id": "WINDOWS-CHROME-EXTENSION-TARGET",
                "result": windows_browser["result"],
                "observed_error": windows_browser["observed_error"],
            },
            {"case_id": "NATIVE-WINDOWS-INGESTOR", "result": native_ingestor["result"]},
            {
                "case_id": "NATIVE-WINDOWS-SQL06-COMMIT-IO",
                "result": native_commit_io["native_sql06"],
            },
            {
                "case_id": "PHYSICAL-POWER-LOSS",
                "result": "HOLD",
                "observed_error": "NOT_EXECUTED_NO_EXTERNAL_FACILITY",
            },
        ]
        + [
            {"case_id": row["case_id"], "result": native_ingestor["result"]}
            for row in native_ingestor["cases"]
        ]
    )


def verify_environment_qualification(
    report: dict[str, Any], *, artifacts: RetainedArtifactIO | None = None
) -> None:
    from tools.run_native_ingestor_qualification import (
        verify_native_commit_io,
        verify_native_ingestor,
    )

    try:
        reports = report["reports"]
        if (
            report["result"] != "PARTIAL_HOLD"
            or report["scope"] != "SUPPLEMENTAL_ENVIRONMENT_ONLY"
            or report["production_authority"] != "NONE"
            or report["live_authority"] != "NONE"
            or report["money_authority"] != "NONE"
            or report["full111"] != "NOT_RERUN_AT_THIS_SOURCE"
            or report["security_review"] != "NOT_REVIEWED"
            or report["binding"] != capture_binding()
            or set(reports)
            != {
                "native",
                "filesystem",
                "linux_browser",
                "windows_browser",
                "native_ingestor",
                "native_commit_io",
            }
        ):
            raise ValueError("header")
        verify_native_storage(reports["native"], artifacts=artifacts)
        verify_filesystem_faults(reports["filesystem"], artifacts=artifacts)
        verify_browser_restart(reports["linux_browser"], artifacts=artifacts)
        verify_windows_browser(reports["windows_browser"], artifacts=artifacts)
        verify_native_ingestor(reports["native_ingestor"], artifacts=artifacts)
        verify_native_commit_io(reports["native_commit_io"], artifacts=artifacts)
        if report["cases"] != _environment_case_projection(reports):
            raise ValueError("case projection")
        terminal_files = report["terminal_files"]
        terminal_reports = [
            reports[name]
            for name in (
                "native",
                "filesystem",
                "linux_browser",
                "windows_browser",
                "native_ingestor",
                "native_commit_io",
            )
        ]
        if (
            not isinstance(terminal_files, list)
            or len(terminal_files) != len(terminal_reports)
            or len({item["path"] for item in terminal_files}) != len(terminal_files)
        ):
            raise ValueError("terminal projection")
        for descriptor, expected in zip(terminal_files, terminal_reports, strict=True):
            boundary = artifacts.recorded_boundary(descriptor["path"]) if artifacts else None
            if (
                json.loads(checked(descriptor, artifacts=artifacts, recorded_boundary=boundary))
                != expected
            ):
                raise ValueError("terminal projection")
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ValueError("E_ENVIRONMENT_QUALIFICATION") from error


def verify_environment_qualification_evidence(
    aggregate_path: Path,
    inventory_path: Path,
    config: Any,
    *,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, object]:
    from tools.retained_artifact_io import RetainedArtifactIO
    from tools.run_full_repair_qualification import validate_inventory_closure

    qualification = config.qualification_evidence
    if (
        qualification is None
        or aggregate_path != qualification.environment_qualification_aggregate
        and artifacts is None
        or inventory_path != qualification.environment_qualification_inventory
        and artifacts is None
    ):
        raise ValueError("E_ENVIRONMENT_QUALIFICATION")
    try:
        if artifacts is None:
            manifest_raw = inventory_path.read_bytes()
            manifest = json.loads(manifest_raw)
            active = RetainedArtifactIO.from_manifest(manifest, inventory_path.parent / "retained")
        else:
            inventory_locator = str(qualification.environment_qualification_inventory)
            manifest_raw = artifacts.read_bytes(
                inventory_locator,
                recorded_boundary=artifacts.recorded_boundary(inventory_locator),
            )
            manifest = json.loads(manifest_raw)
            if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
                raise ValueError("manifest")
            for row in manifest["files"]:
                data = artifacts.read_bytes(
                    row["recorded_locator"], recorded_boundary=row["recorded_boundary"]
                )
                if (
                    len(data) != row["size_bytes"]
                    or hashlib.sha256(data).hexdigest() != row["sha256"]
                ):
                    raise ValueError("manifest")
            active = artifacts
        recorded = str(qualification.environment_qualification_aggregate)
        raw = active.read_bytes(recorded, recorded_boundary=active.recorded_boundary(recorded))
        report = json.loads(raw)
        if not isinstance(report, dict):
            raise ValueError("aggregate")
        validate_inventory_closure(
            manifest,
            report,
            aggregate_locator=recorded,
            aggregate_raw=raw,
            live_roots=environment_live_roots(),
        )
        verify_environment_qualification(report, artifacts=active)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("E_ENVIRONMENT_QUALIFICATION") from error
    return {
        "result": "PARTIAL_HOLD",
        "aggregate_sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_root_sha256": hashlib.sha256(manifest_raw).hexdigest(),
    }


def main() -> None:
    from tools.full_verifier_config import load_controller_config
    from tools.run_full_repair_qualification import (
        collect_retained_sources,
        write_closed_inventory,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--aggregate", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    args = parser.parse_args()
    config = load_controller_config(args.config)
    qualification = config.qualification_evidence
    if (
        qualification is None
        or args.aggregate != qualification.environment_qualification_aggregate
        or args.inventory != qualification.environment_qualification_inventory
        or args.aggregate != args.workspace / "environment-aggregate.json"
        or any(path.exists() for path in (args.workspace, args.aggregate, args.inventory))
        or (args.inventory.parent / "retained").exists()
    ):
        raise ValueError("E_ENVIRONMENT_QUALIFICATION")
    report = run_environment_qualification(args.workspace)
    sources = [
        (args.aggregate, str(args.aggregate.resolve()), str(args.workspace.resolve())),
        *collect_retained_sources(
            report,
            retained_boundaries=environment_retained_boundaries(report, args.workspace),
            live_roots=environment_live_roots(),
        ),
    ]
    write_closed_inventory(sources, args.inventory)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
