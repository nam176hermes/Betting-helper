"""Sign a receipt only for an already prepared, human-attested review output."""

# ruff: noqa: E402, I001
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

import rfc8785
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moj_discovery.review_authorization import (
    _schema_validate,
    review_identity,
    sign_review_execution_receipt,
    verify_review_execution_receipt,
    verify_review_launch_authorization,
    verify_review_result_binding,
)
from moj_discovery.schema_formats import STRICT_FORMAT_CHECKER
from tools.bootstrap_review_authority import bootstrap_review_authority
from tools.issue_review_launch_authorization import (
    _regular_hash,
    authorized_review_context,
    recheck_review_context,
    review_execution_root,
    validate_review_authority_state,
    validate_review_scope,
)


RESULT_DOMAIN = b"HD636/REVIEW-RESULT/v1\0"


def review_content_hash(value: dict[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "content_hash"}
    return hashlib.sha256(RESULT_DOMAIN + rfc8785.dumps(cast(Any, payload))).hexdigest()


def _preparation_root(records: list[dict[str, object]]) -> str:
    return hashlib.sha256(
        b"HD636/REVIEW-PREPARATION/v1\0" + rfc8785.dumps(cast(Any, records))
    ).hexdigest()


def _validate_preparation(attestation: dict[str, object], role: object) -> None:
    expected = {
        "IMPLEMENTATION_READINESS_REVIEWER": ["A_INSTALL_PYTHON", "A_INSTALL_NODE"],
        "CYBERSECURITY_REVIEWER": ["B_INSTALL_PYTHON", "B_INSTALL_NODE"],
    }.get(cast(str, role))
    records = attestation.get("preparation_commands")
    if expected is None or not isinstance(records, list) or len(records) != 2:
        raise ValueError("E_REVIEW_FINALIZE_BINDING")
    actual = cast(list[dict[str, object]], records)
    expected_argv = [
        ["uv", "sync", "--frozen", "--offline"],
        ["pnpm", "install", "--frozen-lockfile", "--offline", "--ignore-scripts"],
    ]
    required = {
        "command_id",
        "argv",
        "cwd",
        "environment",
        "exit_code",
        "stdout_sha256",
        "stderr_sha256",
    }
    for index, record in enumerate(actual):
        if (
            not isinstance(record, dict)
            or set(record) != required
            or record.get("command_id") != expected[index]
            or record.get("argv") != expected_argv[index]
            or record.get("exit_code") != 0
            or not isinstance(record.get("cwd"), str)
            or not isinstance(record.get("environment"), dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in cast(dict[object, object], record["environment"]).items()
            )
            or not all(
                isinstance(record.get(key), str) and len(cast(str, record[key])) == 64
                for key in ("stdout_sha256", "stderr_sha256")
            )
        ):
            raise ValueError("E_REVIEW_FINALIZE_BINDING")
    if attestation.get("preparation_commands_root") != _preparation_root(actual):
        raise ValueError("E_REVIEW_FINALIZE_BINDING")


def _validate_result(result: dict[str, object], role: object) -> None:
    definition = {
        "IMPLEMENTATION_READINESS_REVIEWER": "ImplementationReviewResult",
        "CYBERSECURITY_REVIEWER": "CybersecurityReviewResult",
    }.get(cast(str, role))
    if definition is None:
        raise ValueError("E_REVIEW_FINALIZE_BINDING")
    schema = json.loads(
        (
            RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6/docs/schemas/review-result.schema.json"
        ).read_text()
    )
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]},
        format_checker=STRICT_FORMAT_CHECKER,
    )
    if next(validator.iter_errors(result), None) is not None or result.get(
        "content_hash"
    ) != review_content_hash(result):
        raise ValueError("E_REVIEW_FINALIZE_BINDING")


def _validate_current_workspace(
    authorization: dict[str, object], attestation: dict[str, object]
) -> None:
    _validate_preparation(attestation, authorization.get("review_role"))
    fresh = attestation.get("fresh_session_attestation")
    if (
        attestation.get("workspace_root") != authorization["workspace_root"]
        or attestation.get("unexpected_changed_paths") != []
        or not isinstance(fresh, dict)
    ):
        raise ValueError("E_REVIEW_FINALIZE_BINDING")
    try:
        _schema_validate(fresh, "review-execution-receipt.schema.json", "FreshSessionAttestation")
    except ValueError as error:
        raise ValueError("E_REVIEW_FINALIZE_BINDING") from error


def _validate_consumed_authorization(
    authorization: dict[str, object], authority_config: dict[str, object]
) -> None:
    try:
        validate_review_authority_state(authorization, authority_config)
    except ValueError as error:
        raise ValueError("E_REVIEW_FINALIZE_BINDING") from error


def validate_host_preparation(
    authorization: dict[str, object],
    authority: dict[str, object],
    attestation: dict[str, object],
) -> None:
    root = review_execution_root(authorization, authority).with_name(
        str(authorization["review_run_id"]) + "-preparation"
    )
    try:
        _regular_hash(root / "preparation.json")
        record = json.loads((root / "preparation.json").read_bytes())
        records = attestation.get("preparation_commands")
        if (
            not isinstance(records, list)
            or len(records) != 2
            or record
            != {
                "authorization_id": authorization["authorization_id"],
                "commands": records,
                "preparation_commands_root": _preparation_root(records),
            }
            or attestation.get("preparation_commands_root") != record["preparation_commands_root"]
        ):
            raise ValueError("E_REVIEW_EXECUTION")
        expected = {"preparation.json"}
        for index, row in enumerate(records):
            for stream in ("stdout", "stderr"):
                name = f"{index:02d}.{stream}"
                expected.add(name)
                if _regular_hash(root / name) != row.get(stream + "_sha256"):
                    raise ValueError("E_REVIEW_EXECUTION")
        if {p.name for p in root.iterdir()} != expected:
            raise ValueError("E_REVIEW_EXECUTION")
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError("E_REVIEW_EXECUTION") from error


def validate_host_execution(
    authorization: dict[str, object],
    authority: dict[str, object],
    config: dict[str, object],
    attestation: dict[str, object],
) -> None:
    from tools.run_review_a_checks import run_review_a_checks
    from tools.run_review_b_checks import run_review_b_checks

    validate_host_preparation(authorization, authority, attestation)
    root = review_execution_root(authorization, authority)
    record_path = root / "execution.json"
    _regular_hash(record_path)
    record = json.loads(record_path.read_bytes())
    if (
        not isinstance(record, dict)
        or set(record) != {"authorization_id", "result", "commands", "commands_executed_root"}
        or record["authorization_id"] != authorization["authorization_id"]
    ):
        raise ValueError("E_REVIEW_EXECUTION")
    rows = record["commands"]
    if not isinstance(rows, list) or len(rows) != len(
        cast(list[str], config["mechanical_command_ids"])
    ):
        raise ValueError("E_REVIEW_EXECUTION")
    expected_files = {"execution.json"} | {
        f"{index:02d}.{stream}" for index in range(len(rows)) for stream in ("stdout", "stderr")
    }
    if {path.name for path in root.iterdir()} != expected_files:
        raise ValueError("E_REVIEW_EXECUTION")
    sequence = 0

    def observed(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal sequence
        row = rows[sequence]
        if (
            row.get("argv") != argv
            or row.get("cwd") != kwargs.get("cwd")
            or row.get("environment") != kwargs.get("env")
            or type(row.get("exit_code")) is not int
        ):
            raise ValueError("E_REVIEW_EXECUTION")
        values = []
        for stream in ("stdout", "stderr"):
            path = root / f"{sequence:02d}.{stream}"
            _regular_hash(path)
            if path.stat().st_size > 750000:
                raise ValueError("E_REVIEW_EXECUTION")
            values.append(path.read_bytes())
        sequence += 1
        return subprocess.CompletedProcess(argv, row["exit_code"], *values)

    registry = json.loads(Path(cast(str, config["command_registry_path"])).read_bytes())
    runner = (
        run_review_a_checks
        if config["role"] == "IMPLEMENTATION_READINESS_REVIEWER"
        else run_review_b_checks
    )
    expected = runner(config, registry, execute=observed)
    if record != {"authorization_id": authorization["authorization_id"], **expected} or (
        attestation["commands_executed_root"] != expected["commands_executed_root"]
    ):
        raise ValueError("E_REVIEW_EXECUTION")


def _validate_current_delivery(
    authorization: dict[str, object], result: Path, receipt: Path
) -> None:
    root = Path(cast(str, authorization["allowed_output_root"]))
    try:
        if (
            not root.is_absolute()
            or root != root.resolve(strict=True)
            or not root.is_dir()
            or root.is_symlink()
            or result != root / "result.json"
            or receipt != root / "execution-receipt.json"
            or receipt.exists()
            or receipt.is_symlink()
        ):
            raise ValueError("E_REVIEW_FINALIZE_BINDING")
        for path in (result, root / "workspace-attestation.json"):
            if path != path.resolve(strict=True):
                raise ValueError("E_REVIEW_FINALIZE_BINDING")
            _regular_hash(path)
    except (OSError, ValueError, RuntimeError) as error:
        raise ValueError("E_REVIEW_FINALIZE_BINDING") from error


def finalize_review(
    authorization: dict[str, object],
    result: dict[str, object],
    attestation: dict[str, object],
    private: Ed25519PrivateKey,
    *,
    now: datetime | None = None,
    external_seal: dict[str, object] | None = None,
) -> dict[str, object]:
    _ = (now or datetime.now(UTC)).astimezone(UTC)
    _validate_result(result, authorization.get("review_role"))
    verify_review_result_binding(result, authorization)
    current = authorization.get("schema_version") == "review-launch-authorization/v2"
    if current:
        _validate_current_workspace(authorization, attestation)
    if current and (
        external_seal is None
        or external_seal.get("schema_version") != "external-seal-attestation/v7"
        or external_seal.get("artifact_type") != "RUNTIME_PACK"
        or review_identity(external_seal) != review_identity(authorization)
        or external_seal.get("zip_sha256") != authorization["pack_zip_sha256"]
        or external_seal.get("manifest_sha256") != authorization["pack_manifest_sha256"]
    ):
        raise ValueError("E_REVIEW_FINALIZE_BINDING")
    _validate_preparation(attestation, authorization.get("review_role"))
    if (
        result.get("review_role") != authorization.get("review_role")
        or result.get("review_run_id") != authorization.get("review_run_id")
        or result.get("pack_zip_sha256") != authorization.get("pack_zip_sha256")
        or result.get("repo0_receipt_sha256") != authorization.get("repo0_receipt_sha256")
        or result.get("authorized_production_phases") != "NONE"
        or not isinstance(attestation.get("fresh_session_attestation"), dict)
        or attestation.get("unexpected_changed_paths") != []
    ):
        raise ValueError("E_REVIEW_FINALIZE_BINDING")
    receipt = sign_review_execution_receipt(
        {
            "schema_version": "review-execution-receipt/v2"
            if current
            else "review-execution-receipt/v1",
            "authorization_id": authorization["authorization_id"],
            **(review_identity(authorization) if current else {}),
            "issuer_role": "HOST_REVIEW_AUTHORITY",
            "review_role": authorization["review_role"],
            "review_run_id": authorization["review_run_id"],
            "workspace_root": authorization["workspace_root"],
            "workspace_attestation_sha256": hashlib.sha256(
                rfc8785.dumps(cast(Any, attestation))
            ).hexdigest(),
            "input_content_roots": [
                item["content_root_sha256"]
                for item in cast(list[dict[str, object]], authorization["input_mounts"])
            ],
            "result_sha256": hashlib.sha256(rfc8785.dumps(cast(Any, result))).hexdigest(),
            "commands_executed_root": attestation["commands_executed_root"],
            "allowed_changed_paths": attestation["allowed_changed_paths"],
            "unexpected_changed_paths": [],
            "started_at": attestation["started_at"],
            "finished_at": attestation["finished_at"],
            "authorization_consumed_at": attestation["authorization_consumed_at"],
            "fresh_session_attestation": attestation["fresh_session_attestation"],
            "production_authority": "NONE",
            "signature_algorithm": "Ed25519",
            "host_boot_id": authorization["host_boot_id"],
            "trust_epoch": authorization["trust_epoch"],
            "preparation_commands_root": attestation["preparation_commands_root"],
        },
        private,
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    authorization = json.loads(args.authorization.read_text())
    workspace = Path(cast(str, authorization["workspace_root"]))
    authority = json.loads((RUNTIME_ROOT / "review-config/review-authority.v1.json").read_text())
    context = None
    if authorization.get("schema_version") == "review-launch-authorization/v2":
        context = authorized_review_context(authorization, authority, runtime_root=RUNTIME_ROOT)
        _validate_current_delivery(authorization, args.result, args.receipt)
    result = json.loads(args.result.read_text())
    attestation = json.loads(
        (
            Path(cast(str, authorization["allowed_output_root"])) / "workspace-attestation.json"
        ).read_text()
    )
    if context is not None:
        _validate_result(result, authorization.get("review_role"))
        verify_review_result_binding(result, authorization)
        _validate_current_workspace(authorization, attestation)
        review_config = cast(dict[str, object], context["config"])
        validate_review_scope(review_config, result)
        validate_host_execution(authorization, authority, review_config, attestation)
        recheck_review_context(context)
    bootstrap_review_authority(authority, initialize_if_absent=False)
    _validate_consumed_authorization(authorization, authority)
    private = serialization.load_pem_private_key(
        Path(cast(str, authority["private_key_path"])).read_bytes(), password=None
    )
    if not isinstance(private, Ed25519PrivateKey) or workspace.is_symlink():
        raise ValueError("E_REVIEW_FINALIZE_BINDING")
    verify_review_launch_authorization(
        authorization,
        private.public_key(),
        cast(str, authorization["review_role"]),
        cast(str, authorization["workspace_root"]),
        cast(str, authorization["pack_zip_sha256"]),
        expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        expected_trust_epoch=cast(int, authorization["trust_epoch"]),
    )
    if context is not None:
        recheck_review_context(context)
        _validate_current_delivery(authorization, args.result, args.receipt)
    receipt = finalize_review(
        authorization,
        result,
        attestation,
        private,
        external_seal=cast(dict[str, object], context["seal"]) if context is not None else None,
    )
    public = serialization.load_pem_private_key(
        Path(cast(str, authority["private_key_path"])).read_bytes(), password=None
    )
    if not isinstance(public, Ed25519PrivateKey):
        raise ValueError("E_REVIEW_FINALIZE_BINDING")
    verify_review_execution_receipt(
        receipt,
        authorization,
        public.public_key(),
        result_sha256=cast(str, receipt["result_sha256"]),
        expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        expected_trust_epoch=cast(int, authorization["trust_epoch"]),
    )
    receipt_text = json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    if context is not None:
        _validate_current_delivery(authorization, args.result, args.receipt)
        try:
            with args.receipt.open("x") as output:
                output.write(receipt_text)
        except OSError as error:
            raise ValueError("E_REVIEW_FINALIZE_BINDING") from error
    else:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(receipt_text)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
