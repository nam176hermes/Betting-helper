"""Backend-only evidence for inherited crash IDs; missing full contracts stay HOLD."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from secrets import token_hex
from time import monotonic, sleep
from typing import Any, cast
from uuid import uuid4

from moj_discovery.schema_registry import validate_artifact
from moj_discovery.store import TABLES, VENDOR
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
    "SQL-06": "during_commit",
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


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trusted_command() -> list[str]:
    return [
        str(Path(sys.executable).absolute()),
        "-I",
        str(Path(__file__).with_name("loopback_ack_crash_child.py").resolve()),
    ]


def _launch_provenance(
    command: list[str], *, trusted_command: list[str] | None = None
) -> dict[str, Any]:
    if command != (trusted_command or _trusted_command()):
        raise ValueError("E_CRASH_CHILD_PROVENANCE")
    return {
        "command_prefix": command,
        "executable": {
            "path": command[0],
            "resolved_path": str(Path(command[0]).resolve()),
            "sha256": _sha(Path(command[0])),
        },
        "entrypoint": {"path": command[2], "sha256": _sha(Path(command[2]))},
    }


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
    trusted_command: list[str] | None = None,
    reader_command: list[str] | None = None,
) -> dict[str, Any]:
    command = _trusted_command() if command_prefix is None else list(command_prefix)
    provenance = _launch_provenance(
        command, trusted_command=trusted_command
    )  # Reject substitutions before provision/launch.
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
    expected_state: dict[str, Any]
    if key == "SQL-06":
        expected_state = {
            "allowed_atomic_outcomes": [
                {
                    "before": _oracle(observation, state, False),
                    "after": _oracle(observation, True, False),
                    "replay": "ACK",
                }
                for state in (False, True)
            ]
        }
    else:
        expected_state = {
            "before": expected,
            "after": _oracle(observation, True, recovered_gap),
            "replay": expected_replay,
        }

    def prepare(case: Path) -> None:
        (case / "scenario.json").write_text(json.dumps(scenario, sort_keys=True))
        (case / "launch-input.json").write_text(
            json.dumps(
                {
                    **provenance,
                    "scenario_sha256": _sha(case / "scenario.json"),
                },
                sort_keys=True,
            )
        )

    def boundary(case: Path, identity: dict[str, object]) -> None:
        if _launch_provenance(command, trusted_command=trusted_command) != provenance:
            raise ValueError("E_CRASH_CHILD_PROVENANCE")
        path = case / "boundary.json"
        if not path.is_file():
            raise RuntimeError("E_CRASH_BOUNDARY_MISSING")
        witness = json.loads(path.read_text())
        if key == "SQL-06":
            expected_fields = {
                "identity",
                "phase",
                "commit_armed",
                "operation",
                "target",
                "sqlite_path",
            }
            if (
                not isinstance(witness, dict)
                or set(witness) != expected_fields
                or witness["identity"] != identity
                or witness["phase"] != "during_commit"
                or witness["commit_armed"] is not True
                or witness["operation"] not in {"fsync", "fdatasync"}
                or witness["target"] not in {"rollback_journal", "database"}
                or not str(witness["sqlite_path"]).endswith(
                    ("run.sqlite3-journal", "run.sqlite3")
                )
            ):
                raise RuntimeError("E_CRASH_COMMIT_IO_WITNESS")
            (case / "prerequisite-state.json").write_text(
                json.dumps(witness, sort_keys=True)
            )
            return
        if (
            not isinstance(witness, dict)
            or set(witness)
            != {
                "identity",
                "phase",
                "received_observation_hash",
                "transport_address",
                "in_transaction",
                "tables",
                "ingest_result",
                "wire_ack",
            }
            or not isinstance(witness["tables"], dict)
            or set(witness["tables"]) != set(TABLES)
            or type(witness["in_transaction"]) is not bool
            or not isinstance(witness["transport_address"], list)
            or len(witness["transport_address"]) != 2
            or any(
                not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                for rows in witness["tables"].values()
            )
        ):
            raise RuntimeError("E_CRASH_BOUNDARY_SCHEMA")
        if (
            witness["identity"] != identity
            or witness["phase"] != phase
            or witness["received_observation_hash"] != scenario["delivery"]["content_hash"]
            or witness["transport_address"][0] != "127.0.0.1"
            or witness["in_transaction"] != (phase in BEFORE_STATEMENT)
        ):
            raise RuntimeError("E_CRASH_BOUNDARY_MISMATCH")
        tables = witness["tables"]
        # Separate reads see committed prerequisites, never the pending INSERTs.
        # The uncommitted witness belongs to the pinned child instrumentation.
        durable = read_restart_state(case / observation["discovery_run_id"])
        database = case / observation["discovery_run_id"] / "run.sqlite3"
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            for name in TABLES:
                columns = {
                    item[0]
                    for item in db.execute(
                        f"SELECT * FROM {name} LIMIT 0"  # noqa: S608 -- fixed verified table allowlist
                    ).description
                }
                if any(set(row) != columns for row in tables[name]):
                    raise RuntimeError("E_CRASH_BOUNDARY_SCHEMA")
        baseline = (
            _oracle(observation, base_committed, late)
            if phase in BEFORE_STATEMENT
            else _oracle(observation, committed, gap_committed)
        )
        if _snapshot(durable) != baseline:
            raise RuntimeError("E_CRASH_BOUNDARY_DURABLE_STATE")
        (case / "prerequisite-state.json").write_text(json.dumps(durable, sort_keys=True))
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

    recovery_runs: list[dict[str, Any]] = []

    def recover(case: Path, *, replay: bool = False) -> None:
        if _launch_provenance(command, trusted_command=trusted_command) != provenance:
            raise ValueError("E_CRASH_CHILD_PROVENANCE")
        suffix = "replay" if replay else "reopen"
        argv = [*command, "--recover", str(case), *(["--replay"] if replay else [])]
        (case / f"{suffix}-launch.json").write_text(
            json.dumps({**provenance, "argv": argv}, sort_keys=True)
        )
        with (
            (case / f"{suffix}.stdout").open("wb") as stdout,
            (case / f"{suffix}.stderr").open("wb") as stderr,
        ):
            completed = subprocess.run(  # noqa: S603 -- fixed local child and owned temporary directory
                argv,
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                timeout=10,
                stdout=stdout,
                stderr=stderr,
            )
        recovery_runs.append(
            {
                "phase": suffix,
                "argv": argv,
                "exit": completed.returncode,
                "launch": case / f"{suffix}-launch.json",
                "stdout": case / f"{suffix}.stdout",
                "stderr": case / f"{suffix}.stderr",
            }
        )

    reader_runs: list[dict[str, Any]] = []

    def read_actual(case: Path, label: str) -> dict[str, Any]:
        run_dir = case / observation["discovery_run_id"]
        if reader_command is None:
            return read_restart_state(run_dir)
        reader_input = {
            "run_dir": str(run_dir.resolve()),
            "run_id": observation["discovery_run_id"],
            "case_id": entry["vector_id"],
            "checkpoint_id": entry["crash_checkpoint"],
            "phase": label,
        }
        input_path = case / f"reader-{label}-input.json"
        input_path.write_text(json.dumps(reader_input, sort_keys=True, separators=(",", ":")))
        argv = [*reader_command, str(run_dir), "--identity", str(input_path)]
        completed = subprocess.run(  # noqa: S603 -- fixed local read-only inspector
            argv,
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = case / f"reader-{label}.json"
        output.write_text(completed.stdout)
        reader_runs.append(
            {
                "phase": label,
                "argv": argv,
                "exit": completed.returncode,
                "input": input_path,
                "artifact": output,
            }
        )
        envelope = cast(dict[str, Any], json.loads(completed.stdout))
        if envelope.get("identity") != reader_input or not isinstance(
            envelope.get("state"), dict
        ):
            raise ValueError("E_CRASH_READER_OUTPUT")
        return cast(dict[str, Any], envelope["state"])

    def actual(case: Path) -> dict[str, Any]:
        before = read_actual(case, "before")
        (case / "actual-state.json").write_text(json.dumps(before, sort_keys=True))
        recover(case, replay=True)
        recovery = json.loads((case / "recovery.json").read_text())
        after = read_actual(case, "after")
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

    def compare(actual: dict[str, object], wanted: dict[str, object]) -> dict[str, object]:
        allowed = wanted.get("allowed_atomic_outcomes")
        if isinstance(allowed, list):
            if actual not in allowed:
                raise ValueError("E_RESTART_STATE_MISMATCH")
            return {"result": "PASS", "state": actual, "allowed_atomic_outcome": True}
        from tools.inspect_restart_state import inspect_restart_state

        return inspect_restart_state(actual, wanted)

    result = execute_crash_matrix(
        [{**entry, "expected_post_restart_state": expected_state}],
        command,
        workspace,
        state_reader=actual,
        prepare_case=prepare,
        recover_case=recover,
        validate_boundary=boundary,
        compare_state=compare,
    )
    for row in cast(list[dict[str, Any]], result["records"]):
        if (
            _launch_provenance(command, trusted_command=trusted_command) != provenance
            or row["command"][: len(command)] != command
        ):
            raise ValueError("E_CRASH_CHILD_PROVENANCE")
        case = Path(row["case_directory"])
        if json.loads((case / "launch-input.json").read_text())["scenario_sha256"] != _sha(
            case / "scenario.json"
        ):
            raise ValueError("E_CRASH_CHILD_PROVENANCE")
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
            launch_provenance={**provenance, "argv": row["command"]},
            prerequisite_state_sha256=_sha(case / "prerequisite-state.json"),
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
        if reader_command is not None:
            row.update(
                reader_runs=[
                    {"phase": item["phase"], "argv": item["argv"], "exit": item["exit"],
                     "input_path": str(item["input"].resolve()),
                     "input_sha256": _sha(item["input"]),
                     "path": str(item["artifact"].resolve()),
                     "sha256": _sha(item["artifact"])}
                    for item in reader_runs
                ],
                recovery_runs=[
                    {
                        "phase": item["phase"],
                        "argv": item["argv"],
                        "exit": item["exit"],
                        "launch_path": str(item["launch"].resolve()),
                        "launch_sha256": _sha(item["launch"]),
                        "stdout_path": str(item["stdout"].resolve()),
                        "stdout_sha256": _sha(item["stdout"]),
                        "stderr_path": str(item["stderr"].resolve()),
                        "stderr_sha256": _sha(item["stderr"]),
                    }
                    for item in recovery_runs
                ],
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
            row["reason"] = "FULL_CONFLICT_PROCESS_EVIDENCE_NOT_IMPLEMENTED"
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
    browser_binary: Path | None = None,
    include_mutations: bool = True,
) -> dict[str, Any]:
    from tools.run_indexeddb_crash_matrix import PACK, run_indexeddb_case

    registry_path = "docs/registries/crash-harness-registry.v1.json"
    entries = [
        row
        for row in json.loads((pack / registry_path).read_text())["entries"]
        if row["harness"] == "LOOPBACK_ACK"
    ]
    required = [
        row
        for row in json.loads((PACK / registry_path).read_text())["entries"]
        if row["harness"] == "LOOPBACK_ACK"
    ]
    if entries != required:
        raise ValueError("E_ACK_REQUIRED_CASES")
    if observation_input is not None:
        # Preserve the explicitly scoped legacy diagnostic API.
        return run_family(pack, workspace, "LOOPBACK_ACK", observation_input)
    records = [
        run_indexeddb_case(
            row,
            workspace / str(uuid4()),
            full=True,
            operation="deliver",
            browser_binary=browser_binary,
        )
        for row in entries
    ]
    from tools.owner_mutation_evidence import campaign

    mutations = campaign(entries, workspace / "mutations", records) if include_mutations else []
    return {
        "result": "PASS"
        if all(row["result"] == "PASS" for row in records)
        else "BLOCKED_ENVIRONMENT",
        "records": records,
        "mutation_results": mutations,
        "executed_vector_ids": [row["case_id"] for row in records if row["result"] == "PASS"],
        "killed_child_count": sum(
            row.get("termination", {}).get("method") not in {None, "NONE"} for row in records
        ),
        "legacy_full_qualification": "HOLD",
        "production_authority": "NONE",
    }


def run_browser_handshake(
    entry: dict[str, Any],
    case: Path,
    socket: str,
    request: dict[str, Any],
    identity: dict[str, Any],
    binding: dict[str, Any],
    extension: Path,
    binary: Path,
    observations: list[dict[str, Any]],
    *,
    browser_process: subprocess.Popen[bytes],
    profile: Path,
    sentinel: str,
    initial_sentinel: dict[str, Any],
    input_rejection: bool = False,
) -> dict[str, Any]:
    """Use the existing browser owner and independent SQLite reader for one full case."""
    from tools.inspect_restart_state import _checkpoint, _kill_owned_child
    from tools.qualify_chrome_indexeddb import _browser_process_observation
    from tools.run_indexeddb_crash_matrix import _call

    root = Path(__file__).resolve().parents[1]
    inputs: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}

    def save(name: str, value: Any, *, is_input: bool = False) -> dict[str, str]:
        path = case / (name + ".json")
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
        descriptor = {"path": str(path.resolve()), "sha256": _sha(path)}
        (inputs if is_input else artifacts)[name] = descriptor
        return descriptor

    loaded_assets = {
        name: {"path": str((extension / name).resolve()), "sha256": _sha(extension / name)}
        for name in ("manifest.json", "repair-probe.html")
    }
    marker = profile / "BH_R05_PROFILE_ID"
    marker_artifact = {"path": str(marker.resolve()), "sha256": _sha(marker)}
    profile_before = save(
        "profile-before",
        {
            "profile_path": str(profile.resolve()),
            "marker": marker.read_text(),
            "sentinel": initial_sentinel,
        },
    )
    browser_before = save("browser-process-before", _browser_process_observation(browser_process))
    launch = save(
        "browser-launch",
        {
            "argv": browser_process.args,
            "pid": browser_process.pid,
            "pgid": os.getpgid(browser_process.pid),
            "profile_path": str(profile.resolve()),
            "extension_path": str(extension.resolve()),
            "origin": identity["origin"],
            "executable": str(binary),
            "sha256": _sha(binary),
        },
    )

    processes: list[dict[str, Any]] = []
    owned: subprocess.Popen[bytes] | None = None
    child_identity = {
        key: value for key, value in request["identity"].items() if key not in {"profile_id", "pid"}
    }

    def start(restart: bool) -> dict[str, Any]:
        nonlocal owned
        config = {
            "identity": child_identity,
            "observation": observations[0],
            "origin": identity["origin"],
            "token": token_hex(32),
            "restart": restart,
        }
        descriptor = save(f"server-input-{int(restart)}", config, is_input=True)
        command = [*_trusted_command(), "--browser-server", descriptor["path"]]
        with (case / f"server-{int(restart)}.log").open("wb") as log:
            owned = subprocess.Popen(  # noqa: S603 -- owned isolated local synthetic receiver
                command,
                cwd=root,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        ready = case / f"server-{int(restart)}.json"
        deadline = monotonic() + 10
        while not ready.is_file() and monotonic() < deadline:
            if owned.poll() is not None:
                raise RuntimeError("E_ACK_SERVER_FAILED")
            sleep(0.02)
        if not ready.is_file():
            raise RuntimeError("E_ACK_SERVER_TIMEOUT")
        actual = json.loads(ready.read_text())
        if (
            actual["identity"] != {**child_identity, "pid": owned.pid}
            or actual["address"][0] != "127.0.0.1"
        ):
            raise ValueError("E_ACK_SERVER_IDENTITY")
        from tools.run_gap_coherence_crash_matrix import _proc_observation
        observed, raw = _proc_observation(owned, case / f"server-process-{int(restart)}.json")
        processes.append(
            {
                "observed": observed, "raw_process": raw,
                "argv": command,
                "pid": owned.pid,
                "pgid": os.getpgid(owned.pid),
                "identity": actual["identity"],
                "ready": save(f"server-ready-{int(restart)}", actual),
                "provenance": _launch_provenance(_trusted_command()),
            }
        )
        return {
            "endpoint": "http://127.0.0.1:" + str(actual["address"][1]),
            "token": config["token"],
        }

    def stop(kill: bool) -> None:
        if owned is None or owned.poll() is not None or os.getpgid(owned.pid) != owned.pid:
            raise RuntimeError("E_ACK_SERVER_NOT_OWNED")
        if kill:
            if not _kill_owned_child(owned):
                raise RuntimeError("E_ACK_SERVER_NOT_KILLED")
        else:
            os.killpg(owned.pid, signal.SIGTERM)
        code = owned.wait(timeout=5)
        if code != (-signal.SIGKILL if kill else -signal.SIGTERM):
            raise RuntimeError("E_ACK_SERVER_EXIT")
        processes[-1].update(
            exit=code,
            mechanism="POSIX_OWNED_PROCESS_GROUP_SIGKILL"
            if kill
            else "POSIX_OWNED_PROCESS_GROUP_SIGTERM_CLEANUP",
        )

    reader_runs: list[dict[str, Any]] = []

    def read_backend(phase: str) -> dict[str, Any]:
        run_dir = case / identity["run_id"]
        reader_input = {
            "run_dir": str(run_dir.resolve()),
            "run_id": identity["run_id"],
            "case_id": entry["vector_id"],
            "checkpoint_id": entry["crash_checkpoint"],
            "phase": phase,
        }
        descriptor = save("reader-" + phase, reader_input, is_input=True)
        command = [
            str(Path(sys.executable).absolute()),
            "-I",
            str(root / "tools/restart_state_reader.py"),
            str(run_dir.resolve()),
            "--identity",
            descriptor["path"],
        ]
        result = subprocess.run(  # noqa: S603 -- fixed independent read-only local reader
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = json.loads(result.stdout)
        if output["identity"] != reader_input:
            raise ValueError("E_ACK_READER_IDENTITY")
        artifact = save("reader-output-" + phase, output)
        reader_runs.append(
            {"phase": phase, "argv": command, "exit": result.returncode, "artifact": artifact}
        )
        return cast(dict[str, Any], output["state"])

    def read_browser(phase: str) -> dict[str, Any]:
        value = {
            "identity": request["identity"],
            "options": request["options"],
            "operation": "read",
            "observations": [],
        }
        save("browser-reader-" + phase, value, is_input=True)
        worker_id = str(uuid4())
        result = _call(socket, "startWorker", worker_id, value)
        _call(socket, "terminateWorker", worker_id)
        if result.get("worker_id") != worker_id:
            raise ValueError("E_ACK_READER_WORKER")
        save("browser-" + phase, result)
        return result

    try:
        transport = start(False)
        request = {**request, "transport": transport}
        save("worker", request, is_input=True)
        if input_rejection:
            from tools.owner_mutation_evidence import browser_input

            return browser_input(
                entry, case, socket, request, identity, binding, extension, binary, observations,
                browser_process, profile, sentinel, inputs, artifacts, processes, reader_runs,
                loaded_assets, marker_artifact, profile_before, browser_before, launch,
                save, read_browser, read_backend, stop,
            )
        worker_id = str(uuid4())
        _call(socket, "beginWorker", worker_id, request)
        action = entry["kill_action"]
        if action == "SIGKILL_BACKEND_CHILD":
            assert owned is not None
            backend_identity = {**child_identity, "pid": owned.pid}
            try:
                _checkpoint(
                    case / "backend-checkpoint.json", owned, backend_identity, entry["vector_id"]
                )
            except RuntimeError:
                _call(socket, "waitWorker")
                raise
            checkpoint = json.loads((case / "backend-checkpoint.json").read_text())
            save("backend-boundary", json.loads((case / "backend-boundary.json").read_text()))
            stop(True)
            termination = {
                "method": "POSIX_OWNED_PROCESS_GROUP_SIGKILL",
                "pid": owned.pid,
                "returncode": -signal.SIGKILL,
            }
        else:
            checkpoint = _call(socket, "waitWorker")
            if (
                any(checkpoint.get(key) != value for key, value in identity.items())
                or checkpoint.get("worker_id") != worker_id
                or checkpoint.get("boundary") != entry["crash_checkpoint"]
            ):
                raise ValueError("E_ACK_WORKER_CHECKPOINT")
            termination = (
                {"method": "Worker.terminate", "worker_id": worker_id}
                if action != "NONE"
                else {"method": "NONE"}
            )
        _call(socket, "terminateWorker", worker_id)
        if action != "SIGKILL_BACKEND_CHILD":
            stop(False)
        save("checkpoint", checkpoint)
        transport = start(True)
        actual = read_browser("before")
        backend_before = read_backend("before")
        recovery = {
            **request,
            "operation": "recover",
            "transport": transport,
            "observations": request["observations"][:1] if not actual["entries"] else [],
        }
        save("recovery-worker", recovery, is_input=True)
        recovery_id = str(uuid4())
        recovery_result = _call(socket, "startWorker", recovery_id, recovery)
        _call(socket, "terminateWorker", recovery_id)
        save("recovery-worker-output", recovery_result)
        browser_after = read_browser("after")
        backend_after = read_backend("after")
        stop(False)
        profile_after = save(
            "profile-after",
            {
                "profile_path": str(profile.resolve()),
                "marker": marker.read_text(),
                "sentinel": _call(socket, "readSentinel", identity["profile_id"]),
            },
        )
        browser_after_process = save(
            "browser-process-after", _browser_process_observation(browser_process)
        )
        save("backend-before", backend_before)
        save("backend-after", backend_after)
        save("expected", entry["expected_post_restart_state"])
        wires = {
            path.name: save(path.stem, json.loads(path.read_text()))
            for path in sorted(case.glob("wire-*.json"))
        }
        row = {
            "vector_id": entry["vector_id"],
            "case_id": entry["vector_id"],
            "case_directory": str(case.resolve()),
            "status": "PASS",
            "result": "PASS",
            "executed": True,
            "launch_attempted": True,
            "qualification_scope": "BROWSER_LOOPBACK_ACK",
            "execution_kind": "BROWSER_LOOPBACK_ACK",
            "legacy_full_qualification": "HOLD",
            "identity": identity,
            "worker_id": worker_id,
            "checkpoint": checkpoint,
            "termination": termination,
            "actual": actual,
            "backend_before": backend_before,
            "browser_after": browser_after,
            "backend_after": backend_after,
            "observations": observations,
            "expected": entry["expected_post_restart_state"],
            "observed_error": None,
            "comparison": {"matched": True},
            "evidence_binding": binding,
            "revision": binding["revision"],
            "environment": binding["environment"],
            "inputs": inputs,
            "artifacts": artifacts,
            "wire_artifacts": wires,
            "reader_runs": reader_runs,
            "backend_processes": processes,
            "browser": {"executable": str(binary), "sha256": _sha(binary)},
            "loaded_assets": loaded_assets,
            "profile_readbacks": {
                "before": profile_before,
                "after": profile_after,
                "marker": marker_artifact,
                "sentinel": sentinel,
            },
            "browser_provenance": {
                "launch": launch,
                "before": browser_before,
                "after": browser_after_process,
            },
            "module_hashes": {
                str(path.relative_to(extension)): _sha(path)
                for path in sorted(extension.rglob("*.js"))
            },
        }
        from tools.verify_repair_evidence import _verify_browser_ack

        _verify_browser_ack(row, binding, terminal=False)
        terminal_path = case / "terminal-result.json"
        terminal_path.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")))
        row["terminal_artifact"] = {
            "path": str(terminal_path.resolve()),
            "sha256": _sha(terminal_path),
        }
        return row
    finally:
        if owned is not None and owned.poll() is None:
            _kill_owned_child(owned)
            owned.wait(timeout=5)
