"""Run only the frozen implementation-readiness review leaf commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, cast

import rfc8785

EXPECTED_IDS = ("A_CHECK_SOURCE", "A_CHECK_EVIDENCE", "A_CHECK_BASELINE")
COMMAND_DOMAIN = b"HD636/REVIEW-COMMANDS/v1\0"


def _command_map(registry: dict[str, object]) -> dict[str, dict[str, object]]:
    commands = registry.get("commands")
    if not isinstance(commands, list):
        raise ValueError("E_REVIEW_A_REGISTRY")
    mapped: dict[str, dict[str, object]] = {}
    for row in commands:
        if not isinstance(row, dict) or not isinstance(row.get("command_id"), str):
            raise ValueError("E_REVIEW_A_REGISTRY")
        mapped[cast(str, row["command_id"])] = cast(dict[str, object], row)
    if len(mapped) != len(commands):
        raise ValueError("E_REVIEW_A_REGISTRY")
    return mapped


def run_review_a_checks(
    config: dict[str, object], registry: dict[str, object], *, execute: Callable[..., Any] = subprocess.run
) -> dict[str, object]:
    command_ids = config.get("mechanical_command_ids")
    if (
        config.get("role") != "IMPLEMENTATION_READINESS_REVIEWER"
        or config.get("network") != "DENY"
        or not isinstance(command_ids, list)
        or tuple(command_ids) != EXPECTED_IDS
    ):
        raise ValueError("E_REVIEW_A_CONFIG")
    environment = config.get("environment")
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in environment.items()
    ):
        raise ValueError("E_REVIEW_A_CONFIG")
    commands = _command_map(registry)
    records: list[dict[str, object]] = []
    for command_id in EXPECTED_IDS:
        command = commands.get(command_id)
        if (
            command is None
            or command.get("kind") != "review-leaf"
            or command.get("network") != "DENY"
            or command.get("authenticated_operator_access") != "DENY"
            or command.get("provider_access") != "DENY"
        ):
            raise ValueError("E_REVIEW_A_REGISTRY")
        argv, cwd = command.get("argv"), command.get("cwd")
        if not isinstance(argv, list) or not argv or not isinstance(cwd, str) or not os.path.isabs(cwd):
            raise ValueError("E_REVIEW_A_REGISTRY")
        if not all(isinstance(token, str) and token for token in argv):
            raise ValueError("E_REVIEW_A_REGISTRY")
        completed = execute(argv, cwd=cwd, env={**os.environ, **environment}, capture_output=True)
        stdout = bytes(getattr(completed, "stdout", b""))
        stderr = bytes(getattr(completed, "stderr", b""))
        exit_code = getattr(completed, "returncode", None)
        if exit_code != command.get("expected_exit"):
            raise ValueError("E_REVIEW_A_COMMAND")
        records.append(
            {
                "command_id": command_id,
                "argv": argv,
                "cwd": cwd,
                "environment": environment,
                "exit_code": exit_code,
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            }
        )
    root = hashlib.sha256(
        COMMAND_DOMAIN + rfc8785.dumps(cast(Any, sorted(records, key=lambda item: str(item["command_id"]))))
    ).hexdigest()
    return {"result": "PASS", "commands": records, "commands_executed_root": root}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run_review_a_checks(json.loads(args.config.read_text()), json.loads(args.registry.read_text())),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
