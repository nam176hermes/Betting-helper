import asyncio
import base64
import json
import secrets
import time
from uuid import uuid4

import pytest
from test_live_store import OPERATOR, RUN_ID, envelope, metadata, register
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from moj_discovery.live_receiver import serve_live_receiver
from moj_discovery.live_store import LiveStore
from moj_discovery.live_wire import LiveSession, PairingAuthority, encode_frame

KEY = bytes(range(32))
ORIGIN = "chrome-extension://" + "a" * 32


def handshake(role="CAPTURE_PRODUCER", clock=lambda: 0):
    sid = str(uuid4())
    client = LiveSession(sid, RUN_ID, "CLIENT", role, clock() + 120, clock=clock)
    server = LiveSession(sid, RUN_ID, "BACKEND", role, clock() + 120, clock=clock)
    hello = {"run_id": RUN_ID, "role": role, "client_nonce": secrets.token_urlsafe(32)}
    server.receive(client.send("HELLO", hello, KEY), KEY)
    body = {
        "run_id": RUN_ID,
        "client_nonce": server.client_nonce,
        "server_nonce": secrets.token_urlsafe(32),
    }
    client.receive(server.send("WELCOME", body, KEY), KEY)
    server.receive(client.send("READY", body, KEY), KEY)
    client.receive(server.send("READY_ACK", body, KEY), KEY)
    return client, server


def capture_body(book):
    event = envelope("MarketBook", book)
    return {
        "run_id": RUN_ID,
        "stream_id": OPERATOR,
        "generation": "0",
        "batch_id": str(uuid4()),
        "first_sequence": "1",
        "last_sequence": "1",
        "events": [event],
    }


def test_role_matrix_counter_and_mac(synthetic_book):
    client, server = handshake("UI_SUBSCRIBER")
    with pytest.raises(ValueError, match="ROLE_DENIED"):
        client.send("CAPTURE_BATCH", capture_body(synthetic_book), KEY)
    frame = client.send(
        "REFRESH", {"run_id": RUN_ID, "binding_id": synthetic_book["binding_id"]}, KEY
    )
    server.receive(frame, KEY)
    with pytest.raises(ValueError, match="COUNTER"):
        server.receive(frame, KEY)
    with pytest.raises(ValueError):
        server.receive(frame, bytes(reversed(KEY)))
    producer, _ = handshake()
    with pytest.raises(ValueError, match="ROLE_DENIED"):
        producer.send(
            "REFRESH", {"run_id": RUN_ID, "binding_id": synthetic_book["binding_id"]}, KEY
        )


def test_capture_never_transports_backend_source(synthetic_book, synthetic_provider_response):
    from test_provider_normalization import normalize

    body = capture_body(synthetic_book)
    body["events"] = [
        envelope(
            "ProviderState", normalize(synthetic_provider_response).states[101], stream=OPERATOR
        )
    ]
    client, _ = handshake()
    with pytest.raises(ValueError, match="SCHEMA"):
        client.send("CAPTURE_BATCH", body, KEY)


def test_wrong_hash_and_cross_stream_reject(synthetic_book):
    for mutation in ["hash", "stream", "sequence", "generation"]:
        body = capture_body(synthetic_book)
        if mutation == "hash":
            body["events"][0]["content_hash"] = "f" * 64
        if mutation == "stream":
            body["stream_id"] = str(uuid4())
        if mutation == "sequence":
            body["last_sequence"] = "2"
        if mutation == "generation":
            body["generation"] = "9223372036854775808"
        client, _ = handshake()
        with pytest.raises(ValueError):
            client.send("CAPTURE_BATCH", body, KEY)


def test_pairing_expiry_one_use_and_handshake_deadline(fake_clock):
    authority = PairingAuthority(RUN_ID, 300, clock=lambda: fake_clock.mono)
    ticket = authority.issue("CAPTURE_PRODUCER")
    assert len(ticket.key) == 32 and base64.urlsafe_b64encode(ticket.key).decode() not in repr(
        ticket
    )
    client = LiveSession(
        ticket.session_id, RUN_ID, "CLIENT", ticket.role, 300, clock=lambda: fake_clock.mono
    )
    hello = client.send(
        "HELLO",
        dict(run_id=RUN_ID, role=ticket.role, client_nonce=secrets.token_urlsafe(32)),
        ticket.key,
    )
    server, key = authority.consume(hello)
    with pytest.raises(ValueError):
        authority.consume(hello)
    fake_clock.advance(6)
    with pytest.raises(ValueError, match="TIMEOUT"):
        server.send(
            "WELCOME",
            dict(
                run_id=RUN_ID,
                client_nonce=server.client_nonce,
                server_nonce=secrets.token_urlsafe(32),
            ),
            key,
        )
    expired = authority.issue("UI_SUBSCRIBER")
    other = LiveSession(
        expired.session_id, RUN_ID, "CLIENT", expired.role, 300, clock=lambda: fake_clock.mono
    )
    data = other.send(
        "HELLO",
        dict(run_id=RUN_ID, role=expired.role, client_nonce=secrets.token_urlsafe(32)),
        expired.key,
    )
    fake_clock.advance(121)
    with pytest.raises(ValueError):
        authority.consume(data)


def test_offline_protocol_domain_and_duplicate_json_reject():
    client, server = handshake()
    ping = client.send(
        "PING", dict(run_id=RUN_ID, nonce=secrets.token_urlsafe(32), monotonic_us="0"), KEY
    )
    value = json.loads(ping)
    value["protocol"] = "BH_OFFLINE_WIRE_V1"
    with pytest.raises(ValueError):
        server.receive(json.dumps(value).encode(), KEY)
    with pytest.raises(ValueError):
        server.receive(ping[:-1] + b',"counter":"3"}', KEY)


def test_stop_revokes_unused_pairing():
    authority = PairingAuthority(RUN_ID, 120, clock=lambda: 0)
    ticket = authority.issue("UI_SUBSCRIBER")
    client = LiveSession(ticket.session_id, RUN_ID, "CLIENT", ticket.role, 120, clock=lambda: 0)
    data = client.send(
        "HELLO",
        dict(run_id=RUN_ID, role=ticket.role, client_nonce=secrets.token_urlsafe(32)),
        ticket.key,
    )
    authority.revoke()
    with pytest.raises(ValueError):
        authority.consume(data)
    with pytest.raises(ValueError):
        authority.issue("UI_SUBSCRIBER")


def context(book):
    return {
        "run_id": RUN_ID,
        "allowed_extension_origin": ORIGIN,
        "deadline_mono": time.monotonic() + 120,
        "source_kind": "MOCK",
        "capture_streams": {
            OPERATOR: {
                "binding_id": book["binding_id"],
                "binding_revision": book["binding_revision"],
                "operator_fixture_id": book["operator_fixture_id"],
                "generation": "0",
                "profile_hash": book["profile_hash"],
                "document_epoch": book["document_epoch"],
                "markets": {
                    "FT": {
                        "market_id": book["market_id"],
                        "selections": {s: v["selection_id"] for s, v in book["selections"].items()},
                    }
                },
            }
        },
    }


async def paired_socket(authority, role="CAPTURE_PRODUCER"):
    ticket = authority.issue(role)
    socket = await connect("ws://127.0.0.1:8765/live", origin=ORIGIN, compression=None, proxy=None)
    session = LiveSession(ticket.session_id, RUN_ID, "CLIENT", role, authority.deadline)
    await socket.send(
        session.send(
            "HELLO",
            dict(run_id=RUN_ID, role=role, client_nonce=secrets.token_urlsafe(32)),
            ticket.key,
        ).decode()
    )
    welcome = session.receive((await socket.recv()).encode(), ticket.key)
    await socket.send(session.send("READY", welcome["body"], ticket.key).decode())
    session.receive((await socket.recv()).encode(), ticket.key)
    return socket, session, ticket.key


def test_socket_commit_before_ack_and_role_rejection(tmp_path, synthetic_book):
    async def scenario():
        with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata()) as store:
            register(store)
            ctx = context(synthetic_book)
            authority = PairingAuthority(RUN_ID, ctx["deadline_mono"])
            receiver = await serve_live_receiver(ctx, store, authority)
            try:
                socket, client, key = await paired_socket(authority)
                async with socket:
                    body = capture_body(synthetic_book)
                    await socket.send(client.send("CAPTURE_BATCH", body, key).decode())
                    ack = client.receive((await socket.recv()).encode(), key)
                    assert ack["message_type"] == "ACK"
                    assert (
                        store.read_projection(synthetic_book["binding_id"])["books"]["FT"]
                        == synthetic_book
                    )
                subscriber, ui, ui_key = await paired_socket(authority, "UI_SUBSCRIBER")
                async with subscriber:
                    # Bypass client helper deliberately; server still enforces authenticated role.
                    forbidden = encode_frame(
                        dict(
                            protocol="BH_LIVE_WIRE_V1",
                            session_id=ui.session_id,
                            direction="CLIENT_TO_BACKEND",
                            counter="3",
                            message_type="CAPTURE_BATCH",
                            body=body,
                        ),
                        ui_key,
                    )
                    await subscriber.send(forbidden.decode())
                    with pytest.raises(ConnectionClosed):
                        await subscriber.recv()
                assert store.cursor(OPERATOR) == (1, body["events"][0]["content_hash"])
            finally:
                await receiver.close()

    asyncio.run(scenario())


def test_wrong_origin_path_and_key_write_nothing(tmp_path, synthetic_book):
    async def scenario():
        with LiveStore(tmp_path / "run" / "live.sqlite3", **metadata()) as store:
            register(store)
            ctx = context(synthetic_book)
            authority = PairingAuthority(RUN_ID, ctx["deadline_mono"])
            receiver = await serve_live_receiver(ctx, store, authority)
            try:
                for origin, path in [
                    ("https://example.invalid", "/live"),
                    (ORIGIN, "/offline"),
                    (ORIGIN, "/live?secret=x"),
                ]:
                    with pytest.raises(InvalidStatus):
                        async with connect("ws://127.0.0.1:8765" + path, origin=origin, proxy=None):
                            pass
                ticket = authority.issue("CAPTURE_PRODUCER")
                client = LiveSession(
                    ticket.session_id, RUN_ID, "CLIENT", ticket.role, authority.deadline
                )
                async with connect("ws://127.0.0.1:8765/live", origin=ORIGIN, proxy=None) as socket:
                    await socket.send(
                        client.send(
                            "HELLO",
                            dict(
                                run_id=RUN_ID,
                                role=ticket.role,
                                client_nonce=secrets.token_urlsafe(32),
                            ),
                            KEY,
                        ).decode()
                    )
                    with pytest.raises(ConnectionClosed):
                        await socket.recv()
                assert store.cursor(OPERATOR)[0] == 0
            finally:
                await receiver.close()

    asyncio.run(scenario())
