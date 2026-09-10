"""Authenticated bounded /live receiver. No provider endpoints or generic commands."""

import asyncio
import copy
import importlib
import logging
import math
import re
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from uuid import UUID, uuid4, uuid5

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.protocol import State
from websockets.typing import Origin

from .live_contracts import event_hash
from .live_store import LiveStore
from .live_wire import LiveSession, PairingAuthority, validate_frame

HEALTH = {
    "HIDDEN": "STALE_MARKET",
    "NAVIGATED": "CONTEXT_UNVERIFIED",
    "DOM_UNSTABLE": "STALE_MARKET",
    "PROFILE_EXPIRED": "PROFILE_EXPIRED",
    "SPOOL_CAPACITY": "PAUSED",
    "DISCONNECTED": "CONTEXT_UNVERIFIED",
    "WORKER_RESTART": "CONTEXT_UNVERIFIED",
    "USER_STOP": "STOPPED",
    "PAIRING_RENEWED": "CONTEXT_UNVERIFIED",
    "CAPTURE_REJECTED": "CONTEXT_UNVERIFIED",
}


class LiveReceiver:
    def connected(self, role: str) -> bool:
        return role in self._active

    def __init__(self, context: dict[str, Any], store: LiveStore, pairing: PairingAuthority):
        self.context = copy.deepcopy(context)
        self.store, self.pairing = store, pairing
        self._validate_context()
        self.server: Server | None = None
        self._reserved: set[ServerConnection] = set()
        self._active: dict[str, tuple[ServerConnection, LiveSession, bytes]] = {}
        self._send_locks: dict[ServerConnection, asyncio.Lock] = {}
        self._send_pending: dict[ServerConnection, int] = {}
        self._intake = asyncio.Lock()
        self._stopped_bindings: set[str] = set()
        self.rejections: deque[str] = deque(maxlen=128)
        self.on_ui: Callable[[str, str | None], Awaitable[None]] | None = None
        self.on_capture: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self.on_change: Callable[[str | None, str], Awaitable[None]] | None = None

    def _validate_context(self) -> None:
        try:
            c = self.context
            required = {
                "run_id",
                "allowed_extension_origin",
                "deadline_mono",
                "source_kind",
                "capture_streams",
            }
            if (
                set(c) not in (required, required | {"authority"})
                or c["run_id"] != self.store.run_id
                or c["run_id"] != self.pairing.run_id
                or c["deadline_mono"] != self.pairing.deadline
                or not math.isfinite(c["deadline_mono"])
                or not 0 < c["deadline_mono"] - time.monotonic() <= 7200
                or not re.fullmatch(r"chrome-extension://[a-p]{32}", c["allowed_extension_origin"])
                or c["source_kind"] not in {"MOCK", "OBSERVED_REAL"}
            ):
                raise ValueError()
            streams = c["capture_streams"]
            if type(streams) is not dict or not 1 <= len(streams) <= 5:
                raise ValueError()
            bindings = self.store.bindings()
            seen = set()
            for stream_id, scope in streams.items():
                if str(UUID(stream_id)) != stream_id or set(scope) != {
                    "binding_id",
                    "binding_revision",
                    "operator_fixture_id",
                    "generation",
                    "profile_hash",
                    "document_epoch",
                    "markets",
                }:
                    raise ValueError()
                binding = bindings[scope["binding_id"]]
                if (
                    scope["binding_id"] in seen
                    or binding["revision"] != scope["binding_revision"]
                    or binding["operator_fixture_id"] != scope["operator_fixture_id"]
                    or not re.fullmatch(r"[0-9a-f]{64}", scope["profile_hash"])
                    or not re.fullmatch(r"0|[1-9][0-9]{0,18}", scope["generation"])
                    or int(scope["generation"]) > 2**63 - 1
                ):
                    raise ValueError()
                UUID(scope["document_epoch"])
                seen.add(scope["binding_id"])
                if not scope["markets"] or not set(scope["markets"]) <= {"H1", "H2", "FT"}:
                    raise ValueError()
                for market in scope["markets"].values():
                    if (
                        set(market) != {"market_id", "selections"}
                        or set(market["selections"]) != {"HOME", "DRAW", "AWAY"}
                        or len(set(market["selections"].values())) != 3
                        or any(
                            type(i) is not str or not 1 <= len(i) <= 128
                            for i in (market["market_id"], *market["selections"].values())
                        )
                    ):
                        raise ValueError()
            if c["source_kind"] == "OBSERVED_REAL":
                # PB-16 verifies admitted evidence; a context flag never authorizes real capture.
                importlib.import_module(
                    "moj_discovery.live_preflight_batched"
                ).verify_receiver_authority(c)
        except Exception:
            raise ValueError("E_LIVE_RECEIVER_CONTEXT") from None

    async def start(self) -> None:
        logger = logging.Logger("live-wire", level=logging.CRITICAL)
        logger.propagate = False
        logger.addHandler(logging.NullHandler())
        self.server = await serve(
            self._connection,
            "127.0.0.1",
            8765,
            origins=[Origin(self.context["allowed_extension_origin"])],
            compression=None,
            max_size=262144,
            max_queue=8,
            write_limit=32768,
            open_timeout=5,
            close_timeout=3,
            process_request=self._request,
            logger=logger,
        )

    async def close(self) -> None:
        self.pairing.revoke()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    def _request(self, socket: ServerConnection, request: Request) -> Response | None:
        self._reserved = {s for s in self._reserved if s.state is not State.CLOSED}
        if (
            request.path != "/live"
            or request.headers.get_all("Host") != ["127.0.0.1:8765"]
            or request.headers.get_all("Origin") != [self.context["allowed_extension_origin"]]
        ):
            self.rejections.append("HTTP_BINDING")
            return socket.respond(HTTPStatus.FORBIDDEN, "HTTP_BINDING")
        if len(self._reserved) >= 2 or time.monotonic() >= self.context["deadline_mono"]:
            return socket.respond(HTTPStatus.SERVICE_UNAVAILABLE, "CAPACITY_OR_LEASE")
        self._reserved.add(socket)
        self._send_locks[socket] = asyncio.Lock()
        self._send_pending[socket] = 0
        return None

    async def _send(
        self, peer: tuple[ServerConnection, LiveSession, bytes], kind: str, body: dict[str, Any]
    ) -> None:
        socket, session, key = peer
        if self._send_pending.get(socket, 8) >= 8:
            raise ValueError("E_LIVE_WIRE_BACKPRESSURE")
        self._send_pending[socket] += 1
        try:
            async with self._send_locks[socket]:
                encoded = session.send(kind, body, key)
                await asyncio.wait_for(socket.send(encoded.decode()), 5)
        finally:
            self._send_pending[socket] = max(0, self._send_pending.get(socket, 1) - 1)

    async def publish(self, body: dict[str, Any], *, role: str = "UI_SUBSCRIBER") -> None:
        if role not in {"UI_SUBSCRIBER", "CAPTURE_PRODUCER"}:
            raise ValueError("E_LIVE_PROJECTION_ROLE")
        peer = self._active.get(role)
        if peer is not None:
            try:
                await self._send(peer, "PROJECTION", body)
            except Exception:
                await peer[0].close(1008, "PROJECTION_BACKPRESSURE_OR_REJECTED")

    async def _health(self, binding_id: str | None, code: str) -> None:
        if code not in HEALTH or (
            binding_id is not None and binding_id not in self.store.bindings()
        ):
            raise ValueError("E_LIVE_HEALTH_SCOPE")
        stream = str(uuid5(UUID(self.store.run_id), "BH-LIVE-RECEIVER/health"))
        sequence, previous = self.store.cursor(stream)
        record = dict(
            protocol="BH_LIVE_READONLY_V1",
            run_id=self.store.run_id,
            source_kind="CONTROL",
            stream_id=stream,
            generation="0",
            sequence=str(sequence + 1),
            observation_id=str(uuid4()),
            observed_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            received_mono_us=str(int(time.monotonic() * 1_000_000)),
            payload_type="HealthChange",
            payload=dict(
                binding_id=binding_id,
                reason=code,
                state=HEALTH[code],
                epoch=str(sequence + 1),
                evidence_hashes=[],
            ),
            previous_hash=previous,
            content_hash="0" * 64,
        )
        record["content_hash"] = event_hash(record)
        await asyncio.to_thread(self.store.append, record)

    def _capture_scope(self, event: dict[str, Any]) -> None:
        try:
            scope = self.context["capture_streams"][event["stream_id"]]
            book = event["payload"]
            if (
                scope["binding_id"] in self._stopped_bindings
                or event["generation"] != scope["generation"]
                or any(
                    book[k] != scope[k]
                    for k in (
                        "binding_id",
                        "binding_revision",
                        "operator_fixture_id",
                        "profile_hash",
                        "document_epoch",
                    )
                )
            ):
                raise ValueError()
            market = scope["markets"][book["horizon"]]
            if market["market_id"] != book["market_id"] or market["selections"] != {
                s: b["selection_id"] for s, b in book["selections"].items()
            }:
                raise ValueError()
            if ("SYNTHETIC" in book["quality_flags"]) != (self.context["source_kind"] == "MOCK"):
                raise ValueError()
        except Exception:
            raise ValueError("E_LIVE_CAPTURE_SCOPE") from None

    async def _batch(self, frame: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        validate_frame(frame)
        body = frame["body"]
        for event in body["events"]:
            self._capture_scope(event)
        identity = {k: body[k] for k in ("run_id", "stream_id", "generation", "batch_id")}
        responses = []
        last = None
        rejected = False
        for event in body["events"]:
            try:
                last = await asyncio.to_thread(self.store.append, event)
                if self.on_capture is not None:
                    await self.on_capture(event)
            except (ValueError, OSError):
                rejected = True
                break
        if last is not None:
            responses.append(
                ("ACK", {**identity, "sequence": last.sequence, "content_hash": last.content_hash})
            )
        if rejected:
            responses.append(("NACK", {**identity, "code": "CAPTURE_REJECTED"}))
        return responses

    async def _connection(self, socket: ServerConnection) -> None:
        role = None
        active = False
        try:
            hello = await asyncio.wait_for(socket.recv(), 5)
            if type(hello) is not str:
                raise ValueError("E_LIVE_FRAME_TYPE")
            session, key = self.pairing.consume(hello.encode())
            role = session.role
            peer = (socket, session, key)
            body = dict(
                run_id=self.store.run_id,
                client_nonce=session.client_nonce,
                server_nonce=secrets.token_urlsafe(32),
            )
            await self._send(peer, "WELCOME", body)
            ready = await asyncio.wait_for(
                socket.recv(), max(0, 5 - (time.monotonic() - session.started))
            )
            if type(ready) is not str:
                raise ValueError("E_LIVE_FRAME_TYPE")
            session.receive(ready.encode(), key)
            async with self._intake:
                old = self._active.get(role)
                if old is not None:
                    await old[0].close(1000, "PAIRING_RENEWED")
                self._active[role] = peer
                active = True
                if role == "CAPTURE_PRODUCER":
                    await self._health(None, "PAIRING_RENEWED")
            await self._send(peer, "READY_ACK", body)
            if self.on_change is not None:
                await self.on_change(
                    None, "PAIRING_RENEWED" if role == "CAPTURE_PRODUCER" else "SUBSCRIBED"
                )
            while time.monotonic() < self.context["deadline_mono"]:
                data = await asyncio.wait_for(
                    socket.recv(), max(0, self.context["deadline_mono"] - time.monotonic())
                )
                if type(data) is not str:
                    raise ValueError("E_LIVE_FRAME_TYPE")
                frame = session.receive(data.encode(), key)
                kind, payload = frame["message_type"], frame["body"]
                if kind == "PING":
                    await self._send(peer, "PONG", payload)
                    continue
                if kind == "PONG":
                    continue
                async with self._intake:
                    if self._active.get(role) != peer:
                        raise ValueError("E_LIVE_SESSION_REPLACED")
                    if kind == "CAPTURE_BATCH":
                        replies = await self._batch(frame)
                        for reply_kind, reply in replies:
                            await self._send(peer, reply_kind, reply)
                        if any(k == "NACK" for k, _ in replies):
                            break
                        if self.on_change is not None:
                            await self.on_change(None, "CAPTURE_COMMITTED")
                    elif kind in {"HEALTH", "STOP_CAPTURE"}:
                        if kind == "STOP_CAPTURE":
                            self._stopped_bindings.add(payload["binding_id"])
                        await self._health(
                            payload["binding_id"],
                            "USER_STOP" if kind == "STOP_CAPTURE" else payload["code"],
                        )
                        if self.on_change is not None:
                            await self.on_change(
                                payload["binding_id"],
                                "USER_STOP" if kind == "STOP_CAPTURE" else payload["code"],
                            )
                    elif self.on_ui is not None:
                        binding = payload.get("binding_id")
                        if binding is not None and binding not in self.store.bindings():
                            raise ValueError("E_LIVE_UI_SCOPE")
                        await self.on_ui(kind, binding)
                    else:
                        raise ValueError("E_LIVE_UI_NOT_READY")
        except ConnectionClosed:
            pass
        except Exception:
            self.rejections.append("CONNECTION_REJECTED")
            await socket.close(1008, "CONNECTION_REJECTED")
        finally:
            if active and role is not None and self._active.get(role, (None,))[0] is socket:
                del self._active[role]
                if role == "CAPTURE_PRODUCER":
                    async with self._intake:
                        try:
                            await self._health(None, "DISCONNECTED")
                            if self.on_change is not None:
                                await self.on_change(None, "DISCONNECTED")
                        except (ValueError, OSError):
                            self.rejections.append("HEALTH_STORAGE_FAILED")
            self._reserved.discard(socket)
            self._send_locks.pop(socket, None)
            self._send_pending.pop(socket, None)


async def serve_live_receiver(
    context: dict[str, Any], store: LiveStore, pairing: PairingAuthority
) -> LiveReceiver:
    receiver = LiveReceiver(context, store, pairing)
    await receiver.start()
    return receiver
