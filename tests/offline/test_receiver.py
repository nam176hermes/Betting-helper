import asyncio
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.typing import Origin

from moj_discovery.input_journal import InputJournal
from moj_discovery.offline_protocol import SessionState, verify_frame
from moj_discovery.offline_receiver import serve_offline
from moj_discovery.offline_run import create_offline_run
from moj_discovery.store import RunStore, _runtime_authorizer
from moj_discovery.synthetic_source import load_synthetic_observations
from tests.offline.test_synthetic_source import context, scenario


async def authenticate(
    socket: ClientConnection, ctx: dict[str, Any], sid: str, key: bytes
) -> SessionState:
    state = SessionState(sid, ctx["run_id"], "CLIENT")
    await socket.send(
        state.send(
            "HELLO", {"run_id": ctx["run_id"], "client_nonce": secrets.token_urlsafe(32)}, key
        ).decode()
    )
    welcome = verify_frame((await socket.recv(decode=True)).encode(), key, state)
    await socket.send(state.send("READY", welcome["body"], key).decode())
    verify_frame((await socket.recv(decode=True)).encode(), key, state)
    return state


def test_valid_websocket_changes_actual_shared_sqlite(tmp_path: Path) -> None:
    async def check() -> None:
        ctx = context()
        store = create_offline_run(tmp_path / "run", ctx)
        rows = load_synthetic_observations(scenario(tmp_path / "scenario.json", ctx))
        sid, key = str(uuid4()), secrets.token_bytes(32)
        receiver = await serve_offline(
            ctx,
            lambda value: key if value == sid else None,
            store,
            InputJournal(store.db_path.parent),
        )
        try:
            async with connect(
                ctx["backend_url"], origin=Origin(ctx["allowed_extension_origin"]), compression=None
            ) as socket:
                state = await authenticate(socket, ctx, sid, key)
                body = {
                    name: ctx[name]
                    for name in [
                        "run_id",
                        "browser_run_id",
                        "producer_id",
                        "stream_id",
                        "generation",
                    ]
                }
                body.update(
                    batch_id=str(uuid4()), first_sequence="1", last_sequence="3", observations=rows
                )
                await socket.send(state.send("BATCH", body, key).decode())
                response = verify_frame((await socket.recv(decode=True)).encode(), key, state)
                assert response["message_type"] == "ACK"
                assert response["body"]["highest_contiguous_sequence"] == "3"
            with closing(store.connect()) as db:
                assert len(db.execute("SELECT * FROM raw_commits").fetchall()) == 3
            assert len(list((store.db_path.parent / "raw").glob("*.json"))) == 3
        finally:
            await receiver.close()

    asyncio.run(check())


def test_sqlite_denial_acknowledges_only_committed_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = RunStore.connect

    def limited_connect(self: RunStore) -> sqlite3.Connection:
        db = original(self)
        if len(db.execute("SELECT * FROM raw_commits").fetchall()) >= 2:

            def authorize(
                action: int,
                table: str | None,
                column: str | None,
                database: str | None,
                trigger: str | None,
            ) -> int:
                if action == sqlite3.SQLITE_INSERT and table == "raw_commits":
                    return sqlite3.SQLITE_DENY
                return _runtime_authorizer(action, table, column, database, trigger)

            db.set_authorizer(authorize)
        return db

    monkeypatch.setattr(RunStore, "connect", limited_connect)

    async def check() -> None:
        ctx = context()
        store = create_offline_run(tmp_path / "run", ctx)
        rows = load_synthetic_observations(scenario(tmp_path / "scenario.json", ctx))
        sid, key = str(uuid4()), secrets.token_bytes(32)
        receiver = await serve_offline(
            ctx,
            lambda value: key if value == sid else None,
            store,
            InputJournal(store.db_path.parent),
        )
        try:
            async with connect(
                ctx["backend_url"], origin=Origin(ctx["allowed_extension_origin"]), compression=None
            ) as socket:
                state = await authenticate(socket, ctx, sid, key)
                body = {
                    name: ctx[name]
                    for name in [
                        "run_id",
                        "browser_run_id",
                        "producer_id",
                        "stream_id",
                        "generation",
                    ]
                }
                body.update(
                    batch_id=str(uuid4()), first_sequence="1", last_sequence="3", observations=rows
                )
                await socket.send(state.send("BATCH", body, key).decode())
                ack = verify_frame((await socket.recv(decode=True)).encode(), key, state)
                nack = verify_frame((await socket.recv(decode=True)).encode(), key, state)
                assert ack["message_type"] == "ACK"
                assert ack["body"]["highest_contiguous_sequence"] == "2"
                assert nack["message_type"] == "NACK"
                assert nack["body"]["code"] == "STORAGE_FAILED"
            with closing(store.connect()) as db:
                assert len(db.execute("SELECT * FROM raw_commits").fetchall()) == 2
            outcomes = [
                r["outcome"] for r in receiver.journal.iter_operations() if r["kind"] == "OUTCOME"
            ]
            assert [r["status"] for r in outcomes] == ["APPLIED", "APPLIED", "REJECTED"]
        finally:
            await receiver.close()

    asyncio.run(check())


@pytest.mark.parametrize(
    "attack", ["origin", "path", "host", "mac", "identity", "sensitive", "replay"]
)
def test_rejected_wire_never_writes(tmp_path: Path, attack: str) -> None:
    async def check() -> None:
        ctx = context()
        store = create_offline_run(tmp_path / "run", ctx)
        rows = load_synthetic_observations(scenario(tmp_path / "scenario.json", ctx))
        sid, key = str(uuid4()), secrets.token_bytes(32)
        receiver = await serve_offline(
            ctx,
            lambda value: key if value == sid else None,
            store,
            InputJournal(store.db_path.parent),
        )
        try:
            url = ctx["backend_url"] + ("?forbidden=1" if attack == "path" else "")
            origin = (
                ctx["allowed_extension_origin"] if attack != "origin" else "https://example.invalid"
            )
            headers = {"Host": "localhost:8765"} if attack == "host" else None
            with pytest.raises((ConnectionClosed, InvalidStatus)):
                async with connect(
                    url, origin=Origin(origin), additional_headers=headers, compression=None
                ) as socket:
                    state = await authenticate(socket, ctx, sid, key)
                    body = {
                        name: ctx[name]
                        for name in [
                            "run_id",
                            "browser_run_id",
                            "producer_id",
                            "stream_id",
                            "generation",
                        ]
                    }
                    body.update(
                        batch_id=str(uuid4()),
                        first_sequence="1",
                        last_sequence="3",
                        observations=rows,
                    )
                    if attack == "identity":
                        body["producer_id"] = str(uuid4())
                    if attack == "replay":
                        state.out_counter -= 1
                    data = state.send("BATCH", body, key).decode()
                    if attack == "mac":
                        import json

                        value = json.loads(data)
                        value["mac"] = "0" * 64
                        data = json.dumps(value)
                    if attack == "sensitive":
                        # Malformed peer frames bypass the honest encoder's validation.
                        import json

                        value = json.loads(data)
                        value["body"]["observations"][2]["secret"] = secrets.token_hex(8)
                        data = json.dumps(value)
                    await socket.send(data)
                    await socket.recv()
            with closing(store.connect()) as db:
                assert db.execute("SELECT * FROM raw_commits").fetchall() == []
            assert list((store.db_path.parent / "raw").glob("*.json")) == []
        finally:
            await receiver.close()

    asyncio.run(check())
