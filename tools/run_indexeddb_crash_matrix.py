"""Terminate owned extension Workers at real shared-spool transaction boundaries."""

from __future__ import annotations

import json
import os
import platform
import shutil
from pathlib import Path
from secrets import token_hex
from subprocess import run
from typing import Any
from uuid import uuid4

from moj_discovery.canonical import canonical_content_hash
from moj_discovery.ingest import H0
from moj_discovery.schema_registry import validate_artifact
from tools.qualify_chrome_indexeddb import (
    QualificationRejected,
    _canonical_browser_executable,
    _EnvironmentBlocked,
    _evaluate,
    _kill_owned_process_group,
    _prepare_test_extension,
    _process_executable,
    _sha256,
    _start_chrome,
    _wait_for_probe,
)

ROOT = Path(__file__).parents[1]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"
REGISTRY = PACK / "registries/canonical-hash-domains.v1.json"
CHROME = Path("/home/thenam176/.cache/ms-playwright/chromium-1232/chrome-linux64/chrome")
PRODUCER = "00000000-0000-4000-8000-000000000003"
STREAM = "00000000-0000-4000-8000-000000000002"


def _observations(browser: str) -> list[dict[str, Any]]:
    """Prevalidated synthetic accounting envelopes, not a production projector."""
    values = []
    for sequence in (1, 2, 3):
        value: dict[str, Any] = {
            "schema_version": "raw-observation/v1",
            "raw_observation_id": "observation:" + f"{sequence:064x}",
            "observation_kind": "TERMINAL",
            "pack_hash": "a" * 64,
            "build_hash": "b" * 64,
            "implementation_baseline_hash": "c" * 64,
            "capability_manifest_hash": "d" * 64,
            "discovery_run_id": browser,
            "run_receipt_hash": "e" * 64,
            "stream_id": STREAM,
            "generation": "0",
            "sequence": str(sequence),
            "context": {
                "context_kind": "RUN_BOUND_NOT_DOCUMENT",
                "browser_run_id": browser,
                "browser_boot_id": browser,
                "binding_reason": "TERMINAL_ACCOUNTING",
            },
            "clock_context": {
                "clock_domain_id": PRODUCER,
                "boot_id": browser,
                "unit": "MICROSECOND",
                "monotonic_value": str(sequence),
                "resolution_us": "1",
                "owner": "BACKEND",
                "mapping_id": "NOT_APPLICABLE",
                "mapping_status": "NOT_APPLICABLE",
            },
            "sanitizer_version": "sanitizer/v1",
            "content_hash": "0" * 64,
            "production_authority": "NONE",
            "facts": {
                "terminal_code": "MANUAL_STOP",
                "final_generation": "0",
                "final_sequence": str(sequence),
                "observation_count": str(sequence),
                "gap_count": "0",
                "safety_disposition": "PARTIAL_EVIDENCE_ONLY",
            },
        }
        value["content_hash"] = canonical_content_hash(
            "RawObservation", value, registry_path=REGISTRY
        )
        validate_artifact(value, "raw-observation.schema.json", bootstrap_only=True, vendor=PACK)
        values.append(value)
    return values


def _call(socket: str, method: str, *arguments: object) -> dict[str, Any]:
    value = _evaluate(
        socket,
        f"globalThis.repairProbe.{method}(" + ",".join(json.dumps(arg) for arg in arguments) + ")",
    )
    if not isinstance(value, dict) or "error" in value:
        raise QualificationRejected(f"E_INDEXEDDB_WORKER:{value}")
    return value


def compare_indexeddb_state(
    actual: dict[str, Any],
    identity: dict[str, Any],
    observations: list[dict[str, Any]],
    count: int,
    *,
    ack: int = 0,
) -> None:
    """Parent-only comparator over read-back rows, never checkpoint-derived state."""
    for field, value in identity.items():
        if actual.get(field) != value:
            raise ValueError("E_INDEXEDDB_IDENTITY:" + field)
    entries = actual["entries"]
    states = actual["states"]
    if len(entries) != count or len(states) != (1 if count else 0):
        raise ValueError("E_INDEXEDDB_STATE")
    previous = H0
    hashes = [H0]
    byte_count = 0
    for index, entry in enumerate(entries):
        raw = observations[index]
        record = entry["spool_record"]
        if (
            set(entry) != {"storage_schema_version", "spool_record", "sanitized_observation"}
            or entry["storage_schema_version"] != "browser-spool-entry/v1"
            or entry["sanitized_observation"] != raw
        ):
            raise ValueError("E_INDEXEDDB_ENVELOPE")
        validate_artifact(
            record, "durability-records.schema.json", bootstrap_only=True, vendor=PACK
        )
        cursor = canonical_content_hash(
            "CursorStep",
            {
                "schema_version": "cursor-step/v1",
                "discovery_run_id": raw["discovery_run_id"],
                "browser_run_id": raw["context"]["browser_run_id"],
                "producer_id": PRODUCER,
                "stream_id": STREAM,
                "generation": "0",
                "sequence": str(index + 1),
                "raw_observation_hash": raw["content_hash"],
                "previous_cursor_hash": previous,
            },
            registry_path=REGISTRY,
        )
        position = {
            "generation_key": {
                "stream": {
                    "browser_run_id": raw["context"]["browser_run_id"],
                    "producer_id": PRODUCER,
                    "stream_id": STREAM,
                },
                "generation": "0",
            },
            "sequence": str(index + 1),
        }
        size = len(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode())
        if (
            record["position"] != position
            or record["previous_cursor_hash"] != previous
            or record["cursor_hash"] != cursor
            or record["raw_observation_id"] != raw["raw_observation_id"]
            or record["raw_observation_content_hash"] != raw["content_hash"]
            or record["payload_size_bytes"] != str(size)
            or record["content_hash"]
            != canonical_content_hash("SpoolRecord", record, registry_path=REGISTRY)
        ):
            raise ValueError("E_INDEXEDDB_CHAIN")
        previous = cursor
        hashes.append(cursor)
        byte_count += size
    if actual["keys"] != [[PRODUCER, STREAM, "0" * 19, str(i + 1).zfill(19)] for i in range(count)]:
        raise ValueError("E_INDEXEDDB_KEYS")
    if count and states != [
        {
            "storage_schema_version": "browser-stream-state/v1",
            "producer_id": PRODUCER,
            "stream_id": STREAM,
            "active_generation": "0",
            "next_sequence": str(count + 1),
            "last_cursor_hash": previous,
            "ack_generation": "0",
            "ack_sequence": str(ack),
            "ack_cursor_hash": hashes[ack],
            "normal_bytes_used": str(byte_count),
            "terminal_reserve_bytes_used": "0",
            "generation_state": "ACTIVE",
        }
    ]:
        raise ValueError("E_INDEXEDDB_STATE")


def run_indexeddb_case(
    entry: dict[str, Any],
    workspace: Path,
    *,
    browser_binary: Path | None = None,
    mutation: str | None = None,
    operation: str = "crash",
    full: bool = False,
) -> dict[str, Any]:
    from tools.verify_repair_evidence import capture_binding

    browser_binary = browser_binary or Path(os.environ.get("BH_CHROME_BINARY", str(CHROME)))
    workspace.mkdir(parents=True, exist_ok=False)
    if not browser_binary.is_file():
        return {
            "result": "BLOCKED_ENVIRONMENT",
            "status": "BLOCKED_ENVIRONMENT",
            "blocker_code": "E_BROWSER_UNAVAILABLE",
            "reason": "E_BROWSER_UNAVAILABLE",
            "executed": False,
            "launch_attempted": False,
            "prerequisite": {"name": "Chrome for Testing", "available": False},
            "attempted_real_browser": False,
            "vector_id": entry["vector_id"],
            "case_id": entry["vector_id"],
        }
    evidence_binding = capture_binding()
    registered = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    original = next(row for row in registered if row["vector_id"] == entry["vector_id"])
    if any(
        entry[field] != original[field]
        for field in ("harness", "crash_checkpoint", "kill_action", "source_boundary")
    ):
        raise ValueError("E_INDEXEDDB_REGISTERED_BOUNDARY")
    profile = workspace / "chrome-profile"
    profile.mkdir()
    profile_id = str(uuid4())
    (profile / "BH_R05_PROFILE_ID").write_text(profile_id)
    extension, extension_id, module_hash = _prepare_test_extension(ROOT, workspace)
    process = None
    try:
        origin = "chrome-extension://" + extension_id
        process, socket = _start_chrome(
            browser_binary,
            profile,
            extension,
            origin + "/repair-probe.html",
            workspace / "chrome.log",
        )
        binary = _process_executable(process)
        if binary != _canonical_browser_executable(browser_binary):
            raise ValueError("E_BROWSER_BINARY_MISMATCH")
        _wait_for_probe(socket)
        sentinel = token_hex(32)
        initial_sentinel = _call(socket, "writeSentinel", sentinel, profile_id)
        if (initial_sentinel.get("sentinel") != sentinel
                or initial_sentinel.get("profileId") != profile_id):
            raise ValueError("E_INDEXEDDB_PROFILE")
        run_id = str(uuid4())
        observations = _observations(run_id)
        binding = {
            "run_id": run_id,
            "case_id": entry["vector_id"],
            "checkpoint_id": entry["crash_checkpoint"],
            "test_nonce": token_hex(16),
            "profile_id": profile_id,
            "component": entry["harness"],
            "ordinal": 0,
            "pid": process.pid,
        }
        identity = {
            **binding,
            "module_sha256": module_hash,
            "origin": origin,
            "protocol": "chrome-extension:",
            "module_url": origin + "/src/spool.js",
        }
        request = {
            "identity": binding,
            "operation": operation,
            "options": {
                "browser_run_id": run_id,
                "producer_id": PRODUCER,
                "stream_id": STREAM,
                "generation": "0",
                "registry": json.loads(REGISTRY.read_text()),
            },
            "observations": [
                json.dumps(value, sort_keys=True, separators=(",", ":")) for value in observations
            ],
        }
        if full:
            from tools.run_loopback_ack_crash_matrix import run_browser_handshake

            return run_browser_handshake(
                entry,
                workspace,
                socket,
                request,
                identity,
                evidence_binding,
                extension,
                binary,
                observations,
                browser_process=process, profile=profile, sentinel=sentinel,
                initial_sentinel=initial_sentinel,
            )
        worker_input = workspace / "input.json"
        worker_input.write_text(json.dumps(request, sort_keys=True))
        (workspace / "expected.json").write_text(
            json.dumps(entry["expected_post_restart_state"], sort_keys=True)
        )
        first_id = str(uuid4())
        checkpoint = _call(socket, "startWorker", first_id, request)
        if (
            any(checkpoint.get(key) != value for key, value in identity.items())
            or checkpoint.get("worker_id") != first_id
        ):
            raise ValueError("E_INDEXEDDB_CHECKPOINT_IDENTITY")
        if operation == "crash" and checkpoint.get("boundary") != entry["crash_checkpoint"]:
            raise ValueError("E_INDEXEDDB_CHECKPOINT")
        termination = _call(socket, "terminateWorker", first_id)
        if termination != {"method": "Worker.terminate", "worker_id": first_id}:
            raise ValueError("E_INDEXEDDB_TERMINATION")
        second_id = str(uuid4())
        # The reader receives a database identity only, no scenario or expected rows.
        reader = {
            "identity": binding,
            "options": request["options"],
            "operation": "read",
            "observations": [],
        }
        if mutation:
            reader["mutation"] = mutation
        reader_input = workspace / "reader-input.json"
        reader_input.write_text(json.dumps(reader, sort_keys=True))
        actual = _call(socket, "startWorker", second_id, reader)
        _call(socket, "terminateWorker", second_id)
        persisted = _call(socket, "readSentinel", profile_id)
        if (
            persisted.get("sentinel") != sentinel
            or persisted.get("profileId") != profile_id
            or (profile / "BH_R05_PROFILE_ID").read_text() != profile_id
        ):
            raise ValueError("E_INDEXEDDB_PROFILE")
        if actual.get("worker_id") != second_id:
            raise ValueError("E_INDEXEDDB_WORKER_IDENTITY")
        record = {
            "vector_id": entry["vector_id"],
            "case_id": entry["vector_id"],
            "identity": identity,
            "checkpoint": checkpoint,
            "termination": termination,
            "actual": actual,
            "execution_kind": "EXTENSION_DEDICATED_WORKER_TERMINATION",
            "executed": True,
            "launch_attempted": True,
            "evidence_binding": evidence_binding,
            "command_exit": {"browser": 0, "worker": 0, "reader": 0},
            "browser": {"executable": str(binary), "sha256": _sha256(binary)},
            "profile": str(profile),
            "source_sha256": _sha256(ROOT / "extension/src/spool.ts"),
            "observations": observations,
            "expected": entry["expected_post_restart_state"],
            "qualification_scope": "INDEXEDDB_SPOOL_ONLY",
            "legacy_full_qualification": "HOLD",
            "environment": {"system": platform.system(), "release": platform.release()},
            "input_sha256": _sha256(workspace / "input.json"),
            "expected_sha256": _sha256(workspace / "expected.json"),
            "module_hashes": {
                str(path.relative_to(extension)): _sha256(path)
                for path in sorted(extension.rglob("*.js"))
            },
        }
        (workspace / "observation.json").write_text(json.dumps(record, sort_keys=True))
        count = (
            2
            if operation == "exercise"
            else entry["expected_post_restart_state"]["indexeddb_spool_delta"]
        )
        compare_indexeddb_state(
            actual, identity, observations, count, ack=1 if operation == "exercise" else 0
        )
        if entry["expected_post_restart_state"] != original["expected_post_restart_state"]:
            raise ValueError("E_INDEXEDDB_EXPECTED")
        git = shutil.which("git")
        if git is None:
            raise ValueError("E_INDEXEDDB_REVISION_UNAVAILABLE")
        record["revision"] = run(  # noqa: S603 -- fixed local read-only revision query.
            [git, "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        record["result"] = "PASS"
        record["status"] = "PASS"
        record["comparison"] = {"matched": True, "scope": "INDEXEDDB_SPOOL_ONLY"}
        actual_artifact = workspace / "actual.json"
        actual_artifact.write_text(json.dumps(actual, sort_keys=True, separators=(",", ":")))
        record["actual_artifact"] = {
            "path": str(actual_artifact.resolve()),
            "sha256": _sha256(actual_artifact),
        }
        record["worker_input_artifact"] = {
            "path": str(worker_input.resolve()),
            "sha256": _sha256(worker_input),
        }
        record["reader_input_artifact"] = {
            "path": str(reader_input.resolve()),
            "sha256": _sha256(reader_input),
        }
        expected_artifact = workspace / "expected.json"
        record["expected_artifact"] = {
            "path": str(expected_artifact.resolve()),
            "sha256": _sha256(expected_artifact),
        }
        (workspace / "observation.json").write_text(json.dumps(record, sort_keys=True))
        record["artifact"] = str(workspace / "observation.json")
        record["artifact_sha256"] = _sha256(workspace / "observation.json")
        return record
    except _EnvironmentBlocked as error:
        return {
            "result": "BLOCKED_ENVIRONMENT",
            "status": "BLOCKED_ENVIRONMENT",
            "blocker_code": error.code,
            "blocker_detail": error.detail,
            "reason": error.code,
            "executed": False,
            "launch_attempted": False,
            "prerequisite": {"name": "Chrome for Testing extension origin", "available": False},
            "attempted_real_browser": True,
            "vector_id": entry["vector_id"],
            "case_id": entry["vector_id"],
        }
    finally:
        if process is not None and process.poll() is None:
            _kill_owned_process_group(process)


def run_full_repair_evidence(
    pack: Path,
    runtime: Path,
    workspace: Path,
    *,
    browser_binary: Path | None = None,
) -> dict[str, Any]:
    """Execute all registered durability owners and all governed clock vectors."""
    from tools.run_clock_vector_qualification import run_clock_vector_qualification
    from tools.run_destruction_crash_matrix import run_destruction_crash_matrix
    from tools.run_gap_coherence_crash_matrix import run_gap_coherence_crash_matrix
    from tools.run_loopback_ack_crash_matrix import run_loopback_ack_crash_matrix
    from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix
    from tools.verify_repair_evidence import aggregate_repair_evidence, full_required_ids

    workspace.mkdir(parents=True, exist_ok=False)
    registry = json.loads((pack / "docs/registries/crash-harness-registry.v1.json").read_text())
    owner_reports = {
        "SQLITE_TRANSACTION": run_sqlite_crash_matrix(pack, workspace / "sqlite"),
        "CHROME_INDEXEDDB": run_indexeddb_crash_matrix(
            pack, workspace / "indexeddb", browser_binary=browser_binary
        ),
        "LOOPBACK_ACK": run_loopback_ack_crash_matrix(
            pack, workspace / "loopback-ack", browser_binary=browser_binary
        ),
        "GAP_GENERATION_COHERENCE": run_gap_coherence_crash_matrix(
            pack, workspace / "gap-coherence"
        ),
        "WHOLE_RUN_DESTRUCTION": run_destruction_crash_matrix(
            pack, workspace / "destruction"
        ),
    }
    crash_by_id: dict[str, dict[str, Any]] = {}
    for harness, report in owner_reports.items():
        expected = [
            entry["vector_id"] for entry in registry["entries"] if entry["harness"] == harness
        ]
        records = report.get("records", [])
        actual = [row.get("case_id", row.get("vector_id")) for row in records]
        if actual != expected or report.get("executed_vector_ids") != expected:
            raise ValueError("E_FULL_OWNER_REQUIRED_CASES:" + harness)
        for row in records:
            case_id = row.get("case_id", row.get("vector_id"))
            if case_id in crash_by_id:
                raise ValueError("E_FULL_OWNER_DUPLICATE:" + str(case_id))
            crash_by_id[str(case_id)] = row
    crash = [crash_by_id[entry["vector_id"]] for entry in registry["entries"]]
    clock = run_clock_vector_qualification(
        pack,
        runtime,
        evidence_dir=workspace / "clock",
    )
    records = [*crash, *clock["records"]]
    aggregate = aggregate_repair_evidence(full_required_ids(), records)
    try:
        mutation_summary = validate_full_mutation_reports(pack, owner_reports, clock)
    except (KeyError, TypeError, ValueError, OSError) as error:
        mutation_summary = {"required": 105, "verified": 0, "survivors": None,
                            "complete": False, "error": str(error)}
        aggregate = {**aggregate, "result": "FAIL", "legacy_full_qualification": "HOLD",
                     "errors": [*aggregate["errors"],
                                {"case_id": "", "error": str(error)}]}
    result = {
        **aggregate,
        "records": records,
        "owner_reports": owner_reports,
        "clock_report": clock,
        "mutation_summary": mutation_summary,
    }
    if result["result"] == "PASS" and mutation_summary.get("complete") is True:
        from moj_discovery.durability_release import validate_full_durability_release

        required = full_required_ids()
        result["release_gate"] = validate_full_durability_release(
            required,
            required,
            mutation_survivors=0,
            evidence=records,
            mutation_summary=mutation_summary,
            mutation_evidence={"owner_reports": owner_reports, "clock_report": clock},
        )
    (workspace / "current-aggregate.json").write_text(json.dumps(result, sort_keys=True))
    return result


def required_clock_mutation_ids() -> list[str]:
    from tools.run_clock_vector_qualification import _MUTATION_NAMES

    return list(_MUTATION_NAMES)


def _owner_mutations(report: dict[str, Any]) -> list[dict[str, Any]]:
    if "mutation_results" in report:
        return list(report["mutation_results"])
    return [mutation for row in report.get("records", []) for mutation in row.get("mutations", [])]


def _mutation_id(row: dict[str, Any]) -> str:
    return str(row.get("mutation", row.get("vector_id", row.get("case_id", ""))))


def _verify_owner_mutation(
    harness: str, row: dict[str, Any], binding: dict[str, Any]
) -> None:
    if harness == "GAP_GENERATION_COHERENCE":
        from tools.run_gap_coherence_crash_matrix import verify_gap_mutation

        verify_gap_mutation(row, binding)
    elif harness == "WHOLE_RUN_DESTRUCTION":
        from tools.verify_destruction_evidence import verify_destruction

        execution = row["execution"]
        verify_destruction(execution, binding, mutation_type=row["kind"])
    else:
        from tools.verify_repair_evidence import verify_owner_mutation

        verify_owner_mutation(harness, row, binding)


def _verify_clock_mutation(row: dict[str, Any], binding: dict[str, Any]) -> None:
    from tools.run_clock_vector_qualification import verify_record

    if not verify_record(row, _current_binding=binding):
        raise ValueError("E_FULL_MUTATION_CLOCK_EVIDENCE")


def validate_full_mutation_reports(
    pack: Path,
    owner_reports: dict[str, dict[str, Any]],
    clock_report: dict[str, Any] | None,
) -> dict[str, Any]:
    """Require every registered mutation once and recursively verify its evidence."""
    from tools.verify_repair_evidence import capture_binding

    registry = json.loads((pack / "docs/registries/crash-harness-registry.v1.json").read_text())
    harnesses = list(dict.fromkeys(entry["harness"] for entry in registry["entries"]))
    if set(owner_reports) != set(harnesses):
        raise ValueError("E_FULL_MUTATION_OWNER_SET")
    expected_by_harness = {
        harness: [
            mutation
            for entry in registry["entries"]
            if entry["harness"] == harness
            for mutation in entry["mutation_vector_ids"]
        ]
        for harness in harnesses
    }
    if clock_report is None:
        raise ValueError("E_FULL_MUTATION_CLOCK_EVIDENCE")
    binding = capture_binding()
    verified = 0
    survivors = 0
    for harness, expected in expected_by_harness.items():
        mutations = _owner_mutations(owner_reports[harness])
        if [_mutation_id(row) for row in mutations] != expected:
            raise ValueError("E_FULL_MUTATION_REQUIRED_SET:" + harness)
        for row in mutations:
            if row.get("detected") is not True:
                survivors += 1
                raise ValueError("E_FULL_MUTATION_SURVIVOR:" + _mutation_id(row))
            _verify_owner_mutation(harness, row, binding)
            verified += 1
    clock_mutations = list(clock_report.get("mutation_records", []))
    expected_clock = required_clock_mutation_ids()
    if [_mutation_id(row) for row in clock_mutations] != expected_clock:
        raise ValueError("E_FULL_MUTATION_REQUIRED_SET:CLOCK")
    for row in clock_mutations:
        if row.get("detected") is not True or row.get("executed") is not True:
            raise ValueError("E_FULL_MUTATION_SURVIVOR:" + _mutation_id(row))
        _verify_clock_mutation(row, binding)
        verified += 1
    return {"required": 105, "verified": verified, "survivors": survivors,
            "complete": verified == 105 and survivors == 0}


def run_indexeddb_crash_matrix(
    pack: Path,
    workspace: Path,
    *,
    browser_binary: Path | None = None,
    full: bool = True,
) -> dict[str, Any]:
    entries = json.loads((pack / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    selected = [entry for entry in entries if entry["harness"] == "CHROME_INDEXEDDB"]
    required = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    required_ids = [
        entry["vector_id"] for entry in required if entry["harness"] == "CHROME_INDEXEDDB"
    ]
    if [entry["vector_id"] for entry in selected] != required_ids:
        raise ValueError("E_INDEXEDDB_REQUIRED_CASES")
    records = [
        run_indexeddb_case(
            entry,
            workspace / f"case-{uuid4()}",
            browser_binary=browser_binary,
            full=full,
        )
        for entry in selected
    ]
    return {
        "result": "PASS"
        if all(row["result"] == "PASS" for row in records)
        else "BLOCKED_ENVIRONMENT",
        "executed_vector_ids": [row["vector_id"] for row in records if row["result"] == "PASS"],
        "records": records,
        "killed_child_count": sum(row["result"] == "PASS" for row in records),
        "qualification_scope": "BROWSER_LOOPBACK_ACK" if full else "INDEXEDDB_SPOOL_ONLY",
        "legacy_full_qualification": "HOLD",
    }
