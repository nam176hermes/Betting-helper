"""Supplemental real environment experiments; never broad/physical qualification."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.run_indexeddb_crash_matrix import CHROME, PACK, ROOT, _observations
from tools.verify_repair_evidence import capture_binding

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
    return subprocess.run(  # noqa: S603 -- fixed path translation utility.
        ["/usr/bin/wslpath", "-w", str(path.resolve())], check=True, capture_output=True, text=True
    ).stdout.strip()  # noqa: S603


def localpath(path: str) -> Path:
    if path.startswith("/"):
        return Path(path)
    return Path(
        subprocess.run(  # noqa: S603 -- fixed path translation utility.
            ["/usr/bin/wslpath", "-u", path], check=True, capture_output=True, text=True
        ).stdout.strip()
    )  # noqa: S603


def checked(descriptor: dict[str, str]) -> bytes:
    data = localpath(descriptor["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
        raise ValueError("E_ENV_ARTIFACT_HASH")
    return data


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


def verify_native_storage(report: dict[str, Any]) -> None:
    from moj_discovery.store import validate_journal

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
        raw = json.loads(checked(report["owner_stdout"]))
        if any(report[key] != value for key, value in raw.items()) or checked(
            report["owner_stderr"]
        ):
            raise ValueError("owner")
        for entry in report["dependency_closure"]:
            if checked(entry["source"]) != checked(entry["copy"]):
                raise ValueError("dependency")
        for item in report["runtime_files"]:
            checked(item)
        checked(report["entrypoint"])
        cfg = json.loads(checked(report["owner_input"]))
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
            _verify_native_observation(
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
                or checked(row["writer_stdout"])
                or checked(row["writer_stderr"])
            ):
                raise ValueError("process")
            if (
                json.loads(writer["cim_raw"]) != writer["cim"]
                or localpath(writer["executable"]) != NATIVE
            ):
                raise ValueError("observation")
            if hashlib.sha256(NATIVE.read_bytes()).hexdigest() != writer["sha256"]:
                raise ValueError("executable")
            child_input = json.loads(checked(row["input"]))
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
                _verify_native_observation(process["observed"], expected_command, report["pid"])
                if (
                    process["argv"] != expected_command
                    or process["observed"]["pid"] != process["pid"]
                ):
                    raise ValueError("reader command")
                value = json.loads(checked(process["stdout"]))
                if (
                    process["exit"] != 0
                    or value["pid"] != process["pid"]
                    or checked(process["stderr"])
                ):
                    raise ValueError("reader")
                if value["state"] != (
                    row["before"] if process["mode"] == "setup" else row["after"]
                ):
                    raise ValueError("readback")
                identities.add(process["pid"])
            identities.add(writer["pid"])
        if len(identities) != 8:
            raise ValueError("independent processes")
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ValueError("E_ENV_NATIVE_EVIDENCE") from error


def _verify_native_observation(row: dict[str, Any], command: list[str], parent: int) -> None:
    if (
        row["argv"] != command
        or row["cim"]["CommandLine"] != subprocess.list2cmdline(command)
        or row["pid"] != row["cim"]["ProcessId"]
        or row["cim"]["ParentProcessId"] != parent
        or row["executable"] != row["cim"]["ExecutablePath"]
        or localpath(row["executable"]) != localpath(command[0])
        or row["sha256"] != artifact(localpath(command[0]))["sha256"]
        or json.loads(row["cim_raw"]) != row["cim"]
        or not row["handle"]
    ):
        raise ValueError("E_ENV_NATIVE_OBSERVATION")


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


def verify_filesystem_faults(report: dict[str, Any]) -> None:
    from tools.owner_mutation_evidence import verify_process
    from tools.verify_repair_evidence import aggregate_repair_evidence

    if (
        report["binding"] != capture_binding()
        or report["physical_power_loss"] != "HOLD_NOT_EXECUTED"
    ):
        raise ValueError("E_ENV_FILESYSTEM_BINDING")
    controls = report["commit_io"]["records"]
    if (
        aggregate_repair_evidence([row["vector_id"] for row in controls], controls)["result"]
        != "PASS"
    ):
        raise ValueError("E_ENV_FILESYSTEM_CONTROL")
    names = [
        ("truncated_database", "E_RESTART_DATABASE"),
        ("corrupt_header", "E_RESTART_DATABASE"),
        ("schema_corruption", "E_STORE_SCHEMA"),
        ("missing_database", "E_RESTART_MISSING_DATABASE"),
    ]
    for (name, error), fault in zip(names, report["faults"], strict=True):
        case = Path(fault["case_directory"])
        request = {"run_id": fault["run_id"]}
        if fault["fault"] != name or fault["observed_error"] != error:
            raise ValueError("E_ENV_FILESYSTEM_FAULT")
        verify_process(
            fault["reader_before"], case, "sql-read", "reader-before", request, fault["before"]
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
        before = checked(fault["before_copy"])
        if fault["before"] != controls[1]["actual"]["after"]:
            raise ValueError("E_ENV_FILESYSTEM_BASELINE")
        if name == "missing_database":
            if (
                checked(fault["removed_copy"]) != before
                or (case / fault["run_id"] / "run.sqlite3").exists()
            ):
                raise ValueError("E_ENV_FILESYSTEM_ABSENCE")
        else:
            after = checked(fault["after_file"])
            if (
                name == "truncated_database"
                and after != before[:128]
                or name == "corrupt_header"
                and after != b"BROKEN SQLITE!!!" + before[16:]
                or name == "schema_corruption"
                and after == before
            ):
                raise ValueError("E_ENV_FILESYSTEM_BYTES")


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
    verify_browser_restart(report)
    save(workspace / "browser-terminal.json", report)
    return report


def verify_browser_restart(report: dict[str, Any]) -> None:
    from tools.qualify_chrome_indexeddb import _browser_command, _extension_id
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
        for name, digest in modules.items():
            if artifact(extension / name)["sha256"] != digest:
                raise ValueError("module bytes")
        for name, source in (
            ("manifest.json", "repair-manifest.json"),
            ("repair-probe.html", "repair-probe.html"),
        ):
            if (extension / name).read_bytes() != (
                ROOT / "extension/test-harness" / source
            ).read_bytes():
                raise ValueError("asset")
        key = json.loads((extension / "manifest.json").read_text())["key"]
        if report["origin"] != "chrome-extension://" + _extension_id(key):
            raise ValueError("origin")
        if json.loads((profile / "environment-profile.json").read_text()) != {
            "id": report["profile_id"]
        }:
            raise ValueError("profile")
        if report["processes"][0]["pid"] == report["processes"][1]["pid"]:
            raise ValueError("restart")
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
            value = json.loads((case / f"{phase}-worker.json").read_text())
            request = json.loads(checked(descriptor))
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
        if (
            len(report["before"]["entries"]) != 2
            or not report["before"]["aborted"]
            or any(
                report["before"][key] != report["after"][key]
                for key in ("entries", "states", "keys")
            )
        ):
            raise ValueError("state")
    except (KeyError, ValueError, TypeError, OSError, StopIteration) as error:
        raise ValueError("E_ENV_BROWSER_EVIDENCE") from error


def run_windows_browser(workspace: Path) -> dict[str, Any]:
    from tools.qualify_chrome_indexeddb import (
        _CDP,
        _browser_command,
        _free_port,
        _prepare_test_extension,
    )

    workspace.mkdir(parents=True, exist_ok=True)
    owned = WINDOWS_PARENT / f"browser-environment-{uuid4()}"
    owned.mkdir(parents=True, exist_ok=False)
    extension, extension_id, _ = _prepare_test_extension(ROOT, owned)
    profile = owned / "profile"
    profile.mkdir()
    browser = Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")
    port = _free_port()
    origin = "chrome-extension://" + extension_id
    command = _browser_command(browser, profile, extension, origin + "/repair-probe.html", port)
    command[0] = winpath(browser)
    command = [
        arg.replace(str(profile.resolve()), winpath(profile)).replace(
            str(extension.resolve()), winpath(extension)
        )
        for arg in command
    ]
    config = {
        "workspace": winpath(owned),
        "command": command,
        "origin": origin,
        "port": port,
        "node": winpath(NATIVE.parent.parent / "node/bin/node.exe"),
        "cdp_script": _CDP,
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
    completed = subprocess.run(invocation, capture_output=True, timeout=60)  # noqa: S603
    (workspace / "windows-browser.stdout").write_bytes(completed.stdout)
    (workspace / "windows-browser.stderr").write_bytes(completed.stderr)
    if completed.returncode or completed.stderr:
        raise RuntimeError(
            f"E_ENV_WINDOWS_BROWSER:{completed.returncode}:{completed.stderr.decode()}"
        )
    report: dict[str, Any] = json.loads(completed.stdout)
    report.update(
        {
            "binding": capture_binding(),
            "input": artifact(input_file),
            "owner_command": invocation,
            "stdout": artifact(workspace / "windows-browser.stdout"),
            "stderr": artifact(workspace / "windows-browser.stderr"),
            "owned_workspace": str(owned),
            "browser_binary": artifact(browser),
            "node_binary": artifact(NATIVE.parent.parent / "node/bin/node.exe"),
            "leader_stderr": artifact(owned / "leader.stderr"),
            "leader_stdout": artifact(owned / "leader.stdout"),
            "chrome_log": artifact(owned / "chrome.log"),
            "document_artifact": artifact(owned / "document-observation.json"),
        }
    )
    verify_windows_browser(report)
    save(workspace / "windows-browser-terminal.json", report)
    return report


def verify_windows_browser(report: dict[str, Any]) -> None:
    from tools.qualify_chrome_indexeddb import _CDP, _browser_command

    try:
        cfg = json.loads(checked(report["input"]))
        raw = json.loads(checked(report["stdout"]))
        if (
            any(report[key] != value for key, value in raw.items())
            or checked(report["stderr"])
            or checked(report["leader_stdout"])
            or checked(report["leader_stderr"])
            or report["binding"] != capture_binding()
            or cfg["cdp_script"] != _CDP
        ):
            raise ValueError("binding")
        checked(report["node_binary"])
        checked(report["chrome_log"])
        if json.loads(checked(report["document_artifact"])) != report["document"]:
            raise ValueError("document")
        owned = Path(report["owned_workspace"])
        browser = localpath(report["browser_binary"]["path"])
        if browser != Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"):
            raise ValueError("browser path")
        expected = _browser_command(
            browser,
            owned / "profile",
            owned / "test-extension",
            report["origin"] + "/repair-probe.html",
            cfg["port"],
        )
        expected[0] = winpath(browser)
        expected = [
            arg.replace(str((owned / "profile").resolve()), winpath(owned / "profile")).replace(
                str((owned / "test-extension").resolve()), winpath(owned / "test-extension")
            )
            for arg in expected
        ]
        if cfg["command"] != expected or cfg["workspace"] != winpath(owned):
            raise ValueError("command")
        _verify_native_observation(report["browser"], expected, report["leader_pid"])
        if (
            report["leader"]["pid"] != report["leader_pid"]
            or not report["job_kill_on_close"]
            or report["descendant_cleanup_raw"] != "0"
            or json.loads(report["descendants_raw"]) != report["descendants_before"]
        ):
            raise ValueError("job")
        descendants = report["descendants_before"]
        ids = [item["ProcessId"] for item in descendants]
        if not ids or len(ids) != len(set(ids)) or report["browser"]["pid"] not in ids:
            raise ValueError("descendants")
        if any(item["ParentProcessId"] not in {*ids, report["leader_pid"]} for item in descendants):
            raise ValueError("ownership")
        termination = report["termination"]
        if (
            termination["observed_descendant_pids"] != ids
            or termination["remaining_observed_descendants"] != 0
            or termination["leader_exit"] != 1
            or termination["mechanism"] != "WINDOWS_JOB_KILL_ON_CONTROLLER_TERMINATION"
        ):
            raise ValueError("termination")
        document = report["document"]
        available = (
            document["protocol"] == "chrome-extension:"
            and document["origin"] == report["origin"]
            and document["probe"]
            and document["extensionId"] == report["origin"].split("://")[1]
        )
        if report["result"] != ("PASS" if available else "HOLD") or report["observed_error"] != (
            None if available else "E_EXTENSION_TARGET_UNAVAILABLE"
        ):
            raise ValueError("availability")
        if report["physical_power_loss"] != "HOLD_NOT_EXECUTED":
            raise ValueError("physical claim")
    except (KeyError, ValueError, TypeError, OSError) as error:
        raise ValueError("E_ENV_WINDOWS_BROWSER_EVIDENCE") from error


def run_environment_qualification(workspace: Path) -> dict[str, Any]:
    """Keep every environment result separate from the historical full111 gate."""
    workspace.mkdir(parents=True, exist_ok=False)
    native = run_native_storage(workspace / "native")
    filesystem = run_filesystem_faults(workspace / "filesystem")
    linux_browser = run_browser_restart(workspace / "linux-browser")
    windows_browser = run_windows_browser(workspace / "windows-browser")
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
                "case_id": "WINDOWS-CHROME-EXTENSION-TARGET",
                "result": windows_browser["result"],
                "observed_error": windows_browser["observed_error"],
            },
            {
                "case_id": "NATIVE-WINDOWS-INGESTOR",
                "result": "HOLD",
                "observed_error": native["native_ingestor"],
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
        ]
    ]
    save(workspace / "environment-aggregate.json", report)
    return report
