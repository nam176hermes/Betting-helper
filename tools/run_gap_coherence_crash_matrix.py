"""Execute all registered generation/coherence cases against an owned SQLite process."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import secrets
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from tools.run_loopback_ack_crash_matrix import run_family
from tools.run_sqlite_crash_matrix import _compile_commit_shim

ROOT = Path(__file__).resolve().parents[1]
CHILD = Path(__file__).with_name("gap_coherence_crash_child.py")
READER = Path(__file__).with_name("gap_state_reader.py")
NONE = {"CONFLICT-01", "LATE-01", "GAP-11", "CAPACITY-01", "EPOCH-05"}
ROLLBACK = {*(f"GAP-{n:02d}" for n in range(1, 9)), "CLOCK-01", "EPOCH-01", "EPOCH-03"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha(path)}


def _key(case_id: str) -> str:
    return "-".join(case_id.split("-")[:2])


def _initial(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "controller": "OPEN",
        "generations": {"0": "ACTIVE"},
        "cursor": "GEN0_Q1_H1",
        "counts": {},
        "capacity": None,
    }


def _terminal(case_id: str, run_id: str) -> dict[str, Any]:
    value = _initial(run_id)
    key = _key(case_id)
    if key.startswith("GAP-0") or key == "GAP-10":
        value.update(controller="SHOCKED_CLOSED", generations={"0": "CLOSED", "1": "ACTIVE"})
        value["counts"] = {"gap": 1, "shock": 1, "transition": 1, "binding": 1}
    elif key == "CONFLICT-01":
        value.update(controller="SHOCKED_CLOSED", generations={"0": "CLOSED", "1": "ACTIVE"})
        value["counts"] = {"conflict": 1, "gap": 1, "shock": 1, "transition": 1, "binding": 1}
    elif key == "LATE-01":
        value.update(
            controller="WAITING_FOR_RESNAPSHOT", generations={"0": "CLOSED", "1": "ACTIVE"}
        )
        value["counts"] = {"gap": 1, "shock": 1, "transition": 2, "binding": 1, "late": 1}
    elif key == "GAP-11":
        value.update(
            controller="SHOCKED_CLOSED",
            generations={"0": "CLOSED", "1": "CLOSED", "2": "ACTIVE"},
            cursor="GEN1_Q0_H0",
        )
        value["counts"] = {"gap": 2, "shock": 2, "transition": 3, "binding": 2}
    elif key == "CAPACITY-01":
        value["controller"] = "SHOCKED_CLOSED"
        value["capacity"] = {
            "normal_limit": 7,
            "terminal_reserve": 1,
            "used": 7,
            "unacknowledged_rows": 1,
            "evicted": 0,
            "status": "SAFETY_STOP",
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


def _read(
    case: Path, identity: dict[str, Any], phase: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    input_path = case / f"reader-{phase}-input.json"
    value = {
        "run_id": identity["run_id"],
        "case_id": identity["case_id"],
        "checkpoint_id": identity["checkpoint_id"],
        "phase": phase,
    }
    input_path.write_text(json.dumps(value, sort_keys=True))
    command = [
        str(Path(sys.executable).absolute()),
        "-I",
        str(READER.resolve()),
        str((case / "gap-owner.sqlite3").resolve()),
        "--identity",
        str(input_path.resolve()),
    ]
    result = subprocess.run(  # noqa: S603 -- fixed local read-only reader
        command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=10
    )
    output_path = case / f"reader-{phase}.json"
    output_path.write_text(result.stdout)
    output = json.loads(result.stdout)
    if output["identity"] != value:
        raise ValueError("E_GAP_READER_OUTPUT")
    return output, {
        "phase": phase,
        "argv": command,
        "exit": result.returncode,
        "input": _artifact(input_path),
        "output": _artifact(output_path),
    }


def verify_gap_record(row: dict[str, Any], binding: dict[str, Any]) -> None:
    if row.get("evidence_binding") != binding or row.get("revision") != binding["revision"]:
        raise ValueError("E_GAP_STALE_BINDING")
    case = Path(row["case_directory"])
    for name in (
        "scenario_artifact",
        "checkpoint_artifact",
        "boundary_artifact",
        "actual_artifact",
    ):
        descriptor = row[name]
        if (
            not Path(descriptor["path"]).resolve().is_relative_to(case.resolve())
            or _sha(Path(descriptor["path"])) != descriptor["sha256"]
        ):
            raise ValueError("E_GAP_ARTIFACT")
    registry = json.loads(
        (
            ROOT / "vendor/hybrid-discovery-v6.3.6/docs/registries/crash-harness-registry.v1.json"
        ).read_text()
    )
    entry = next(item for item in registry["entries"] if item["vector_id"] == row["case_id"])
    if row.get("expected") != entry["expected_post_restart_state"]:
        raise ValueError("E_GAP_ORACLE")
    if (
        row.get("status") != "PASS"
        or row.get("executed") is not True
        or row.get("launch_attempted") is not True
        or row.get("execution_kind") != "GAP_GENERATION_COHERENCE_PROCESS"
        or row.get("qualification_scope") != "GAP_GENERATION_COHERENCE"
    ):
        raise ValueError("E_GAP_TERMINAL_RECORD")
    boundary = json.loads(Path(row["boundary_artifact"]["path"]).read_text())
    if (
        row["identity"]["run_id"] != row["actual"]["run_id"]
        or row["identity"]["case_id"] != row["case_id"]
        or row["identity"]["checkpoint_id"] != entry["crash_checkpoint"]
        or row["checkpoint"] != row["identity"]
        or boundary["identity"] != row["identity"]
    ):
        raise ValueError("E_GAP_IDENTITY")
    if row["actual"] != _terminal(row["case_id"], row["identity"]["run_id"]):
        raise ValueError("E_GAP_STATE")
    if row["actual"] != row["after_restart"]:
        raise ValueError("E_GAP_STATE")
    if row["comparison"] != {"matched": True} or row["observed_error"] is not None:
        raise ValueError("E_GAP_COMPARISON")
    expected_action = entry["kill_action"]
    if row["kill_action"] != expected_action or row["command_exit"]["child"] != (
        0 if expected_action == "NONE" else -signal.SIGKILL
    ):
        raise ValueError("E_GAP_TERMINATION")
    if len(row["reader_runs"]) != 2 or any(item["exit"] != 0 for item in row["reader_runs"]):
        raise ValueError("E_GAP_READER")
    for item in row["reader_runs"]:
        reader_input = json.loads(Path(item["input"]["path"]).read_text())
        if any(
            name in reader_input for name in ("expected", "expected_post_restart_state", "oracle")
        ):
            raise ValueError("E_GAP_READER_ORACLE")
        if (
            _sha(Path(item["input"]["path"])) != item["input"]["sha256"]
            or _sha(Path(item["output"]["path"])) != item["output"]["sha256"]
        ):
            raise ValueError("E_GAP_READER")
        reader_output = json.loads(Path(item["output"]["path"]).read_text())
        expected_state = (
            row["before_restart"] if item["phase"] == "before" else row["after_restart"]
        )
        if reader_output["identity"] != reader_input or reader_output["state"] != expected_state:
            raise ValueError("E_GAP_READER")
    launch = row["launch_provenance"]
    python = Path(sys.executable).absolute()
    if (
        launch["command_prefix"][:3] != [str(python), "-I", str(CHILD.resolve())]
        or launch["argv"] != row["command"]
        or launch["child_sha256"] != _sha(CHILD)
        or launch["python_sha256"] != _sha(python)
        or row["command_exit"]["recovery"] != 0
        or row["command_exit"]["reader"] != 0
    ):
        raise ValueError("E_GAP_PROCESS_PROVENANCE")
    scenario = json.loads(Path(row["scenario_artifact"]["path"]).read_text())
    if scenario != {"run_id": row["identity"]["run_id"], "case_id": row["case_id"]}:
        raise ValueError("E_GAP_INPUT")
    if "terminal_artifact" in row:
        saved = json.loads(Path(row["terminal_artifact"]["path"]).read_text())
        if _sha(Path(row["terminal_artifact"]["path"])) != row["terminal_artifact"][
            "sha256"
        ] or saved != {key: value for key, value in row.items() if key != "terminal_artifact"}:
            raise ValueError("E_GAP_TERMINAL_ARTIFACT")


def _run_case(
    entry: dict[str, Any], case: Path, ordinal: int, shim: Path, binding: dict[str, Any]
) -> dict[str, Any]:
    case.mkdir()
    run_id, nonce = str(uuid4()), secrets.token_hex(16)
    identity = {
        "run_id": run_id,
        "case_id": entry["vector_id"],
        "checkpoint_id": entry["crash_checkpoint"],
        "component": entry["harness"],
        "pid": 0,
        "ordinal": ordinal,
        "test_nonce": nonce,
    }
    scenario = {"run_id": run_id, "case_id": entry["vector_id"]}
    scenario_path = case / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, sort_keys=True))
    ready = case / "checkpoint.json"
    prefix = [
        str(Path(sys.executable).absolute()),
        "-I",
        str(CHILD.resolve()),
        "--commit-shim",
        str(shim.resolve()),
    ]
    command = [
        *prefix,
        "--vector-id",
        entry["vector_id"],
        "--ready",
        str(ready.resolve()),
        "--run-id",
        run_id,
        "--case-id",
        entry["vector_id"],
        "--checkpoint-id",
        entry["crash_checkpoint"],
        "--component",
        entry["harness"],
        "--ordinal",
        str(ordinal),
        "--test-nonce",
        nonce,
        "--hold",
    ]
    with (case / "child.stdout").open("wb") as stdout, (case / "child.stderr").open("wb") as stderr:
        child = subprocess.Popen(  # noqa: S603 -- fixed owned local child
            command, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True
        )
    identity["pid"] = child.pid
    deadline = monotonic() + 10
    while not ready.is_file() and monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"E_GAP_CHILD_FAILED:{entry['vector_id']}:{child.returncode}")
        sleep(0.02)
    if not ready.is_file() or json.loads(ready.read_text()) != identity:
        raise RuntimeError("E_GAP_CHECKPOINT")
    boundary = json.loads((case / "boundary.json").read_text())
    if boundary["identity"] != identity:
        raise RuntimeError("E_GAP_BOUNDARY")
    action = entry["kill_action"]
    if action == "NONE":
        exit_code = child.wait(timeout=5)
    else:
        os.killpg(child.pid, signal.SIGKILL)
        exit_code = child.wait(timeout=5)
    before, before_run = _read(case, identity, "before")
    recover_command = [*prefix, "--recover", str(case.resolve())]
    recovery = subprocess.run(  # noqa: S603 -- fixed owned local recovery child
        recover_command, cwd=ROOT, check=True, capture_output=True, timeout=10
    )
    after, after_run = _read(case, identity, "after")
    actual = after["state"]
    if actual != _terminal(entry["vector_id"], run_id):
        raise ValueError("E_GAP_STATE")
    actual_path = case / "actual.json"
    actual_path.write_text(json.dumps(actual, sort_keys=True, separators=(",", ":")))
    row = {
        "vector_id": entry["vector_id"],
        "case_id": entry["vector_id"],
        "case_directory": str(case.resolve()),
        "status": "PASS",
        "result": "PASS",
        "executed": True,
        "launch_attempted": True,
        "execution_kind": "GAP_GENERATION_COHERENCE_PROCESS",
        "qualification_scope": "GAP_GENERATION_COHERENCE",
        "identity": identity,
        "kill_action": action,
        "checkpoint": json.loads(ready.read_text()),
        "actual": actual,
        "before_restart": before["state"],
        "after_restart": after["state"],
        "expected": entry["expected_post_restart_state"],
        "observed_error": None,
        "comparison": {"matched": True},
        "evidence_binding": binding,
        "revision": binding["revision"],
        "environment": binding["environment"],
        "command_exit": {"child": exit_code, "recovery": recovery.returncode, "reader": 0},
        "command": command,
        "launch_provenance": {
            "command_prefix": prefix,
            "argv": command,
            "child_sha256": _sha(CHILD),
            "python_sha256": _sha(Path(sys.executable)),
        },
        "reader_runs": [before_run, after_run],
        "scenario_artifact": _artifact(scenario_path),
        "checkpoint_artifact": _artifact(ready),
        "boundary_artifact": _artifact(case / "boundary.json"),
        "actual_artifact": _artifact(actual_path),
        "legacy_full_qualification": "HOLD",
        "production_authority": "NONE",
    }
    verify_gap_record(row, binding)
    terminal_path = case / "terminal-result.json"
    terminal_path.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")))
    row["terminal_artifact"] = _artifact(terminal_path)
    return row


def _mutations(records: list[dict[str, Any]], binding: dict[str, Any]) -> list[dict[str, str]]:
    detected = []
    for row in records:
        for suffix in ("MUT-EXPECTED", "MUT-INPUT"):
            damaged = copy.deepcopy(row)
            if suffix == "MUT-EXPECTED":
                damaged["comparison"] = {"matched": False}
            else:
                damaged["actual"]["controller"] = "WRONG"
            try:
                verify_gap_record(damaged, binding)
            except ValueError as error:
                detected.append({"mutation": f"{row['case_id']}-{suffix}", "error": str(error)})
    return detected


def run_gap_coherence_crash_matrix(
    pack: Path, workspace: Path, *, observation_input: dict[str, Any] | None = None
) -> dict[str, Any]:
    if observation_input is not None:
        return run_family(pack, workspace, "GAP_GENERATION_COHERENCE", observation_input)
    from tools.verify_repair_evidence import capture_binding

    entries = [
        row
        for row in json.loads(
            (pack / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if row["harness"] == "GAP_GENERATION_COHERENCE"
    ]
    if len(entries) != 21:
        raise ValueError("E_GAP_REGISTRY")
    workspace.mkdir(parents=True, exist_ok=True)
    shim = _compile_commit_shim(workspace)
    binding = capture_binding()
    records = [
        _run_case(entry, workspace / f"gap-{ordinal:02d}", ordinal, shim, binding)
        for ordinal, entry in enumerate(entries)
    ]
    mutations = _mutations(records, binding)
    return {
        "result": "PASS",
        "executed_vector_ids": [row["case_id"] for row in records],
        "killed_child_count": sum(row["kill_action"] != "NONE" for row in records),
        "mutation_survivors": 42 - len(mutations),
        "mutation_results": mutations,
        "records": records,
        "legacy_full_qualification": "HOLD",
        "production_authority": "NONE",
        "environment": {"platform": platform.platform()},
    }
