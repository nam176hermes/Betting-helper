"""Backend-only evidence for inherited crash IDs; missing full contracts stay HOLD."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from moj_discovery.schema_registry import validate_artifact
from moj_discovery.store import VENDOR
from tools.inspect_restart_state import execute_crash_matrix
from tools.loopback_ack_crash_child import BEFORE_STATEMENT, position
from tools.restart_state_reader import read_restart_state

PHASES = {
    "SEND-01": "after_receive_before_begin",
    "SQL-01": "after_raw_insert",
    "SQL-02": "after_application_insert",
    "SQL-03": "after_revision_insert",
    "SQL-04": "after_cursor_insert",
    "SQL-05": "after_outbox_insert",
    "SQL-07": "after_commit_before_send",
    "ACK-06": "after_duplicate_ack",
    "GAP-01": "after_gap_insert",
    "GAP-02": "after_shock_insert",
    "GAP-03": "after_coherence_transition",
    "GAP-04": "after_controller_close",
    "GAP-05": "after_epoch_binding",
    "GAP-06": "after_predecessor_close",
    "GAP-07": "after_generation_transition",
    "GAP-08": "after_successor_insert",
    "GAP-10": "after_gap_commit",
    "LATE-01": "after_late_rejection",
}
CHAIN = ("raw_commits", "application_records", "derived_revisions", "reducer_cursors", "ack_outbox")
GAP_INSERTS = (
    "gap_records",
    "shock_observations",
    "coherence_transitions",
    "gap_epoch_bindings",
    "generation_transitions",
    "stream_generations",
)
H0 = "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c"
CHILD = [sys.executable, "-m", "tools.loopback_ack_crash_child"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Fixed observed projection; no vector/checkpoint/oracle data is consulted."""
    tables = state["tables"]
    return {
        "counts": {name: len(rows) for name, rows in tables.items()},
        "raw": [
            [row["sequence"], row["raw_observation_content_hash"], row["cursor_hash"]]
            for row in tables["raw_commits"]
        ],
        "generations": sorted(
            [[row["generation"], row["generation_state"]] for row in tables["stream_generations"]]
        ),
        "controllers": [
            [row["controller_state"], row["controller_revision"]]
            for row in tables["coherence_controllers"]
        ],
        "gap_ranges": [
            [row["missing_from_sequence"], row["missing_to_sequence"], row["detected_sequence"]]
            for row in tables["gap_records"]
        ],
        "ack_cursors": tables["ack_cursors"],
    }


def _oracle(base: dict[str, Any], committed: bool, gap: bool) -> dict[str, Any]:
    """Parent-only requirement oracle. Compute H1 independently from the published preimage."""
    step = {
        "schema_version": "cursor-step/v1",
        "discovery_run_id": base["discovery_run_id"],
        "browser_run_id": base["context"]["browser_run_id"],
        "producer_id": base["clock_context"]["clock_domain_id"],
        "stream_id": base["stream_id"],
        "generation": "0",
        "sequence": "1",
        "raw_observation_hash": base["content_hash"],
        "previous_cursor_hash": H0,
    }
    cursor = hashlib.sha256(
        b"HYBRID-DISCOVERY/v6.2/CursorStep/v1\0"
        + json.dumps(step, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    counts = dict.fromkeys(
        (
            *CHAIN,
            "raw_conflicts",
            "ack_cursors",
            "gap_records",
            "gap_epoch_bindings",
            "generation_transitions",
            "coherence_transitions",
            "shock_observations",
        ),
        0,
    )
    counts.update(run_meta=1, stream_generations=1, coherence_epochs=1, coherence_controllers=1)
    if committed:
        counts.update(dict.fromkeys(CHAIN, 1))
    if gap:
        counts.update(dict.fromkeys(GAP_INSERTS, 1))
        counts["stream_generations"] = 2
    return {
        "counts": counts,
        "raw": [[1, base["content_hash"], cursor]] if committed else [],
        "generations": [[0, "QUARANTINED_GAP"], [1, "ACTIVE"]] if gap else [[0, "ACTIVE"]],
        "controllers": [["SHOCKED_CLOSED", 1]] if gap else [["OPEN", 0]],
        "gap_ranges": [[2, 2, 3]] if gap else [],
        "ack_cursors": [],
    }


def run_backend_case(
    entry: dict[str, Any],
    observation: dict[str, Any],
    workspace: Path,
    *,
    command_prefix: list[str] | None = None,
) -> dict[str, Any]:
    key = "-".join(entry["vector_id"].split("-")[:2])
    if key not in PHASES:
        raise ValueError("E_CRASH_BOUNDARY_NOT_IMPLEMENTED:" + key)
    registry = json.loads((VENDOR / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    matches = [row for row in registry if row["vector_id"] == entry["vector_id"]]
    if len(matches) != 1 or any(
        entry[field] != matches[0][field]
        for field in ("crash_checkpoint", "harness", "source_boundary", "kill_action")
    ):
        raise ValueError("E_CRASH_REGISTERED_BOUNDARY_MISMATCH")
    validate_artifact(
        observation, "raw-observation.schema.json", bootstrap_only=True, vendor=VENDOR
    )
    if observation["generation"] != "0" or observation["sequence"] != "1":
        raise ValueError("E_CRASH_SCENARIO_POSITION")
    phase = PHASES[key]
    is_gap = key.startswith("GAP")
    late = key == "LATE-01"
    base_committed = is_gap or late or key == "ACK-06"
    committed = base_committed or key == "SQL-07"
    gap_committed = key == "GAP-10" or late
    scenario: dict[str, Any] = {
        "phase": phase,
        "observation": observation,
        "setup_deliveries": (
            [observation, position(observation, 3)]
            if late
            else [observation]
            if base_committed
            else []
        ),
        "delivery": position(observation, 2 if late else 3) if is_gap or late else observation,
    }
    expected = _oracle(observation, committed, gap_committed)
    # Preserve inherited parent expectations for every SQL delta we actually cover.
    # Other vector fields (browser ACK/spool/release) remain unqualified below.
    if not late:
        for name, delta in entry["expected_post_restart_state"].get("sql_row_deltas", {}).items():
            if name in expected["counts"]:
                baseline = int(name in CHAIN and base_committed)
                baseline += int(
                    name
                    in {
                        "run_meta",
                        "coherence_epochs",
                        "coherence_controllers",
                        "stream_generations",
                    }
                )
                expected["counts"][name] = baseline + delta
    recovered_gap = is_gap or late
    expected_replay = (
        "E_INGEST_GENERATION_CLOSED" if gap_committed else "E_INGEST_GAP" if is_gap else "ACK"
    )
    expected_state = {
        "before": expected,
        "after": _oracle(observation, True, recovered_gap),
        "replay": expected_replay,
    }

    def prepare(case: Path) -> None:
        (case / "scenario.json").write_text(json.dumps(scenario, sort_keys=True))

    def boundary(case: Path, identity: dict[str, object]) -> None:
        path = case / "boundary.json"
        if not path.is_file():
            raise RuntimeError("E_CRASH_BOUNDARY_MISSING")
        witness = json.loads(path.read_text())
        if (
            witness["identity"] != identity
            or witness["phase"] != phase
            or witness["received_observation_hash"] != scenario["delivery"]["content_hash"]
            or witness["transport_address"][0] != "127.0.0.1"
            or witness["in_transaction"] != (phase in BEFORE_STATEMENT)
        ):
            raise RuntimeError("E_CRASH_BOUNDARY_MISMATCH")
        tables = witness["tables"]
        if phase in BEFORE_STATEMENT and witness["ingest_result"] is not None:
            raise RuntimeError("E_CRASH_ACK_BEFORE_COMMIT")
        if key in {"GAP-10", "LATE-01"} and witness["ingest_result"] != {
            "error": "E_INGEST_GAP" if key == "GAP-10" else "E_INGEST_GENERATION_CLOSED"
        }:
            raise RuntimeError("E_CRASH_INGEST_RESULT")
        if key == "SQL-07" and witness["ingest_result"] != {"ack": tables["ack_outbox"][0]}:
            raise RuntimeError("E_CRASH_INGEST_RESULT")
        if key.startswith("SQL") and key != "SQL-07":
            written = int(key[-2:])
            if [len(tables[name]) for name in CHAIN] != [int(i < written) for i in range(5)]:
                raise RuntimeError("E_CRASH_BOUNDARY_TRANSACTION_STATE")
        if is_gap and key != "GAP-10":
            stage = int(key[-2:])
            expected_counts = [int(stage >= n) for n in (1, 2, 3, 5, 7, 8)]
            expected_counts[-1] += 1  # Existing predecessor generation.
            controller = "SHOCKED_CLOSED" if stage >= 4 else "OPEN"
            generation = "QUARANTINED_GAP" if stage >= 6 else "ACTIVE"
            if (
                [len(tables[name]) for name in GAP_INSERTS] != expected_counts
                or tables["coherence_controllers"][0]["controller_state"] != controller
                or tables["stream_generations"][0]["generation_state"] != generation
            ):
                raise RuntimeError("E_CRASH_BOUNDARY_TRANSACTION_STATE")
        if key == "ACK-06":
            ack = witness["wire_ack"]
            if not isinstance(ack, dict) or ack.get("ack") != tables["ack_outbox"][0]:
                raise RuntimeError("E_CRASH_WIRE_ACK")

    def recover(case: Path, *, replay: bool = False) -> None:
        suffix = "replay" if replay else "reopen"
        with (
            (case / f"{suffix}.stdout").open("wb") as stdout,
            (case / f"{suffix}.stderr").open("wb") as stderr,
        ):
            subprocess.run(  # noqa: S603 -- fixed local child and owned temporary directory
                [*CHILD, "--recover", str(case), *(["--replay"] if replay else [])],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                timeout=10,
                stdout=stdout,
                stderr=stderr,
            )

    def actual(case: Path) -> dict[str, Any]:
        run_dir = case / observation["discovery_run_id"]
        before = read_restart_state(run_dir)
        (case / "actual-state.json").write_text(json.dumps(before, sort_keys=True))
        recover(case, replay=True)
        recovery = json.loads((case / "recovery.json").read_text())
        after = read_restart_state(run_dir)
        if after != recovery["after"]:
            raise ValueError("E_CRASH_RECOVERY_OBSERVATION")
        replay = recovery["replay"]
        if "ack" in replay and replay["ack"] != after["tables"]["ack_outbox"][0]:
            raise ValueError("E_CRASH_RECOVERY_ACK")
        return {
            "before": _snapshot(before),
            "after": _snapshot(after),
            "replay": replay.get("error", "ACK"),
        }

    child_module = {
        "SQLITE_TRANSACTION": "tools.sqlite_crash_child",
        "GAP_GENERATION_COHERENCE": "tools.gap_coherence_crash_child",
        "LOOPBACK_ACK": "tools.loopback_ack_crash_child",
    }[entry["harness"]]
    result = execute_crash_matrix(
        [{**entry, "expected_post_restart_state": expected_state}],
        [sys.executable, "-m", child_module] if command_prefix is None else command_prefix,
        workspace,
        state_reader=actual,
        prepare_case=prepare,
        recover_case=recover,
        validate_boundary=boundary,
    )
    for row in cast(list[dict[str, Any]], result["records"]):
        case = Path(row["case_directory"])
        root = Path(__file__).resolve().parents[1]
        row.update(
            input_sha256=_sha(case / "scenario.json"),
            actual_state_sha256=_sha(case / "actual-state.json"),
            actual_state_artifact=str(case / "actual-state.json"),
            recovery_sha256=_sha(case / "recovery.json"),
            boundary_sha256=_sha(case / "boundary.json"),
            expected_sha256=hashlib.sha256(
                json.dumps(expected_state, sort_keys=True).encode()
            ).hexdigest(),
            execution_kind="BACKEND_ONLY_PROCESS_CRASH",
            phase=phase,
            comparison_state_sha256=_sha(case / "comparison-state.json"),
            code_revision=subprocess.run(  # noqa: S603 -- read-only local Git identity
                ["git", "rev-parse", "HEAD"],  # noqa: S607 -- existing repository Git executable
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            source_sha256={
                name: _sha(root / name)
                for name in (
                    "tools/inspect_restart_state.py",
                    "tools/loopback_ack_crash_child.py",
                    "tools/run_loopback_ack_crash_matrix.py",
                    "tools/restart_state_reader.py",
                    "tools/sqlite_crash_child.py",
                    "tools/gap_coherence_crash_child.py",
                    "src/moj_discovery/store.py",
                    "src/moj_discovery/ingest.py",
                    "src/moj_discovery/canonical.py",
                    "schema-lock.json",
                    "uv.lock",
                    "vendor/hybrid-discovery-v6.3.6/sql/discovery-store-v1.sql",
                )
            },
            environment={"platform": platform.platform(), "python": sys.version},
        )
        (case / "result.json").write_text(json.dumps(row, sort_keys=True))
    result.update(scope="BACKEND_ONLY", legacy_full_qualification="HOLD")
    return result


def run_family(
    pack: Path,
    workspace: Path,
    family: str,
    observation_input: dict[str, Any] | None,
) -> dict[str, Any]:
    entries = json.loads((pack / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    rows = []
    for entry in entries:
        if entry["harness"] != family:
            continue
        key = "-".join(entry["vector_id"].split("-")[:2])
        row: dict[str, Any] = {
            "vector_id": entry["vector_id"],
            "status": "NOT_IMPLEMENTED",
            "reason": "FULL_BROWSER_OR_LIFECYCLE_CONTRACT_MISSING",
        }
        if family == "WHOLE_RUN_DESTRUCTION":
            row["reason"] = "DESTRUCTION_OWNER_AND_AUTHORITY_NOT_IMPLEMENTED"
        elif family == "CHROME_INDEXEDDB" or key in {"ACK-01", "ACK-02", "ACK-03"}:
            row["reason"] = "REAL_EXTENSION_ACK_OR_SPOOL_NOT_IMPLEMENTED"
        elif key in {"ACK-04", "ACK-05"}:
            row["reason"] = "BACKEND_CONFIRMATION_OWNER_NOT_IMPLEMENTED"
        elif key == "CONFLICT-01":
            row["reason"] = "HOLD_CONTRACT:CONFLICT-01_SUCCESSOR"
        elif key in {"SQL-06", "GAP-09"}:
            row["reason"] = "DURING_COMMIT_CHECKPOINT_NOT_EXPOSED"
        elif key == "LATE-01":
            row["reason"] = "LATE_HISTORY_REPAIR_NOT_IMPLEMENTED"
        if key in PHASES and observation_input is not None:
            result = run_backend_case(entry, observation_input, workspace)
            row.update(scoped_result=result["result"], scoped_evidence=result["records"][0])
        rows.append(row)
    return {
        "result": "HOLD",
        "legacy_full_qualification": "HOLD",
        "records": rows,
        "executed_vector_ids": [],
        "killed_child_count": sum("scoped_result" in row for row in rows),
    }


def run_loopback_ack_crash_matrix(
    pack: Path,
    workspace: Path,
    *,
    observation_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_family(pack, workspace, "LOOPBACK_ACK", observation_input)
