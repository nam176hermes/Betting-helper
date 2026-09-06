"""Deterministic aggregation for the two isolated review roles."""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .review_authorization import verify_review_execution_receipt

RESULT_DOMAIN = b"HD636/REVIEW-RESULT/v1\0"
_IMPLEMENTATION_FLAGS = (
    "REPO0_BASELINE_VALID", "SAFE_TO_IMPLEMENT_R0", "SAFE_TO_IMPLEMENT_F0A",
    "SAFE_TO_IMPLEMENT_SEC0", "SAFE_TO_IMPLEMENT_E0", "SAFE_TO_IMPLEMENT_D0",
)
_SECURITY_FLAGS = (
    "CYBERSECURITY_REVIEW_COMPLETE", "CHROME_CAPABILITY_BOUNDARY_PASS",
    "AUTHORIZATION_TRUST_PASS", "CREDENTIAL_EVIDENCE_BOUNDARY_PASS",
    "HASHING_CRYPTOGRAPHY_PASS", "CUSTODY_ISOLATION_PASS",
)
_SEVERITY = {"CRITICAL": 0, "IMPORTANT": 1, "MINOR": 2}


def _digest(value: object) -> str:
    return hashlib.sha256(rfc8785.dumps(cast(Any, value))).hexdigest()


def review_content_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        RESULT_DOMAIN + rfc8785.dumps(cast(Any, {key: item for key, item in value.items() if key != "content_hash"}))
    ).hexdigest()


def _instant(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError("E_REVIEW_FRESHNESS") from error
    if result.tzinfo is None:
        raise ValueError("E_REVIEW_FRESHNESS")
    return result.astimezone(UTC)


def _complete_receipt(receipt: dict[str, object], role: str) -> None:
    required = {
        "authorization_id", "review_role", "review_run_id", "workspace_root", "input_content_roots",
        "result_sha256", "commands_executed_root", "finished_at", "fresh_session_attestation",
        "production_authority", "signature_algorithm", "signature", "host_boot_id", "trust_epoch",
        "preparation_commands_root",
    }
    if not required <= set(receipt) or receipt.get("review_role") != role:
        raise ValueError("E_REVIEW_RECEIPT")
    roots = receipt["input_content_roots"]
    fresh = receipt["fresh_session_attestation"]
    if (
        not isinstance(roots, list)
        or len(roots) != 5
        or not all(isinstance(item, str) and len(item) == 64 for item in roots)
        or not isinstance(fresh, dict)
        or fresh.get("attested") is not True
        or fresh.get("procedural_not_cryptographic") is not True
        or receipt.get("production_authority") != "NONE"
        or receipt.get("signature_algorithm") != "Ed25519"
    ):
        raise ValueError("E_REVIEW_RECEIPT")


def _review_is_well_formed(review: dict[str, object], role: str) -> None:
    if (
        review.get("schema_version") != "independent-review-result/v1"
        or review.get("review_role") != role
        or review.get("authorized_production_phases") != "NONE"
        or review.get("content_hash") != review_content_hash(review)
        or not isinstance(review.get("findings"), list)
        or not isinstance(review.get("verdicts"), dict)
    ):
        raise ValueError("E_REVIEW_RESULT")


def _has_blocking_findings(review: dict[str, object]) -> bool:
    return any(
        isinstance(item, dict) and item.get("blocking") is True
        for item in cast(list[object], review["findings"])
    )


def aggregate_independent_reviews(
    implementation: dict[str, object],
    cybersecurity: dict[str, object],
    implementation_receipt: dict[str, object],
    cybersecurity_receipt: dict[str, object],
    implementation_authorization: dict[str, object],
    cybersecurity_authorization: dict[str, object],
    public_key: Ed25519PublicKey,
    config: dict[str, object],
    *,
    expected_host_boot_id: str,
    expected_trust_epoch: int,
    now: datetime | None = None,
) -> dict[str, object]:
    if config.get("authorized_production_phases") != "NONE":
        raise ValueError("E_REVIEW_AUTHORITY")
    _review_is_well_formed(implementation, "IMPLEMENTATION_READINESS_REVIEWER")
    _review_is_well_formed(cybersecurity, "CYBERSECURITY_REVIEWER")
    verify_review_execution_receipt(
        implementation_receipt,
        implementation_authorization,
        public_key,
        result_sha256=_digest(implementation),
        expected_host_boot_id=expected_host_boot_id,
        expected_trust_epoch=expected_trust_epoch,
        now=now,
    )
    verify_review_execution_receipt(
        cybersecurity_receipt,
        cybersecurity_authorization,
        public_key,
        result_sha256=_digest(cybersecurity),
        expected_host_boot_id=expected_host_boot_id,
        expected_trust_epoch=expected_trust_epoch,
        now=now,
    )
    _complete_receipt(implementation_receipt, "IMPLEMENTATION_READINESS_REVIEWER")
    _complete_receipt(cybersecurity_receipt, "CYBERSECURITY_REVIEWER")
    if (
        implementation.get("pack_zip_sha256") != cybersecurity.get("pack_zip_sha256")
        or implementation.get("repo0_receipt_sha256") != cybersecurity.get("repo0_receipt_sha256")
        or implementation_receipt["workspace_root"] == cybersecurity_receipt["workspace_root"]
        or implementation_receipt["authorization_id"] == cybersecurity_receipt["authorization_id"]
        or implementation_receipt["review_run_id"] == cybersecurity_receipt["review_run_id"]
        or implementation_receipt["input_content_roots"] != cybersecurity_receipt["input_content_roots"]
        or implementation_authorization.get("one_use_serial")
        == cybersecurity_authorization.get("one_use_serial")
        or implementation_authorization.get("allowed_output_root")
        == cybersecurity_authorization.get("allowed_output_root")
    ):
        raise ValueError("E_REVIEW_INDEPENDENCE")
    if (
        implementation_receipt["result_sha256"] != _digest(implementation)
        or cybersecurity_receipt["result_sha256"] != _digest(cybersecurity)
    ):
        raise ValueError("E_REVIEW_RECEIPT")
    aggregate_at = (now or datetime.now(UTC)).astimezone(UTC)
    latest_finish = max(_instant(implementation_receipt["finished_at"]), _instant(cybersecurity_receipt["finished_at"]))
    delay = config.get("maximum_aggregate_delay_seconds")
    if not isinstance(delay, int) or isinstance(delay, bool):
        raise ValueError("E_REVIEW_FRESHNESS")
    if (aggregate_at - latest_finish).total_seconds() > delay:
        raise ValueError("E_REVIEW_FRESHNESS")
    implementation_verdicts = implementation["verdicts"]
    cybersecurity_verdicts = cybersecurity["verdicts"]
    assert isinstance(implementation_verdicts, dict) and isinstance(cybersecurity_verdicts, dict)
    if implementation_verdicts.get("AUTHORIZED_PRODUCTION_PHASES") != "NONE" or cybersecurity_verdicts.get("AUTHORIZED_PRODUCTION_PHASES") != "NONE":
        raise ValueError("E_REVIEW_AUTHORITY")
    ready = implementation_verdicts.get("READY_TO_IMPLEMENT_DISCOVERY_PACK")
    if ready == "YES" and any(implementation_verdicts.get(flag) != "YES" for flag in _IMPLEMENTATION_FLAGS):
        raise ValueError("E_REVIEW_PREREQUISITES")
    security_complete = all(cybersecurity_verdicts.get(flag) == "YES" for flag in _SECURITY_FLAGS)
    passed = (
        implementation.get("review_outcome") == "PASS"
        and cybersecurity.get("review_outcome") == "PASS"
        and ready == "YES"
        and security_complete
        and not _has_blocking_findings(implementation)
        and not _has_blocking_findings(cybersecurity)
    )
    findings = [
        *cast(list[object], implementation["findings"]),
        *cast(list[object], cybersecurity["findings"]),
    ]
    if not all(isinstance(item, dict) for item in findings):
        raise ValueError("E_REVIEW_RESULT")
    finding_rows = [cast(dict[str, object], item) for item in findings]
    ids = [str(item.get("finding_id")) for item in finding_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("E_REVIEW_FINDINGS")
    finding_rows.sort(key=lambda item: (_SEVERITY.get(str(item.get("severity")), 99), str(item.get("finding_id"))))
    result_hashes = [
        _digest(implementation), _digest(cybersecurity), _digest(implementation_receipt), _digest(cybersecurity_receipt)
    ]
    aggregate_name = hashlib.sha256(
        b"".join(bytes.fromhex(value) for value in result_hashes)
    ).hexdigest()
    aggregate: dict[str, object] = {
        "schema_version": "independent-review-result/v1",
        "review_role": "AGGREGATE_REVIEWER",
        "review_outcome": "PASS" if passed else "HOLD",
        "findings": finding_rows,
        "pack_zip_sha256": implementation["pack_zip_sha256"],
        "repo0_receipt_sha256": implementation["repo0_receipt_sha256"],
        "review_run_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "hd634:" + aggregate_name)),
        "implementation_review_sha256": result_hashes[0],
        "cybersecurity_review_sha256": result_hashes[1],
        "implementation_receipt_sha256": result_hashes[2],
        "cybersecurity_receipt_sha256": result_hashes[3],
        "verdicts": {
            **{flag: implementation_verdicts.get(flag, "NO") for flag in _IMPLEMENTATION_FLAGS},
            "READY_TO_IMPLEMENT_DISCOVERY_PACK": "YES" if passed else "NO",
            "SAFE_TO_FREEZE_SCOPE0": implementation_verdicts.get("SAFE_TO_FREEZE_SCOPE0", "NO"),
            "AUTHORIZED_PRODUCTION_PHASES": "NONE",
        },
        "authorized_production_phases": "NONE",
    }
    aggregate["content_hash"] = review_content_hash(aggregate)
    return aggregate


def build_plan_self_review(record: dict[str, object]) -> dict[str, object]:
    forbidden = {"zip_sha256", "zip", "sidecar", "manifest_sha256", "final_manifest_sha256"}
    required = {
        "schema_version", "governed_content_root", "task_manifest_sha256", "checks", "test_exit_code",
        "test_output_sha256", "independent_plan_review", "runtime_implementation_ready", "authorized_production_phases",
    }
    if set(record) != required or forbidden & set(record) or record.get("schema_version") != "plan-self-review/v1":
        raise ValueError("E_SELF_REVIEW_BINDING")
    if (
        record.get("test_exit_code") != 0
        or record.get("independent_plan_review") != "PENDING"
        or record.get("runtime_implementation_ready") != "NO"
        or record.get("authorized_production_phases") != "NONE"
    ):
        raise ValueError("E_SELF_REVIEW_BINDING")
    return record
