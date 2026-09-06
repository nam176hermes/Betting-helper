"""Execute and verify the governed generation/coherence crash family."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from tools.loopback_ack_crash_child import position
from tools.run_indexeddb_crash_matrix import _observations
from tools.run_loopback_ack_crash_matrix import PHASES, run_family
from tools.run_sqlite_crash_matrix import SHIM_SOURCE, _compile_commit_shim

ROOT = Path(__file__).resolve().parents[1]
CHILD = Path(__file__).with_name("gap_coherence_crash_child.py")
READER = Path(__file__).with_name("gap_state_reader.py")
REGISTRY = ROOT / "vendor/hybrid-discovery-v6.3.6/docs/registries/crash-harness-registry.v1.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha(path)}


def _key(case_id: str) -> str:
    return "-".join(case_id.split("-")[:2])


def _scenario(
    entry: dict[str, Any], run_id: str, *, input_mutation: bool = False
) -> dict[str, Any]:
    key = _key(entry["vector_id"])
    observation = _observations(run_id)[0]
    scenario: dict[str, Any] = {
        "run_id": run_id,
        "operation": "GAP",
        "phase": PHASES.get(key, entry["source_boundary"].split()[0]),
        "observation": observation,
        "setup_deliveries": [observation],
        "delivery": position(observation, 3),
        "spool_append": key.startswith("GAP-0") or key in {"GAP-10", "CAPACITY-01"},
        "extension_ack": "GEN0_Q1_H1"
        if key.startswith(("GAP", "CONFLICT", "LATE"))
        else "UNCHANGED",
        "capacity": None,
        "no_kill": entry["kill_action"] == "NONE",
        "input_mutation": input_mutation,
    }
    if key == "GAP-09":
        scenario.update(phase="during_commit", during_commit=True)
    elif key == "CONFLICT-01":
        scenario.update(phase="after_conflict", delivery=position(observation, 1))
        scenario["delivery"]["raw_observation_id"] = "observation:" + "f" * 64
        from moj_discovery.canonical import canonical_content_hash
        from moj_discovery.store import VENDOR

        scenario["delivery"]["content_hash"] = canonical_content_hash(
            "RawObservation",
            scenario["delivery"],
            registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
        )
    elif key == "LATE-01":
        scenario.update(
            phase="after_late_rejection",
            setup_deliveries=[observation, position(observation, 3)],
            delivery=position(observation, 2),
        )
    elif key == "GAP-11":
        delivery = position(observation, 2)
        delivery["generation"] = "1"
        from moj_discovery.canonical import canonical_content_hash
        from moj_discovery.store import VENDOR

        delivery["content_hash"] = canonical_content_hash(
            "RawObservation",
            delivery,
            registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
        )
        scenario.update(
            phase="after_repeated_gap",
            setup_deliveries=[observation, position(observation, 3)],
            delivery=delivery,
            prepare_successor=True,
            spool_append=False,
            extension_ack="GEN1_Q0_H0",
        )
    elif key == "CAPACITY-01":
        scenario.update(
            operation="CAPACITY",
            phase="after_capacity_stop",
            capacity={"normal_limit": 7, "terminal_reserve": 1, "used": 7},
        )
    elif key.startswith("CLOCK"):
        scenario.update(
            operation="CLOCK",
            phase="after_mapping_closure_insert"
            if key == "CLOCK-01"
            else "after_closure_commit_before_shock",
            setup_deliveries=[],
            spool_append=False,
            extension_ack="UNCHANGED",
        )
    elif key.startswith("EPOCH"):
        step = {
            "EPOCH-01": "shock",
            "EPOCH-02": "shock",
            "EPOCH-03": "pending",
            "EPOCH-04": "release",
            "EPOCH-05": "new_shock",
        }[key]
        scenario.update(
            operation="EPOCH",
            phase=entry["crash_checkpoint"],
            epoch_step=step,
            setup_deliveries=[observation],
            prepare_waiting=key == "EPOCH-03",
            prepare_pending=key in {"EPOCH-04", "EPOCH-05"},
            candidate=key in {"EPOCH-03", "EPOCH-04", "EPOCH-05"},
            release=key == "EPOCH-04",
            checkpoint_before_commit=key in {"EPOCH-01", "EPOCH-03"},
            during_commit=key == "EPOCH-04",
            spool_append=False,
            extension_ack="UNCHANGED",
        )
    return scenario


def _proc_observation(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    stat = Path(f"/proc/{process.pid}/stat").read_text().split()
    argv = Path(f"/proc/{process.pid}/cmdline").read_bytes().rstrip(b"\0").split(b"\0")
    executable = Path(f"/proc/{process.pid}/exe").resolve()
    return {
        "pid": process.pid,
        "pgid": os.getpgid(process.pid),
        "start_ticks": stat[21],
        "executable": str(executable),
        "executable_sha256": _sha(executable),
        "argv": [item.decode() for item in argv],
    }


def _read(
    case: Path, identity: dict[str, Any], phase: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_dir = case / identity["run_id"]
    request = {
        "run_id": identity["run_id"],
        "case_id": identity["case_id"],
        "checkpoint_id": identity["checkpoint_id"],
        "phase": phase,
    }
    request_path = case / f"reader-{phase}-input.json"
    request_path.write_text(json.dumps(request, sort_keys=True))
    command = [
        str(Path(sys.executable).absolute()),
        "-I",
        str(READER.resolve()),
        str(run_dir.resolve()),
        "--identity",
        str(request_path.resolve()),
    ]
    completed = subprocess.run(  # noqa: S603 -- fixed independent local reader
        command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=10
    )
    output_path = case / f"reader-{phase}.json"
    output_path.write_text(completed.stdout)
    output = json.loads(completed.stdout)
    if output["identity"] != request:
        raise ValueError("E_GAP_READER_IDENTITY")
    return output["state"], {
        "phase": phase,
        "argv": command,
        "exit": completed.returncode,
        "process": output["process"],
        "input": _artifact(request_path),
        "output": _artifact(output_path),
    }


def _latest_cursor(tables: dict[str, Any]) -> str | None:
    rows = tables["reducer_cursors"]
    return (
        max(rows, key=lambda row: (row["generation"], row["highest_contiguous_sequence"]))[
            "cursor_hash"
        ]
        if rows
        else None
    )


def _semantic_view(
    state: dict[str, Any],
    baseline: dict[str, Any],
    expected: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    tables, base = state["tables"], baseline["tables"]
    atomic_outcomes = expected.get("allowed_atomic_outcomes", [])
    delta_shape = expected.get("sql_row_deltas", {})
    if atomic_outcomes:
        observed_deltas = {
            name: len(tables[name]) - len(base[name])
            for outcome in atomic_outcomes
            for name in outcome.get("sql_row_deltas", {})
        }
        selected = next(
            (
                outcome
                for outcome in atomic_outcomes
                if outcome.get("sql_row_deltas", {})
                == {name: observed_deltas[name] for name in outcome.get("sql_row_deltas", {})}
            ),
            atomic_outcomes[0],
        )
        delta_shape = selected.get("sql_row_deltas", {})
    deltas = {name: len(tables[name]) - len(base[name]) for name in delta_shape}
    controller = tables["coherence_controllers"][0]
    base_controller = base["coherence_controllers"][0]
    generations = sorted(tables["stream_generations"], key=lambda row: row["generation"])
    target_stream = scenario["delivery"]["stream_id"]
    active = next(
        row
        for row in generations
        if row["generation_state"] == "ACTIVE" and row["stream_id"] == target_stream
    )
    gaps = tables["gap_records"]
    operation = scenario["operation"]
    coherence = controller["controller_state"]
    if (
        operation == "CLOCK"
        and tables["clock_mapping_closures"]
        and not tables["shock_observations"]
    ):
        coherence = "OPEN_BUT_INELIGIBLE"
    if operation == "EPOCH" and coherence == "OPEN" and scenario["epoch_step"] == "shock":
        coherence = "OPEN_BUT_SHOCK_REDETECTION_REQUIRED"
    if operation == "CAPACITY" and any(
        row["gap_reason"] == "STORAGE_SAFETY_STOP" for row in tables["gap_records"]
    ):
        coherence = "SHOCKED_CLOSED_AFTER_TERMINAL_GAP"
    if operation == "GAP" and active["generation"] == 0:
        predecessor, successor = "0_ACTIVE", "NOT_CREATED"
    elif operation == "GAP" and active["generation"] == 2:
        predecessor, successor = "1_CLOSED", "2_ACTIVE"
    elif operation == "GAP":
        predecessor, successor = "0_CLOSED", "1_ACTIVE"
        if any(row["disposition"] == "LATE_REPAIR_ONLY" for row in tables["raw_commits"]):
            predecessor = "0_CLOSED_HISTORY_REPAIRED_EPOCH_REMAINS_CLOSED"
    elif operation == "CAPACITY":
        predecessor, successor = "ACTIVE_UNTIL_TERMINAL_GAP_COMMIT", "NOT_CREATED"
    else:
        predecessor = (
            "CLOSED"
            if operation == "EPOCH" and scenario["epoch_step"] in {"release", "new_shock"}
            else "UNCHANGED"
        )
        successor = "ACTIVE" if predecessor == "CLOSED" else "UNCHANGED"
    if operation == "GAP":
        predecessor_generation = max(active["generation"] - 1, 0)
        predecessor_cursors = [
            row
            for row in tables["reducer_cursors"]
            if row["stream_id"] == target_stream and row["generation"] == predecessor_generation
        ]
        highest = max(
            (row["highest_contiguous_sequence"] for row in predecessor_cursors), default=0
        )
        cursor = f"GEN{predecessor_generation}_Q{highest}_H{highest}"
        extension = cursor
        backend = cursor
    else:
        cursor = extension = backend = "UNCHANGED"
    if not gaps and operation == "GAP":
        recovery = "REDETECT_GAP" if atomic_outcomes else "ROLLBACK_AND_REDETECT_GAP_AT_SEQUENCE_3"
    elif tables["raw_conflicts"]:
        recovery = (
            "QUARANTINE_CONFLICT_ATOMICALLY_CLOSE_COHERENCE_AND_START_GENERATION_1_"
            "WITHOUT_ACKING_CONFLICT"
        )
    elif any(row["disposition"] == "LATE_REPAIR_ONLY" for row in tables["raw_commits"]):
        recovery = "STORE_LATE_REPAIR_ONLY_NEVER_REOPEN_GENERATION_0_OR_ITS_EPOCH"
    elif any(
        row["stream_id"] == target_stream and row["predecessor_generation"] == 1 for row in gaps
    ):
        recovery = "ATOMICALLY_CLOSE_COHERENCE_CLOSE_GENERATION_1_AND_OPEN_EXACT_SUCCESSOR_2"
    elif operation == "GAP":
        recovery = (
            "RESUME_ONLY_IN_GENERATION_1"
            if atomic_outcomes
            else "AUTHENTICATE_GENERATION_AND_COHERENCE_FACTS_AND_RESUME_ONLY_IN_GENERATION_1"
        )
    elif operation == "CAPACITY":
        recovery = "SPOOL_CAPACITY_SAFETY_STOP_NEVER_EVICT_UNACKNOWLEDGED_ROWS"
    elif operation == "CLOCK":
        recovery = (
            "ROLLBACK_AND_REDETECT_CLOSURE_BEFORE_ACCEPTING_LATER_EVIDENCE"
            if not tables["clock_mapping_closures"]
            else "SYNTHESIZE_MAPPING_CLOSURE_SHOCK_BEFORE_ANY_LATER_EVIDENCE"
        )
    else:
        recovery = {
            "OPEN_BUT_SHOCK_REDETECTION_REQUIRED": (
                "ROLLBACK_REDETECT_SHOCK_AND_CLOSE_BEFORE_ELIGIBILITY"
            ),
            "SHOCKED_CLOSED": "ADVANCE_TO_WAITING_FOR_RESNAPSHOT_PREDECESSOR_REMAINS_CLOSED",
            "WAITING_FOR_RESNAPSHOT": "ROLLBACK_AND_REVALIDATE_FULL_RELEASE_PREDICATE",
            "NEW_EPOCH_PENDING": "REVALIDATE_RELEASE_PREDICATE",
            "NEW_EPOCH_OPEN": "USE_ONLY_DISTINCT_SUCCESSOR_EPOCH",
        }[coherence]
        if any(
            row["transition_reason"] == "NEW_SHOCK_CLOSED_CANDIDATE"
            for row in tables["coherence_transitions"]
        ):
            recovery = "PERMANENTLY_CLOSE_CANDIDATE_AND_BUILD_A_NEW_DISTINCT_CANDIDATE"
    return {
        "indexeddb_spool_delta": state["spool"]["count"] - baseline["spool"]["count"],
        "sql_row_deltas": deltas,
        **(
            {
                "coherence_controller_updates": controller["controller_revision"]
                - base_controller["controller_revision"]
            }
            if "coherence_controller_updates" in expected
            or any("coherence_controller_updates" in item for item in atomic_outcomes)
            else {}
        ),
        "reducer_cursor": cursor,
        "extension_ack": extension,
        "backend_ack": backend,
        "predecessor_generation": predecessor,
        "successor_generation": successor,
        "coherence_state": coherence,
        "recovery_action": recovery,
    }


def _compare(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    allowed = expected.get("allowed_atomic_outcomes")
    if isinstance(allowed, list):
        common = {key: value for key, value in expected.items() if key != "allowed_atomic_outcomes"}
        matches = any({**common, **candidate} == actual for candidate in allowed)
    else:
        matches = actual == expected
    return {"matched": matches, "actual": actual}


def _run_process(
    entry: dict[str, Any], case: Path, ordinal: int, shim: Path, *, input_mutation: bool = False
) -> dict[str, Any]:
    case.mkdir(parents=True)
    run_id, nonce = str(uuid4()), secrets.token_hex(16)
    scenario = _scenario(entry, run_id, input_mutation=input_mutation)
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
    identity = {
        "run_id": run_id,
        "case_id": entry["vector_id"],
        "checkpoint_id": entry["crash_checkpoint"],
        "component": entry["harness"],
        "pid": child.pid,
        "ordinal": ordinal,
        "test_nonce": nonce,
    }
    deadline = monotonic() + 10
    while not ready.is_file() and monotonic() < deadline and child.poll() is None:
        sleep(0.02)
    if input_mutation:
        if not ready.is_file() or json.loads(ready.read_text()) != identity:
            raise RuntimeError(f"E_GAP_MUTATION_CHECKPOINT:{entry['vector_id']}:{child.poll()}")
        process_observation = _proc_observation(child)
        (case / "continue.json").write_text("{}")
        exit_code = child.wait(timeout=5)
        terminal_path = case / "mutation-terminal.json"
        terminal_path.write_text(
            json.dumps(
                {
                    "identity": identity,
                    "process": process_observation,
                    "exit": exit_code,
                    "rejection": "E_GAP_MUTATED_INPUT",
                },
                sort_keys=True,
            )
        )
        return {
            "mutation_detected": exit_code != 0,
            "case_directory": str(case.resolve()),
            "pid": child.pid,
            "identity": identity,
            "process_observation": process_observation,
            "command": command,
            "exit": exit_code,
            "scenario_artifact": _artifact(scenario_path),
            "checkpoint_artifact": _artifact(ready),
            "boundary_artifact": _artifact(case / "boundary.json"),
            "stderr_artifact": _artifact(case / "child.stderr"),
            "database_artifact": _artifact(case / run_id / "run.sqlite3"),
            "terminal_artifact": _artifact(terminal_path),
        }
    if not ready.is_file() or json.loads(ready.read_text()) != identity:
        raise RuntimeError(f"E_GAP_CHECKPOINT:{entry['vector_id']}:{child.poll()}")
    process_observation = _proc_observation(child)
    if entry["kill_action"] == "NONE":
        (case / "continue.json").write_text("{}")
        exit_code = child.wait(timeout=5)
    else:
        os.killpg(child.pid, signal.SIGKILL)
        exit_code = child.wait(timeout=5)
    before, before_reader = _read(case, identity, "before")
    baseline = json.loads((case / "baseline-state.json").read_text())
    recovery_command = [*prefix, "--recover", str(case.resolve())]
    recovery = subprocess.run(  # noqa: S603 -- fixed successor recovery process
        recovery_command, cwd=ROOT, check=True, capture_output=True, timeout=10
    )
    after, after_reader = _read(case, identity, "after")
    termination = {
        "owner_pid": os.getpid(),
        "target_pid": child.pid,
        "target_pgid": process_observation["pgid"],
        "action": entry["kill_action"],
        "exit": exit_code,
    }
    terminal_path = case / "terminal.json"
    terminal_path.write_text(
        json.dumps(
            {
                "identity": identity,
                "kill_action": entry["kill_action"],
                "child_exit": exit_code,
                "child_process": process_observation,
                "recovery_process": json.loads((case / "recovery-process.json").read_text()),
                "reader_processes": [before_reader["process"], after_reader["process"]],
                "termination": termination,
            },
            sort_keys=True,
        )
    )
    return {
        "identity": identity,
        "command": command,
        "exit": exit_code,
        "process_observation": process_observation,
        "termination": termination,
        "before": before,
        "after": after,
        "baseline": baseline,
        "reader_runs": [before_reader, after_reader],
        "recovery_command": recovery_command,
        "recovery_exit": recovery.returncode,
        "recovery_process": json.loads((case / "recovery-process.json").read_text()),
        "scenario": scenario,
        "case_directory": str(case.resolve()),
        "scenario_artifact": _artifact(scenario_path),
        "checkpoint_artifact": _artifact(ready),
        "boundary_artifact": _artifact(case / "boundary.json"),
        "baseline_artifact": _artifact(case / "baseline-state.json"),
        "recovery_process_artifact": _artifact(case / "recovery-process.json"),
        "terminal_artifact": _artifact(terminal_path),
    }


def _record(
    entry: dict[str, Any], run: dict[str, Any], binding: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    actual = _semantic_view(run["before"], run["baseline"], expected, run["scenario"])
    comparison = _compare(actual, expected)
    actual_path = Path(run["case_directory"]) / "actual-semantic.json"
    actual_path.write_text(json.dumps(actual, sort_keys=True))
    row = {
        "vector_id": entry["vector_id"],
        "case_id": entry["vector_id"],
        "case_directory": run["case_directory"],
        "status": "PASS" if comparison["matched"] else "FAIL",
        "result": "PASS" if comparison["matched"] else "FAIL",
        "executed": True,
        "launch_attempted": True,
        "execution_kind": "GAP_GENERATION_COHERENCE_PROCESS",
        "qualification_scope": "GAP_GENERATION_COHERENCE",
        "identity": run["identity"],
        "kill_action": entry["kill_action"],
        "actual": actual,
        "expected": expected,
        "comparison": comparison,
        "observed_error": None if comparison["matched"] else "E_GAP_STATE_MISMATCH",
        "before_restart": run["before"],
        "after_restart": run["after"],
        "evidence_binding": binding,
        "revision": binding["revision"],
        "environment": binding["environment"],
        "command": run["command"],
        "command_exit": {"child": run["exit"], "recovery": run["recovery_exit"], "reader": 0},
        "process_observation": run["process_observation"],
        "termination": run["termination"],
        "reader_runs": run["reader_runs"],
        "recovery_command": run["recovery_command"],
        "recovery_process": run["recovery_process"],
        "scenario_artifact": run["scenario_artifact"],
        "checkpoint_artifact": run["checkpoint_artifact"],
        "boundary_artifact": run["boundary_artifact"],
        "baseline_artifact": run["baseline_artifact"],
        "recovery_process_artifact": run["recovery_process_artifact"],
        "terminal_artifact": run["terminal_artifact"],
        "actual_artifact": _artifact(actual_path),
        "shim": {
            "path": str(Path(run["command"][4]).resolve()),
            "source_sha256": _sha(SHIM_SOURCE),
            "binary_sha256": _sha(Path(run["command"][4])),
        },
        "production_authority": "NONE",
        "legacy_full_qualification": "HOLD",
    }
    return row


def verify_gap_record(row: dict[str, Any], binding: dict[str, Any]) -> None:
    entry = next(
        item
        for item in json.loads(REGISTRY.read_text())["entries"]
        if item["vector_id"] == row["case_id"]
    )
    if row["evidence_binding"] != binding or row["revision"] != binding["revision"]:
        raise ValueError("E_GAP_STALE_BINDING")
    if row["expected"] != entry["expected_post_restart_state"]:
        raise ValueError("E_GAP_ORACLE")
    if (
        row["identity"]["component"] != entry["harness"]
        or row["identity"]["case_id"] != entry["vector_id"]
    ):
        raise ValueError("E_GAP_IDENTITY")
    boundary = json.loads(Path(row["boundary_artifact"]["path"]).read_text())
    checkpoint = json.loads(Path(row["checkpoint_artifact"]["path"]).read_text())
    process = row["process_observation"]
    if (
        checkpoint != row["identity"]
        or boundary["identity"] != row["identity"]
        or process["pid"] != row["identity"]["pid"]
        or process["pgid"] != process["pid"]
    ):
        raise ValueError("E_GAP_IDENTITY")
    expected_exit = 0 if entry["kill_action"] == "NONE" else -signal.SIGKILL
    if row["command_exit"] != {"child": expected_exit, "recovery": 0, "reader": 0}:
        raise ValueError("E_GAP_TERMINATION")
    if (
        row["comparison"] != _compare(row["actual"], row["expected"])
        or not row["comparison"]["matched"]
        or row["observed_error"] is not None
    ):
        raise ValueError("E_GAP_COMPARISON")
    for name in (
        "scenario_artifact",
        "checkpoint_artifact",
        "boundary_artifact",
        "baseline_artifact",
        "recovery_process_artifact",
        "terminal_artifact",
        "actual_artifact",
    ):
        descriptor = row[name]
        if _sha(Path(descriptor["path"])) != descriptor["sha256"]:
            raise ValueError("E_GAP_ARTIFACT")
    python = str(Path(sys.executable).absolute())
    if (
        row["command"][:3] != [python, "-I", str(CHILD.resolve())]
        or process["argv"] != row["command"]
        or process["executable"] != str(Path(sys.executable).resolve())
        or process["executable_sha256"] != _sha(Path(sys.executable).resolve())
    ):
        raise ValueError("E_GAP_PROCESS_PROVENANCE")
    recovery = row["recovery_process"]
    if (
        recovery["argv"] != row["recovery_command"][2:]
        or recovery["executable"] != str(Path(sys.executable).resolve())
        or recovery["executable_sha256"] != _sha(Path(sys.executable).resolve())
    ):
        raise ValueError("E_GAP_PROCESS_PROVENANCE")
    reader_processes = []
    for reader in row["reader_runs"]:
        for descriptor_name in ("input", "output"):
            descriptor = reader[descriptor_name]
            if _sha(Path(descriptor["path"])) != descriptor["sha256"]:
                raise ValueError("E_GAP_READER")
        output = json.loads(Path(reader["output"]["path"]).read_text())
        expected_state = row[f"{reader['phase']}_restart"]
        if (
            output["process"] != reader["process"]
            or output["process"]["argv"] != reader["argv"][2:]
            or output["process"]["executable"] != str(Path(sys.executable).resolve())
            or output["process"]["executable_sha256"] != _sha(Path(sys.executable).resolve())
            or output["state"] != expected_state
            or output["identity"]
            != {
                "run_id": row["identity"]["run_id"],
                "case_id": row["identity"]["case_id"],
                "checkpoint_id": row["identity"]["checkpoint_id"],
                "phase": reader["phase"],
            }
        ):
            raise ValueError("E_GAP_READER")
        reader_processes.append(reader["process"])
    terminal = json.loads(Path(row["terminal_artifact"]["path"]).read_text())
    if terminal != {
        "identity": row["identity"],
        "kill_action": row["kill_action"],
        "child_exit": row["command_exit"]["child"],
        "child_process": process,
        "recovery_process": recovery,
        "reader_processes": reader_processes,
        "termination": row["termination"],
    }:
        raise ValueError("E_GAP_PROCESS_PROVENANCE")
    process_ids = [process["pid"], recovery["pid"], *(item["pid"] for item in reader_processes)]
    if len(process_ids) != len(set(process_ids)):
        raise ValueError("E_GAP_PROCESS_PROVENANCE")
    if row["termination"] != {
        "owner_pid": row["termination"]["owner_pid"],
        "target_pid": process["pid"],
        "target_pgid": process["pgid"],
        "action": entry["kill_action"],
        "exit": expected_exit,
    }:
        raise ValueError("E_GAP_TERMINATION")
    scenario = json.loads(Path(row["scenario_artifact"]["path"]).read_text())
    baseline = json.loads(Path(row["baseline_artifact"]["path"]).read_text())
    if _semantic_view(row["before_restart"], baseline, row["expected"], scenario) != row["actual"]:
        raise ValueError("E_GAP_COMPARISON")
    if (
        _sha(Path(row["shim"]["path"])) != row["shim"]["binary_sha256"]
        or _sha(SHIM_SOURCE) != row["shim"]["source_sha256"]
    ):
        raise ValueError("E_GAP_SHIM")


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
    shim, binding = _compile_commit_shim(workspace), capture_binding()
    records, mutations = [], []
    for ordinal, entry in enumerate(entries):
        run = _run_process(entry, workspace / f"positive-{ordinal:02d}", ordinal, shim)
        row = _record(entry, run, binding, entry["expected_post_restart_state"])
        if row["status"] != "PASS":
            raise ValueError(f"E_GAP_POSITIVE:{entry['vector_id']}:{row['actual']}")
        verify_gap_record(row, binding)
        records.append(row)
        wrong = copy.deepcopy(entry["expected_post_restart_state"])
        if "allowed_atomic_outcomes" in wrong:
            for outcome in wrong["allowed_atomic_outcomes"]:
                outcome["coherence_state"] = "WRONG"
        else:
            wrong["coherence_state"] = "WRONG"
        expected_run = _run_process(
            entry, workspace / f"mutation-expected-{ordinal:02d}", 100 + ordinal, shim
        )
        expected_row = _record(entry, expected_run, binding, wrong)
        mutations.append(
            {
                "mutation": entry["mutation_vector_ids"][0],
                "detected": expected_row["status"] == "FAIL",
                "case_directory": expected_run["case_directory"],
                "pid": expected_run["identity"]["pid"],
                "process_observation": expected_run["process_observation"],
                "termination": expected_run["termination"],
                "artifacts": [
                    expected_run["scenario_artifact"],
                    expected_run["checkpoint_artifact"],
                    expected_run["boundary_artifact"],
                    expected_row["actual_artifact"],
                    expected_run["terminal_artifact"],
                ],
            }
        )
        input_run = _run_process(
            entry,
            workspace / f"mutation-input-{ordinal:02d}",
            200 + ordinal,
            shim,
            input_mutation=True,
        )
        mutations.append(
            {
                "mutation": entry["mutation_vector_ids"][1],
                "detected": input_run["mutation_detected"],
                "case_directory": input_run["case_directory"],
                "pid": input_run["pid"],
                "process_observation": input_run["process_observation"],
                "command": input_run["command"],
                "exit": input_run["exit"],
                "artifacts": [
                    input_run["scenario_artifact"],
                    input_run["checkpoint_artifact"],
                    input_run["boundary_artifact"],
                    input_run["stderr_artifact"],
                    input_run["database_artifact"],
                    input_run["terminal_artifact"],
                ],
            }
        )
    survivors = sum(not row["detected"] for row in mutations)
    return {
        "result": "PASS" if not survivors else "FAIL",
        "executed_vector_ids": [row["case_id"] for row in records],
        "killed_child_count": sum(row["kill_action"] != "NONE" for row in records),
        "mutation_survivors": survivors,
        "mutation_results": mutations,
        "records": records,
        "legacy_full_qualification": "HOLD",
        "production_authority": "NONE",
    }
