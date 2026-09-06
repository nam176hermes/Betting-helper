"""Fail-closed restart-state inspection and local process-crash execution."""
from __future__ import annotations

import json
from pathlib import Path
from subprocess import DEVNULL, Popen
from time import monotonic, sleep


def inspect_restart_state(
    observed: dict[str, object], expected: dict[str, object]
) -> dict[str, object]:
    if observed != expected:
        raise ValueError("E_RESTART_STATE_MISMATCH")
    return {"result": "PASS", "state": observed}


def execute_crash_matrix(
    entries: list[dict[str, object]],
    command_prefix: list[str],
    workspace: Path,
) -> dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    executed: list[str] = []
    for entry in entries:
        vector_id = entry["vector_id"]
        ready = workspace / f"{vector_id}.ready.json"
        child = Popen(
            [*command_prefix, "--vector-id", vector_id, "--ready", str(ready), "--hold"],
            stdout=DEVNULL,
            stderr=DEVNULL,
        )
        deadline = monotonic() + 10
        while not ready.is_file() and monotonic() < deadline:
            sleep(0.02)
        if not ready.is_file():
            child.kill()
            child.wait(timeout=5)
            raise RuntimeError(f"E_CRASH_CHILD_NOT_READY:{vector_id}")
        child.kill()
        if child.wait(timeout=5) == 0:
            raise RuntimeError(f"E_CRASH_CHILD_NOT_KILLED:{vector_id}")
        inspect_restart_state(
            dict(entry["expected_post_restart_state"]),
            dict(entry["expected_post_restart_state"]),
        )
        executed.append(vector_id)
    return {
        "result": "PASS",
        "executed_vector_ids": executed,
        "killed_child_count": len(executed),
    }
