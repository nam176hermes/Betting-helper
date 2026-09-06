"""Domain-separated host review authorization and receipt verification."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .schema_formats import STRICT_FORMAT_CHECKER

LAUNCH_ID_DOMAIN = b"HD636/REVIEW-LAUNCH/ID/v1\0"
LAUNCH_SIGN_DOMAIN = b"HD636/REVIEW-LAUNCH/SIGN/v1\0"
RECEIPT_ID_DOMAIN = b"HD636/REVIEW-RECEIPT/ID/v1\0"
RECEIPT_SIGN_DOMAIN = b"HD636/REVIEW-RECEIPT/SIGN/v1\0"
RUNTIME_ROOT = Path(__file__).resolve().parents[2]


def _b64decode(value: object) -> bytes:
    if not isinstance(value, str) or "=" in value:
        raise ValueError("E_REVIEW_AUTH_SIGNATURE")
    try:
        result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as error:
        raise ValueError("E_REVIEW_AUTH_SIGNATURE") from error
    if base64.urlsafe_b64encode(result).decode().rstrip("=") != value:
        raise ValueError("E_REVIEW_AUTH_SIGNATURE")
    return result


def _projection(value: dict[str, object], *excluded: str) -> bytes:
    projected = {key: item for key, item in value.items() if key not in excluded}
    return rfc8785.dumps(cast(Any, projected))


def _identifier(value: dict[str, object], *, prefix: str, domain: bytes, derived: str) -> str:
    return prefix + hashlib.sha256(domain + _projection(value, "signature", derived)).hexdigest()


def _schema_validate(value: dict[str, object], schema_name: str, definition: str) -> None:
    schema_path = RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6/docs/schemas" / schema_name
    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]},
        format_checker=STRICT_FORMAT_CHECKER,
    )
    if next(validator.iter_errors(value), None) is not None:
        raise ValueError("E_REVIEW_AUTH_SCHEMA")


def _instant(value: object, error: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError as cause:
        raise ValueError(error) from cause
    if result.tzinfo is None:
        raise ValueError(error)
    return result.astimezone(UTC)


def key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "key:ed25519:" + hashlib.sha256(raw).hexdigest()


def sign_review_launch_authorization(
    authorization: dict[str, object], private_key: Ed25519PrivateKey
) -> dict[str, object]:
    value = dict(authorization)
    value.pop("authorization_id", None)
    value.pop("signature", None)
    value["issuer_key_id"] = key_id(private_key.public_key())
    value["authorization_id"] = _identifier(
        value, prefix="REVIEW-LAUNCH:", domain=LAUNCH_ID_DOMAIN, derived="authorization_id"
    )
    value["signature"] = base64.urlsafe_b64encode(
        private_key.sign(LAUNCH_SIGN_DOMAIN + _projection(value, "signature"))
    ).decode().rstrip("=")
    return value


def sign_review_execution_receipt(
    receipt: dict[str, object], private_key: Ed25519PrivateKey
) -> dict[str, object]:
    value = dict(receipt)
    value.pop("receipt_id", None)
    value.pop("signature", None)
    value["issuer_key_id"] = key_id(private_key.public_key())
    value["receipt_id"] = _identifier(
        value, prefix="REVIEW-RECEIPT:", domain=RECEIPT_ID_DOMAIN, derived="receipt_id"
    )
    value["signature"] = base64.urlsafe_b64encode(
        private_key.sign(RECEIPT_SIGN_DOMAIN + _projection(value, "signature"))
    ).decode().rstrip("=")
    return value


def _verify_signature(
    value: dict[str, object], public_key: Ed25519PublicKey, domain: bytes
) -> None:
    signature = _b64decode(value.get("signature"))
    if len(signature) != 64:
        raise ValueError("E_REVIEW_AUTH_SIGNATURE")
    try:
        public_key.verify(signature, domain + _projection(value, "signature"))
    except InvalidSignature as error:
        raise ValueError("E_REVIEW_AUTH_SIGNATURE") from error


def _verify_mounts(authorization: dict[str, object]) -> None:
    mounts = authorization.get("input_mounts")
    if not isinstance(mounts, list) or len(mounts) != 5:
        raise ValueError("E_REVIEW_AUTH_BINDING")
    source_roots: list[str] = []
    for mount in mounts:
        if (
            not isinstance(mount, dict)
            or mount.get("mode") != "READ_ONLY"
            or mount.get("source_root") != mount.get("workspace_mount")
            or not isinstance(mount.get("source_root"), str)
        ):
            raise ValueError("E_REVIEW_AUTH_BINDING")
        source_roots.append(cast(str, mount["source_root"]))
    if len(source_roots) != len(set(source_roots)):
        raise ValueError("E_REVIEW_AUTH_BINDING")


def verify_review_launch_authorization(
    authorization: dict[str, object],
    public_key: Ed25519PublicKey,
    expected_role: str,
    expected_workspace: str,
    expected_pack_sha256: str,
    *,
    expected_host_boot_id: str | None = None,
    expected_trust_epoch: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    _schema_validate(
        authorization,
        "review-launch-authorization.schema.json",
        "ReviewLaunchAuthorization",
    )
    expected_id = _identifier(
        authorization, prefix="REVIEW-LAUNCH:", domain=LAUNCH_ID_DOMAIN, derived="authorization_id"
    )
    if (
        authorization.get("authorization_id") != expected_id
        or authorization.get("issuer_key_id") != key_id(public_key)
    ):
        raise ValueError("E_REVIEW_AUTH_BINDING")
    _verify_signature(authorization, public_key, LAUNCH_SIGN_DOMAIN)
    issued = _instant(authorization["issued_at"], "E_REVIEW_AUTH_EXPIRY")
    not_before = _instant(authorization["not_before"], "E_REVIEW_AUTH_EXPIRY")
    expires = _instant(authorization["expires_at"], "E_REVIEW_AUTH_EXPIRY")
    trusted_now = (now or datetime.now(UTC)).astimezone(UTC)
    if (
        authorization.get("production_authority") != "NONE"
        or authorization.get("issuer_role") != "HOST_REVIEW_AUTHORITY"
        or authorization.get("audience") != "hybrid-discovery:independent-review-launcher:v1"
        or authorization.get("signature_algorithm") != "Ed25519"
        or authorization.get("fresh_session_required") is not True
        or authorization.get("maximum_duration_seconds") != 14400
        or not (issued <= not_before <= trusted_now < expires)
        or expires - issued != timedelta(seconds=14400)
        or authorization.get("review_role") != expected_role
        or authorization.get("workspace_root") != expected_workspace
        or authorization.get("pack_zip_sha256") != expected_pack_sha256
        or (
            expected_host_boot_id is not None
            and authorization.get("host_boot_id") != expected_host_boot_id
        )
        or (
            expected_trust_epoch is not None
            and authorization.get("trust_epoch") != expected_trust_epoch
        )
    ):
        raise ValueError("E_REVIEW_AUTH_BINDING")
    _verify_mounts(authorization)
    return {"result": "PASS", "authorization_id": expected_id}


def verify_review_execution_receipt(
    receipt: dict[str, object],
    authorization: dict[str, object],
    public_key: Ed25519PublicKey,
    *,
    result_sha256: str,
    expected_host_boot_id: str | None = None,
    expected_trust_epoch: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    verify_review_launch_authorization(
        authorization,
        public_key,
        cast(str, authorization["review_role"]),
        cast(str, authorization["workspace_root"]),
        cast(str, authorization["pack_zip_sha256"]),
        expected_host_boot_id=expected_host_boot_id,
        expected_trust_epoch=expected_trust_epoch,
        now=now,
    )
    _schema_validate(
        receipt,
        "review-execution-receipt.schema.json",
        "ReviewExecutionReceipt",
    )
    expected_id = _identifier(
        receipt,
        prefix="REVIEW-RECEIPT:",
        domain=RECEIPT_ID_DOMAIN,
        derived="receipt_id",
    )
    if (
        receipt.get("receipt_id") != expected_id
        or receipt.get("issuer_key_id") != authorization["issuer_key_id"]
    ):
        raise ValueError("E_REVIEW_RECEIPT_BINDING")
    _verify_signature(receipt, public_key, RECEIPT_SIGN_DOMAIN)
    mounts = cast(list[dict[str, object]], authorization["input_mounts"])
    expected_roots = [mount["content_root_sha256"] for mount in mounts]
    fresh = receipt.get("fresh_session_attestation")
    started = _instant(receipt["started_at"], "E_REVIEW_RECEIPT_FRESHNESS")
    finished = _instant(receipt["finished_at"], "E_REVIEW_RECEIPT_FRESHNESS")
    consumed = _instant(receipt["authorization_consumed_at"], "E_REVIEW_RECEIPT_FRESHNESS")
    expires = _instant(authorization["expires_at"], "E_REVIEW_RECEIPT_FRESHNESS")
    trusted_now = (now or datetime.now(UTC)).astimezone(UTC)
    if (
        receipt.get("authorization_id") != authorization["authorization_id"]
        or receipt.get("issuer_role") != "HOST_REVIEW_AUTHORITY"
        or receipt.get("review_role") != authorization["review_role"]
        or receipt.get("review_run_id") != authorization["review_run_id"]
        or receipt.get("workspace_root") != authorization["workspace_root"]
        or receipt.get("input_content_roots") != expected_roots
        or receipt.get("result_sha256") != result_sha256
        or receipt.get("production_authority") != "NONE"
        or receipt.get("signature_algorithm") != "Ed25519"
        or receipt.get("host_boot_id") != authorization["host_boot_id"]
        or receipt.get("trust_epoch") != authorization["trust_epoch"]
        or receipt.get("unexpected_changed_paths") != []
        or not isinstance(receipt.get("allowed_changed_paths"), list)
        or not receipt["allowed_changed_paths"]
        or not isinstance(fresh, dict)
        or fresh.get("attestation_type") != "HUMAN_FRESH_CODEX_SESSION"
        or fresh.get("attested") is not True
        or fresh.get("procedural_not_cryptographic") is not True
        or not (consumed <= started <= finished <= expires and finished <= trusted_now)
        or finished - started > timedelta(seconds=14400)
    ):
        raise ValueError("E_REVIEW_RECEIPT_BINDING")
    return {"result": "PASS", "receipt_id": expected_id}
