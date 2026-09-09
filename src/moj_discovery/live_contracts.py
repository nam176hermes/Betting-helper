"""Source-owned live schema boundary; validation never confers source authority."""

import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import rfc8785

from .canonical import _validate_unicode
from .schema_registry import _compiled, _plain_json

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts/live_readonly/v1"
RECORD_KINDS = frozenset(
    {
        "ProviderState",
        "MarketBook",
        "FixtureBinding",
        "BindingChange",
        "HealthChange",
        "LiveEvent",
    }
)
MAX_INTEGER = 2**63 - 1
COUNTERS = frozenset(
    {
        "received_mono_us",
        "content_revision",
        "binding_revision",
        "capture_revision",
        "browser_mono_us",
        "revision",
        "before_revision",
        "epoch",
        "generation",
        "sequence",
        "counter",
        "first_sequence",
        "last_sequence",
        "monotonic_us",
    }
)


def schema_validate(value: object, name: str, kind: str | None = None) -> None:
    """Resolve only registered local resources; no external resolver or I/O callback."""
    if name not in {"records", "wire", "config", "operator-profile", "run-intent"}:
        raise ValueError("E_LIVE_SCHEMA_NAME")
    schema = (CONTRACTS / f"{name}.schema.json").read_bytes()
    resources = tuple(p.read_bytes() for p in sorted(CONTRACTS.glob("*.schema.json")))
    if kind is not None:
        if name != "records" or kind not in RECORD_KINDS:
            raise ValueError("E_LIVE_SCHEMA_KIND")
        schema = json.dumps({"$ref": f"urn:betting-helper:live-records:v1#/$defs/{kind}"}).encode()
    if not _plain_json(value):
        raise ValueError("E_LIVE_JSON_TYPE")
    _validate_unicode(value)
    _scalars(value)
    _compiled(schema, resources).validate(value)


def _scalars(value: Any, key: str = "") -> None:
    if type(value) is float:
        raise ValueError("E_LIVE_INTEGER_TYPE")
    if isinstance(value, dict):
        for name, child in value.items():
            _scalars(child, name)
    elif isinstance(value, list):
        for child in value:
            _scalars(child, key)
    elif isinstance(value, str):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("E_LIVE_CONTROL_CHARACTER")
        if key in COUNTERS and int(value) > MAX_INTEGER:
            raise ValueError("E_LIVE_INTEGER_RANGE")


def _semantics(value: dict[str, Any], kind: str) -> None:
    if kind == "LiveEvent":
        _semantics(value["payload"], value["payload_type"])
    elif kind == "BindingChange":
        _semantics(value["after"], "FixtureBinding")
    elif kind in {"ProviderState", "FixtureBinding"}:
        if value["home_id"] == value["away_id"]:
            raise ValueError("E_LIVE_PARTICIPANTS")
        if kind == "ProviderState":
            # This adapter has no verified upstream update-time field.
            if value["provider_updated_at"] is not None:
                raise ValueError("E_LIVE_SOURCE_TIME_UNVERIFIED")
            if value["events_status"] in {"OBSERVED_EMPTY", "UNKNOWN_SECTION"} and value["events"]:
                raise ValueError("E_LIVE_EVENTS_STATUS")
        else:
            if value["operator_home_id"] == value["operator_away_id"]:
                raise ValueError("E_LIVE_PARTICIPANTS")
            if value["orientation_status"] == "VERIFIED" and not value["evidence_hashes"]:
                raise ValueError("E_LIVE_BINDING_EVIDENCE")
            for key in ("operator_match_url", "livescore_match_url"):
                if value[key] is not None:
                    url = urlsplit(value[key])
                    if (
                        url.scheme != "https"
                        or not url.hostname
                        or url.username
                        or url.password
                        or url.query
                        or url.fragment
                        or url.port not in {None, 443}
                    ):
                        raise ValueError("E_LIVE_BINDING_URL")
    elif kind == "MarketBook":
        selections = value["selections"].values()
        if len({row["selection_id"] for row in selections}) != 3:
            raise ValueError("E_LIVE_SELECTION_IDENTITY")
        if any(Decimal(row["decimal_odds"]) <= 1 for row in selections):
            raise ValueError("E_LIVE_ODDS")


def validate_live_record(value: object, kind: str) -> dict[str, Any]:
    try:
        schema_validate(value, "records", kind)
        record = cast(dict[str, Any], value)
        _scalars(record)
        _semantics(record, kind)
        if len(rfc8785.dumps(record)) > 65536:
            raise ValueError("E_LIVE_RECORD_SIZE")
        return copy.deepcopy(record)
    except Exception:
        # Schema exceptions include rejected data; never propagate them to logging.
        raise ValueError("E_LIVE_RECORD") from None


def event_hash(value: object) -> str:
    record = validate_live_record(value, "LiveEvent")
    del record["content_hash"]
    return hashlib.sha256(b"BH-LIVE-READONLY/Event/v1\0" + rfc8785.dumps(record)).hexdigest()
