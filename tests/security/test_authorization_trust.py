from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from moj_discovery.review_authorization import (
    sign_review_launch_authorization,
    verify_review_launch_authorization,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)
WORKSPACE = "/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6.3.6/review-a"
PACK_SHA256 = "a" * 64
BOOT_ID = "00000000-0000-0000-0000-000000000000"


def _launch(
    private: Ed25519PrivateKey,
    *,
    boot_id: str = BOOT_ID,
    audience: str = "hybrid-discovery:independent-review-launcher:v1",
    review_role: str = "IMPLEMENTATION_READINESS_REVIEWER",
    trust_epoch: int = 0,
    issued_at: datetime = NOW,
    not_before: datetime = NOW,
    expires_at: datetime = NOW + timedelta(seconds=14400),
) -> dict[str, object]:
    return sign_review_launch_authorization(
        {
            "schema_version": "review-launch-authorization/v1",
            "issuer_role": "HOST_REVIEW_AUTHORITY",
            "audience": audience,
            "review_role": review_role,
            "review_run_id": "11111111-1111-4111-8111-111111111111",
            "pack_zip_sha256": PACK_SHA256,
            "pack_manifest_sha256": "b" * 64,
            "repo0_receipt_sha256": "c" * 64,
            "repo0_commit_oid": "d" * 40,
            "repo0_tree_oid": "e" * 40,
            "repo0_file_tree_root_sha256": "f" * 64,
            "workspace_root": WORKSPACE,
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
            "allowed_output_root": (
                "/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a"
            ),
            "prompt_sha256": "1" * 64,
            "command_registry_sha256": "2" * 64,
            "issued_at": issued_at.isoformat(),
            "not_before": not_before.isoformat(),
            "expires_at": expires_at.isoformat(),
            "maximum_duration_seconds": 14400,
            "one_use_serial": "3" * 32,
            "nonce": "A" * 43,
            "fresh_session_required": True,
            "production_authority": "NONE",
            "signature_algorithm": "Ed25519",
            "host_boot_id": boot_id,
            "trust_epoch": trust_epoch,
        },
        private,
    )


def test_security_boundary() -> None:
    vectors = {
        "allow": "SEC_AUTHORIZATION_TRUST-ALLOW",
        "deny": "SEC_AUTHORIZATION_TRUST-DENY",
        "mutate": "SEC_AUTHORIZATION_TRUST-MUTATE",
    }
    private = Ed25519PrivateKey.generate()
    launch = _launch(private)
    assert (
        verify_review_launch_authorization(
            launch,
            private.public_key(),
            "IMPLEMENTATION_READINESS_REVIEWER",
            WORKSPACE,
            PACK_SHA256,
            expected_host_boot_id=BOOT_ID,
            expected_trust_epoch=0,
            now=NOW,
        )["result"]
        == "PASS"
    ), vectors["allow"]

    with pytest.raises(ValueError):
        verify_review_launch_authorization(
            _launch(private, boot_id="10000000-0000-0000-0000-000000000000"),
            private.public_key(),
            "IMPLEMENTATION_READINESS_REVIEWER",
            WORKSPACE,
            PACK_SHA256,
            expected_host_boot_id=BOOT_ID,
            expected_trust_epoch=0,
            now=NOW,
        )
    for changed, kwargs in (
        (_launch(private, review_role="CYBERSECURITY_REVIEWER"), {}),
        (_launch(private, audience="hybrid-discovery:wrong:v1"), {}),
        (_launch(private, trust_epoch=1), {}),
    ):
        with pytest.raises(ValueError):
            verify_review_launch_authorization(
                changed,
                private.public_key(),
                "IMPLEMENTATION_READINESS_REVIEWER",
                WORKSPACE,
                PACK_SHA256,
                expected_host_boot_id=BOOT_ID,
                expected_trust_epoch=0,
                now=NOW,
                **kwargs,
            )
    mutated = dict(launch)
    mutated["audience"] = "hybrid-discovery:mutated:v1"
    with pytest.raises(ValueError):
        verify_review_launch_authorization(
            mutated,
            private.public_key(),
            "IMPLEMENTATION_READINESS_REVIEWER",
            WORKSPACE,
            PACK_SHA256,
            expected_host_boot_id=BOOT_ID,
            expected_trust_epoch=0,
            now=NOW,
        )
    assert vectors["deny"] and vectors["mutate"]
    with pytest.raises(ValueError):
        verify_review_launch_authorization(
            launch,
            Ed25519PrivateKey.generate().public_key(),
            "IMPLEMENTATION_READINESS_REVIEWER",
            WORKSPACE,
            PACK_SHA256,
            now=NOW,
        )
