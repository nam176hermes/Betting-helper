import json
from uuid import uuid4

import pytest

from moj_discovery.offline_protocol import SessionState, encode_frame, verify_frame
from tests.offline.test_contracts import batch

KEY = bytes(range(32))  # Test codec vector only; runtime generates a fresh private key.


def test_shape_valid_frame_with_wrong_mac_is_rejected() -> None:
    frame = batch()
    frame["mac"] = "0" * 64
    session = SessionState(frame["session_id"], frame["body"]["run_id"], "BACKEND")
    with pytest.raises(ValueError, match="E_OFFLINE_MAC"):
        verify_frame(json.dumps(frame).encode(), KEY, session)
    assert session.in_counter == 0


def handshake() -> tuple[SessionState, SessionState]:
    import secrets

    sid, run = str(uuid4()), str(uuid4())
    client, backend = SessionState(sid, run, "CLIENT"), SessionState(sid, run, "BACKEND")
    client_nonce, server_nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    common = {"run_id": run, "client_nonce": client_nonce, "server_nonce": server_nonce}
    hello = client.send("HELLO", {"run_id": run, "client_nonce": client_nonce}, KEY)
    verify_frame(hello, KEY, backend)
    verify_frame(backend.send("WELCOME", common, KEY), KEY, client)
    verify_frame(client.send("READY", common, KEY), KEY, backend)
    assert not client.ready and not backend.ready
    verify_frame(backend.send("READY_ACK", common, KEY), KEY, client)
    return client, backend


def test_handshake_and_replay_counter() -> None:
    client, backend = handshake()
    assert client.ready and backend.ready
    ping = client.send("PING", {"nonce": "A" * 43, "monotonic_us": "3"}, KEY)
    verify_frame(ping, KEY, backend)
    with pytest.raises(ValueError, match="E_OFFLINE_SESSION_COUNTER"):
        verify_frame(ping, KEY, backend)
    assert backend.in_counter == 3


@pytest.mark.parametrize("mutation", ["session", "direction", "counter", "body", "mac"])
def test_authenticated_mutations_do_not_advance_session(mutation: str) -> None:
    client, backend = handshake()
    value = json.loads(client.send("PING", {"nonce": "A" * 43, "monotonic_us": "3"}, KEY))
    if mutation == "session":
        value["session_id"] = str(uuid4())
    elif mutation == "direction":
        value["direction"] = "BACKEND_TO_CLIENT"
    elif mutation == "counter":
        value["counter"] = "99"
    elif mutation == "body":
        value["body"]["monotonic_us"] = "4"
    else:
        value["mac"] = "0" * 64
    with pytest.raises(ValueError):
        verify_frame(json.dumps(value).encode(), KEY, backend)
    assert backend.in_counter == 2


def test_handshake_bypass_and_timeout() -> None:
    sid, run = str(uuid4()), str(uuid4())
    state = SessionState(sid, run, "BACKEND")
    frame = {
        "protocol": "BH_OFFLINE_WIRE_V1",
        "session_id": sid,
        "direction": "CLIENT_TO_BACKEND",
        "counter": "1",
        "message_type": "PING",
        "body": {"nonce": "A" * 43, "monotonic_us": "0"},
    }
    with pytest.raises(ValueError, match="E_OFFLINE_HANDSHAKE_ORDER"):
        verify_frame(encode_frame(frame, KEY), KEY, state)
    clock = [0.0]
    state = SessionState(sid, run, "BACKEND", clock=lambda: clock[0])
    frame.update(message_type="HELLO", body={"run_id": run, "client_nonce": "A" * 43})
    clock[0] = 6.0
    with pytest.raises(ValueError, match="E_OFFLINE_HANDSHAKE_TIMEOUT"):
        verify_frame(encode_frame(frame, KEY), KEY, state)
    assert state.in_counter == 0


def test_typescript_and_python_produce_identical_authenticated_bytes() -> None:
    import subprocess
    from pathlib import Path

    frame = {
        "protocol": "BH_OFFLINE_WIRE_V1",
        "session_id": "00000000-0000-4000-8000-000000000001",
        "direction": "CLIENT_TO_BACKEND",
        "counter": "1",
        "message_type": "HELLO",
        "body": {"run_id": "00000000-0000-4000-8000-000000000002", "client_nonce": "A" * 43},
    }
    program = """
import {readFileSync,readdirSync} from 'node:fs';
import {encodeFrame} from './extension/.test-build/src/offline/protocol.js';
import {validateArtifact} from './extension/.test-build/src/schema-registry.js';
const schemas=['vendor/hybrid-discovery-v6.3.6/schemas','contracts/offline_slice/v1']
.flatMap(dir=>readdirSync(dir).filter(n=>n.endsWith('.schema.json'))
.map(n=>JSON.parse(readFileSync(dir+'/'+n,'utf8'))));
const frame=JSON.parse(readFileSync(0,'utf8'));
const key=Uint8Array.from({length:32},(_,i)=>i);
const validate=v=>validateArtifact(v,'urn:betting-helper:offline-slice:frame:v1',schemas);
process.stdout.write(await encodeFrame(frame,key,validate));
"""
    output = subprocess.check_output(  # noqa: S603 -- fixed pinned Node and unit codec input
        ["node", "--input-type=module", "-e", program],  # noqa: S607 -- pinned Node
        input=json.dumps(frame).encode(),
        cwd=Path(__file__).resolve().parents[2],
        timeout=20,
    )
    assert output == encode_frame(frame, KEY)


def test_valid_mac_does_not_authorize_wrong_handshake_nonce() -> None:
    import secrets
    sid, run = str(uuid4()), str(uuid4())
    client, backend = SessionState(sid, run, "CLIENT"), SessionState(sid, run, "BACKEND")
    hello = {"run_id": run, "client_nonce": secrets.token_urlsafe(32)}
    verify_frame(client.send("HELLO", hello, KEY), KEY, backend)
    common = {**hello, "server_nonce": secrets.token_urlsafe(32)}
    verify_frame(backend.send("WELCOME", common, KEY), KEY, client)
    value = json.loads(client.send("READY", common, KEY))
    value.pop("mac")
    value["body"]["server_nonce"] = secrets.token_urlsafe(32)
    with pytest.raises(ValueError, match="E_OFFLINE_NONCE"):
        verify_frame(encode_frame(value, KEY), KEY, backend)
    assert backend.in_counter == 1 and not backend.ready
