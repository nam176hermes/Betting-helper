"""Fail-closed restart-state inspection and local process-crash execution."""

from __future__ import annotations

import hashlib
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
    prepare_case: Callable[[Path], None] | None = None,
    recover_case: Callable[[Path], None] | None = None,
    validate_boundary: Callable[[Path, dict[str, object]], None] | None = None,
    compare_state: Callable[
        [dict[str, object], dict[str, object]], dict[str, object]
    ] = inspect_restart_state,
) -> dict[str, object]:
    if state_reader is None:
        raise ValueError("E_ACTUAL_STATE_READER_REQUIRED")
    _require_supported_termination()
    workspace.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    run_directory = workspace / f"run-{run_id}"
    run_directory.mkdir()
    executed: list[str] = []
    records: list[dict[str, object]] = []
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
        if prepare_case is not None:
            prepare_case(case_directory)
        ready = case_directory / "checkpoint.json"
        nonce = secrets.token_hex(16)
        with (
            (case_directory / "child.stdout").open("wb") as stdout,
            (case_directory / "child.stderr").open("wb") as stderr,
        ):
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
                if validate_boundary is not None:
                    validate_boundary(case_directory, identity)
                killed = _kill_owned_child(child)
                return_code = child.wait(timeout=5)
                if not killed or return_code != -signal.SIGKILL:
                    if return_code != 0:
                        raise RuntimeError(f"E_CRASH_CHILD_FAILED:{vector_id}:{return_code}")
                    raise RuntimeError(f"E_CRASH_CHILD_NOT_KILLED:{vector_id}")
                if recover_case is not None:
                    recover_case(case_directory)
                try:
                    observed = dict(state_reader(case_directory))
                except Exception as error:
                    raise RuntimeError(f"E_ACTUAL_STATE_READER_FAILED:{vector_id}") from error
                observation_path = case_directory / "comparison-state.json"
                observation_path.write_text(json.dumps(observed, sort_keys=True))
                # Only the parent writes the oracle, after all child work has finished.
                (case_directory / "expected-state.json").write_text(
                    json.dumps(expected, sort_keys=True)
                )
                comparison = compare_state(observed, expected)
                executed.append(vector_id)
                records.append(
                    {
                        "vector_id": vector_id,
                        "case_directory": str(case_directory),
                        "pid": child.pid,
                        "command": child.args,
                        "termination_returncode": return_code,
                        "termination_mechanism": "POSIX_OWNED_PROCESS_GROUP_SIGKILL",
                        "checkpoint": identity,
                        "checkpoint_sha256": hashlib.sha256(ready.read_bytes()).hexdigest(),
                        "actual_state_sha256": hashlib.sha256(
                            observation_path.read_bytes()
                        ).hexdigest(),
                        "comparison": comparison["result"],
                    }
                )
            except Exception as error:
                (case_directory / "failure.json").write_text(
                    json.dumps(
                        {
                            "vector_id": vector_id,
                            "status": "FAIL",
                            "error": str(error),
                            "checkpoint_identity": identity,
                        },
                        sort_keys=True,
                    )
                )
                raise
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
        "records": records,
    }
