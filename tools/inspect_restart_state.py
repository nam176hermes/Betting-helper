"""Fail-closed restart-state inspection and local process-crash execution."""
from __future__ import annotations

import json
import os
import secrets
import signal
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from subprocess import Popen, TimeoutExpired
from time import monotonic, sleep
from typing import Any

ActualStateReader = Callable[[Path], Mapping[str, Any]]
CHECKPOINT_TIMEOUT_SECONDS = 10.0
CHECKPOINT_FIELDS = {
    "run_id",
    "case_id",
    "checkpoint_id",
    "component",
    "pid",
    "ordinal",
    "test_nonce",
}


def inspect_restart_state(
    observed: dict[str, object], expected: dict[str, object]
) -> dict[str, object]:
    if observed != expected:
        raise ValueError("E_RESTART_STATE_MISMATCH")
    return {"result": "PASS", "state": observed}


def _require_supported_termination() -> None:
    if os.name != "posix":
        raise RuntimeError(f"E_CRASH_TERMINATION_UNSUPPORTED:{os.name}")


def _kill_owned_child(child: Popen[bytes]) -> bool:
    _require_supported_termination()
    if child.poll() is not None:
        return False
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    return True


def _checkpoint(
    ready: Path, child: Popen[bytes], identity: dict[str, object], vector_id: str
) -> None:
    deadline = monotonic() + CHECKPOINT_TIMEOUT_SECONDS
    while not ready.is_file() and monotonic() < deadline:
        return_code = child.poll()
        if return_code is not None:
            raise RuntimeError(f"E_CRASH_CHILD_FAILED:{vector_id}:{return_code}")
        sleep(0.02)
    if not ready.is_file():
        raise RuntimeError(f"E_CRASH_CHECKPOINT_MISSING:{vector_id}")
    try:
        record = json.loads(ready.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"E_CRASH_CHECKPOINT_INVALID:{vector_id}") from error
    if not isinstance(record, dict) or set(record) != CHECKPOINT_FIELDS or record != identity:
        raise RuntimeError(f"E_CRASH_CHECKPOINT_MISMATCH:{vector_id}")


def execute_crash_matrix(
    entries: list[dict[str, object]],
    command_prefix: list[str],
    workspace: Path,
    *,
    state_reader: ActualStateReader | None = None,
) -> dict[str, object]:
    if state_reader is None:
        raise ValueError("E_ACTUAL_STATE_READER_REQUIRED")
    _require_supported_termination()
    workspace.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    run_directory = workspace / f"run-{run_id}"
    run_directory.mkdir()
    executed: list[str] = []
    for ordinal, entry in enumerate(entries):
        vector_id = entry.get("vector_id")
        checkpoint_id = entry.get("crash_checkpoint")
        component = entry.get("harness")
        expected = entry.get("expected_post_restart_state")
        if (
            not isinstance(vector_id, str)
            or not vector_id
            or not isinstance(checkpoint_id, str)
            or not checkpoint_id
            or not isinstance(component, str)
            or not component
            or not isinstance(expected, dict)
        ):
            raise ValueError("E_CRASH_CASE_INVALID")
        case_directory = run_directory / f"case-{ordinal:04d}"
        case_directory.mkdir()
        ready = case_directory / "checkpoint.json"
        nonce = secrets.token_hex(16)
        with (case_directory / "child.stdout").open("wb") as stdout, (
            case_directory / "child.stderr"
        ).open("wb") as stderr:
            child = Popen(  # noqa: S603 - command is a closed caller-supplied test harness
                [
                    *command_prefix,
                    "--vector-id",
                    vector_id,
                    "--ready",
                    str(ready),
                    "--run-id",
                    run_id,
                    "--case-id",
                    vector_id,
                    "--checkpoint-id",
                    checkpoint_id,
                    "--component",
                    component,
                    "--ordinal",
                    str(ordinal),
                    "--test-nonce",
                    nonce,
                    "--hold",
                ],
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            identity: dict[str, object] = {
                "run_id": run_id,
                "case_id": vector_id,
                "checkpoint_id": checkpoint_id,
                "component": component,
                "pid": child.pid,
                "ordinal": ordinal,
                "test_nonce": nonce,
            }
            try:
                _checkpoint(ready, child, identity, vector_id)
                killed = _kill_owned_child(child)
                return_code = child.wait(timeout=5)
                if not killed or return_code != -signal.SIGKILL:
                    if return_code != 0:
                        raise RuntimeError(
                            f"E_CRASH_CHILD_FAILED:{vector_id}:{return_code}"
                        )
                    raise RuntimeError(f"E_CRASH_CHILD_NOT_KILLED:{vector_id}")
                try:
                    observed = dict(state_reader(case_directory))
                except Exception as error:
                    raise RuntimeError(
                        f"E_ACTUAL_STATE_READER_FAILED:{vector_id}"
                    ) from error
                inspect_restart_state(observed, expected)
                executed.append(vector_id)
            finally:
                _kill_owned_child(child)
                try:
                    child.wait(timeout=5)
                except TimeoutExpired as error:
                    raise RuntimeError(f"E_CRASH_CHILD_REAP_FAILED:{vector_id}") from error
    return {
        "result": "PASS",
        "executed_vector_ids": executed,
        "killed_child_count": len(executed),
    }
