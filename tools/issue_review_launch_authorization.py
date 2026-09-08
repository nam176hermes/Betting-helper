"""Issue one host-authority review launch authorization after all bindings are measured."""

# ruff: noqa: E402, I001, E501
from __future__ import annotations

import argparse
import base64
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
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from tools.bootstrap_review_authority import bootstrap_review_authority
from moj_discovery.review_authorization import (
    review_identity,
    sign_review_launch_authorization,
    verify_review_launch_authorization,
)


def review_public_key(authority_config: dict[str, object]) -> tuple[Ed25519PublicKey, int]:
    record_path = Path(cast(str, authority_config["public_key_path"]))
    _regular_hash(record_path)
    record = json.loads(record_path.read_text())
    encoded = record.get("public_key_b64url") if isinstance(record, dict) else None
    epoch = record.get("trust_epoch") if isinstance(record, dict) else None
    if not isinstance(encoded, str) or type(epoch) is not int or epoch < 0:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != encoded:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return Ed25519PublicKey.from_public_bytes(raw), epoch


def authorized_review_context(
    authorization: dict[str, object],
    authority: dict[str, object],
    *,
    runtime_root: Path = RUNTIME_ROOT,
) -> dict[str, object]:
    config = review_config_for_role(
        cast(str, authorization["review_role"]), 2, runtime_root=runtime_root
    )
    public, epoch = review_public_key(authority)
    verify_review_launch_authorization(
        authorization,
        public,
        cast(str, config["role"]),
        cast(str, config["workspace_root"]),
        cast(str, authorization["pack_zip_sha256"]),
        expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        expected_trust_epoch=epoch,
    )
    return measure_review_context(config, authorization)


def review_config_for_role(
    role: str, version: int, *, runtime_root: Path = RUNTIME_ROOT
) -> dict[str, object]:
    names = {"IMPLEMENTATION_READINESS_REVIEWER": "review-a", "CYBERSECURITY_REVIEWER": "review-b"}
    if role not in names or type(version) is not int or version not in {1, 2}:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    path = runtime_root / "review-config" / f"{names[role]}.v{version}.json"
    _regular_hash(path)
    config = json.loads(path.read_bytes())
    if (
        not isinstance(config, dict)
        or config.get("role") != role
        or config.get("schema_version") != f"review-config/v{version}"
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return cast(dict[str, object], config)


def _regular_hash(path: Path) -> str:
    if (
        path.is_symlink()
        or not path.is_file()
        or stat.S_ISLNK(path.lstat().st_mode)
        or path.stat().st_nlink != 1
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recheck_review_context(context: dict[str, object]) -> None:
    for name, expected in cast(dict[str, str], context["snapshots"]).items():
        if _regular_hash(Path(name)) != expected:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")


def measure_review_context(
    config: dict[str, object], authorization: dict[str, object] | None = None
) -> dict[str, object]:
    """Bounded locator extraction, then actual sealed verification, before authority."""
    from tools.assemble_review_pack import load_sealed_assembly_context
    from tools.build_candidate_qualification_receipt import _read_bytes
    from tools.qualify_descendant_repository import verify_descendant_qualification_receipt
    from tools.seal_review_pack import verify_sealed_review_pack

    try:
        if config.get("schema_version") != "review-config/v2":
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        inputs = cast(list[str], config["input_roots"])
        if not isinstance(inputs, list) or len(inputs) != 5:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        pack, runtime = Path(inputs[0]), Path(inputs[1])
        if pack != pack.resolve(strict=True) or runtime != runtime.resolve(strict=True):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        manifest_path = pack / "MANIFEST_SHA256.json"
        snapshots = {str(manifest_path): _regular_hash(manifest_path)}
        manifest = json.loads(manifest_path.read_bytes())
        entries = manifest["entries"]
        if manifest.get("schema_version") != "manifest-sha256/v1" or not isinstance(entries, list):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")

        def member(path: Path) -> bytes:
            relative = path.relative_to(pack).as_posix()
            if path != path.resolve(strict=True):
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            digest = _regular_hash(path)
            raw = path.read_bytes()
            rows = [row for row in entries if isinstance(row, dict) and row.get("path") == relative]
            if rows != [{"path": relative, "size": str(len(raw)), "sha256": digest}]:
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            snapshots[str(path)] = digest
            return raw

        metadata = review_config_for_role(
            "IMPLEMENTATION_READINESS_REVIEWER", 2, runtime_root=runtime
        )
        used: dict[str, bytes] = {}
        for selected in (config, metadata):
            role = cast(str, selected["role"])
            if selected != review_config_for_role(role, 2, runtime_root=runtime):
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            label = "a" if role == "IMPLEMENTATION_READINESS_REVIEWER" else "b"
            relative = f"docs/configs/review-{label}.v2.json"
            raw = member(pack / relative)
            materialized = runtime / f"review-config/review-{label}.v2.json"
            snapshots[str(materialized)] = _regular_hash(materialized)
            if materialized.read_bytes() != raw or json.loads(raw) != selected:
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            used[relative] = raw
            registry_relative = "docs/registries/" + (
                "review-command-registry.v1.json"
                if label == "a"
                else "cybersecurity-command-registry.v1.json"
            )
            if selected["command_registry_path"] != str(pack / registry_relative):
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            used[registry_relative] = member(pack / registry_relative)
        if any(
            config[key] != metadata[key]
            for key in ("input_roots", "input_mounts", "seal_inputs", "repository_identity")
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        registry = json.loads(used["docs/registries/review-command-registry.v1.json"])
        if (
            set(registry) != {"schema_version", "commands"}
            or registry["schema_version"] != "review-command-registry/v1"
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        rows = registry["commands"]
        if not isinstance(rows, list) or len({row["command_id"] for row in rows}) != len(rows):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        leaf = [row for row in rows if row.get("command_id") == "A_CHECK_DESCENDANT"]
        if (
            len(leaf) != 1
            or not isinstance(leaf[0].get("argv"), list)
            or len(leaf[0]["argv"]) != 21
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        recorded = leaf[0]["argv"][16]
        if recorded != str(
            runtime / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        named_config = pack / "docs/configs/full-verifier-controller.v2.json"
        named_receipt = pack / "docs/receipts/descendant-repository-qualification-receipt.json"
        retained_manifest, retained_root = (
            pack / "evidence/retained-artifact-manifest.json",
            pack / "evidence/retained",
        )
        argv = [
            "uv",
            "run",
            "--frozen",
            "--offline",
            "python",
            "tools/qualify_descendant_repository.py",
            "--root",
            str(runtime),
            "--config",
            str(named_config),
            "--check-only",
            "--receipt",
            str(named_receipt),
            "--pack",
            str(pack),
            "--recorded-config",
            recorded,
            "--retained-manifest",
            str(retained_manifest),
            "--retained-root",
            str(retained_root),
        ]
        expected_row = {
            "command_id": "A_CHECK_DESCENDANT",
            "purpose": "A_CHECK_DESCENDANT",
            "cwd": str(runtime),
            "argv": argv,
            "expected_exit": 0,
            "kind": "review-leaf",
            "available_at": "SEALED",
            "network": "DENY",
            "authenticated_operator_access": "DENY",
            "provider_access": "DENY",
        }
        if leaf != [expected_row] or config["repository_identity"] != {
            "kind": "DESCENDANT",
            "receipt": str(named_receipt),
        }:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        seal_inputs = cast(dict[str, str], config["seal_inputs"])
        if seal_inputs != {"attestation": inputs[2], "zip": inputs[3], "sidecar": inputs[4]}:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        for path in (
            named_config,
            named_receipt,
            retained_manifest,
            Path(cast(str, config["prompt_path"])),
        ):
            member(path)
        for locator in inputs[2:]:
            snapshots[locator] = _regular_hash(Path(locator))
        mounts = cast(list[dict[str, object]], config["input_mounts"])
        if mounts != [
            {"source_root": value, "workspace_mount": value, "mode": "READ_ONLY"}
            for value in inputs
        ]:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        if authorization is not None and (
            authorization.get("schema_version") != "review-launch-authorization/v2"
            or authorization.get("review_role") != config["role"]
            or authorization.get("workspace_root") != config["workspace_root"]
            or authorization.get("allowed_output_root") != config["output_root"]
            or authorization.get("excluded_roots") != config["excluded_roots"]
            or authorization.get("pack_manifest_sha256") != snapshots[str(manifest_path)]
            or authorization.get("command_registry_sha256")
            != snapshots[cast(str, config["command_registry_path"])]
            or authorization.get("prompt_sha256") != snapshots[cast(str, config["prompt_path"])]
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        controller, artifacts = load_sealed_assembly_context(
            pack, named_config, recorded, retained_manifest, retained_root
        )
        if (
            controller.current_checkout_root != runtime
            or controller.descendant_repository_receipt is None
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        for relative, raw in used.items():
            if raw != _read_bytes(controller.governed_source_pack / relative, artifacts):
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
        if named_receipt.read_bytes() != _read_bytes(
            controller.descendant_repository_receipt, artifacts
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        verify_descendant_qualification_receipt(
            runtime,
            controller.descendant_repository_receipt,
            pack=controller.governed_source_pack,
            config=controller,
            artifacts=artifacts,
        )
        seal = verify_sealed_review_pack(
            pack,
            Path(inputs[3]),
            Path(inputs[4]),
            Path(inputs[2]),
            config_path=named_config,
            recorded_config_locator=recorded,
            retained_manifest=retained_manifest,
            retained_root=retained_root,
        )
        identity = review_identity(seal)
        roots = [
            seal["governed_content_root"],
            identity["repository_file_tree_root_sha256"],
            *[snapshots[path] for path in inputs[2:]],
        ]
        measured_mounts = [
            {**mount, "content_root_sha256": root}
            for mount, root in zip(mounts, roots, strict=True)
        ]
        if (
            seal["schema_version"] != "external-seal-attestation/v7"
            or seal["artifact_type"] != "RUNTIME_PACK"
            or seal["zip_sha256"] != snapshots[inputs[3]]
            or seal["manifest_sha256"] != snapshots[str(manifest_path)]
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        if authorization is not None and (
            review_identity(authorization) != identity
            or authorization["input_mounts"] != measured_mounts
            or authorization["pack_zip_sha256"] != seal["zip_sha256"]
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        context: dict[str, object] = {
            "seal": seal,
            "mounts": measured_mounts,
            "snapshots": snapshots,
            "transport": expected_row,
            "controller": controller,
            "artifacts": artifacts,
        }
        recheck_review_context(context)
        return context
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("E_REVIEW_LAUNCH_INPUT") from error


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
    if config.get("schema_version") == "review-config/v2":
        return cast(list[dict[str, object]], measure_review_context(config)["mounts"])
    mounts = config.get("input_mounts")
    inputs = config.get("input_roots")
    if (
        not isinstance(mounts, list)
        or not isinstance(inputs, list)
        or len(mounts) != 5
        or len(inputs) != 5
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    result: list[dict[str, object]] = []
    for index, mount in enumerate(mounts):
        if not isinstance(mount, dict) or mount.get("mode") != "READ_ONLY":
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        source = mount.get("source_root")
        if (
            source != mount.get("workspace_mount")
            or source != inputs[index]
            or not isinstance(source, str)
        ):
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
    config: dict[str, object],
    authority_config: dict[str, object],
    output: Path,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if (
        config.get("network") != "DENY"
        or config.get("role") not in {"IMPLEMENTATION_READINESS_REVIEWER", "CYBERSECURITY_REVIEWER"}
        or authority_config.get("production_authority") != "NONE"
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    if config.get("schema_version") not in {"review-config/v1", "review-config/v2"}:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    current = config.get("schema_version") == "review-config/v2"
    context = measure_review_context(config) if current else None
    if context is not None:
        recheck_review_context(context)
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
    mounts = (
        cast(list[dict[str, object]], context["mounts"])
        if context is not None
        else _mount_roots(config)
    )
    serial = secrets.token_hex(16)
    input_roots = cast(list[str], config["input_roots"])
    runtime_receipt = (
        {}
        if current
        else json.loads(
            (Path(input_roots[0]) / "docs/receipts/repo0-baseline-receipt.json").read_text()
        )
    )
    value: dict[str, object] = {
        "schema_version": "review-launch-authorization/v2"
        if current
        else "review-launch-authorization/v1",
        "issuer_role": "HOST_REVIEW_AUTHORITY",
        "audience": "hybrid-discovery:independent-review-launcher:v1",
        "review_role": config["role"],
        "review_run_id": str(uuid.uuid4()),
        "pack_zip_sha256": _regular_hash(Path(cast(str, seal_inputs["zip"]))),
        "pack_manifest_sha256": attestation["manifest_sha256"],
        **(
            review_identity(attestation)
            if current
            else {
                "repo0_receipt_sha256": attestation["repo0_receipt_sha256"],
                "repo0_commit_oid": runtime_receipt["baseline_commit"],
                "repo0_tree_oid": runtime_receipt["baseline_tree"],
                "repo0_file_tree_root_sha256": mounts[1]["content_root_sha256"],
            }
        ),
        "workspace_root": config["workspace_root"],
        "input_mounts": mounts,
        "excluded_roots": config["excluded_roots"],
        "allowed_output_root": config["output_root"],
        "prompt_sha256": _regular_hash(Path(cast(str, config["prompt_path"]))),
        "command_registry_sha256": _regular_hash(Path(cast(str, config["command_registry_path"]))),
        "issued_at": trusted_now.isoformat(),
        "not_before": trusted_now.isoformat(),
        "expires_at": (trusted_now + timedelta(seconds=14400)).isoformat(),
        "maximum_duration_seconds": 14400,
        "one_use_serial": serial,
        "nonce": secrets.token_urlsafe(32),
        "fresh_session_required": True,
        "production_authority": "NONE",
        "signature_algorithm": "Ed25519",
        "host_boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "trust_epoch": public["trust_epoch"],
    }
    if context is not None:
        recheck_review_context(context)
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
    print(
        json.dumps(
            issue_review_launch_authorization(
                config, json.loads(authority_path.read_text()), args.output
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
