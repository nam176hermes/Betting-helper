"""Authenticated loopback-only receiver for synthetic accounting runs."""

import asyncio
import logging
import secrets
from collections.abc import Callable
from contextlib import closing
from http import HTTPStatus
from time import monotonic
from typing import Any

import rfc8785
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.protocol import State
from websockets.typing import Origin

from .canonical import parse_strict_json
from .input_journal import InputJournal
from .offline_protocol import SessionState, validate_context, validate_frame, verify_frame
from .store import RunStore
from .synthetic_source import validate_synthetic_observation


class OfflineReceiver:
    def __init__(
        self,
        context: dict[str, Any],
        key_provider: Callable[[str], bytes | None],
        store: RunStore,
        journal: InputJournal,
    ):
        validate_context(context)
        if journal.context != context or store.db_path != journal.store.db_path:
            raise ValueError("E_OFFLINE_SOURCE_BINDING")
        self.context = context
        self.key_provider = key_provider
        self.store = store
        self.journal = journal
        self.server: Server | None = None
        self._reserved: set[ServerConnection] = set()
        self._used_sessions: set[str] = set()
        self._lock = asyncio.Lock()
        self._active: ServerConnection | None = None
        self.started = monotonic()
        self.rejections: list[str] = []

    async def start(self) -> None:
        logger = logging.Logger("offline-wire", level=logging.CRITICAL)
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
            open_timeout=5,
            close_timeout=3,
            process_request=self._request,
            logger=logger,
        )

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    def _request(self, connection: ServerConnection, request: Request) -> Response | None:
        self._reserved = {item for item in self._reserved if item.state is not State.CLOSED}
        if (
            request.path != "/offline"
            or request.headers.get_all("Host") != ["127.0.0.1:8765"]
            or request.headers.get_all("Origin") != [self.context["allowed_extension_origin"]]
        ):
            self.rejections.append("E_OFFLINE_HTTP_BINDING")
            return connection.respond(HTTPStatus.FORBIDDEN, "E_OFFLINE_HTTP_BINDING")
        if len(self._reserved) >= 2:
            self.rejections.append("E_OFFLINE_SOCKET_CAPACITY")
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "E_OFFLINE_SOCKET_CAPACITY")
        self._reserved.add(connection)
        return None

    async def _connection(self, socket: ServerConnection) -> None:
        try:
            deadline = monotonic() + 5
            hello_data = await asyncio.wait_for(socket.recv(), 5)
            if not isinstance(hello_data, str):
                raise ValueError("E_OFFLINE_FRAME_TYPE")
            hello = parse_strict_json(hello_data.encode())
            if not isinstance(hello, dict):
                raise ValueError("E_OFFLINE_FRAME_TYPE")
            validate_frame(hello)
            sid = hello["session_id"]
            key = self.key_provider(sid)
            if key is None or sid in self._used_sessions:
                raise ValueError("E_OFFLINE_SESSION_REUSE")
            state = SessionState(sid, self.context["run_id"], "BACKEND")
            state.started = deadline - 5
            verify_frame(hello_data.encode(), key, state)
            self._used_sessions.add(sid)
            body = {
                "run_id": self.context["run_id"],
                "client_nonce": state.client_nonce,
                "server_nonce": secrets.token_urlsafe(32),
            }
            await socket.send(state.send("WELCOME", body, key).decode())
            ready = await asyncio.wait_for(socket.recv(), max(0, deadline - monotonic()))
            if not isinstance(ready, str):
                raise ValueError("E_OFFLINE_FRAME_TYPE")
            verify_frame(ready.encode(), key, state)
            await socket.send(state.send("READY_ACK", body, key).decode())
            async with self._lock:
                if self._active is not None and self._active is not socket:
                    await self._active.close(1000, "E_OFFLINE_REPLACED")
                self._active = socket
            while True:
                remaining = 600 - (monotonic() - self.started)
                if remaining <= 0:
                    raise ValueError("E_OFFLINE_RUN_TIMEOUT")
                data = await asyncio.wait_for(socket.recv(), remaining)
                if not isinstance(data, str):
                    raise ValueError("E_OFFLINE_FRAME_TYPE")
                frame = verify_frame(data.encode(), key, state)
                if frame["message_type"] == "STOP":
                    break
                if frame["message_type"] == "PING":
                    await socket.send(state.send("PONG", frame["body"], key).decode())
                    continue
                if frame["message_type"] != "BATCH":
                    raise ValueError("E_OFFLINE_MESSAGE_TYPE")
                async with self._lock:
                    if self._active is not socket:
                        raise ValueError("E_OFFLINE_SESSION_REPLACED")
                    responses = await self.process_batch(frame)
                for message_type, response in responses:
                    await socket.send(state.send(message_type, response, key).decode())
                if any(kind == "NACK" for kind, _ in responses):
                    await socket.close(1008, "E_OFFLINE_BATCH_REJECTED")
                    return
        except ConnectionClosed:
            pass
        except Exception:
            # Never log peer text, keys, exception strings, URLs or payload fingerprints.
            self.rejections.append("E_OFFLINE_CONNECTION_REJECTED")
            await socket.close(1008, "E_OFFLINE_CONNECTION_REJECTED")
        finally:
            self._reserved.discard(socket)
            if self._active is socket:
                self._active = None

    async def process_batch(self, frame: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        validate_frame(frame)
        if frame["message_type"] != "BATCH":
            raise ValueError("E_OFFLINE_MESSAGE_TYPE")
        body = frame["body"]
        fields = ("run_id", "browser_run_id", "producer_id", "stream_id", "generation")
        if any(body[name] != self.context[name] for name in fields):
            raise ValueError("E_OFFLINE_IDENTITY")
        with closing(self.store.connect()) as db:
            binding = db.execute(
                "SELECT producer_id FROM stream_generations WHERE run_id=? "
                "AND browser_run_id=? AND stream_id=? AND generation=?",
                (
                    body["run_id"],
                    body["browser_run_id"],
                    body["stream_id"],
                    int(body["generation"]),
                ),
            ).fetchall()
        if len(binding) != 1 or binding[0]["producer_id"] != body["producer_id"]:
            raise ValueError("E_OFFLINE_IDENTITY")
        payloads = [rfc8785.dumps(row) for row in body["observations"]]
        for payload in payloads:
            validate_synthetic_observation(payload, self.context)
        identity = {name: body[name] for name in ("batch_id", *fields)}
        ack = None
        rejection = None
        for payload in payloads:
            outcome = self.journal.apply(payload, body["batch_id"])
            if outcome["status"] != "APPLIED":
                rejection = ("NACK", {**identity, "code": outcome["code"]})
                break
            ack = outcome["ack"]
        responses = []
        if ack is not None:
            sequence = ack["highest_contiguous_sequence"]
            with closing(self.store.connect()) as db:
                confirmed = db.execute(
                    "SELECT MAX(highest_contiguous_sequence) FROM ack_cursors WHERE owner='BACKEND'"
                ).fetchone()[0]
            if confirmed is None or sequence > confirmed:
                self.journal.record_ack_confirmation(
                    body["generation"], str(sequence), ack["cursor_hash"]
                )
            responses.append(
                (
                    "ACK",
                    {
                        **identity,
                        "highest_contiguous_sequence": str(sequence),
                        "cursor_hash": ack["cursor_hash"],
                    },
                )
            )
        if rejection is not None:
            responses.append(rejection)
        return responses


async def serve_offline(
    context: dict[str, Any],
    key_provider: Callable[[str], bytes | None],
    store: RunStore,
    journal: InputJournal,
) -> OfflineReceiver:
    receiver = OfflineReceiver(context, key_provider, store, journal)
    await receiver.start()
    return receiver
