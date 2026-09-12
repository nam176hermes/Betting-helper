import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from moj_discovery import review_authorization as authorization
from moj_discovery.review_aggregation import (
    aggregate_independent_reviews,
    build_plan_self_review,
    review_content_hash,
)
from moj_discovery.review_authorization import (
    sign_review_execution_receipt,
    sign_review_launch_authorization,
)
from tests.release.test_descendant_repository_qualification import SOURCE_CONFIG
from tools.sync_pack_assets import sync_pack_assets

NOW = datetime(2026, 9, 5, tzinfo=UTC)
CONFIG = {"authorized_production_phases": "NONE", "maximum_aggregate_delay_seconds": 3600}


def _review(role: str) -> dict[str, object]:
    verdicts = {
        "AUTHORIZED_PRODUCTION_PHASES": "NONE",
        "SAFE_TO_FREEZE_SCOPE0": "NO",
    }
    if role == "IMPLEMENTATION_READINESS_REVIEWER":
        verdicts.update(
            {
                "REPO0_BASELINE_VALID": "YES",
                "READY_TO_IMPLEMENT_DISCOVERY_PACK": "YES",
                "SAFE_TO_IMPLEMENT_R0": "YES",
                "SAFE_TO_IMPLEMENT_F0A": "YES",
                "SAFE_TO_IMPLEMENT_SEC0": "YES",
                "SAFE_TO_IMPLEMENT_E0": "YES",
                "SAFE_TO_IMPLEMENT_D0": "YES",
            }
        )
    else:
        verdicts.update(
            {
                "CYBERSECURITY_REVIEW_COMPLETE": "YES",
                "CHROME_CAPABILITY_BOUNDARY_PASS": "YES",
                "AUTHORIZATION_TRUST_PASS": "YES",
                "CREDENTIAL_EVIDENCE_BOUNDARY_PASS": "YES",
                "HASHING_CRYPTOGRAPHY_PASS": "YES",
                "CUSTODY_ISOLATION_PASS": "YES",
            }
        )
    value: dict[str, object] = {
        "schema_version": "independent-review-result/v1",
        "review_role": role,
        "review_outcome": "PASS",
        "findings": [],
        "pack_zip_sha256": "a" * 64,
        "repo0_receipt_sha256": "b" * 64,
        "review_run_id": (
            "11111111-1111-4111-8111-111111111111"
            if role == "IMPLEMENTATION_READINESS_REVIEWER"
            else "22222222-2222-4222-8222-222222222222"
        ),
        "verdicts": verdicts,
        "authorized_production_phases": "NONE",
    }
    value["content_hash"] = review_content_hash(value)
    return value


def _authorization(
    review: dict[str, object],
    workspace: str,
    output: str,
    serial: str,
    private: Ed25519PrivateKey,
) -> dict[str, object]:
    issued = NOW - timedelta(minutes=1)
    return sign_review_launch_authorization(
        {
            "schema_version": "review-launch-authorization/v1",
            "issuer_role": "HOST_REVIEW_AUTHORITY",
            "audience": "hybrid-discovery:independent-review-launcher:v1",
            "review_role": review["review_role"],
            "review_run_id": review["review_run_id"],
            "pack_zip_sha256": review["pack_zip_sha256"],
            "pack_manifest_sha256": "9" * 64,
            "repo0_receipt_sha256": review["repo0_receipt_sha256"],
            "repo0_commit_oid": "a" * 40,
            "repo0_tree_oid": "b" * 40,
            "repo0_file_tree_root_sha256": "c" * 64,
            "workspace_root": workspace,
            "input_mounts": [
                {
                    "source_root": f"/sealed/input-{index}",
                    "workspace_mount": f"/sealed/input-{index}",
                    "mode": "READ_ONLY",
                    "content_root_sha256": sha256(f"input-{index}".encode()).hexdigest(),
                }
                for index in range(5)
            ],
            "excluded_roots": ["/authoring", "/peer"],
            "allowed_output_root": output,
            "prompt_sha256": "d" * 64,
            "command_registry_sha256": "e" * 64,
            "issued_at": issued.isoformat(),
            "not_before": issued.isoformat(),
            "expires_at": (issued + timedelta(seconds=14400)).isoformat(),
            "maximum_duration_seconds": 14400,
            "one_use_serial": serial,
            "nonce": "A" * 43,
            "fresh_session_required": True,
            "production_authority": "NONE",
            "signature_algorithm": "Ed25519",
            "host_boot_id": "00000000-0000-0000-0000-000000000000",
            "trust_epoch": 0,
        },
        private,
    )


def _receipt(
    review: dict[str, object],
    authorization: dict[str, object],
    private: Ed25519PrivateKey,
) -> dict[str, object]:
    return sign_review_execution_receipt(
        {
            "schema_version": "review-execution-receipt/v1",
            "authorization_id": authorization["authorization_id"],
            "issuer_role": "HOST_REVIEW_AUTHORITY",
            "review_role": review["review_role"],
            "review_run_id": review["review_run_id"],
            "workspace_root": authorization["workspace_root"],
            "workspace_attestation_sha256": "f" * 64,
            "input_content_roots": [
                sha256(f"input-{index}".encode()).hexdigest() for index in range(5)
            ],
            "result_sha256": sha256(__import__("rfc8785").dumps(review)).hexdigest(),
            "commands_executed_root": "c" * 64,
            "allowed_changed_paths": ["result.json"],
            "unexpected_changed_paths": [],
            "started_at": (NOW - timedelta(seconds=30)).isoformat(),
            "finished_at": NOW.isoformat(),
            "authorization_consumed_at": (NOW - timedelta(seconds=30)).isoformat(),
            "fresh_session_attestation": {
                "attestation_type": "HUMAN_FRESH_CODEX_SESSION",
                "attested": True,
                "attested_by": "reviewer",
                "attested_at": NOW.isoformat(),
                "procedural_not_cryptographic": True,
            },
            "production_authority": "NONE",
            "signature_algorithm": "Ed25519",
            "host_boot_id": "00000000-0000-0000-0000-000000000000",
            "trust_epoch": 0,
            "preparation_commands_root": "d" * 64,
        },
        private,
    )


def _aggregate(
    implementation: dict[str, object],
    cybersecurity: dict[str, object],
    receipt_a: dict[str, object],
    receipt_b: dict[str, object],
    authorization_a: dict[str, object],
    authorization_b: dict[str, object],
    private: Ed25519PrivateKey,
) -> dict[str, object]:
    return aggregate_independent_reviews(
        implementation,
        cybersecurity,
        receipt_a,
        receipt_b,
        authorization_a,
        authorization_b,
        private.public_key(),
        CONFIG,
        expected_host_boot_id="00000000-0000-0000-0000-000000000000",
        expected_trust_epoch=0,
        now=NOW,
    )


def test_ready_yes_scope_no_is_valid_and_incomplete_security_holds() -> None:
    implementation, cybersecurity = (
        _review("IMPLEMENTATION_READINESS_REVIEWER"),
        _review("CYBERSECURITY_REVIEWER"),
    )
    private = Ed25519PrivateKey.generate()
    workspace_a = (
        "/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6.3.6/review-a"
    )
    workspace_b = (
        "/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6.3.6/review-b"
    )
    output_a = "/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a"
    output_b = "/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-b"
    authorization_a = _authorization(implementation, workspace_a, output_a, "1" * 32, private)
    authorization_b = _authorization(cybersecurity, workspace_b, output_b, "2" * 32, private)
    receipt_a = _receipt(implementation, authorization_a, private)
    receipt_b = _receipt(cybersecurity, authorization_b, private)
    result = _aggregate(
        implementation,
        cybersecurity,
        receipt_a,
        receipt_b,
        authorization_a,
        authorization_b,
        private,
    )
    assert result["review_outcome"] == "PASS"
    assert result["verdicts"]["READY_TO_IMPLEMENT_DISCOVERY_PACK"] == "YES"
    assert result["verdicts"]["SAFE_TO_FREEZE_SCOPE0"] == "NO"
    digests = [
        sha256(rfc8785.dumps(value)).digest()
        for value in (implementation, cybersecurity, receipt_a, receipt_b)
    ]
    expected_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "hd634:" + sha256(b"".join(digests)).hexdigest(),
        )
    )
    assert result["review_run_id"] == expected_id
    incomplete = deepcopy(cybersecurity)
    del incomplete["verdicts"]["CUSTODY_ISOLATION_PASS"]
    incomplete["content_hash"] = review_content_hash(incomplete)
    held = _aggregate(
        implementation,
        incomplete,
        receipt_a,
        _receipt(incomplete, authorization_b, private),
        authorization_a,
        authorization_b,
        private,
    )
    assert held["review_outcome"] == "HOLD"
    assert held["verdicts"]["READY_TO_IMPLEMENT_DISCOVERY_PACK"] == "NO"
    broken = deepcopy(implementation)
    broken["verdicts"]["REPO0_BASELINE_VALID"] = "NO"
    broken["content_hash"] = review_content_hash(broken)
    with pytest.raises(ValueError, match="E_REVIEW_PREREQUISITES"):
        _aggregate(
            broken,
            cybersecurity,
            _receipt(broken, authorization_a, private),
            receipt_b,
            authorization_a,
            authorization_b,
            private,
        )
    with pytest.raises(ValueError, match="E_REVIEW_INDEPENDENCE"):
        same_serial = _authorization(cybersecurity, workspace_b, output_b, "1" * 32, private)
        _aggregate(
            implementation,
            cybersecurity,
            receipt_a,
            _receipt(cybersecurity, same_serial, private),
            authorization_a,
            same_serial,
            private,
        )
    forged = deepcopy(receipt_b)
    forged["signature"] = "A" * 86
    with pytest.raises(ValueError, match="E_REVIEW_AUTH_SIGNATURE"):
        _aggregate(
            implementation,
            cybersecurity,
            receipt_a,
            forged,
            authorization_a,
            authorization_b,
            private,
        )


def test_self_review_cannot_bind_the_future_zip() -> None:
    record = {
        "schema_version": "plan-self-review/v1",
        "governed_content_root": "a" * 64,
        "task_manifest_sha256": "b" * 64,
        "checks": {"pass": True},
        "test_exit_code": 0,
        "test_output_sha256": "c" * 64,
        "independent_plan_review": "PENDING",
        "runtime_implementation_ready": "NO",
        "authorized_production_phases": "NONE",
    }
    assert build_plan_self_review(record) == record
    record["zip_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="E_SELF_REVIEW_BINDING"):
        build_plan_self_review(record)


IDENTITY = {
    "repository_qualification_receipt_sha256": "b" * 64,
    "repository_identity_kind": "DESCENDANT",
    "repository_commit_oid": "a" * 40,
    "repository_tree_oid": "b" * 40,
    "repository_file_tree_root_sha256": "c" * 64,
}


@pytest.fixture
def signed_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    # Official isolated vendor synchronization; no schema/signature verifier stub.
    sync_pack_assets(SOURCE_CONFIG.parents[2], tmp_path)
    monkeypatch.setattr(authorization, "RUNTIME_ROOT", tmp_path)
    private = Ed25519PrivateKey.generate()
    reviews, launches, receipts = [], [], []
    for index, role in enumerate(("IMPLEMENTATION_READINESS_REVIEWER", "CYBERSECURITY_REVIEWER")):
        old_review = _review(role)
        label = "a" if index == 0 else "b"
        launch = _authorization(
            old_review,
            f"/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6.3.6/review-{label}",
            f"/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-{label}",
            str(index + 1) * 32,
            private,
        )
        review = deepcopy(old_review)
        del review["repo0_receipt_sha256"]
        review.update(IDENTITY, schema_version="independent-review-result/v2")
        if index == 0:
            review["verdicts"]["DESCENDANT_REPOSITORY_VALID"] = review["verdicts"].pop(
                "REPO0_BASELINE_VALID"
            )
        else:
            del review["verdicts"]["SAFE_TO_FREEZE_SCOPE0"]
        review["content_hash"] = review_content_hash(review)
        authorization._schema_validate(
            review,
            "review-result.schema.json",
            "ImplementationReviewResult" if index == 0 else "CybersecurityReviewResult",
        )
        for key in list(launch):
            if key.startswith("repo0_"):
                del launch[key]
        launch.update(IDENTITY, schema_version="review-launch-authorization/v2")
        launch["command_registry_sha256"] = str(index + 3) * 64
        launch = authorization.sign_review_launch_authorization(launch, private)
        receipt = _receipt(review, launch, private)
        receipt.update(IDENTITY, schema_version="review-execution-receipt/v2")
        receipt = authorization.sign_review_execution_receipt(receipt, private)
        authorization.verify_review_execution_receipt(
            receipt,
            launch,
            private.public_key(),
            result_sha256=sha256(rfc8785.dumps(review)).hexdigest(),
            now=NOW,
        )
        reviews.append(review)
        launches.append(launch)
        receipts.append(receipt)
    return {"private": private, "reviews": reviews, "launches": launches, "receipts": receipts}


def _aggregate_current(chain: dict[str, Any]) -> dict[str, object]:
    return aggregate_independent_reviews(
        chain["reviews"][0],
        chain["reviews"][1],
        chain["receipts"][0],
        chain["receipts"][1],
        chain["launches"][0],
        chain["launches"][1],
        chain["private"].public_key(),
        {
            "schema_version": "review-aggregation-config/v2",
            "authorized_production_phases": "NONE",
            "maximum_aggregate_delay_seconds": 3600,
        },
        expected_host_boot_id="00000000-0000-0000-0000-000000000000",
        expected_trust_epoch=0,
        now=NOW,
        external_seal={
            **IDENTITY,
            "schema_version": "external-seal-attestation/v7",
            "artifact_type": "RUNTIME_PACK",
            "zip_sha256": "a" * 64,
            "manifest_sha256": "9" * 64,
        },
    )


def test_current_aggregate_uses_exact_schema_and_distinct_registry_bindings(
    signed_current: dict[str, Any],
) -> None:
    result = _aggregate_current(signed_current)
    assert result["schema_version"] == "review-aggregate-result/v2"
    assert result["review_outcome"] == "PASS"
    assert all(result[key] == value for key, value in IDENTITY.items())
    authorization._schema_validate(
        result, "review-result.schema.json", "DescendantAggregateReviewResult"
    )


@pytest.mark.parametrize("field", list(IDENTITY))
def test_current_receipt_rejects_resigned_identity_substitution(
    signed_current: dict[str, Any], field: str
) -> None:
    receipt = deepcopy(signed_current["receipts"][0])
    receipt[field] = (
        "ZERO_PARENT_BASELINE" if field == "repository_identity_kind" else "d" * len(receipt[field])
    )
    receipt = authorization.sign_review_execution_receipt(receipt, signed_current["private"])
    with pytest.raises(ValueError, match="E_REVIEW_(AUTH_SCHEMA|IDENTITY)"):
        authorization.verify_review_execution_receipt(
            receipt,
            signed_current["launches"][0],
            signed_current["private"].public_key(),
            result_sha256=sha256(rfc8785.dumps(signed_current["reviews"][0])).hexdigest(),
            now=NOW,
        )


@pytest.mark.parametrize(
    "field,value",
    [("pack_zip_sha256", "f" * 64), ("review_run_id", "33333333-3333-4333-8333-333333333333")],
)
def test_result_must_match_own_authorization(
    signed_current: dict[str, Any], field: str, value: str
) -> None:
    for index in range(2):
        review = signed_current["reviews"][index]
        review[field] = value
        review["content_hash"] = review_content_hash(review)
        receipt = signed_current["receipts"][index]
        receipt["result_sha256"] = sha256(rfc8785.dumps(review)).hexdigest()
        signed_current["receipts"][index] = authorization.sign_review_execution_receipt(
            receipt, signed_current["private"]
        )
    with pytest.raises(ValueError, match="E_REVIEW_RESULT_BINDING"):
        _aggregate_current(signed_current)


@pytest.mark.parametrize(
    "rejecting_role", ["IMPLEMENTATION_READINESS_REVIEWER", "CYBERSECURITY_REVIEWER"]
)
def test_authenticated_rejection_is_preserved(rejecting_role: str) -> None:
    a, b = _review("IMPLEMENTATION_READINESS_REVIEWER"), _review("CYBERSECURITY_REVIEWER")
    rejected = a if rejecting_role == a["review_role"] else b
    rejected["review_outcome"] = "REJECTED"
    rejected["content_hash"] = review_content_hash(rejected)
    private = Ed25519PrivateKey.generate()
    aa = _authorization(
        a,
        "/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6.3.6/review-a",
        "/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a",
        "1" * 32,
        private,
    )
    ab = _authorization(
        b,
        "/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6.3.6/review-b",
        "/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-b",
        "2" * 32,
        private,
    )
    result = _aggregate(a, b, _receipt(a, aa, private), _receipt(b, ab, private), aa, ab, private)
    assert result["review_outcome"] == "REJECTED"
    assert isinstance(result["verdicts"], dict)
    assert result["verdicts"]["READY_TO_IMPLEMENT_DISCOVERY_PACK"] == "NO"
