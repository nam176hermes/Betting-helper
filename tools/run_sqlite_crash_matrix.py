"""Block legacy SQLite crash evidence until an independent reader exists."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.run_loopback_ack_crash_matrix import run_family


def run_sqlite_crash_matrix(
    pack: Path,
    workspace: Path,
    *,
    observation_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if observation_input is None:
        # Keep R01's no-scenario/no-reader legacy entry point fail-closed.
        raise ValueError("E_ACTUAL_STATE_READER_REQUIRED")
    return run_family(pack, workspace, "SQLITE_TRANSACTION", observation_input)
