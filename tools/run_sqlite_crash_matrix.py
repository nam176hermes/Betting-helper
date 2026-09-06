"""Block legacy SQLite crash evidence until an independent reader exists."""
from __future__ import annotations

from pathlib import Path


def run_sqlite_crash_matrix(pack: Path, workspace: Path) -> dict[str, object]:
    raise ValueError("E_ACTUAL_STATE_READER_REQUIRED")
