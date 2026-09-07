"""Parent-only verification of disposable destruction facts, never a state writer."""

from __future__ import annotations

import copy
import hashlib
import json
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.retained_artifact_io import RetainedArtifactIO

import rfc8785

from moj_discovery.schema_registry import validate_artifact
from moj_discovery.store import VENDOR
from tools.destruction_support import consumption, content_hash, inventory, validate_plan
from tools.run_gap_coherence_crash_matrix import _validate_snapshot_ddl, _verify_proc_observation

ROOT = Path(__file__).resolve().parents[1]
RECOVERY_ACTIONS = {
    "unauthorized": "DO_NOT_DELETE",
    "consumed": (
        "FAIL_CLOSED_REVALIDATE_SAME_RECEIPT_BYTES_AS_DATA_ONLY_AND_RECONSTRUCT_ONLY_THE_BYTE_IDENTICAL_"
        "EXTERNAL_INTENT_MATCHING_PRECOMMITTED_ID_CONTENT_HASH_INVENTORY_HASH_CREATED_AT_AND_FIXED_"
        "ARTIFACT_ORDER_NEVER_RECONSUME_OR_ALTER_ANY_FIELD"
    ),
    "intent": (
        "REVALIDATE_PERSISTED_EXTERNAL_INTENT_ID_AND_CANONICAL_CONTENT_HASH_AGAINST_IMMUTABLE_PRECOMMIT_"
        "PLUS_EXACT_RUN_MANIFEST_RECEIPT_CONSUMPTION_AND_HUMAN_BINDINGS_THEN_RESUME_SAME_WHOLE_RUN_DESTRUCTION"
    ),
    "extension_deleted": (
        "REVALIDATE_EXTERNAL_INTENT_AGAINST_COMMITTED_ONE_USE_CONSUMPTION_FOR_THE_SAME_RUN_"
        "THEN_DELETE_BACKEND_AND_PROVE_PARTIAL_HISTORY"
    ),
    "backend_deleted": (
        "REVALIDATE_SIGNED_EXTERNAL_INTENT_EXACT_RUN_MANIFEST_AND_RECEIPT_CONTENT_HASH_BINDING_"
        "THEN_DELETE_ONLY_THE_SAME_RUN_INDEXEDDB_AND_WRITE_PROOF"
    ),
    "both_deleted": "WRITE_LOGICAL_DELETION_PROOF_FROM_ACCEPTED_EXTERNAL_INTENT",
    "proved": "NO_FURTHER_ACTION_LOGICAL_DELETION_COMPLETE_SECURE_ERASURE_CLAIM_FALSE",
}


def compare_destruction(row: dict[str, Any], plan: dict[str, Any]) -> None:
    validate_plan(plan)
    before, crashed, after = (row[key] for key in ("before", "crashed", "after"))
    original = inventory(before)
    if original != plan["export"]["inventory"] or not all(
        original[k]["present"] for k in ("browser", "backend")
    ):
        raise ValueError("E_DESTRUCTION_INVENTORY_HASH")
    base_tables = before["backend"]["state"]["tables"]
    if (
        base_tables["authorization_consumptions"]
        or base_tables["run_meta"][0]["run_status"] != "CLOSED"
        or len(base_tables["stream_generations"]) != 2
        or any(g["generation_state"] != "CLOSED" for g in base_tables["stream_generations"])
        or base_tables["coherence_controllers"][0]["controller_state"] != "SHOCKED_CLOSED"
        or len(base_tables["reducer_cursors"]) != 1
        or len(base_tables["ack_cursors"]) != 1
        or before["browser"]["states"][0]["ack_sequence"] != "1"
    ):
        raise ValueError("E_DESTRUCTION_FINAL_BASELINE")
    seen_workers = []
    for state in (before, crashed, after):
        browser, backend, external = state["browser"], state["backend"], state["external"]
        seen_workers.append(browser["worker_id"])
        if any(browser.get(key) != value for key, value in row["identity"].items()):
            raise ValueError("E_DESTRUCTION_BROWSER_IDENTITY")
        if browser["present"] != (browser["database_name"] in browser["database_names"]):
            raise ValueError("E_DESTRUCTION_BROWSER_PRESENCE")
        if browser["present"]:
            if (
                inventory({"browser": browser, "backend": backend})["browser"]
                != original["browser"]
            ):
                raise ValueError("E_DESTRUCTION_BROWSER_RETENTION")
        elif any(browser[key] for key in ("states", "entries", "keys")):
            raise ValueError("E_DESTRUCTION_BROWSER_PRESENCE")
        if backend["present"]:
            _validate_snapshot_ddl(backend["state"])
            tables = copy.deepcopy(backend["state"]["tables"])
            consumed = tables["authorization_consumptions"]
            if consumed not in ([], [consumption(plan)]):
                raise ValueError("E_DESTRUCTION_CONSUMPTION")
            status = tables["run_meta"][0]["run_status"]
            if status != ("DESTRUCTION_PENDING" if external["intent"] else "CLOSED"):
                raise ValueError("E_DESTRUCTION_INTENT_ORDER")
            tables["run_meta"][0]["run_status"] = "CLOSED"
            tables["authorization_consumptions"] = []
            if tables != base_tables:
                raise ValueError("E_DESTRUCTION_RETENTION")
        elif backend["state"] is not None or state["database_files"]:
            raise ValueError("E_DESTRUCTION_BACKEND_PRESENCE")
        if external["intent"] is not None and external["intent"] != plan["intent"]:
            raise ValueError("E_DESTRUCTION_INTENT_PRECOMMIT")
        if external["proof"]:
            proof = external["proof"]
            validate_artifact(
                proof, "durability-records.schema.json", bootstrap_only=True, vendor=VENDOR
            )
            if (
                proof["content_hash"] != content_hash(proof)
                or proof["run_id"] != plan["run_id"]
                or proof["destruction_intent_id"] != plan["intent"]["destruction_intent_id"]
                or proof["proof_state"] != "COMPLETE_LOGICAL_DELETION"
                or proof["secure_erasure_claim"] is not False
                or browser["present"]
                or backend["present"]
            ):
                raise ValueError("E_DESTRUCTION_PROOF")
    if len(set(seen_workers)) != 3:
        raise ValueError("E_DESTRUCTION_READER_REUSED")
    browser_present, backend_present = crashed["browser"]["present"], crashed["backend"]["present"]
    has_intent, has_proof = (crashed["external"][key] is not None for key in ("intent", "proof"))
    consumed = (
        bool(crashed["backend"]["state"]["tables"]["authorization_consumptions"])
        if backend_present
        else True
    )
    if not consumed:
        key = "unauthorized"
    elif not has_intent:
        key = "consumed"
    elif browser_present and backend_present:
        key = "intent"
    elif backend_present:
        key = "extension_deleted"
    elif browser_present:
        key = "backend_deleted"
    else:
        key = "proved" if has_proof else "both_deleted"
    projected: dict[str, Any] = {
        "indexeddb_store": "PRESENT" if browser_present else "DELETED",
        "backend_database": "PRESENT" if backend_present else "DELETED",
        "external_intent_delta": int(has_intent),
        "external_proof_delta": int(has_proof),
        "sql_row_deltas": ({"authorization_consumptions": 1} if consumed else {})
        if backend_present
        else "NOT_APPLICABLE_DATABASE_DELETED",
        "reducer_cursor": "FINAL_UNCHANGED"
        if browser_present and backend_present
        else "READABLE_FROM_BACKEND"
        if backend_present
        else "UNAVAILABLE_AFTER_DELETE"
        if browser_present
        else "RECORDED_IN_INTENT_ONLY",
        "extension_ack": "FINAL_UNCHANGED"
        if browser_present
        else "UNAVAILABLE_AFTER_DELETE"
        if backend_present
        else "RECORDED_IN_INTENT_ONLY",
        "backend_ack": "FINAL_UNCHANGED"
        if backend_present
        else "UNAVAILABLE_AFTER_DELETE"
        if browser_present
        else "RECORDED_IN_INTENT_ONLY",
        "recovery_action": RECOVERY_ACTIONS[key],
    }
    for field, final in (
        ("predecessor_generation", "FINAL_CLOSED"),
        ("successor_generation", "FINAL"),
        ("coherence_state", "FINAL_CLOSED"),
    ):
        projected[field] = (
            final
            if browser_present and backend_present
            else "READABLE_FROM_BACKEND"
            if backend_present
            else "UNAVAILABLE_AFTER_DELETE"
            if browser_present
            else "RECORDED_IN_INTENT_ONLY"
        )
    if key in {"consumed", "intent"}:
        projected["run_status"] = crashed["backend"]["state"]["tables"]["run_meta"][0]["run_status"]
    if key == "consumed":
        projected.update(
            receipt_state="CONSUMED_ONE_USE_PERMANENTLY_BURNED",
            deletion_started=False,
            second_authorization_consumption_allowed=False,
            new_authority_required=False,
        )
    if projected != row["expected"]:
        raise ValueError("E_RESTART_STATE_MISMATCH")
    if key == "unauthorized":
        if inventory(after) != original or any(after["external"].values()):
            raise ValueError("E_DESTRUCTION_UNAUTHORIZED_DELETE")
    elif (
        after["browser"]["present"]
        or after["backend"]["present"]
        or after["external"]["intent"] != plan["intent"]
        or not after["external"]["proof"]
    ):
        raise ValueError("E_DESTRUCTION_RECOVERY")
    if has_proof and after["external"]["proof"] != crashed["external"]["proof"]:
        raise ValueError("E_DESTRUCTION_PROOF_REWRITE")


def verify_destruction(
    row: dict[str, Any],
    current: dict[str, Any],
    *,
    terminal: bool = True,
    mutation_type: str | None = None,
    artifacts: RetainedArtifactIO | None = None,
) -> None:
    from tools.run_indexeddb_crash_matrix import PRODUCER, REGISTRY, STREAM, compare_indexeddb_state
    from tools.verify_repair_evidence import (
        _contains_expected,
        _read_retained,
        _sqlite_descriptor,
        _sqlite_file,
        _verify_browser_binding,
        _verify_retained_typescript_graph,
    )

    if (
        row["evidence_binding"] != current
        or row["revision"] != current["revision"]
        or row["environment"] != current["environment"]
    ):
        raise ValueError("E_REPAIR_STALE_BINDING")
    if row["mutation_type"] != mutation_type:
        raise ValueError("E_DESTRUCTION_MUTATION_IDENTITY")
    entries = json.loads((VENDOR / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    entry = next(entry for entry in entries if entry["vector_id"] == row["case_id"])
    if (
        entry["harness"] != "WHOLE_RUN_DESTRUCTION"
        or row["expected"] != entry["expected_post_restart_state"]
        or row["identity"]["case_id"] != entry["vector_id"]
        or row["identity"]["checkpoint_id"] != entry["crash_checkpoint"]
    ):
        raise ValueError("E_DESTRUCTION_REGISTRY")
    identity = row["identity"]
    if (
        identity["component"] != "WHOLE_RUN_DESTRUCTION"
        or identity["origin"] != "chrome-extension://jnegjfjalhnpdeejfcjlobpbdpabdfhp"
        or identity["protocol"] != "chrome-extension:"
        or identity["module_url"] != identity["origin"] + "/src/spool.js"
    ):
        raise ValueError("E_DESTRUCTION_BROWSER_IDENTITY")
    _verify_browser_binding(row, current)
    case = Path(row["case_directory"])
    _verify_retained_typescript_graph(row, current, "E_DESTRUCTION_MODULE")
    loaded_inputs = {
        key: _sqlite_descriptor(row, descriptor, "E_DESTRUCTION_INPUT")
        for key, descriptor in row["inputs"].items()
    }
    if any(_contains_expected(value) for value in loaded_inputs.values()):
        raise ValueError("E_DESTRUCTION_ORACLE_INPUT")
    owner_input = loaded_inputs["owner-input"]
    if (
        set(owner_input) != {"identity", "socket", "options"}
        or owner_input["identity"] != identity
        or owner_input["options"]
        != {
            "browser_run_id": identity["run_id"],
            "producer_id": PRODUCER,
            "stream_id": STREAM,
            "generation": "0",
            "registry": json.loads(REGISTRY.read_text()),
        }
    ):
        raise ValueError("E_DESTRUCTION_READER_INPUT")
    observation = loaded_inputs["setup-input"]["observation"]
    compare_indexeddb_state(row["before"]["browser"], identity, [observation], 1, ack=1)
    raw = row["before"]["backend"]["state"]["tables"]["raw_commits"]
    if len(raw) != 1 or raw[0]["raw_observation_content_hash"] != observation["content_hash"]:
        raise ValueError("E_DESTRUCTION_FINAL_BASELINE")
    for key, descriptor in row["artifacts"].items():
        value = _sqlite_descriptor(row, descriptor, "E_DESTRUCTION_ARTIFACT")
        if key in {"before", "crashed", "after", "expected"} and value != row[key]:
            raise ValueError("E_DESTRUCTION_ARTIFACT")
    plan = loaded_inputs["precommit"]
    if plan["run_id"] != row["identity"]["run_id"]:
        raise ValueError("E_DESTRUCTION_RUN_ID")
    for kind, filename in (
        ("intent", f".local/destruction/{identity['run_id']}.intent.json"),
        ("proof", f".local/destruction/{identity['run_id']}.deletion-proof.json"),
        ("consumption", "consumed-external.json"),
    ):
        expected_value = (
            (consumption(plan) if row["after"]["external"]["intent"] else None)
            if kind == "consumption"
            else row["after"]["external"][kind]
        )
        if kind == "consumption" and expected_value is not None:
            # The retained committed SQLite row encodes its BOOLEAN as INTEGER.
            expected_value = {**expected_value, "one_use": 1}
        descriptor = row["artifacts"].get("external-" + kind)
        if expected_value is None:
            if descriptor is not None or (case / filename).exists():
                raise ValueError("E_DESTRUCTION_EXTERNAL_ARTIFACT")
        elif (
            descriptor is None
            or descriptor["path"] != str(case / filename)
            or _sqlite_descriptor(row, descriptor, "E_DESTRUCTION_EXTERNAL_ARTIFACT")
            != expected_value
            or _read_retained(Path(descriptor["path"])) != rfc8785.dumps(expected_value)
        ):
            raise ValueError("E_DESTRUCTION_EXTERNAL_ARTIFACT")
    processes = row["processes"]
    names = ["setup", "reader-before", "destruction", "reader-crashed", "recovery", "reader-after"]
    if mutation_type == "INPUT":
        names.remove("recovery")
    if [p["name"] for p in processes] != names:
        raise ValueError("E_DESTRUCTION_PROCESS_SET")
    if len({p["pid"] for p in processes}) != len(names) or row["reader_runs"] != [
        p for p in processes if p["mode"] == "read"
    ]:
        raise ValueError("E_DESTRUCTION_PROCESS_IDENTITY")
    for process in processes:
        mode, name = process["mode"], process["name"]
        command = [
            str(Path(sys.executable).absolute()),
            "-I",
            str(ROOT / "tools/destruction_crash_child.py"),
            mode,
            process["input"]["path"],
            "--start",
            str(case / (name + ".start")),
        ]
        _verify_proc_observation(process["observed"], process["raw_process"], command)
        if (
            process["command"] != command
            or process["pid"] != process["observed"]["pid"]
            or process["pgid"] != process["observed"]["pgid"]
            or process["pid"] != process["pgid"]
        ):
            raise ValueError("E_DESTRUCTION_PROCESS_IDENTITY")
        stderr = process.get("stderr")
        if not isinstance(stderr, dict) or set(stderr) != {"path", "sha256"}:
            raise ValueError("E_DESTRUCTION_PROCESS_STDERR")
        stderr_path = _sqlite_file(
            row, stderr["path"], stderr["sha256"], "E_DESTRUCTION_PROCESS_STDERR"
        )
        if stderr_path != case / (name + ".stderr") or _read_retained(stderr_path) != b"":
            raise ValueError("E_DESTRUCTION_PROCESS_STDERR")
        stdout = process["stdout"]
        if not isinstance(stdout, dict) or set(stdout) != {"path", "sha256"}:
            raise ValueError("E_DESTRUCTION_PROCESS_OUTPUT")
        output_path = _sqlite_file(
            row, stdout["path"], stdout["sha256"], "E_DESTRUCTION_PROCESS_OUTPUT"
        )
        if output_path != case / (name + ".stdout"):
            raise ValueError("E_DESTRUCTION_PROCESS_OUTPUT")
        expected_exit = (1 if mutation_type == "INPUT" else -signal.SIGKILL) if mode == "run" else 0
        if (
            hashlib.sha256(_read_retained(output_path)).hexdigest() != process["stdout"]["sha256"]
            or process["exit_code"] != expected_exit
        ):
            raise ValueError("E_DESTRUCTION_PROCESS_EXIT")
        source = _sqlite_descriptor(row, process["input"], "E_DESTRUCTION_INPUT")
        if mode in {"read", "run", "recover"} and source != loaded_inputs["owner-input"]:
            raise ValueError("E_DESTRUCTION_READER_INPUT")
        if mode != "run" or mutation_type == "INPUT":
            output = _sqlite_descriptor(row, stdout, "E_DESTRUCTION_PROCESS_OUTPUT")
            if not isinstance(output, dict) or set(output) != {"pid", "result"}:
                raise ValueError("E_DESTRUCTION_PROCESS_OUTPUT")
            if output["pid"] != process["pid"]:
                raise ValueError("E_DESTRUCTION_PROCESS_IDENTITY")
            if mode == "setup":
                acks = row["before"]["backend"]["state"]["tables"]["ack_outbox"]
                if len(acks) != 1 or output["result"] != acks[0]:
                    raise ValueError("E_DESTRUCTION_PROCESS_OUTPUT")
            if mode == "recover" and output["result"] != {"completed": True}:
                raise ValueError("E_DESTRUCTION_PROCESS_OUTPUT")
            if mode == "read" and output["result"] != row[name.removeprefix("reader-")]:
                raise ValueError("E_DESTRUCTION_READER_OUTPUT")
            if mode == "run" and output["result"] != {
                "observed_error": "E_DESTRUCTION_HUMAN_INVOCATION"
            }:
                raise ValueError("E_DESTRUCTION_WRONG_REJECTION")
        elif _read_retained(output_path) != b"":
            raise ValueError("E_DESTRUCTION_PROCESS_OUTPUT")
    if mutation_type == "INPUT":
        if row["checkpoint"] is not None:
            raise ValueError("E_DESTRUCTION_INPUT_MUTATION_CHECKPOINT")
        original = _sqlite_descriptor(
            row, row["artifacts"]["original-plan"], "E_DESTRUCTION_MUTATION_INPUT"
        )
        validate_plan(original)
        wanted = copy.deepcopy(original)
        wanted["intent"]["human_invocation"] = False
        if plan != wanted or any(
            inventory(row[phase]) != original["export"]["inventory"]
            or any(row[phase]["external"].values())
            for phase in ("before", "crashed", "after")
        ):
            raise ValueError("E_DESTRUCTION_MUTATION_INPUT")
        try:
            validate_plan(plan)
        except ValueError as error:
            if (
                str(error) != row["observed_error"]
                or str(error) != "E_DESTRUCTION_HUMAN_INVOCATION"
            ):
                raise ValueError("E_DESTRUCTION_WRONG_REJECTION") from error
        else:
            raise ValueError("E_DESTRUCTION_MUTATION_SURVIVOR")
    else:
        checkpoint = _sqlite_descriptor(row, row["checkpoint"], "E_DESTRUCTION_CHECKPOINT")
        if checkpoint != {**row["identity"], "pid": processes[2]["pid"]}:
            raise ValueError("E_DESTRUCTION_CHECKPOINT")
        compare_destruction(row, plan)
        if mutation_type == "EXPECTED":
            altered = _sqlite_descriptor(
                row, row["artifacts"]["mutation-oracle"], "E_DESTRUCTION_MUTATION_ORACLE"
            )
            wanted = copy.deepcopy(row["expected"])
            wanted["indexeddb_store"] = (
                "DELETED" if wanted["indexeddb_store"] == "PRESENT" else "PRESENT"
            )
            if altered != wanted:
                raise ValueError("E_DESTRUCTION_MUTATION_UNCHANGED")
            try:
                compare_destruction({**row, "expected": altered}, plan)
            except ValueError as error:
                if str(error) != "E_RESTART_STATE_MISMATCH" or row["observed_error"] != str(error):
                    raise ValueError("E_DESTRUCTION_WRONG_REJECTION") from error
            else:
                raise ValueError("E_DESTRUCTION_MUTATION_SURVIVOR")
    if mutation_type is None:
        if [m["vector_id"] for m in row["mutations"]] != entry["mutation_vector_ids"]:
            raise ValueError("E_DESTRUCTION_MUTATION_SET")
        for mutation in row["mutations"]:
            execution = mutation["execution"]
            expected_error = (
                "E_RESTART_STATE_MISMATCH"
                if mutation["kind"] == "EXPECTED"
                else "E_DESTRUCTION_HUMAN_INVOCATION"
            )
            if (
                not mutation["detected"]
                or mutation["observed_error"] != expected_error
                or mutation["expected_error"] != expected_error
                or execution["identity"]["run_id"] == row["identity"]["run_id"]
                or Path(execution["case_directory"])
                != case / ("mutation-" + mutation["kind"].lower())
                or execution["case_id"] != row["case_id"]
            ):
                raise ValueError("E_DESTRUCTION_MUTATION_IDENTITY")
            verify_destruction(execution, current, mutation_type=mutation["kind"])
    elif row["mutations"]:
        raise ValueError("E_DESTRUCTION_MUTATION_RECURSION")
    if terminal:
        saved = _sqlite_descriptor(row, row["terminal_artifact"], "E_DESTRUCTION_TERMINAL")
        if saved != {key: value for key, value in row.items() if key != "terminal_artifact"}:
            raise ValueError("E_DESTRUCTION_TERMINAL")
