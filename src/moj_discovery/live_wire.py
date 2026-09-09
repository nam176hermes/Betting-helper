"""Closed live-only wire, role-bound handshake, finite one-time pairing lease."""

import base64
import hashlib
import hmac
import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

import rfc8785

from .canonical import parse_strict_json
from .live_contracts import event_hash, schema_validate, validate_live_record

PROTOCOL = "BH_LIVE_WIRE_V1"
DOMAIN = b"BH-LIVE-WIRE/v1\0"
ROLES = frozenset({"CAPTURE_PRODUCER", "UI_SUBSCRIBER"})
CLIENT_TYPES = {
    "CAPTURE_PRODUCER": {"CAPTURE_BATCH", "HEALTH", "STOP_CAPTURE", "PING", "PONG"},
    "UI_SUBSCRIBER": {
        "WATCHLIST_ADD",
        "WATCHLIST_REMOVE",
        "SELECT_ACTIVE",
        "REFRESH",
        "STOP_SESSION",
        "PING",
        "PONG",
    },
}
BACKEND_TYPES = frozenset({"ACK", "NACK", "PROJECTION", "PING", "PONG"})


def validate_frame(value: object) -> dict[str, Any]:
    try:
        schema_validate(value, "wire")
        frame = cast(dict[str, Any], value)
        if len(rfc8785.dumps(frame)) > 262144:
            raise ValueError()
        body = frame["body"]
        if frame["message_type"] == "CAPTURE_BATCH":
            first, last = int(body["first_sequence"]), int(body["last_sequence"])
            if last - first + 1 != len(body["events"]):
                raise ValueError()
            for sequence, raw in enumerate(body["events"], first):
                event = validate_live_record(raw, "LiveEvent")
                if (
                    event["source_kind"] != "OPERATOR"
                    or event["payload_type"] != "MarketBook"
                    or any(event[k] != body[k] for k in ("run_id", "stream_id", "generation"))
                    or event["sequence"] != str(sequence)
                    or event_hash(event) != event["content_hash"]
                ):
                    raise ValueError()
        elif frame["message_type"] == "PROJECTION":
            validate_live_record(body["binding"], "FixtureBinding")
            if body["provider_state"] is not None:
                state = validate_live_record(body["provider_state"], "ProviderState")
                if state["fixture_id"] != body["binding"]["provider_fixture_id"]:
                    raise ValueError()
            horizons = set()
            for value in body["books"]:
                book = validate_live_record(value, "MarketBook")
                if (
                    book["binding_id"] != body["binding"]["binding_id"]
                    or book["binding_revision"] != body["binding"]["revision"]
                    or book["horizon"] in horizons
                ):
                    raise ValueError()
                horizons.add(book["horizon"])
        return frame
    except Exception:
        raise ValueError("E_LIVE_WIRE_SCHEMA") from None


def encode_frame(content: dict[str, Any], key: bytes) -> bytes:
    if type(key) is not bytes or len(key) != 32 or "mac" in content:
        raise ValueError("E_LIVE_WIRE_KEY")
    validate_frame({**content, "mac": "0" * 64})
    signature = hmac.new(key, DOMAIN + rfc8785.dumps(content), hashlib.sha256).hexdigest()
    return rfc8785.dumps({**content, "mac": signature})


def decode_frame(data: bytes, key: bytes) -> dict[str, Any]:
    if type(data) is not bytes or len(data) > 262144 or type(key) is not bytes or len(key) != 32:
        raise ValueError("E_LIVE_WIRE_FRAME")
    try:
        frame = validate_frame(parse_strict_json(data))
        content = {k: v for k, v in frame.items() if k != "mac"}
        expected = hmac.new(key, DOMAIN + rfc8785.dumps(content), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(frame["mac"], expected):
            raise ValueError()
        return frame
    except Exception:
        raise ValueError("E_LIVE_WIRE_AUTHENTICATION") from None


class LiveSession:
    def __init__(
        self,
        session_id: str,
        run_id: str,
        side: str,
        role: str,
        deadline_mono: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        for identifier in (session_id, run_id):
            if str(UUID(identifier)) != identifier:
                raise ValueError("E_LIVE_WIRE_IDENTITY")
        if (
            side not in {"CLIENT", "BACKEND"}
            or role not in ROLES
            or not math.isfinite(deadline_mono)
            or not 0 < deadline_mono - clock() <= 7200
        ):
            raise ValueError("E_LIVE_WIRE_ROLE_OR_LEASE")
        self.session_id, self.run_id, self.side, self.role = session_id, run_id, side, role
        self.deadline, self.clock, self.started = deadline_mono, clock, clock()
        self.stage, self.in_counter, self.out_counter = 0, 0, 0
        self.client_nonce: str | None = None
        self.server_nonce: str | None = None

    @property
    def ready(self) -> bool:
        return self.stage == 4 and self.clock() < self.deadline

    def accept(self, frame: dict[str, Any], incoming: bool) -> None:
        validate_frame(frame)
        now = self.clock()
        if now < self.started or now >= self.deadline:
            raise ValueError("E_LIVE_WIRE_LEASE")
        outgoing = "CLIENT_TO_BACKEND" if self.side == "CLIENT" else "BACKEND_TO_CLIENT"
        direction = (
            ("BACKEND_TO_CLIENT" if outgoing == "CLIENT_TO_BACKEND" else "CLIENT_TO_BACKEND")
            if incoming
            else outgoing
        )
        counter = (self.in_counter if incoming else self.out_counter) + 1
        body, kind = frame["body"], frame["message_type"]
        if (
            frame["session_id"] != self.session_id
            or frame["direction"] != direction
            or frame["counter"] != str(counter)
            or body["run_id"] != self.run_id
        ):
            raise ValueError("E_LIVE_WIRE_SESSION_COUNTER")
        stage, client, server = self.stage, self.client_nonce, self.server_nonce
        if stage < 4:
            if now - self.started > 5:
                raise ValueError("E_LIVE_WIRE_HANDSHAKE_TIMEOUT")
            types = ("HELLO", "WELCOME", "READY", "READY_ACK")
            expected_incoming = stage % 2 == (1 if self.side == "CLIENT" else 0)
            if kind != types[stage] or incoming != expected_incoming:
                raise ValueError("E_LIVE_WIRE_HANDSHAKE_ORDER")
            for name in ("client_nonce", "server_nonce"):
                if name in body:
                    decoded = base64.urlsafe_b64decode(body[name] + "=")
                    if (
                        len(decoded) != 32
                        or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != body[name]
                    ):
                        raise ValueError("E_LIVE_WIRE_NONCE")
            if stage == 0:
                if body["role"] != self.role:
                    raise ValueError("E_LIVE_WIRE_ROLE")
                client = body["client_nonce"]
            elif body["client_nonce"] != client:
                raise ValueError("E_LIVE_WIRE_NONCE")
            if stage == 1:
                server = body["server_nonce"]
                if server == client:
                    raise ValueError("E_LIVE_WIRE_NONCE")
            elif stage >= 2 and body["server_nonce"] != server:
                raise ValueError("E_LIVE_WIRE_NONCE")
            stage += 1
        elif kind not in (
            CLIENT_TYPES[self.role] if direction == "CLIENT_TO_BACKEND" else BACKEND_TYPES
        ):
            raise ValueError("E_LIVE_WIRE_ROLE_DENIED")
        self.stage, self.client_nonce, self.server_nonce = stage, client, server
        if incoming:
            self.in_counter = counter
        else:
            self.out_counter = counter

    def send(self, kind: str, body: dict[str, Any], key: bytes) -> bytes:
        content = dict(
            protocol=PROTOCOL,
            session_id=self.session_id,
            direction="CLIENT_TO_BACKEND" if self.side == "CLIENT" else "BACKEND_TO_CLIENT",
            counter=str(self.out_counter + 1),
            message_type=kind,
            body=body,
        )
        data = encode_frame(content, key)
        self.accept({**content, "mac": "0" * 64}, False)
        return data

    def receive(self, data: bytes, key: bytes) -> dict[str, Any]:
        frame = decode_frame(data, key)
        self.accept(frame, True)
        return frame


@dataclass(frozen=True)
class PairingTicket:
    session_id: str
    role: str
    expires_mono: float
    key: bytes = field(repr=False)

    def __repr__(self) -> str:
        return "PairingTicket([REDACTED])"


class PairingAuthority:
    def __init__(
        self, run_id: str, deadline_mono: float, *, clock: Callable[[], float] = time.monotonic
    ):
        if (
            str(UUID(run_id)) != run_id
            or not math.isfinite(deadline_mono)
            or not 0 < deadline_mono - clock() <= 7200
        ):
            raise ValueError("E_LIVE_PAIRING_SCOPE")
        self.run_id, self.deadline, self.clock = run_id, deadline_mono, clock
        self._tickets: dict[str, PairingTicket] = {}
        self._issued = 0
        self._lock = threading.Lock()

    def issue(self, role: str) -> PairingTicket:
        with self._lock:
            now = self.clock()
            self._tickets = {s: t for s, t in self._tickets.items() if t.expires_mono > now}
            if (
                role not in ROLES
                or now >= self.deadline
                or len(self._tickets) >= 2
                or self._issued >= 32
            ):
                raise ValueError("E_LIVE_PAIRING_CAP")
            ticket = PairingTicket(
                str(uuid4()), role, min(now + 120, self.deadline), secrets.token_bytes(32)
            )
            self._tickets[ticket.session_id] = ticket
            self._issued += 1
            return ticket

    def revoke(self) -> None:
        with self._lock:
            self._tickets.clear()
            self.deadline = self.clock()

    def consume(self, data: bytes) -> tuple[LiveSession, bytes]:
        with self._lock:
            try:
                if type(data) is not bytes or len(data) > 262144:
                    raise ValueError()
                hello = validate_frame(parse_strict_json(data))
                ticket = self._tickets[hello["session_id"]]
                if self.clock() >= ticket.expires_mono:
                    raise ValueError()
                session = LiveSession(
                    ticket.session_id,
                    self.run_id,
                    "BACKEND",
                    ticket.role,
                    self.deadline,
                    clock=self.clock,
                )
                session.receive(data, ticket.key)
                if session.stage != 1:
                    raise ValueError()
                del self._tickets[ticket.session_id]
                return session, ticket.key
            except Exception:
                raise ValueError("E_LIVE_PAIRING_REJECTED") from None
