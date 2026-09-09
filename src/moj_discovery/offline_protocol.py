"""Closed offline schema and identity checks; no production transport authority."""

import json
from functools import lru_cache
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing import Registry, Resource

from .schema_formats import STRICT_FORMAT_CHECKER
from .store import VENDOR

CONTRACTS = VENDOR.parents[1] / "contracts/offline_slice/v1"
MAX_INTEGER = 9223372036854775807


@lru_cache(maxsize=3)
def _validator(name: str) -> Draft202012Validator:
    resources = [json.loads(p.read_text()) for p in (VENDOR / "schemas").glob("*.json")]
    resources += [json.loads(p.read_text()) for p in CONTRACTS.glob("*.schema.json")]
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in resources)
    return Draft202012Validator(
        json.loads((CONTRACTS / name).read_text()),
        registry=registry,
        format_checker=STRICT_FORMAT_CHECKER,
    )


def validate_context(value: dict[str, Any]) -> None:
    try:
        _validator("context.schema.json").validate(value)
        if not 1024 <= int(value["normal_spool_limit_bytes"]) <= 133169152:
            raise ValueError()
        if int(value["generation"]) > MAX_INTEGER:
            raise ValueError()
    except Exception:
        raise ValueError("E_OFFLINE_SOURCE_BINDING") from None


def validate_frame(value: dict[str, Any]) -> None:
    try:
        _validator("frame.schema.json").validate(value)
        if int(value["counter"]) > MAX_INTEGER:
            raise ValueError()
        if value["message_type"] == "BATCH":
            body = value["body"]
            first, last = int(body["first_sequence"]), int(body["last_sequence"])
            if not 1 <= first <= last <= MAX_INTEGER or last - first + 1 != len(
                body["observations"]
            ):
                raise ValueError()
            if int(body["generation"]) > MAX_INTEGER:
                raise ValueError()
            for sequence, raw in enumerate(body["observations"], first):
                if (
                    raw["discovery_run_id"] != body["run_id"]
                    or raw["context"]["browser_run_id"] != body["browser_run_id"]
                    or raw["stream_id"] != body["stream_id"]
                    or raw["generation"] != body["generation"]
                    or raw["sequence"] != str(sequence)
                    or len(rfc8785.dumps(raw)) > 65536
                ):
                    raise ValueError()
        if len(rfc8785.dumps(value)) > 262144:
            raise ValueError()
    except Exception:
        raise ValueError("E_OFFLINE_SCHEMA") from None
