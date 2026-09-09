import asyncio
import json
import secrets
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from websockets.asyncio.server import ServerConnection

from moj_discovery.input_journal import InputJournal
from moj_discovery.offline_protocol import encode_frame
from moj_discovery.offline_receiver import serve_offline
from moj_discovery.offline_run import create_offline_run
from moj_discovery.synthetic_source import load_synthetic_observations
from tests.offline.test_synthetic_source import context, scenario
from tools.offline_browser import OfflineBrowser, prepare_offline_extension


@pytest.mark.parametrize("fault", ["none", "ack-loss", "fake-ack", "wrong-generation"])
def test_real_extension_flush_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    extension, identity = prepare_offline_extension(tmp_path)
    original = ServerConnection.send
    dropped = False
    keys = {str(uuid4()): secrets.token_bytes(32) for _ in range(4)}

    async def send(self: ServerConnection, message: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal dropped
        if (
            fault == "ack-loss"
            and not dropped
            and isinstance(message, str)
            and json.loads(message).get("message_type") == "ACK"
        ):
            dropped = True
            await self.close(1000, "OFFLINE_TEST_ACK_LOSS")
            return
        if fault in {"fake-ack", "wrong-generation"} and isinstance(message, str):
            frame = json.loads(message)
            if frame["message_type"] == "ACK":
                frame["body"]["cursor_hash" if fault == "fake-ack" else "generation"] = (
                    "0" * 64 if fault == "fake-ack" else "1"
                )
                del frame["mac"]
                message = encode_frame(frame, keys[frame["session_id"]]).decode()
        await original(self, message, *args, **kwargs)

    monkeypatch.setattr(ServerConnection, "send", send)

    async def check() -> None:
        ctx = context()
        ctx["allowed_extension_origin"] = "chrome-extension://" + identity
        store = create_offline_run(tmp_path / "run", ctx)
        rows = load_synthetic_observations(scenario(tmp_path / "scenario.json", ctx))
        receiver = await serve_offline(ctx, keys.get, store, InputJournal(store.db_path.parent))
        browser = None
        try:
            browser = await asyncio.to_thread(
                OfflineBrowser, tmp_path / "browser", extension, ctx["allowed_extension_origin"]
            )

            async def command(value: dict[str, Any]) -> dict[str, Any]:
                assert browser is not None
                return await asyncio.to_thread(browser.command, value)

            initialized = await command(
                {
                    "operation": "INIT",
                    "context": ctx,
                    "credentials": [
                        {"sessionId": sid, "key": list(key)} for sid, key in keys.items()
                    ],
                }
            )
            assert initialized["status"] == "OK", initialized
            appended = await command({"operation": "APPEND", "observations": rows})
            assert appended["state"]["pendingCount"] == 3, appended
            flushed = await command({"operation": "FLUSH"})
            rejected = fault in {"fake-ack", "wrong-generation"}
            assert flushed["status"] == ("REJECTED" if rejected else "OK"), flushed
            if not rejected:
                assert flushed["state"]["ackSequence"] == "3"
                assert flushed["state"]["pendingCount"] == 0
            await command({"operation": "RESTART_WORKER"})
            reopened = await command({"operation": "INIT", "context": ctx, "credentials": []})
            assert reopened["state"]["ackSequence"] == ("0" if rejected else "3")
            assert [json.loads(row) for row in reopened["retained"]] == rows
            with closing(store.connect()) as db:
                assert len(db.execute("SELECT * FROM raw_commits").fetchall()) == (
                    1 if rejected else 3
                )
            assert dropped == (fault == "ack-loss")
            # Scan retained bytes, including CDP transcripts, for every actual ephemeral secret.
            for path in tmp_path.rglob("*"):
                if path.is_file() and "profile" not in path.parts:
                    data = path.read_bytes()
                    for key in keys.values():
                        assert key.hex().encode() not in data
                        assert json.dumps(list(key)).encode() not in data
        finally:
            if browser is not None:
                await asyncio.to_thread(browser.close)
            await receiver.close()

    asyncio.run(check())
