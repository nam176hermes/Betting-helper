"""Issue one host-authority review launch authorization after all bindings are measured."""
# ruff: noqa: E402, I001, E501
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.bootstrap_review_authority import bootstrap_review_authority
from moj_discovery.review_authorization import sign_review_launch_authorization


def _regular_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or stat.S_ISLNK(path.lstat().st_mode):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _directory_root(path: Path, record: str, field: str) -> str:
    if path.is_symlink() or not path.is_dir() or stat.S_ISLNK(path.lstat().st_mode):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    value = json.loads((path / record).read_text())
    root = value.get(field) if isinstance(value, dict) else None
    if not isinstance(root, str) or len(root) != 64:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return root


def _runtime_root(path: Path, receipt_path: Path) -> str:
    from tools.qualify_zero_parent_baseline import _repository_identity

    receipt = json.loads(receipt_path.read_text())
    commit, tree, root = _repository_identity(path)
    if not isinstance(receipt, dict) or (
        receipt.get("baseline_commit"),
        receipt.get("baseline_tree"),
        receipt.get("baseline_file_root_sha256"),
    ) != (commit, tree, root):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return root


def _mount_roots(config: dict[str, object]) -> list[dict[str, object]]:
    mounts = config.get("input_mounts")
    inputs = config.get("input_roots")
    if not isinstance(mounts, list) or not isinstance(inputs, list) or len(mounts) != 5 or len(inputs) != 5:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    result: list[dict[str, object]] = []
    for index, mount in enumerate(mounts):
        if not isinstance(mount, dict) or mount.get("mode") != "READ_ONLY":
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        source = mount.get("source_root")
        if source != mount.get("workspace_mount") or source != inputs[index] or not isinstance(source, str):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        path = Path(source)
        if index == 0:
            root = _directory_root(path, "GOVERNED_CONTENT_ROOT.json", "root_sha256")
        elif index == 1:
            root = _runtime_root(
                path,
                Path(cast(str, inputs[0])) / "docs/receipts/repo0-baseline-receipt.json",
            )
        else:
            root = _regular_hash(path)
        result.append({**mount, "content_root_sha256": root})
    if len({cast(str, item["source_root"]) for item in result}) != 5:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return result


def issue_review_launch_authorization(
    config: dict[str, object], authority_config: dict[str, object], output: Path, *, now: datetime | None = None
) -> dict[str, object]:
    if config.get("network") != "DENY" or config.get("role") not in {
        "IMPLEMENTATION_READINESS_REVIEWER", "CYBERSECURITY_REVIEWER"
    } or authority_config.get("production_authority") != "NONE":
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    bootstrap_review_authority(authority_config, initialize_if_absent=False)
    private_path = Path(cast(str, authority_config["private_key_path"]))
    public = json.loads(Path(cast(str, authority_config["public_key_path"])).read_text())
    private = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey) or not isinstance(public, dict):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    seal_inputs = config.get("seal_inputs")
    if not isinstance(seal_inputs, dict):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    attestation_path = Path(cast(str, seal_inputs["attestation"]))
    attestation = json.loads(attestation_path.read_text())
    if not isinstance(attestation, dict):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    trusted_now = (now or datetime.now(UTC)).astimezone(UTC)
    mounts = _mount_roots(config)
    serial = secrets.token_hex(16)
    input_roots = cast(list[str], config["input_roots"])
    runtime_receipt = json.loads(
        (Path(input_roots[0]) / "docs/receipts/repo0-baseline-receipt.json").read_text()
    )
    value: dict[str, object] = {
        "schema_version": "review-launch-authorization/v1", "issuer_role": "HOST_REVIEW_AUTHORITY",
        "audience": "hybrid-discovery:independent-review-launcher:v1", "review_role": config["role"],
        "review_run_id": str(uuid.uuid4()), "pack_zip_sha256": _regular_hash(Path(cast(str, seal_inputs["zip"]))),
        "pack_manifest_sha256": attestation["manifest_sha256"], "repo0_receipt_sha256": attestation["repo0_receipt_sha256"],
        "repo0_commit_oid": runtime_receipt["baseline_commit"], "repo0_tree_oid": runtime_receipt["baseline_tree"],
        "repo0_file_tree_root_sha256": mounts[1]["content_root_sha256"], "workspace_root": config["workspace_root"],
        "input_mounts": mounts, "excluded_roots": config["excluded_roots"], "allowed_output_root": config["output_root"],
        "prompt_sha256": _regular_hash(Path(cast(str, config["prompt_path"]))),
        "command_registry_sha256": _regular_hash(Path(cast(str, config["command_registry_path"]))),
        "issued_at": trusted_now.isoformat(), "not_before": trusted_now.isoformat(),
        "expires_at": (trusted_now + timedelta(seconds=14400)).isoformat(), "maximum_duration_seconds": 14400,
        "one_use_serial": serial, "nonce": secrets.token_urlsafe(32), "fresh_session_required": True,
        "production_authority": "NONE", "signature_algorithm": "Ed25519",
        "host_boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "trust_epoch": public["trust_epoch"],
    }
    signed = sign_review_launch_authorization(value, private)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(signed, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(temporary, output)
    return signed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    authority_path = Path(cast(str, config["authority_config"]))
    print(json.dumps(issue_review_launch_authorization(config, json.loads(authority_path.read_text()), args.output), sort_keys=True))


if __name__ == "__main__":
    main()
