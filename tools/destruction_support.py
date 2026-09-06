"""Disposable-owner destruction mechanics; not a user-run authorization subsystem.

The signing key is the governed public RFC8032 mechanism-test key, never trusted
for production. Only stores created under an exclusive owner marker are eligible.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from moj_discovery.authorization_semantics import SIGNATURE_DOMAIN, _signature_is_valid
from moj_discovery.canonical import canonical_content_hash
from moj_discovery.ingest import Ingestor
from moj_discovery.schema_registry import validate_artifact
from moj_discovery.store import VENDOR, RunStore, _runtime_authorizer
from tools.gap_state_reader import read_gap_state
from tools.loopback_ack_crash_child import position, provision
from tools.run_indexeddb_crash_matrix import _call

ARTIFACTS = ["GAPS", "MAPPINGS", "MAPPING_CLOSURES", "DERIVED_REVISIONS", "PRE_DELETE_INVENTORY"]
TEST_SCOPE = "DISPOSABLE_DESTRUCTION_OWNER_ONLY_NO_EXTERNAL_AUTHORITY"
CREATED_AT = "2030-01-01T00:00:00.000000Z"


def digest(value: Any) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def content_hash(value: dict[str, Any]) -> str:
    return canonical_content_hash(
        value["record_type"],
        value,
        registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
    )


def immutable_json(path: Path, value: Any) -> None:
    """Exclusive, flushed external artifacts; replay must be byte-identical."""
    raw = rfc8785.dumps(value)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError("E_DESTRUCTION_IMMUTABLE_ARTIFACT")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def owned_case(case: Path, run_id: str) -> Path:
    if str(UUID(run_id, version=4)) != run_id:
        raise ValueError("E_DESTRUCTION_RUN_ID")
    if case.is_symlink() or not case.is_absolute() or case == Path("/"):
        raise ValueError("E_DESTRUCTION_DISPOSABLE_ONLY")
    marker = case / "DISPOSABLE_OWNER.json"
    if marker.is_symlink() or json.loads(marker.read_text()) != {
        "scope": TEST_SCOPE,
        "case_directory": str(case),
        "run_id": run_id,
    }:
        raise ValueError("E_DESTRUCTION_DISPOSABLE_ONLY")
    for path in (
        case / run_id,
        case / run_id / "run.sqlite3",
        case / ".local",
        case / ".local/destruction",
    ):
        if path.is_symlink():
            raise ValueError("E_DESTRUCTION_DISPOSABLE_ONLY")
    return case / run_id / "run.sqlite3"


def worker_read(
    config: dict[str, Any], operation: str = "destruction-read", **extra: Any
) -> dict[str, Any]:
    worker = str(uuid4())
    request = {
        "identity": config["identity"],
        "options": config["options"],
        "operation": operation,
        "observations": [],
        **extra,
    }
    try:
        result = _call(config["socket"], "startWorker", worker, request)
    finally:
        _call(config["socket"], "terminateWorker", worker)
    if result.get("worker_id") != worker or any(
        result.get(key) != value for key, value in config["identity"].items()
    ):
        raise ValueError("E_DESTRUCTION_BROWSER_IDENTITY")
    return result


def read_actual(case: Path, config: dict[str, Any]) -> dict[str, Any]:
    run_id = config["identity"]["run_id"]
    database = owned_case(case, run_id)
    external = case / ".local/destruction"
    files = {
        kind: external / f"{run_id}.{suffix}.json"
        for kind, suffix in (("intent", "intent"), ("proof", "deletion-proof"))
    }
    if any(path.is_symlink() for path in files.values()):
        raise ValueError("E_DESTRUCTION_DISPOSABLE_ONLY")
    return {
        "browser": worker_read(config),
        "backend": {
            "present": database.is_file(),
            "state": read_gap_state(database.parent) if database.is_file() else None,
        },
        "external": {
            kind: json.loads(path.read_text()) if path.is_file() else None
            for kind, path in files.items()
        },
        "database_files": sorted(path.name for path in database.parent.iterdir()),
    }


def inventory(actual: dict[str, Any]) -> dict[str, Any]:
    browser = actual["browser"]
    return {
        "browser": {
            key: browser[key] for key in ("database_name", "present", "states", "entries", "keys")
        },
        "backend": copy.deepcopy(actual["backend"]),
    }


def prepare_backend(case: Path, observation: dict[str, Any]) -> dict[str, Any]:
    owned_case(case, observation["discovery_run_id"])
    store = provision(case, observation)
    ack = Ingestor(store).apply(observation)
    Ingestor(store).confirm_ack(ack)
    # Governed gap transaction closes the predecessor and coherence epoch.
    try:
        Ingestor(store).apply(position(observation, 3))
    except ValueError as error:
        if str(error) != "E_INGEST_GAP":
            raise
    else:
        raise ValueError("E_DESTRUCTION_GAP_FIXTURE")
    with closing(store.connect()) as connection, connection:
        connection.execute(
            "UPDATE stream_generations SET generation_state='CLOSED',"
            "closed_at_us=max(opened_at_us,10),close_reason='RUN_CLOSED' "
            "WHERE generation_state='ACTIVE'"
        )
        connection.execute(
            "UPDATE stream_generations SET generation_state='CLOSED' "
            "WHERE generation_state='QUARANTINED_GAP'"
        )
        connection.execute("UPDATE run_meta SET run_status='CLOSED',closed_at_us=10")
    return ack


def make_plan(run_id: str, captured: dict[str, Any]) -> dict[str, Any]:
    exported = {
        "test_scope": TEST_SCOPE,
        "run_id": run_id,
        "inventory": inventory(captured),
        "required_artifacts": ARTIFACTS,
    }
    vectors = json.loads((VENDOR / "vectors/authorization-v1.json").read_text())
    receipt = copy.deepcopy(
        vectors["test_only_signed_record_vectors"]["base_records"][
            "EvidenceExportAcceptedGateReceipt"
        ]
    )
    receipt.update(
        record_id=str(uuid4()),
        bound_run_id=run_id,
        accepted_sanitized_export_manifest_hash=digest(exported),
    )
    receipt["content_hash"] = content_hash(receipt)
    key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(vectors["rfc8032_test_vector_1"]["seed_hex"])
    )
    receipt["signature"] = (
        base64.urlsafe_b64encode(
            key.sign(SIGNATURE_DOMAIN + bytes.fromhex(receipt["content_hash"]))
        )
        .decode()
        .rstrip("=")
    )
    intent = {
        "record_type": "RunDestructionIntent",
        "schema_version": "1",
        "destruction_intent_id": "DESTRUCTION_INTENT:" + os.urandom(32).hex(),
        "content_hash_algorithm": "HD-JCS-SHA256-v1",
        "content_hash_domain": "HYBRID-DISCOVERY/v6.2/RunDestructionIntent/v1\0",
        "content_hash": "0" * 64,
        "run_id": run_id,
        "run_state": "RUN_CLOSED",
        "writer_count": "0",
        "export_status": "VALIDATED_REPLAYED_SECRET_SCANNED_ACCEPTED",
        "accepted_sanitized_export_manifest_hash": digest(exported),
        "accounting_status": "ALL_ROWS_ACK_CHAIN_OR_EXPLICIT_GAP_EXPORT_ACCOUNTED",
        "required_artifacts_included": ARTIFACTS,
        "destruction_authorization_id": receipt["record_id"],
        "destruction_gate_receipt_content_hash": receipt["content_hash"],
        "destruction_gate_receipt": receipt,
        "destruction_gate_receipt_verification": (
            "CANONICAL_BYTES_CONTENT_HASH_AND_ED25519_SIGNATURE_VERIFIED_BEFORE_CONSUMPTION"
        ),
        "destruction_authorization_consumption_id": "AUTHORIZATION_CONSUMPTION:"
        + os.urandom(32).hex(),
        "destruction_authority_consumption_state": "COMMITTED_BEFORE_WHOLE_RUN_DESTRUCTION",
        "human_invocation": True,
        "human_invocation_mode": "EXPLICIT_HUMAN_INVOCATION",
        "pre_delete_inventory_hash": digest(exported["inventory"]),
        "external_intent_path": f".local/destruction/{run_id}.intent.json",
        "created_at": CREATED_AT,
        "immutable": True,
    }
    intent["content_hash"] = content_hash(intent)
    plan = {"test_scope": TEST_SCOPE, "run_id": run_id, "export": exported, "intent": intent}
    validate_plan(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> None:
    intent, exported = plan["intent"], plan["export"]
    receipt = intent["destruction_gate_receipt"]
    if plan["test_scope"] != TEST_SCOPE or exported["test_scope"] != TEST_SCOPE:
        raise ValueError("E_DESTRUCTION_DISPOSABLE_ONLY")
    if intent["human_invocation"] is not True:
        raise ValueError("E_DESTRUCTION_HUMAN_INVOCATION")
    if not (plan["run_id"] == intent["run_id"] == exported["run_id"] == receipt["bound_run_id"]):
        raise ValueError("E_DESTRUCTION_AUTHORITY_RUN")
    if intent["pre_delete_inventory_hash"] != digest(exported["inventory"]):
        raise ValueError("E_DESTRUCTION_INVENTORY_HASH")
    if not (
        intent["accepted_sanitized_export_manifest_hash"]
        == receipt["accepted_sanitized_export_manifest_hash"]
        == digest(exported)
    ):
        raise ValueError("E_DESTRUCTION_AUTHORITY_HASH")
    if (
        intent["external_intent_path"] != f".local/destruction/{plan['run_id']}.intent.json"
        or intent["destruction_authorization_id"] != receipt["record_id"]
        or intent["destruction_gate_receipt_content_hash"] != receipt["content_hash"]
        or intent["content_hash"] != content_hash(intent)
    ):
        raise ValueError("E_DESTRUCTION_INTENT_PRECOMMIT")
    validate_artifact(intent, "durability-records.schema.json", bootstrap_only=True, vendor=VENDOR)
    vectors = json.loads((VENDOR / "vectors/authorization-v1.json").read_text())
    test = vectors["rfc8032_test_vector_1"]
    if (
        receipt["issuer_key_id"] != test["key_id"]
        or receipt["issuer_role"] != "PACK_REVIEWER"
        or receipt["audience"] != "hybrid-discovery:bootstrap-gate:v1"
        or receipt["content_hash"] != content_hash(receipt)
        or not _signature_is_valid(
            receipt, Ed25519PublicKey.from_public_bytes(bytes.fromhex(test["public_key_hex"]))
        )
    ):
        raise ValueError("E_DESTRUCTION_AUTHORITY_SIGNATURE")


def consumption(plan: dict[str, Any]) -> dict[str, Any]:
    intent = plan["intent"]
    receipt = intent["destruction_gate_receipt"]
    return {
        "consumption_id": intent["destruction_authorization_consumption_id"],
        "run_id": plan["run_id"],
        "receipt_record_type": receipt["record_type"],
        "receipt_schema_version": receipt["schema_version"],
        "receipt_id": receipt["record_id"],
        "destruction_intent_id": intent["destruction_intent_id"],
        "precommitted_destruction_intent_content_hash": intent["content_hash"],
        "staged_pre_delete_inventory_hash": intent["pre_delete_inventory_hash"],
        "staged_intent_created_at": intent["created_at"],
        "intent_authorization_id": receipt["record_id"],
        "intent_consumption_id": intent["destruction_authorization_consumption_id"],
        "intent_run_id": plan["run_id"],
        "receipt_scope": receipt["scope"],
        "gate_kind": receipt["gate_kind"],
        "gate_result": receipt["gate_result"],
        "receipt_bound_run_id": receipt["bound_run_id"],
        "accepted_sanitized_export_manifest_hash": intent[
            "accepted_sanitized_export_manifest_hash"
        ],
        "receipt_bound_sanitized_export_manifest_hash": receipt[
            "accepted_sanitized_export_manifest_hash"
        ],
        **{
            key: receipt[key]
            for key in (
                "issuer",
                "issuer_key_id",
                "audience",
                "serial",
                "nonce",
                "signature_algorithm",
                "signature",
                "one_use",
                "declared_use_semantics",
                "consumed_before",
            )
        },
        "scope_binding_hash": digest(
            {
                "run_id": plan["run_id"],
                "manifest": receipt["accepted_sanitized_export_manifest_hash"],
            }
        ),
        "receipt_content_hash": receipt["content_hash"],
        "intent_receipt_content_hash": receipt["content_hash"],
        "receipt_verification_state": "CANONICAL_BYTES_CONTENT_HASH_AND_ED25519_SIGNATURE_VERIFIED",
        "consumption_commit_state": "COMMITTED_BEFORE_WHOLE_RUN_DESTRUCTION",
        "explicit_human_invocation": 1,
        "verifier_clock_domain_id": plan["run_id"],
        "verifier_boot_id": plan["run_id"],
        "verifier_clock_unit": "MICROSECOND",
        "verifier_monotonic_value": 10,
        "verifier_clock_resolution_us": 1,
        "consumed_at_us": 10,
    }


def insert_consumption(connection: sqlite3.Connection, values: dict[str, Any]) -> None:
    def owner_authorizer(
        action: int, first: str | None, second: str | None, db: str | None, trigger: str | None
    ) -> int:
        if action == sqlite3.SQLITE_FUNCTION and second in {"substr", "instr", "replace"}:
            return sqlite3.SQLITE_OK
        return _runtime_authorizer(action, first, second, db, trigger)

    # Only this disposable test owner needs the governed consumption-trigger functions.
    connection.set_authorizer(owner_authorizer)
    if not values or any(not key.replace("_", "").isalnum() for key in values):
        raise ValueError("E_DESTRUCTION_CONSUMPTION_COLUMNS")
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO authorization_consumptions ({columns}) VALUES ({placeholders})",  # noqa: S608
        tuple(values.values()),
    )


def validate_consumed(case: Path, plan: dict[str, Any]) -> None:
    database = owned_case(case, plan["run_id"])
    validate_plan(plan)
    expected = consumption(plan)
    if database.exists():
        with closing(RunStore(database).connect()) as connection:
            rows = [
                dict(row) for row in connection.execute("SELECT * FROM authorization_consumptions")
            ]
        if rows != [expected]:
            raise ValueError("E_DESTRUCTION_AUTHORITY_REQUIRED")
    else:
        saved = case / "consumed-external.json"
        if not saved.is_file() or json.loads(saved.read_text()) != expected:
            raise ValueError("E_DESTRUCTION_AUTHORITY_REQUIRED")


def persist_intent(case: Path, plan: dict[str, Any]) -> None:
    validate_consumed(case, plan)
    immutable_json(case / plan["intent"]["external_intent_path"], plan["intent"])
    database = owned_case(case, plan["run_id"])
    if database.exists():
        with closing(RunStore(database).connect()) as connection, connection:
            if connection.execute("SELECT run_status FROM run_meta").fetchone()[0] == "CLOSED":
                connection.execute("UPDATE run_meta SET run_status='DESTRUCTION_PENDING'")


def validate_external(case: Path, plan: dict[str, Any]) -> None:
    validate_consumed(case, plan)
    path = case / plan["intent"]["external_intent_path"]
    if (
        not path.is_file()
        or path.is_symlink()
        or path.read_bytes() != rfc8785.dumps(plan["intent"])
    ):
        raise ValueError("E_DESTRUCTION_INTENT_PRECOMMIT")


def delete_backend(case: Path, plan: dict[str, Any]) -> None:
    validate_external(case, plan)
    database = owned_case(case, plan["run_id"])
    # Never recursive: exclusively the disposable database and SQLite sidecars.
    for suffix in ("", "-journal", "-wal", "-shm"):
        target = Path(str(database) + suffix)
        if target.is_symlink():
            raise ValueError("E_DESTRUCTION_DISPOSABLE_ONLY")
        if target.exists():
            target.unlink()
    fd = os.open(database.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_proof(case: Path, config: dict[str, Any], plan: dict[str, Any]) -> None:
    validate_external(case, plan)
    state = read_actual(case, config)
    if state["browser"]["present"] or state["backend"]["present"]:
        raise ValueError("E_DESTRUCTION_PROOF_STORES_PRESENT")
    path = case / f".local/destruction/{plan['run_id']}.deletion-proof.json"
    if path.exists():
        proof = json.loads(path.read_text())
        validate_artifact(
            proof, "durability-records.schema.json", bootstrap_only=True, vendor=VENDOR
        )
        if (
            proof["content_hash"] != content_hash(proof)
            or proof["run_id"] != plan["run_id"]
            or proof["destruction_intent_id"] != plan["intent"]["destruction_intent_id"]
            or proof["external_proof_path"] != str(path.relative_to(case))
            or proof["extension_store_state"] != "DELETED"
            or proof["backend_store_state"] != "DELETED"
            or proof["proof_state"] != "COMPLETE_LOGICAL_DELETION"
        ):
            raise ValueError("E_DESTRUCTION_PROOF")
        return
    proof = {
        "record_type": "DeletionProof",
        "schema_version": "1",
        "content_hash": "0" * 64,
        "deletion_proof_id": "DELETION_PROOF:" + os.urandom(32).hex(),
        "run_id": plan["run_id"],
        "destruction_intent_id": plan["intent"]["destruction_intent_id"],
        "extension_store_state": "DELETED",
        "backend_store_state": "DELETED",
        "proof_state": "COMPLETE_LOGICAL_DELETION",
        "external_proof_path": str(path.relative_to(case)),
        "secure_erasure_claim": False,
        "completed_at": CREATED_AT,
        "immutable": True,
    }
    proof["content_hash"] = content_hash(proof)
    validate_artifact(proof, "durability-records.schema.json", bootstrap_only=True, vendor=VENDOR)
    immutable_json(path, proof)
