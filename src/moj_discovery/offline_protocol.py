"""Closed offline schema and identity checks; no production transport authority."""

import json
from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

import rfc8785
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .schema_registry import _compiled, validate_artifact
from .store import VENDOR

CONTRACTS = VENDOR.parents[1] / "contracts/offline_slice/v1"
MAX_INTEGER = 9223372036854775807


def _validator(name: str) -> Draft202012Validator:
    return _compiled((CONTRACTS / name).read_bytes(), _resources())


def _resources() -> tuple[bytes, ...]:
    return tuple(p.read_bytes() for p in sorted((VENDOR / "schemas").glob("*.json"))) + tuple(
        p.read_bytes() for p in sorted(CONTRACTS.glob("*.schema.json"))
    )


@lru_cache(maxsize=8)
def _envelope(schema_bytes: bytes, resources: tuple[bytes, ...]) -> Draft202012Validator:
    schema = json.loads(schema_bytes)
    observations = schema["$defs"]["BATCH"]["properties"]["observations"]
    if observations["items"] != {"$ref": "urn:hybrid-discovery:v6.2:raw-observation:v1"}:
        raise ValueError("E_OFFLINE_SCHEMA_CONTRACT")
    # Equivalent conjunction: closed envelope AND every complete raw schema below.
    # Separate raw proofs can be reused by the journal/ingestor, with exact source bytes.
    observations["items"] = True
    encoded = json.dumps(schema).encode()
    return _compiled(
        encoded, tuple(encoded if data == schema_bytes else data for data in resources)
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
        _envelope((CONTRACTS / "frame.schema.json").read_bytes(), _resources()).validate(value)
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
                validate_artifact(
                    raw, "raw-observation.schema.json", bootstrap_only=True, vendor=VENDOR
                )
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


# Standard-library HMAC; the key is never included in frame or context serialization.
def encode_frame(frame_without_mac: dict[str, Any], key: bytes) -> bytes:
    import hashlib
    import hmac

    if len(key) != 32 or "mac" in frame_without_mac:
        raise ValueError("E_OFFLINE_KEY_OR_FRAME")
    frame = {**frame_without_mac, "mac": "0" * 64}
    validate_frame(frame)
    frame["mac"] = hmac.new(
        key, b"BH-OFFLINE-WIRE/v1\0" + rfc8785.dumps(frame_without_mac), hashlib.sha256
    ).hexdigest()
    return rfc8785.dumps(frame)


class SessionState:
    def __init__(
        self, session_id: str, run_id: str, role: str, clock: Callable[[], float] | None = None
    ) -> None:
        from time import monotonic

        if role not in {"CLIENT", "BACKEND"}:
            raise ValueError("E_OFFLINE_ROLE")
        self.session_id = session_id
        self.run_id = run_id
        self.role = role
        self.clock = clock or monotonic
        self.started = self.clock()
        self.stage = 0
        self.in_counter = 0
        self.out_counter = 0
        self.client_nonce: str | None = None
        self.server_nonce: str | None = None

    @property
    def ready(self) -> bool:
        return self.stage == 4

    def accept(self, frame: dict[str, Any], *, incoming: bool) -> None:
        import base64

        outgoing = "CLIENT_TO_BACKEND" if self.role == "CLIENT" else "BACKEND_TO_CLIENT"
        direction = (
            ("BACKEND_TO_CLIENT" if outgoing == "CLIENT_TO_BACKEND" else "CLIENT_TO_BACKEND")
            if incoming
            else outgoing
        )
        expected_counter = (self.in_counter if incoming else self.out_counter) + 1
        if (
            frame["session_id"] != self.session_id
            or frame["direction"] != direction
            or frame["counter"] != str(expected_counter)
        ):
            raise ValueError("E_OFFLINE_SESSION_COUNTER")
        body = frame["body"]
        if "run_id" in body and body["run_id"] != self.run_id:
            raise ValueError("E_OFFLINE_SOURCE_BINDING")
        client_nonce, server_nonce = self.client_nonce, self.server_nonce
        stage = self.stage
        if stage < 4:
            if self.clock() - self.started > 5:
                raise ValueError("E_OFFLINE_HANDSHAKE_TIMEOUT")
            types = ("HELLO", "WELCOME", "READY", "READY_ACK")
            expected_incoming = (stage % 2 == 1) if self.role == "CLIENT" else (stage % 2 == 0)
            if frame["message_type"] != types[stage] or incoming != expected_incoming:
                raise ValueError("E_OFFLINE_HANDSHAKE_ORDER")
            for name in ("client_nonce", "server_nonce"):
                if name in body:
                    nonce = body[name]
                    decoded = base64.urlsafe_b64decode(nonce + "=")
                    if (
                        len(decoded) != 32
                        or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != nonce
                    ):
                        raise ValueError("E_OFFLINE_NONCE")
            if stage == 0:
                client_nonce = body["client_nonce"]
            elif body["client_nonce"] != client_nonce:
                raise ValueError("E_OFFLINE_NONCE")
            if stage == 1:
                server_nonce = body["server_nonce"]
                if server_nonce == client_nonce:
                    raise ValueError("E_OFFLINE_NONCE")
            elif stage >= 2 and body["server_nonce"] != server_nonce:
                raise ValueError("E_OFFLINE_NONCE")
            stage += 1
        elif stage != 4 or frame["message_type"] in {"HELLO", "WELCOME", "READY", "READY_ACK"}:
            raise ValueError("E_OFFLINE_HANDSHAKE_ORDER")
        elif frame["message_type"] == "STOP":
            stage = 5
        self.client_nonce, self.server_nonce, self.stage = client_nonce, server_nonce, stage
        if incoming:
            self.in_counter = expected_counter
        else:
            self.out_counter = expected_counter

    def send(self, message_type: str, body: dict[str, Any], key: bytes) -> bytes:
        frame = {
            "protocol": "BH_OFFLINE_WIRE_V1",
            "session_id": self.session_id,
            "direction": "CLIENT_TO_BACKEND" if self.role == "CLIENT" else "BACKEND_TO_CLIENT",
            "counter": str(self.out_counter + 1),
            "message_type": message_type,
            "body": body,
        }
        encoded = encode_frame(frame, key)
        self.accept(frame, incoming=False)
        return encoded


def verify_frame(data: bytes, key: bytes, session: SessionState) -> dict[str, Any]:
    import hashlib
    import hmac

    from .canonical import parse_strict_json

    if len(data) > 262144 or len(key) != 32:
        raise ValueError("E_OFFLINE_FRAME_SIZE_OR_KEY")
    try:
        parsed = parse_strict_json(data)
        if not isinstance(parsed, dict):
            raise ValueError()
        frame = cast(dict[str, Any], parsed)
        validate_frame(frame)
    except Exception:
        raise ValueError("E_OFFLINE_SCHEMA") from None
    content = {k: v for k, v in frame.items() if k != "mac"}
    expected = hmac.new(
        key, b"BH-OFFLINE-WIRE/v1\0" + rfc8785.dumps(content), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(frame["mac"], expected):
        raise ValueError("E_OFFLINE_MAC")
    session.accept(frame, incoming=True)
    return frame
