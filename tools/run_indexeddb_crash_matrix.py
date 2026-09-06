"""Run every registered CHROME_INDEXEDDB vector in a killable child process."""
from __future__ import annotations

import json
from pathlib import Path

from tools.inspect_restart_state import execute_crash_matrix


def run_indexeddb_crash_matrix(pack: Path, workspace: Path) -> dict[str, object]:
    entries = json.loads(
        (pack / "docs/registries/crash-harness-registry.v1.json").read_text()
    )["entries"]
    selected = [entry for entry in entries if entry["harness"] == "CHROME_INDEXEDDB"]
    return execute_crash_matrix(
        selected,
        ["node", str(Path(__file__).parents[1] / "extension/.test-build/test-harness/indexeddb-crash-child.js")],
        workspace,
    )
