import json
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import cast

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from moj_discovery.review_authorization import (
    sign_review_execution_receipt,
    sign_review_launch_authorization,
    verify_review_execution_receipt,
    verify_review_launch_authorization,
)
from tools.issue_review_launch_authorization import _mount_roots
from tools.qualify_zero_parent_baseline import _repository_identity

NOW = datetime(2030, 1, 1, tzinfo=UTC)
WORKSPACE = "/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6.3.6/review-a"
PACK_HASH = "a" * 64


def test_mount_roots_read_governed_root_schema(tmp_path) -> None:
    pack = tmp_path / "pack"
    runtime = tmp_path / "runtime"
    (pack / "docs/receipts").mkdir(parents=True)
    runtime.mkdir()
    (runtime / "source.txt").write_text("source")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=runtime, check=True)
    subprocess.run(["git", "add", "source.txt"], cwd=runtime, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "baseline"],
        cwd=runtime,
        check=True,
    )
    commit, tree, file_root = _repository_identity(runtime)
    (pack / "GOVERNED_CONTENT_ROOT.json").write_text(
        json.dumps({"root_sha256": "a" * 64})
    )
    (pack / "docs/receipts/repo0-baseline-receipt.json").write_text(
        json.dumps(
            {
                "baseline_commit": commit,
                "baseline_tree": tree,
                "baseline_file_root_sha256": file_root,
            }
        )
    )
    inputs = [pack, runtime]
    for name in ("attestation.json", "pack.zip", "pack.zip.sha256"):
        path = tmp_path / name
        path.write_text(name)
        inputs.append(path)
    roots = _mount_roots(
        {
            "input_roots": [str(path) for path in inputs],
            "input_mounts": [
                {"source_root": str(path), "workspace_mount": str(path), "mode": "READ_ONLY"}
                for path in inputs
            ],
        }
    )

    assert roots[0]["content_root_sha256"] == "a" * 64
    assert roots[1]["content_root_sha256"] == file_root


def _authorization(private: Ed25519PrivateKey) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "review-launch-authorization/v1", "issuer_role": "HOST_REVIEW_AUTHORITY",
        "audience": "hybrid-discovery:independent-review-launcher:v1",
        "review_role": "IMPLEMENTATION_READINESS_REVIEWER",
        "review_run_id": "11111111-1111-4111-8111-111111111111", "pack_zip_sha256": PACK_HASH,
        "pack_manifest_sha256": "b" * 64, "repo0_receipt_sha256": "c" * 64,
        "repo0_commit_oid": "d" * 40, "repo0_tree_oid": "e" * 40,
        "repo0_file_tree_root_sha256": "f" * 64, "workspace_root": WORKSPACE,
        "input_mounts": [
            {"source_root": f"/sealed/input-{index}", "workspace_mount": f"/sealed/input-{index}",
             "mode": "READ_ONLY", "content_root_sha256": sha256(f"input-{index}".encode()).hexdigest()}
            for index in range(5)
        ],
        "excluded_roots": ["/authoring", "/peer"],
        "allowed_output_root": "/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a",
        "prompt_sha256": "1" * 64, "command_registry_sha256": "2" * 64,
        "issued_at": NOW.isoformat(), "not_before": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=14400)).isoformat(), "maximum_duration_seconds": 14400,
        "one_use_serial": "3" * 32, "nonce": "A" * 43, "fresh_session_required": True,
        "production_authority": "NONE", "signature_algorithm": "Ed25519",
        "host_boot_id": "00000000-0000-0000-0000-000000000000", "trust_epoch": 0,
    }
    return sign_review_launch_authorization(value, private)


def _receipt(authorization: dict[str, object], private: Ed25519PrivateKey) -> dict[str, object]:
    result = {"result": "PASS"}
    value: dict[str, object] = {
        "schema_version": "review-execution-receipt/v1", "authorization_id": authorization["authorization_id"],
        "issuer_role": "HOST_REVIEW_AUTHORITY", "review_role": authorization["review_role"],
        "review_run_id": authorization["review_run_id"], "workspace_root": authorization["workspace_root"],
        "workspace_attestation_sha256": "4" * 64,
        "input_content_roots": [item["content_root_sha256"] for item in cast(list[dict[str, object]], authorization["input_mounts"])],
        "result_sha256": sha256(rfc8785.dumps(result)).hexdigest(), "commands_executed_root": "5" * 64,
        "allowed_changed_paths": ["result.json"], "unexpected_changed_paths": [],
        "started_at": (NOW + timedelta(seconds=1)).isoformat(), "finished_at": (NOW + timedelta(seconds=2)).isoformat(),
        "authorization_consumed_at": NOW.isoformat(),
        "fresh_session_attestation": {"attestation_type": "HUMAN_FRESH_CODEX_SESSION", "attested": True,
                                      "attested_by": "reviewer", "attested_at": NOW.isoformat(),
                                      "procedural_not_cryptographic": True},
        "production_authority": "NONE", "signature_algorithm": "Ed25519",
        "host_boot_id": authorization["host_boot_id"], "trust_epoch": authorization["trust_epoch"],
        "preparation_commands_root": "6" * 64,
    }
    return sign_review_execution_receipt(value, private)


def test_wrong_role_workspace_pack_or_expiry_is_rejected() -> None:
    private = Ed25519PrivateKey.generate()
    authorization = _authorization(private)
    assert verify_review_launch_authorization(
        authorization, private.public_key(), "IMPLEMENTATION_READINESS_REVIEWER", WORKSPACE, PACK_HASH, now=NOW
    )["result"] == "PASS"
    for field, value in (
        ("review_role", "CYBERSECURITY_REVIEWER"), ("workspace_root", "/wrong"),
        ("pack_zip_sha256", "b" * 64), ("expires_at", (NOW + timedelta(seconds=1)).isoformat()),
    ):
        changed = deepcopy(authorization)
        changed[field] = value
        with pytest.raises(ValueError):
            verify_review_launch_authorization(
                changed, private.public_key(), "IMPLEMENTATION_READINESS_REVIEWER", WORKSPACE, PACK_HASH, now=NOW
            )


def test_receipt_has_a_separate_domain_and_exact_launch_binding() -> None:
    private = Ed25519PrivateKey.generate()
    authorization = _authorization(private)
    receipt = _receipt(authorization, private)
    result_hash = cast(str, receipt["result_sha256"])
    assert verify_review_execution_receipt(
        receipt, authorization, private.public_key(), result_sha256=result_hash, now=NOW + timedelta(seconds=3)
    )["result"] == "PASS"
    changed = deepcopy(receipt)
    cast(list[str], changed["input_content_roots"]).reverse()
    with pytest.raises(ValueError):
        verify_review_execution_receipt(
            changed, authorization, private.public_key(), result_sha256=result_hash, now=NOW + timedelta(seconds=3)
        )
    with pytest.raises(ValueError, match="E_REVIEW_AUTH_BINDING"):
        verify_review_execution_receipt(
            receipt,
            authorization,
            private.public_key(),
            result_sha256=result_hash,
            expected_host_boot_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
            expected_trust_epoch=0,
            now=NOW + timedelta(seconds=3),
        )
