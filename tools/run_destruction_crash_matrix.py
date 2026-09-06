"""Run real destruction only on exclusive disposable SQLite/extension stores."""

from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from secrets import token_hex
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from tools.destruction_support import TEST_SCOPE, immutable_json, make_plan, worker_read
from tools.inspect_restart_state import _kill_owned_child
from tools.qualify_chrome_indexeddb import (
    _browser_process_observation,
    _canonical_browser_executable,
    _kill_owned_process_group,
    _prepare_test_extension,
    _start_chrome,
    _wait_for_probe,
)
from tools.run_gap_coherence_crash_matrix import _artifact, _proc_observation
from tools.run_indexeddb_crash_matrix import (
    CHROME,
    PRODUCER,
    REGISTRY,
    ROOT,
    STREAM,
    _call,
    _observations,
)

CHILD = Path(__file__).with_name("destruction_crash_child.py").resolve()


def _process(
    case: Path,
    mode: str,
    input_path: Path,
    name: str,
    *,
    kill: bool = False,
    rejection: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    start = case / (name + ".start")
    command = [
        str(Path(sys.executable).absolute()),
        "-I",
        str(CHILD),
        mode,
        str(input_path),
        "--start",
        str(start),
    ]
    output, error = case / (name + ".stdout"), case / (name + ".stderr")
    with output.open("wb") as stdout, error.open("wb") as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)  # noqa: S603
        try:
            deadline = monotonic() + 15
            ready = start.with_suffix(".ready")
            while not ready.exists():
                if child.poll() is not None or monotonic() > deadline:
                    raise ValueError("E_DESTRUCTION_CHILD_START:" + error.read_text())
                sleep(0.01)
            observed, raw = _proc_observation(child, case / (name + "-process.json"))
            if ready.read_text() != str(child.pid):
                raise ValueError("E_DESTRUCTION_PROCESS_IDENTITY")
            start.write_text(str(child.pid))
            if kill:
                checkpoint = case / "checkpoint.json"
                deadline = monotonic() + 20
                while not checkpoint.exists():
                    if child.poll() is not None or monotonic() > deadline:
                        raise ValueError("E_DESTRUCTION_CHECKPOINT:" + error.read_text())
                    sleep(0.02)
                identity = json.loads(input_path.read_text())["identity"]
                if json.loads(checkpoint.read_text()) != {**identity, "pid": child.pid}:
                    raise ValueError("E_DESTRUCTION_CHECKPOINT_IDENTITY")
                if not _kill_owned_child(child):
                    raise ValueError("E_DESTRUCTION_NOT_KILLED")
            code = child.wait(timeout=30)
            if code != (-signal.SIGKILL if kill else 1 if rejection else 0):
                raise ValueError(
                    "E_DESTRUCTION_CHILD_FAILED:" + output.read_text() + error.read_text()
                )
        finally:
            if child.poll() is None:
                _kill_owned_child(child)
                child.wait(timeout=5)
    result = None if kill else json.loads(output.read_text())
    if result is not None and result["pid"] != child.pid:
        raise ValueError("E_DESTRUCTION_PROCESS_IDENTITY")
    if rejection and (result is None or result["result"] != {"observed_error": rejection}):
        raise ValueError("E_DESTRUCTION_WRONG_REJECTION")
    return (None if result is None else result["result"]), {
        "mode": mode,
        "name": name,
        "command": command,
        "pid": child.pid,
        "pgid": child.pid,
        "observed": observed,
        "raw_process": raw,
        "input": _artifact(input_path),
        "stdout": _artifact(output),
        "stderr": _artifact(error),
        "exit_code": code,
    }


def run_destruction_case(
    entry: dict[str, Any], case: Path, *, mutation: str | None = None
) -> dict[str, Any]:
    from tools.verify_destruction_evidence import compare_destruction, verify_destruction
    from tools.verify_repair_evidence import capture_binding

    case = case.resolve()
    case.mkdir(parents=True, exist_ok=False)
    run_id, profile_id = str(uuid4()), str(uuid4())
    immutable_json(
        case / "DISPOSABLE_OWNER.json",
        {"scope": TEST_SCOPE, "case_directory": str(case), "run_id": run_id},
    )
    profile = case / "chrome-profile"
    profile.mkdir()
    marker = profile / "BH_R05_PROFILE_ID"
    marker.write_text(profile_id)
    extension, extension_id, module_hash = _prepare_test_extension(ROOT, case)
    module_hashes_before = {
        str(path.relative_to(extension)): _artifact(path)["sha256"]
        for path in sorted(extension.rglob("*.js"))
    }
    binary = _canonical_browser_executable(Path(os.environ.get("BH_CHROME_BINARY", str(CHROME))))
    origin = "chrome-extension://" + extension_id
    process, socket = _start_chrome(
        binary, profile, extension, origin + "/repair-probe.html", case / "chrome.log"
    )
    inputs: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}

    def save(name: str, value: Any, *, input_file: bool = False) -> Path:
        path = case / (name + ".json")
        immutable_json(path, value)
        (inputs if input_file else artifacts)[name] = _artifact(path)
        return path

    try:
        _wait_for_probe(socket)
        sentinel = token_hex(32)
        identity = {
            "run_id": run_id,
            "case_id": entry["vector_id"],
            "checkpoint_id": entry["crash_checkpoint"],
            "component": "WHOLE_RUN_DESTRUCTION",
            "ordinal": 0,
            "test_nonce": token_hex(16),
            "pid": process.pid,
            "profile_id": profile_id,
            "origin": origin,
            "protocol": "chrome-extension:",
            "module_url": origin + "/src/spool.js",
            "module_sha256": module_hash,
        }
        options = {
            "browser_run_id": run_id,
            "producer_id": PRODUCER,
            "stream_id": STREAM,
            "generation": "0",
            "registry": json.loads(REGISTRY.read_text()),
        }
        config = {"identity": identity, "options": options, "socket": socket}
        config_path = save("owner-input", config, input_file=True)
        save(
            "profile-before",
            {
                "profile_path": str(profile),
                "marker": marker.read_text(),
                "sentinel": _call(socket, "writeSentinel", sentinel, profile_id),
            },
        )
        save("browser-process-before", _browser_process_observation(process))
        save(
            "browser-launch",
            {
                "argv": process.args,
                "pid": process.pid,
                "pgid": os.getpgid(process.pid),
                "profile_path": str(profile),
                "extension_path": str(extension),
                "origin": origin,
                "executable": str(binary),
                "sha256": _artifact(binary)["sha256"],
            },
        )
        observation = _observations(run_id)[0]
        ack, setup = _process(
            case,
            "setup",
            save("setup-input", {"observation": observation}, input_file=True),
            "setup",
        )
        save(
            "browser-setup",
            worker_read(
                config,
                "destruction-prepare",
                observations=[json.dumps(observation, sort_keys=True, separators=(",", ":"))],
                final_ack={
                    "generation": str(ack["generation"]),
                    "sequence": str(ack["highest_contiguous_sequence"]),
                    "cursor_hash": ack["cursor_hash"],
                },
            ),
        )
        before, reader_before = _process(case, "read", config_path, "reader-before")
        plan = make_plan(run_id, before)
        if mutation == "INPUT":
            save("original-plan", plan)
            plan = copy.deepcopy(plan)
            plan["intent"]["human_invocation"] = False
        save("precommit", plan, input_file=True)
        _, destruction = _process(
            case,
            "run",
            config_path,
            "destruction",
            kill=mutation != "INPUT",
            rejection="E_DESTRUCTION_HUMAN_INVOCATION" if mutation == "INPUT" else None,
        )
        crashed, reader_crashed = _process(case, "read", config_path, "reader-crashed")
        recovery = None
        if mutation != "INPUT":
            _, recovery = _process(case, "recover", config_path, "recovery")
        after, reader_after = _process(case, "read", config_path, "reader-after")
        save("before", before)
        save("crashed", crashed)
        save("after", after)
        for kind, path in (
            ("intent", case / f".local/destruction/{run_id}.intent.json"),
            ("proof", case / f".local/destruction/{run_id}.deletion-proof.json"),
            ("consumption", case / "consumed-external.json"),
        ):
            if path.is_file():
                artifacts["external-" + kind] = _artifact(path)
        save("expected", entry["expected_post_restart_state"])
        save(
            "profile-after",
            {
                "profile_path": str(profile),
                "marker": marker.read_text(),
                "sentinel": _call(socket, "readSentinel", profile_id),
            },
        )
        save("browser-process-after", _browser_process_observation(process))
        module_hashes_after = {
            str(path.relative_to(extension)): _artifact(path)["sha256"]
            for path in sorted(extension.rglob("*.js"))
        }
        execution_binding = {
            "before": module_hashes_before,
            "after": module_hashes_after,
        }
        binding_path = save("typescript-execution-binding", execution_binding)
        binding = capture_binding()
        row = {
            "case_id": entry["vector_id"],
            "vector_id": entry["vector_id"],
            "case_directory": str(case),
            "status": "PASS",
            "executed": True,
            "launch_attempted": True,
            "result": "PASS",
            "execution_kind": "DISPOSABLE_DESTRUCTION_PROCESS_CRASH",
            "qualification_scope": "DISPOSABLE_DESTRUCTION",
            "identity": identity,
            "evidence_binding": binding,
            "revision": binding["revision"],
            "environment": binding["environment"],
            "before": before,
            "crashed": crashed,
            "after": after,
            "expected": entry["expected_post_restart_state"],
            "inputs": inputs,
            "artifacts": artifacts,
            "checkpoint": _artifact(case / "checkpoint.json") if mutation != "INPUT" else None,
            "processes": [
                p
                for p in (setup, reader_before, destruction, reader_crashed, recovery, reader_after)
                if p
            ],
            "reader_runs": [reader_before, reader_crashed, reader_after],
            "mutations": [],
            "browser": {"executable": str(binary), "sha256": _artifact(binary)["sha256"]},
            "loaded_assets": {
                name: _artifact(extension / name) for name in ("manifest.json", "repair-probe.html")
            },
            "module_hashes": module_hashes_after,
            "typescript_execution_binding": execution_binding,
            "typescript_execution_binding_artifact": _artifact(binding_path),
            "profile_readbacks": {
                "before": artifacts["profile-before"],
                "after": artifacts["profile-after"],
                "marker": _artifact(marker),
                "sentinel": sentinel,
            },
            "browser_provenance": {
                "launch": artifacts["browser-launch"],
                "before": artifacts["browser-process-before"],
                "after": artifacts["browser-process-after"],
            },
            "production_authority": "NONE",
            "live_authority": "NONE",
            "money_authority": "NONE",
        }
        row["mutation_type"] = mutation
        if mutation != "INPUT":
            compare_destruction(row, plan)
        if mutation == "EXPECTED":
            wrong_oracle = copy.deepcopy(row["expected"])
            wrong_oracle["indexeddb_store"] = (
                "DELETED" if wrong_oracle["indexeddb_store"] == "PRESENT" else "PRESENT"
            )
            save("mutation-oracle", wrong_oracle)
            try:
                compare_destruction({**row, "expected": wrong_oracle}, plan)
            except ValueError as error:
                row["observed_error"] = str(error)
            else:
                raise ValueError("E_DESTRUCTION_MUTATION_SURVIVOR")
        elif mutation == "INPUT":
            row["observed_error"] = "E_DESTRUCTION_HUMAN_INVOCATION"
        else:
            for kind, mutation_id in zip(
                ("EXPECTED", "INPUT"), entry["mutation_vector_ids"], strict=True
            ):
                execution = run_destruction_case(
                    entry, case / ("mutation-" + kind.lower()), mutation=kind
                )
                wanted = (
                    "E_RESTART_STATE_MISMATCH"
                    if kind == "EXPECTED"
                    else "E_DESTRUCTION_HUMAN_INVOCATION"
                )
                row["mutations"].append(
                    {
                        "vector_id": mutation_id,
                        "kind": kind,
                        "execution": execution,
                        "observed_error": execution["observed_error"],
                        "expected_error": wanted,
                        "detected": execution["observed_error"] == wanted,
                    }
                )
        verify_destruction(row, binding, terminal=False, mutation_type=mutation)
        path = save("terminal-result", row)
        # Exclude the terminal descriptor from its own serialized artifact map.
        row["artifacts"].pop("terminal-result")
        row["terminal_artifact"] = _artifact(path)
        return row
    finally:
        _kill_owned_process_group(process)


def run_destruction_crash_matrix(pack: Path, workspace: Path) -> dict[str, Any]:
    entries = [
        entry
        for entry in json.loads(
            (pack / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if entry["harness"] == "WHOLE_RUN_DESTRUCTION"
    ]
    from tools.verify_repair_evidence import aggregate_repair_evidence

    records = [run_destruction_case(entry, workspace / str(uuid4())) for entry in entries]
    ids = [entry["vector_id"] for entry in entries]
    aggregate = aggregate_repair_evidence(ids, records)
    return {
        **aggregate,
        "records": records,
        "declared_vector_ids": ids,
        "executed_vector_ids": ids,
        "killed_child_count": len(records),
        "mutation_survivors": sum(not m["detected"] for row in records for m in row["mutations"]),
    }
