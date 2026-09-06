"""Run every registered WHOLE_RUN_DESTRUCTION vector in a killable child."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.inspect_restart_state import execute_crash_matrix


def run_destruction_crash_matrix(pack: Path, workspace: Path) -> dict[str, object]:
    entries = [
        entry
        for entry in json.loads(
            (pack / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if entry["harness"] == "WHOLE_RUN_DESTRUCTION"
    ]
    result = execute_crash_matrix(
        entries, [sys.executable, str(Path(__file__).with_name("destruction_crash_child.py"))], workspace
    )
    return {**result, "declared_vector_ids": [entry["vector_id"] for entry in entries]}
