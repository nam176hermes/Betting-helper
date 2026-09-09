"""Installed runtime contract; this does not issue browser or release approval."""

import asyncio
import inspect
import platform
import subprocess
from importlib.metadata import version

from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.typing import Origin


def test_required_environment() -> None:
    assert platform.python_version() == "3.12.3"
    assert version("websockets") == "17.1"
    for argv, expected in [
        (["uv", "--version"], "uv 0.11.7"),
        (["node", "--version"], "v22.23.0"),
        (["pnpm", "--version"], "10.33.2"),
    ]:
        result = subprocess.check_output(argv, text=True, timeout=10)  # noqa: S603 -- fixed tool version argv
        assert result.strip().startswith(expected)
    parameters = inspect.signature(serve).parameters
    assert {
        "origins",
        "compression",
        "max_size",
        "max_queue",
        "open_timeout",
        "close_timeout",
        "process_request",
    } <= parameters.keys()


def test_pinned_transport_uses_real_loopback() -> None:
    async def check() -> None:
        async def echo(socket: ServerConnection) -> None:
            await socket.send(await socket.recv())

        async with serve(
            echo,
            "127.0.0.1",
            0,
            compression=None,
            origins=[Origin("chrome-extension://" + "a" * 32)],
            max_size=262144,
            max_queue=8,
            open_timeout=5,
            close_timeout=3,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(
                f"ws://127.0.0.1:{port}/offline",
                origin=Origin("chrome-extension://" + "a" * 32),
                compression=None,
            ) as client:
                await client.send("synthetic transport smoke")
                assert await client.recv() == "synthetic transport smoke"

    asyncio.run(check())
