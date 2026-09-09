"""Adversarial real WebSocket peer; keys remain in the parent process memory."""

import asyncio
import hashlib
import hmac
import json
import secrets
from typing import Any
from uuid import uuid4

import rfc8785
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.typing import Origin

from moj_discovery.offline_protocol import SessionState, encode_frame, verify_frame


def run_wire_case(
    case_id: str,
    context: dict[str, Any],
    credentials: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        observed: list[dict[str, Any]] = []
        attempts = 5 if case_id == "OFF-23" else (2 if case_id == "OFF-10" else 1)
        for attempt in range(attempts):
            credential = credentials[0 if case_id == "OFF-23" and attempt == 3 else attempt]
            key = bytes(credential["key"])
            state = SessionState(credential["sessionId"], context["run_id"], "CLIENT")
            url = context["backend_url"]
            origin = context["allowed_extension_origin"]
            if case_id == "OFF-10":
                if attempt == 0:
                    origin = "https://example.invalid"
                else:
                    url += "/forbidden"
            try:
                async with connect(
                    url, origin=Origin(origin), compression=None, open_timeout=5, close_timeout=2
                ) as socket:
                    if case_id == "OFF-23" and attempt in {1, 2}:
                        body = {
                            "run_id": context["run_id"],
                            "client_nonce": secrets.token_urlsafe(32),
                        }
                        if attempt == 2:
                            body["server_nonce"] = secrets.token_urlsafe(32)
                        frame = {
                            "protocol": "BH_OFFLINE_WIRE_V1",
                            "session_id": state.session_id,
                            "direction": "BACKEND_TO_CLIENT"
                            if attempt == 1
                            else "CLIENT_TO_BACKEND",
                            "counter": "1",
                            "message_type": "HELLO" if attempt == 1 else "READY",
                            "body": body,
                        }
                        # Deliberate invalid-direction/order peer; normal codec rejects it locally.
                        frame["mac"] = hmac.new(
                            key, b"BH-OFFLINE-WIRE/v1\0" + rfc8785.dumps(frame), hashlib.sha256
                        ).hexdigest()
                        await socket.send(rfc8785.dumps(frame).decode())
                        await asyncio.wait_for(socket.recv(), 5)
                        raise AssertionError("E_OFFLINE_HANDSHAKE_BYPASS_ACCEPTED")
                    await socket.send(
                        state.send(
                            "HELLO",
                            {
                                "run_id": context["run_id"],
                                "client_nonce": secrets.token_urlsafe(32),
                            },
                            key,
                        ).decode()
                    )
                    welcome = verify_frame(
                        (await asyncio.wait_for(socket.recv(decode=True), 5)).encode(), key, state
                    )
                    if case_id == "OFF-23" and attempt == 0:
                        forged = {**welcome["body"], "server_nonce": secrets.token_urlsafe(32)}
                        await socket.send(
                            encode_frame(
                                {
                                    "protocol": "BH_OFFLINE_WIRE_V1",
                                    "session_id": state.session_id,
                                    "direction": "CLIENT_TO_BACKEND",
                                    "counter": "2",
                                    "message_type": "READY",
                                    "body": forged,
                                },
                                key,
                            ).decode()
                        )
                        await asyncio.wait_for(socket.recv(), 5)
                        raise AssertionError("E_OFFLINE_NONCE_ACCEPTED")
                    await socket.send(state.send("READY", welcome["body"], key).decode())
                    verify_frame(
                        (await asyncio.wait_for(socket.recv(decode=True), 5)).encode(), key, state
                    )
                    body = {
                        name: context[name]
                        for name in (
                            "run_id",
                            "browser_run_id",
                            "producer_id",
                            "stream_id",
                            "generation",
                        )
                    }
                    body.update(
                        batch_id=str(uuid4()),
                        first_sequence="1",
                        last_sequence="1",
                        observations=rows[:1],
                    )
                    data = state.send("BATCH", body, key).decode()
                    if case_id == "OFF-09":
                        frame = json.loads(data)
                        frame["mac"] = "0" * 64
                        data = json.dumps(frame)
                    await socket.send(data)
                    response = verify_frame(
                        (await asyncio.wait_for(socket.recv(decode=True), 5)).encode(), key, state
                    )
                    observed.append(
                        {"message_type": response["message_type"], "body": response["body"]}
                    )
                    if case_id == "OFF-08":
                        await socket.send(data)
                        await asyncio.wait_for(socket.recv(), 5)
                        raise AssertionError("E_OFFLINE_COUNTER_ACCEPTED")
            except InvalidStatus as error:
                observed.append({"rejected": "HTTP", "status": error.response.status_code})
            except ConnectionClosed:
                observed.append({"rejected": "CONNECTION_CLOSED", "after_ready": state.ready})
        return {"case_id": case_id, "observed": observed}

    return asyncio.run(run())
