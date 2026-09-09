"""Synthetic accounting observations only; never provider or operator observations."""

import hashlib
from pathlib import Path
from typing import Any, cast

import rfc8785

from .canonical import canonical_content_hash, parse_strict_json, verify_canonical_content_hash
from .offline_protocol import validate_context
from .schema_registry import validate_artifact
from .store import VENDOR


def validate_synthetic_observation(data: bytes, context: dict[str, Any]) -> dict[str, Any]:
    if len(data) > 65536:
        raise ValueError("E_OFFLINE_INPUT_SIZE")
    try:
        raw = parse_strict_json(data)
    except Exception:
        raise ValueError("E_OFFLINE_JSON") from None
    try:
        validate_artifact(raw, "raw-observation.schema.json", bootstrap_only=True, vendor=VENDOR)
    except Exception:
        raise ValueError("E_OFFLINE_SCHEMA") from None
    value = cast(dict[str, Any], raw)
    validate_context(context)
    if (
        value["observation_kind"] != "TERMINAL"
        or value["context"]["context_kind"] != "RUN_BOUND_NOT_DOCUMENT"
        or value["discovery_run_id"] != context["run_id"]
        or value["context"]["browser_run_id"] != context["browser_run_id"]
        or value["stream_id"] != context["stream_id"]
        or value["generation"] != context["generation"]
    ):
        raise ValueError("E_OFFLINE_SOURCE_BINDING")
    try:
        verify_canonical_content_hash(
            "RawObservation",
            value,
            value["content_hash"],
            registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
        )
    except Exception:
        raise ValueError("E_OFFLINE_CONTENT_HASH") from None
    return value


def load_synthetic_observations(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if len(data) > 262144:
        raise ValueError("E_OFFLINE_INPUT_SIZE")
    try:
        manifest = cast(dict[str, Any], parse_strict_json(data))
        if (
            set(manifest) != {"schema_version", "source_kind", "context", "record_count"}
            or manifest["schema_version"] != "offline-scenario/v1"
            or manifest["source_kind"] != "SYNTHETIC_TEST"
            or type(manifest["record_count"]) is not int
            or not 1 <= manifest["record_count"] <= 1000
        ):
            raise ValueError()
        context = manifest["context"]
        validate_context(context)
    except Exception:
        raise ValueError("E_OFFLINE_SOURCE_BINDING") from None
    result = []
    for sequence in range(1, manifest["record_count"] + 1):
        raw: dict[str, Any] = {
            "schema_version": "raw-observation/v1",
            "raw_observation_id": "observation:"
            + hashlib.sha256(
                rfc8785.dumps(
                    [context["run_id"], context["stream_id"], context["generation"], str(sequence)]
                )
            ).hexdigest(),
            "observation_kind": "TERMINAL",
            "pack_hash": context["vendor_sha256"],
            "build_hash": context["code_sha256"],
            "implementation_baseline_hash": context["code_sha256"],
            "capability_manifest_hash": context["schema_lock_sha256"],
            "discovery_run_id": context["run_id"],
            # Synthetic context digest; it is explicitly not a signed live receipt.
            "run_receipt_hash": hashlib.sha256(rfc8785.dumps(context)).hexdigest(),
            "stream_id": context["stream_id"],
            "generation": context["generation"],
            "sequence": str(sequence),
            "context": {
                "context_kind": "RUN_BOUND_NOT_DOCUMENT",
                "browser_run_id": context["browser_run_id"],
                "browser_boot_id": context["browser_run_id"],
                "binding_reason": "TERMINAL_ACCOUNTING",
            },
            "clock_context": {
                "clock_domain_id": context["producer_id"],
                "boot_id": context["browser_run_id"],
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
                "final_generation": context["generation"],
                "final_sequence": str(sequence),
                "observation_count": str(sequence),
                "gap_count": "0",
                "safety_disposition": "PARTIAL_EVIDENCE_ONLY",
            },
        }
        raw["content_hash"] = canonical_content_hash(
            "RawObservation",
            raw,
            registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
        )
        result.append(validate_synthetic_observation(rfc8785.dumps(raw), context))
    return result
