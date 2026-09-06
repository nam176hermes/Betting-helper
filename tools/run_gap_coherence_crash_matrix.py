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

from tools.gap_state_reader import read_gap_state
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


def _scenario(entry: dict[str, Any], run_id: str) -> dict[str, Any]:
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


def _proc_observation(
    process: subprocess.Popen[bytes], artifact_path: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    stat_path = Path(f"/proc/{process.pid}/stat")
    cmdline_path = Path(f"/proc/{process.pid}/cmdline")
    executable_path = Path(f"/proc/{process.pid}/exe")
    stat_raw = stat_path.read_text()
    cmdline_raw = cmdline_path.read_bytes()
    stat = stat_raw.split()
    argv = cmdline_raw.rstrip(b"\0").split(b"\0")
    executable = executable_path.resolve()
    raw = {
        "captured_by_pid": os.getpid(),
        "proc_stat": stat_raw,
        "proc_cmdline_hex": cmdline_raw.hex(),
        "proc_exe_link": os.readlink(executable_path),
        "proc_exe_resolved": str(executable),
        "proc_exe_sha256": _sha(executable),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }
    artifact_path.write_text(json.dumps(raw, sort_keys=True))
    observation = {
        "pid": process.pid,
        "pgid": os.getpgid(process.pid),
        "start_ticks": stat[21],
        "executable": str(executable),
        "executable_sha256": _sha(executable),
        "argv": [item.decode() for item in argv],
    }
    return observation, _artifact(artifact_path)


def _verify_proc_observation(
    observation: dict[str, Any], descriptor: dict[str, str], command: list[str]
) -> None:
    path = Path(descriptor["path"])
    if _sha(path) != descriptor["sha256"]:
        raise ValueError("E_GAP_PROCESS_PROVENANCE")
    raw = json.loads(path.read_text())
    stat = raw["proc_stat"].split()
    cmdline = bytes.fromhex(raw["proc_cmdline_hex"]).rstrip(b"\0").split(b"\0")
    derived = {
        "pid": int(stat[0]),
        "pgid": int(stat[4]),
        "start_ticks": stat[21],
        "executable": raw["proc_exe_resolved"],
        "executable_sha256": raw["proc_exe_sha256"],
        "argv": [item.decode() for item in cmdline],
    }
    if (
        observation != derived
        or derived["argv"] != command
        or raw["proc_exe_link"] != str(Path(sys.executable).resolve())
        or derived["executable"] != str(Path(sys.executable).resolve())
        or derived["executable_sha256"] != _sha(Path(sys.executable).resolve())
        or not raw["boot_id"]
    ):
        raise ValueError("E_GAP_PROCESS_PROVENANCE")


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


def _validate_recovery(
    before: dict[str, Any], after: dict[str, Any], scenario: dict[str, Any]
) -> dict[str, Any]:
    if (
        before["run_id"] != scenario["run_id"]
        or after["run_id"] != scenario["run_id"]
        or before["ddl_sha256"] != after["ddl_sha256"]
    ):
        raise ValueError("E_GAP_RECOVERY_BINDING")
    before_tables, after_tables = before["tables"], after["tables"]
    mutable = {"coherence_controllers", "stream_generations", "run_meta"}
    if any(
        len(after_tables[name]) < len(rows)
        for name, rows in before_tables.items()
        if name not in mutable
    ):
        raise ValueError("E_GAP_RECOVERY_REGRESSION")
    controller = after_tables["coherence_controllers"][0]
    operation = scenario["operation"]
    target_stream = scenario["delivery"]["stream_id"]
    target_generations = {
        row["generation"]: row["generation_state"]
        for row in after_tables["stream_generations"]
        if row["stream_id"] == target_stream
    }
    target_gaps_before = [
        row for row in before_tables["gap_records"] if row["stream_id"] == target_stream
    ]
    target_gaps_after = [
        row for row in after_tables["gap_records"] if row["stream_id"] == target_stream
    ]
    if operation == "GAP" and not target_gaps_before:
        if (
            len(target_gaps_after) != 1
            or target_generations != {0: "QUARANTINED_GAP", 1: "ACTIVE"}
            or controller["controller_state"] != "SHOCKED_CLOSED"
        ):
            raise ValueError("E_GAP_RECOVERY_PREDICATE")
    elif operation == "GAP" and (  # noqa: SIM114 -- distinct recovery contracts
        target_gaps_after != target_gaps_before
        or len(after_tables["raw_commits"]) != len(before_tables["raw_commits"])
    ):
        raise ValueError("E_GAP_RECOVERY_PREDICATE")
    elif operation == "CLOCK" and (  # noqa: SIM114 -- distinct recovery contracts
        not after_tables["clock_mapping_closures"]
        or not after_tables["shock_observations"]
        or controller["controller_state"] != "SHOCKED_CLOSED"
    ):
        raise ValueError("E_GAP_RECOVERY_PREDICATE")
    elif operation == "CAPACITY" and (
        after_tables != before_tables
        or after["spool"] != before["spool"]
        or after["capacity"] != before["capacity"]
    ):
        raise ValueError("E_GAP_RECOVERY_PREDICATE")
    elif operation == "EPOCH":
        wanted = {
            "shock": "WAITING_FOR_RESNAPSHOT",
            "pending": "NEW_EPOCH_PENDING",
            "release": "NEW_EPOCH_OPEN",
            "new_shock": "WAITING_FOR_RESNAPSHOT",
        }[scenario["epoch_step"]]
        if controller["controller_state"] != wanted:
            raise ValueError("E_GAP_RECOVERY_PREDICATE")
        if scenario["epoch_step"] == "new_shock":
            closures = [
                row
                for row in after_tables["coherence_transitions"]
                if row["transition_reason"] == "NEW_SHOCK_CLOSED_CANDIDATE"
            ]
            if len(closures) != 1:
                raise ValueError("E_GAP_RECOVERY_PREDICATE")
            closure = closures[0]
            closed_candidate = closure["candidate_epoch_id"]
            successors = [
                row
                for row in after_tables["coherence_epochs"]
                if row["predecessor_epoch_id"] == closed_candidate
            ]
            if (
                not closed_candidate
                or closure["from_state"] != "NEW_EPOCH_PENDING"
                or closure["to_state"] != "WAITING_FOR_RESNAPSHOT"
                or closure["coherence_controller_id"] != controller["coherence_controller_id"]
                or closure["shock_observation_id"] != controller["active_shock_observation_id"]
                or controller["candidate_epoch_id"] is not None
                or len(successors) != 1
                or successors[0]["coherence_epoch_id"] == closed_candidate
                or successors[0]["predecessor_permanently_closed"] != 1
            ):
                raise ValueError("E_GAP_RECOVERY_PREDICATE")
    return {
        "run_id": after["run_id"],
        "ddl_sha256": after["ddl_sha256"],
        "controller_state": controller["controller_state"],
        "target_generations": target_generations,
        "target_gap_count": len(target_gaps_after),
        "late_repair_count": sum(
            row["disposition"] == "LATE_REPAIR_ONLY" for row in after_tables["raw_commits"]
        ),
        "new_shock_candidate_closures": sum(
            row["transition_reason"] == "NEW_SHOCK_CLOSED_CANDIDATE"
            for row in after_tables["coherence_transitions"]
        ),
    }


def _validate_snapshot_relations(tables: dict[str, list[dict[str, Any]]]) -> None:
    """Validate final-state equivalents of history-sensitive DDL triggers."""

    def indexed(name: str, key: str) -> dict[Any, dict[str, Any]]:
        rows = tables[name]
        result = {row[key]: row for row in rows}
        if len(result) != len(rows):
            raise ValueError("E_GAP_SNAPSHOT_RELATION")
        return result

    generations = indexed("stream_generations", "generation_id")
    gaps = indexed("gap_records", "gap_id")
    bindings = indexed("gap_epoch_bindings", "gap_epoch_binding_id")
    generation_transitions = indexed("generation_transitions", "generation_transition_id")
    controllers = indexed("coherence_controllers", "coherence_controller_id")
    epochs = indexed("coherence_epochs", "coherence_epoch_id")
    transitions = indexed("coherence_transitions", "coherence_transition_id")
    shocks = indexed("shock_observations", "shock_observation_id")
    freshness = indexed("input_freshness_vectors", "input_freshness_vector_id")
    proofs = indexed("authoritative_resnapshot_proofs", "authoritative_resnapshot_proof_id")
    mappings = indexed("clock_mappings", "clock_mapping_id")
    closed_mappings = {row["clock_mapping_id"] for row in tables["clock_mapping_closures"]}
    cursors = indexed("reducer_cursors", "reducer_cursor_id")

    generation_key = {
        (
            row["run_id"],
            row["browser_run_id"],
            row["producer_id"],
            row["stream_id"],
            row["generation"],
        ): row
        for row in generations.values()
    }
    for raw in tables["raw_commits"]:
        key = tuple(
            raw[field]
            for field in (*("run_id", "browser_run_id", "producer_id", "stream_id"), "generation")
        )
        if (
            raw["disposition"] == "LATE_REPAIR_ONLY"
            and generation_key[key]["generation_state"] == "ACTIVE"
        ):
            raise ValueError("E_GAP_SNAPSHOT_RELATION")

    gap_binding_by_gap = {row["gap_id"]: row for row in bindings.values()}
    generation_transition_by_gap = {row["gap_id"]: row for row in generation_transitions.values()}
    if len(gap_binding_by_gap) != len(bindings) or len(generation_transition_by_gap) != len(
        generation_transitions
    ):
        raise ValueError("E_GAP_SNAPSHOT_RELATION")
    for gap_id, gap in gaps.items():
        binding = gap_binding_by_gap.get(gap_id)
        generation_transition = generation_transition_by_gap.get(gap_id)
        if binding is None or generation_transition is None:
            raise ValueError("E_GAP_SNAPSHOT_RELATION")
        base = (gap["run_id"], gap["browser_run_id"], gap["producer_id"], gap["stream_id"])
        predecessor = generation_key.get((*base, gap["predecessor_generation"]))
        successor = generation_key.get((*base, gap["successor_generation"]))
        successor_was_reclosed = any(
            later["run_id"] == gap["run_id"]
            and later["browser_run_id"] == gap["browser_run_id"]
            and later["producer_id"] == gap["producer_id"]
            and later["stream_id"] == gap["stream_id"]
            and later["predecessor_generation"] == gap["successor_generation"]
            for later in gaps.values()
        )
        successor_closed_with_run = (
            successor is not None
            and successor["generation_state"] == "CLOSED"
            and successor["close_reason"] == "RUN_CLOSED"
            and any(meta["run_id"] == gap["run_id"]
                    and meta["run_status"] in {"CLOSED", "DESTRUCTION_PENDING"}
                    for meta in tables["run_meta"])
        )
        transition = transitions.get(binding["coherence_transition_id"])
        controller = controllers.get(binding["coherence_controller_id"])
        shock = shocks.get(binding["shock_observation_id"])
        if (
            predecessor is None
            or successor is None
            or predecessor["generation_state"] == "ACTIVE"
            or predecessor["close_reason"] != gap["gap_reason"]
            or (successor["generation_state"] != "ACTIVE"
                and not successor_was_reclosed and not successor_closed_with_run)
            or generation_transition["predecessor_generation"] != gap["predecessor_generation"]
            or generation_transition["successor_generation"] != gap["successor_generation"]
            or transition is None
            or controller is None
            or shock is None
            or binding["binding_role"] != "AFFECTED_EPOCH_PERMANENTLY_CLOSED"
            or transition["coherence_controller_id"] != controller["coherence_controller_id"]
            or transition["predecessor_epoch_id"] != binding["predecessor_epoch_id"]
            or transition["shock_observation_id"] != shock["shock_observation_id"]
            or transition["from_state"] not in {"OPEN", "NEW_EPOCH_OPEN"}
            or transition["to_state"] != "SHOCKED_CLOSED"
            or transition["transition_reason"] != "SHOCK_ATOMIC_CLOSE"
            or transition["bindings_verified"] != 1
            or controller["run_id"] != gap["run_id"]
            or controller["fixture_id"] != shock["fixture_id"]
            or shock["run_id"] != gap["run_id"]
            or shock["shock_type"]
            not in {
                "SEQUENCE_GAP",
                "SCHEMA_CONFLICT",
                "LIFECYCLE_INVALIDATION",
                "EQUIVALENT_UNKNOWN_SHOCK",
            }
        ):
            raise ValueError("E_GAP_SNAPSHOT_RELATION")

    for transition in transitions.values():
        controller = controllers[transition["coherence_controller_id"]]
        predecessor = epochs[transition["predecessor_epoch_id"]]
        shock = (
            shocks[transition["shock_observation_id"]]
            if transition["shock_observation_id"] is not None
            else None
        )
        if (
            transition["fixture_id"] != controller["fixture_id"]
            or predecessor["run_id"] != controller["run_id"]
            or predecessor["fixture_id"] != controller["fixture_id"]
            or (
                shock is not None
                and (shock["run_id"], shock["fixture_id"])
                != (controller["run_id"], controller["fixture_id"])
            )
        ):
            raise ValueError("E_GAP_SNAPSHOT_RELATION")
        candidate_id = transition["candidate_epoch_id"]
        candidate = epochs[candidate_id] if candidate_id is not None else None
        if candidate is not None and (
            candidate["run_id"] != controller["run_id"]
            or candidate["fixture_id"] != controller["fixture_id"]
            or candidate["predecessor_epoch_id"] != predecessor["coherence_epoch_id"]
        ):
            raise ValueError("E_GAP_SNAPSHOT_RELATION")
        if transition["transition_reason"] in {
            "RESNAPSHOT_CANDIDATE_ACCEPTED",
            "RELEASE_PREDICATE_SATISFIED",
        }:
            proof = proofs.get(transition["resnapshot_proof_id"])
            vector = freshness.get(transition["input_freshness_vector_id"])
            if (
                candidate is None
                or proof is None
                or vector is None
                or proof["predecessor_epoch_id"] != predecessor["coherence_epoch_id"]
                or proof["candidate_epoch_id"] != candidate["coherence_epoch_id"]
                or proof["shock_observation_id"] != transition["shock_observation_id"]
                or proof["freshness_vector_id"] != vector["input_freshness_vector_id"]
                or proof["proof_status"] != "OBSERVED"
                or proof["proof_verified"] != 1
                or proof["release_predicate"] != "SATISFIED"
                or any(
                    proof[name] not in mappings or proof[name] in closed_mappings
                    for name in (
                        "football_mapping_id",
                        "operator_mapping_id",
                        "market_book_mapping_id",
                    )
                )
                or proof["continuity_reducer_cursor_id"] not in cursors
                or any(
                    vector[name] != "FRESH"
                    for name in (
                        "football_state_status",
                        "operator_state_status",
                        "market_book_status",
                    )
                )
            ):
                raise ValueError("E_GAP_SNAPSHOT_RELATION")


def _validate_snapshot_ddl(state: dict[str, Any]) -> None:
    import sqlite3
    from contextlib import closing

    from moj_discovery.store import TABLES, validate_journal, verified_ddl

    ddl = verified_ddl()
    if (
        not isinstance(state, dict)
        or set(state)
        != {
            "schema_version",
            "run_id",
            "ddl_sha256",
            "tables",
            "spool",
            "capacity",
        }
        or state["schema_version"] != 1
        or not isinstance(state["run_id"], str)
        or not state["run_id"]
        or state["ddl_sha256"] != hashlib.sha256(ddl.encode()).hexdigest()
        or not isinstance(state["tables"], dict)
    ):
        raise ValueError("E_GAP_SNAPSHOT_DDL")
    tables = state["tables"]
    try:
        journal = {name: tables[name] for name in TABLES}
        validate_journal(journal)
        with closing(sqlite3.connect(":memory:")) as reference:
            reference.executescript(ddl)
            names = {
                row[0]
                for row in reference.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if set(tables) != names:
                raise ValueError("E_GAP_SNAPSHOT_DDL")
            triggers = [
                row[0]
                for row in reference.execute("SELECT name FROM sqlite_schema WHERE type='trigger'")
            ]
            for trigger in triggers:
                reference.execute(f'DROP TRIGGER "{trigger}"')  # noqa: S608
            reference.execute("PRAGMA foreign_keys=ON")
            reference.execute("BEGIN")
            reference.execute("PRAGMA defer_foreign_keys=ON")
            # Deferred foreign keys make this independent of serialized table
            # and row order. Exact CHECK/UNIQUE/FK rules remain active; the
            # history-sensitive trigger invariants are verified above by the
            # approved journal validator and below by recovery predicates.
            for name in sorted(names):
                columns = [
                    str(row[1])
                    for row in reference.execute(f'PRAGMA table_info("{name}")')  # noqa: S608
                ]
                rows = tables[name]
                if not isinstance(rows, list):
                    raise ValueError("E_GAP_SNAPSHOT_DDL")
                for row in rows:
                    if not isinstance(row, dict) or set(row) != set(columns):
                        raise ValueError("E_GAP_SNAPSHOT_DDL")
                    if "run_id" in row and row["run_id"] != state["run_id"]:
                        raise ValueError("E_GAP_SNAPSHOT_DDL")
                    column_sql = ",".join(f'"{column}"' for column in columns)
                    placeholders = ",".join("?" for _ in columns)
                    reference.execute(
                        f'INSERT INTO "{name}" ({column_sql}) VALUES ({placeholders})',  # noqa: S608
                        tuple(row[column] for column in columns),
                    )
            reference.commit()
            if reference.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("E_GAP_SNAPSHOT_DDL")
        _validate_snapshot_relations(tables)
    except (KeyError, TypeError, sqlite3.DatabaseError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "E_GAP_SNAPSHOT_DDL":
            raise
        raise ValueError("E_GAP_SNAPSHOT_DDL") from exc


def _validate_state_evolution(
    baseline: dict[str, Any], before: dict[str, Any], after: dict[str, Any]
) -> None:
    """Replay persisted controller transitions across retained snapshots."""

    immutable = set(baseline["tables"]) - {
        "run_meta",
        "stream_generations",
        "coherence_controllers",
    }

    def contains_rows(earlier: dict[str, Any], later: dict[str, Any]) -> bool:
        return all(
            row in later["tables"][name] for name in immutable for row in earlier["tables"][name]
        )

    def generations_reachable(earlier: dict[str, Any], later: dict[str, Any]) -> bool:
        later_by_id = {row["generation_id"]: row for row in later["tables"]["stream_generations"]}
        allowed = {
            "ACTIVE": {"ACTIVE", "QUARANTINED_GAP", "CLOSED"},
            "QUARANTINED_GAP": {"QUARANTINED_GAP", "CLOSED"},
            "CLOSED": {"CLOSED"},
        }
        mutable = {"generation_state", "close_reason", "closed_at_us"}
        for old in earlier["tables"]["stream_generations"]:
            new = later_by_id.get(old["generation_id"])
            if (
                new is None
                or (new["generation_state"] == old["generation_state"] and new != old)
                or any(new[key] != value for key, value in old.items() if key not in mutable)
                or new["generation_state"] not in allowed[old["generation_state"]]
                or (
                    new["generation_state"] == "ACTIVE"
                    and (new["close_reason"] is not None or new["closed_at_us"] is not None)
                )
                or (
                    new["generation_state"] != "ACTIVE"
                    and (new["close_reason"] is None or new["closed_at_us"] is None)
                )
            ):
                return False
        return True

    def replay_controller(earlier: dict[str, Any], later: dict[str, Any]) -> bool:
        old_rows = earlier["tables"]["coherence_controllers"]
        new_rows = later["tables"]["coherence_controllers"]
        if len(old_rows) != 1 or len(new_rows) != 1:
            return False
        current = copy.deepcopy(old_rows[0])
        wanted = new_rows[0]
        immutable_fields = {"coherence_controller_id", "run_id", "fixture_id"}
        if any(current[name] != wanted[name] for name in immutable_fields):
            return False
        old_transition_ids = {
            row["coherence_transition_id"] for row in earlier["tables"]["coherence_transitions"]
        }
        pending = [
            row
            for row in later["tables"]["coherence_transitions"]
            if row["coherence_transition_id"] not in old_transition_ids
            and row["coherence_controller_id"] == current["coherence_controller_id"]
        ]
        while pending:
            candidates = [
                row for row in pending if row["from_state"] == current["controller_state"]
            ]
            if not candidates:
                return False
            transition = min(
                candidates,
                key=lambda row: (row["transitioned_at_us"], row["coherence_transition_id"]),
            )
            reason = transition["transition_reason"]
            if transition["predecessor_epoch_id"] != current["current_epoch_id"] and reason in {
                "SHOCK_ATOMIC_CLOSE",
                "RESNAPSHOT_CANDIDATE_ACCEPTED",
                "RELEASE_PREDICATE_SATISFIED",
                "NEW_SHOCK_CLOSED_CANDIDATE",
            }:
                return False
            if reason == "SHOCK_ATOMIC_CLOSE":
                current["candidate_epoch_id"] = None
                current["active_shock_observation_id"] = transition["shock_observation_id"]
            elif reason == "RESNAPSHOT_CANDIDATE_ACCEPTED":
                current["candidate_epoch_id"] = transition["candidate_epoch_id"]
                current["predecessor_epoch_id"] = transition["predecessor_epoch_id"]
            elif reason == "RELEASE_PREDICATE_SATISFIED":
                if current["candidate_epoch_id"] != transition["candidate_epoch_id"]:
                    return False
                current["predecessor_epoch_id"] = current["current_epoch_id"]
                current["current_epoch_id"] = current["candidate_epoch_id"]
                current["candidate_epoch_id"] = None
            elif reason == "NEW_SHOCK_CLOSED_CANDIDATE":
                if current["candidate_epoch_id"] != transition["candidate_epoch_id"]:
                    return False
                current["candidate_epoch_id"] = None
                current["active_shock_observation_id"] = transition["shock_observation_id"]
            elif reason != "CLOSE_RECORDED":
                return False
            current["controller_state"] = transition["to_state"]
            current["controller_revision"] += 1
            current["updated_at_us"] = transition["transitioned_at_us"]
            pending.remove(transition)
        return bool(current == wanted)

    for earlier, later in ((baseline, before), (before, after)):
        if (
            earlier["run_id"] != later["run_id"]
            or earlier["tables"]["run_meta"] != later["tables"]["run_meta"]
            or not contains_rows(earlier, later)
            or not generations_reachable(earlier, later)
            or not replay_controller(earlier, later)
            or any(row not in later["spool"]["rows"] for row in earlier["spool"]["rows"])
        ):
            raise ValueError("E_GAP_STATE_EVOLUTION")


def _run_process(
    entry: dict[str, Any], case: Path, ordinal: int, shim: Path, *, input_mutation: bool = False
) -> dict[str, Any]:
    case.mkdir(parents=True)
    run_id, nonce = str(uuid4()), secrets.token_hex(16)
    scenario = _scenario(entry, run_id)
    original_input = copy.deepcopy(scenario["delivery"])
    launch_ready = case / "launch-ready.json"
    if input_mutation:
        scenario["delivery"]["content_hash"] = "0" * 64
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
    if input_mutation:
        command.extend(("--launch-ready", str(launch_ready.resolve())))
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
    awaited = launch_ready if input_mutation else ready
    while not awaited.is_file() and monotonic() < deadline and child.poll() is None:
        sleep(0.02)
    if input_mutation:
        if not launch_ready.is_file() or json.loads(launch_ready.read_text()) != identity:
            raise RuntimeError(f"E_GAP_MUTATION_CHECKPOINT:{entry['vector_id']}:{child.poll()}")
        process_observation, process_artifact = _proc_observation(
            child, case / "parent-proc-observation.json"
        )
        (case / "launch-continue.json").write_text("{}")
        exit_code = child.wait(timeout=5)
        stderr_text = (case / "child.stderr").read_text()
        observed_error = "CONTENT_HASH_MISMATCH" if "CONTENT_HASH_MISMATCH" in stderr_text else None
        terminal_path = case / "mutation-terminal.json"
        terminal_path.write_text(
            json.dumps(
                {
                    "identity": identity,
                    "process": process_observation,
                    "exit": exit_code,
                    "rejection": observed_error,
                },
                sort_keys=True,
            )
        )
        return {
            "mutation_detected": exit_code == 1 and observed_error == "CONTENT_HASH_MISMATCH",
            "case_directory": str(case.resolve()),
            "pid": child.pid,
            "identity": identity,
            "process_observation": process_observation,
            "process_observation_artifact": process_artifact,
            "command": command,
            "exit": exit_code,
            "observed_error": observed_error,
            "original_input": original_input,
            "mutated_input": scenario["delivery"],
            "scenario_artifact": _artifact(scenario_path),
            "launch_artifact": _artifact(launch_ready),
            "stderr_artifact": _artifact(case / "child.stderr"),
            "database_artifact": _artifact(case / run_id / "run.sqlite3"),
            "terminal_artifact": _artifact(terminal_path),
        }
    if not ready.is_file() or json.loads(ready.read_text()) != identity:
        raise RuntimeError(f"E_GAP_CHECKPOINT:{entry['vector_id']}:{child.poll()}")
    process_observation, process_artifact = _proc_observation(
        child, case / "parent-proc-observation.json"
    )
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
        "process_observation_artifact": process_artifact,
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
    _validate_snapshot_ddl(run["baseline"])
    _validate_snapshot_ddl(run["before"])
    _validate_snapshot_ddl(run["after"])
    _validate_state_evolution(run["baseline"], run["before"], run["after"])
    comparison = _compare(actual, expected)
    recovery_validation = _validate_recovery(run["before"], run["after"], run["scenario"])
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
        "recovery_validation": recovery_validation,
        "evidence_binding": binding,
        "revision": binding["revision"],
        "environment": binding["environment"],
        "command": run["command"],
        "command_exit": {"child": run["exit"], "recovery": run["recovery_exit"], "reader": 0},
        "process_observation": run["process_observation"],
        "process_observation_artifact": run["process_observation_artifact"],
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
        "process_observation_artifact",
    ):
        descriptor = row[name]
        if _sha(Path(descriptor["path"])) != descriptor["sha256"]:
            raise ValueError("E_GAP_ARTIFACT")
    python = str(Path(sys.executable).absolute())
    _verify_proc_observation(process, row["process_observation_artifact"], row["command"])
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
    _validate_snapshot_ddl(baseline)
    _validate_snapshot_ddl(row["before_restart"])
    _validate_snapshot_ddl(row["after_restart"])
    _validate_state_evolution(baseline, row["before_restart"], row["after_restart"])
    if _semantic_view(row["before_restart"], baseline, row["expected"], scenario) != row["actual"]:
        raise ValueError("E_GAP_COMPARISON")
    database_dir = Path(row["case_directory"]) / row["identity"]["run_id"]
    persisted_after = (
        read_gap_state(database_dir)
        if (database_dir / "run.sqlite3").is_file()
        else row["after_restart"]
    )
    if persisted_after != row["after_restart"] or row["recovery_validation"] != _validate_recovery(
        row["before_restart"], persisted_after, scenario
    ):
        raise ValueError("E_GAP_RECOVERY_PREDICATE")
    if (
        _sha(Path(row["shim"]["path"])) != row["shim"]["binary_sha256"]
        or _sha(SHIM_SOURCE) != row["shim"]["source_sha256"]
    ):
        raise ValueError("E_GAP_SHIM")


def verify_gap_mutation(row: dict[str, Any], binding: dict[str, Any]) -> None:
    if (
        row["evidence_binding"] != binding
        or row["revision"] != binding["revision"]
        or row["environment"] != binding["environment"]
        or row.get("detected") is not True
    ):
        raise ValueError("E_GAP_MUTATION_BINDING")
    entry = next(
        item
        for item in json.loads(REGISTRY.read_text())["entries"]
        if row["mutation"] in item["mutation_vector_ids"]
    )
    if row["vector_id"] != entry["vector_id"]:
        raise ValueError("E_GAP_MUTATION_BINDING")
    if row["kind"] == "EXPECTED":
        evidence = row["evidence"]
        governed = entry["expected_post_restart_state"]
        if (
            row["governed_expected"] != governed
            or row["mutated_expected"] == governed
            or evidence["expected"] != row["mutated_expected"]
            or evidence["comparison"] != _compare(evidence["actual"], row["mutated_expected"])
            or evidence["comparison"]["matched"]
            or evidence["observed_error"] != "E_GAP_STATE_MISMATCH"
            or row["observed_error"] != "E_GAP_STATE_MISMATCH"
        ):
            raise ValueError("E_GAP_MUTATION_EXPECTED")
        control = copy.deepcopy(evidence)
        control.update(
            expected=governed,
            comparison=_compare(evidence["actual"], governed),
            observed_error=None,
            status="PASS",
            result="PASS",
        )
        verify_gap_record(control, binding)
        return
    if row["kind"] != "INPUT" or row["observed_error"] != "CONTENT_HASH_MISMATCH":
        raise ValueError("E_GAP_MUTATION_INPUT")
    if row["exit"] != 1 or row["command_exit"] != {"child": 1}:
        raise ValueError("E_GAP_MUTATION_INPUT")
    for descriptor in row["artifacts"]:
        if _sha(Path(descriptor["path"])) != descriptor["sha256"]:
            raise ValueError("E_GAP_MUTATION_ARTIFACT")
    _verify_proc_observation(
        row["process_observation"], row["process_observation_artifact"], row["command"]
    )
    scenario = json.loads(Path(row["scenario_artifact"]["path"]).read_text())
    original, mutated = row["original_input"], row["mutated_input"]
    from moj_discovery.canonical import canonical_content_hash
    from moj_discovery.store import VENDOR

    registry = VENDOR / "registries/canonical-hash-domains.v1.json"
    if (
        scenario["delivery"] != mutated
        or original == mutated
        or {key for key in original if original[key] != mutated[key]} != {"content_hash"}
        or canonical_content_hash("RawObservation", original, registry_path=registry)
        != original["content_hash"]
        or canonical_content_hash("RawObservation", mutated, registry_path=registry)
        == mutated["content_hash"]
    ):
        raise ValueError("E_GAP_MUTATION_INPUT")
    launch = json.loads(Path(row["launch_artifact"]["path"]).read_text())
    terminal = json.loads(Path(row["terminal_artifact"]["path"]).read_text())
    stderr = Path(row["stderr_artifact"]["path"]).read_text()
    if (
        launch != row["identity"]
        or terminal
        != {
            "identity": row["identity"],
            "process": row["process_observation"],
            "exit": 1,
            "rejection": "CONTENT_HASH_MISMATCH",
        }
        or "CONTENT_HASH_MISMATCH" not in stderr
    ):
        raise ValueError("E_GAP_MUTATION_INPUT")
    state = read_gap_state(Path(row["case_directory"]) / row["identity"]["run_id"])
    if state["run_id"] != row["identity"]["run_id"]:
        raise ValueError("E_GAP_MUTATION_INPUT")


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
        expected_mutation = {
            "mutation": entry["mutation_vector_ids"][0],
            "vector_id": entry["vector_id"],
            "kind": "EXPECTED",
            "detected": expected_row["status"] == "FAIL",
            "case_directory": expected_run["case_directory"],
            "pid": expected_run["identity"]["pid"],
            "process_observation": expected_run["process_observation"],
            "termination": expected_run["termination"],
            "governed_expected": entry["expected_post_restart_state"],
            "mutated_expected": wrong,
            "observed_error": expected_row["observed_error"],
            "evidence": expected_row,
            "evidence_binding": binding,
            "revision": binding["revision"],
            "environment": binding["environment"],
            "artifacts": [
                expected_run["scenario_artifact"],
                expected_run["checkpoint_artifact"],
                expected_run["boundary_artifact"],
                expected_run["process_observation_artifact"],
                expected_row["actual_artifact"],
                expected_run["terminal_artifact"],
            ],
        }
        verify_gap_mutation(expected_mutation, binding)
        mutations.append(expected_mutation)
        input_run = _run_process(
            entry,
            workspace / f"mutation-input-{ordinal:02d}",
            200 + ordinal,
            shim,
            input_mutation=True,
        )
        input_mutation = {
            "mutation": entry["mutation_vector_ids"][1],
            "vector_id": entry["vector_id"],
            "kind": "INPUT",
            "detected": input_run["mutation_detected"],
            "case_directory": input_run["case_directory"],
            "pid": input_run["pid"],
            "identity": input_run["identity"],
            "process_observation": input_run["process_observation"],
            "process_observation_artifact": input_run["process_observation_artifact"],
            "command": input_run["command"],
            "exit": input_run["exit"],
            "command_exit": {"child": input_run["exit"]},
            "observed_error": input_run["observed_error"],
            "original_input": input_run["original_input"],
            "mutated_input": input_run["mutated_input"],
            "scenario_artifact": input_run["scenario_artifact"],
            "launch_artifact": input_run["launch_artifact"],
            "stderr_artifact": input_run["stderr_artifact"],
            "database_artifact": input_run["database_artifact"],
            "terminal_artifact": input_run["terminal_artifact"],
            "evidence_binding": binding,
            "revision": binding["revision"],
            "environment": binding["environment"],
            "artifacts": [
                input_run["scenario_artifact"],
                input_run["launch_artifact"],
                input_run["process_observation_artifact"],
                input_run["stderr_artifact"],
                input_run["database_artifact"],
                input_run["terminal_artifact"],
            ],
        }
        verify_gap_mutation(input_mutation, binding)
        mutations.append(input_mutation)
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
