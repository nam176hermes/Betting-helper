"""Run every registered LOOPBACK_ACK vector in a killable Python child."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.inspect_restart_state import execute_crash_matrix


def run_loopback_ack_crash_matrix(pack: Path, workspace: Path) -> dict[str, object]:
    entries = json.loads(
        (pack / "docs/registries/crash-harness-registry.v1.json").read_text()
    )["entries"]
    selected = [entry for entry in entries if entry["harness"] == "LOOPBACK_ACK"]
    return execute_crash_matrix(
        selected, [sys.executable, str(Path(__file__).with_name("loopback_ack_crash_child.py"))], workspace
    )
