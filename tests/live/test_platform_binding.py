import asyncio
import os
from contextlib import contextmanager
from typing import Any

import pytest

from tools.qualify_live_platform import validate_platform_choice


def test_platform_selection_cannot_relabel_linux_as_windows() -> None:
    validate_platform_choice("LINUX_CHROME", "linux")
    validate_platform_choice("WINDOWS_CHROME_WSL2", "win32")
    with pytest.raises(ValueError):
        validate_platform_choice("WINDOWS_CHROME_WSL2", "linux")
    with pytest.raises(ValueError):
        validate_platform_choice("UNKNOWN", "")


def test_terminal_repair_is_explicit_bounded_and_detaches(monkeypatch: Any) -> None:
    from tools import run_live_readonly

    class Terminal:
        def __init__(self, fd: int):
            self.reader = os.fdopen(fd)

        def fileno(self) -> int:
            return self.reader.fileno()

        def readline(self, limit: int) -> str:
            return self.reader.readline(limit)

        def write(self, _text: str) -> None:
            pass

        def flush(self) -> None:
            pass

    read_fd, write_fd = os.pipe()
    terminal = Terminal(read_fd)
    issued = []

    @contextmanager
    def tty() -> Any:
        try:
            yield terminal
        finally:
            terminal.reader.close()

    monkeypatch.setattr(run_live_readonly, "controlling_tty", tty)
    monkeypatch.setattr(
        run_live_readonly, "show_local_pairing", lambda service: issued.append(service)
    )

    async def scenario() -> None:
        close = run_live_readonly.enable_local_repair(None)  # type: ignore[arg-type]
        assert len(issued) == 1
        os.write(write_fd, b"ignored\n")
        await asyncio.sleep(0.02)
        assert len(issued) == 1
        os.write(write_fd, b"PAIR\n")
        await asyncio.sleep(0.02)
        assert len(issued) == 2
        close()
        close()
        assert terminal.reader.closed

    try:
        asyncio.run(scenario())
    finally:
        os.close(write_fd)
