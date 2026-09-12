"""Run every frozen cybersecurity review leaf command exactly once."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import rfc8785

from tools.run_review_a_checks import review_environment

EXPECTED_IDS = (
    "SEC_CAPABILITY_MANIFEST",
    "SEC_CDP_REACHABILITY",
    "SEC_DYNAMIC_DISPATCH",
    "SEC_TARGET_ESCAPE",
    "SEC_MESSAGE_SMUGGLING",
    "SEC_OUTBOUND_NETWORK",
    "SEC_AUTHORIZATION_TRUST",
    "SEC_REPLAY_REVOCATION",
    "SEC_CREDENTIAL_EVIDENCE",
    "SEC_CANONICAL_HASHING",
    "SEC_NO_ARCHIVE",
    "SEC_BUBBLEWRAP_ISOLATION",
    "SEC_SUPPLY_CHAIN",
    "SEC_PRODUCTION_BUILD_EXCLUSION",
)
COMMAND_DOMAIN = b"HD636/REVIEW-COMMANDS/v1\0"


def run_review_b_checks(
    config: dict[str, object],
    registry: dict[str, object],
    *,
    execute: Callable[..., Any] = subprocess.run,
) -> dict[str, object]:
    command_ids = config.get("mechanical_command_ids")
    if (
        config.get("role") != "CYBERSECURITY_REVIEWER"
        or config.get("network") != "DENY"
        or not isinstance(command_ids, list)
        or tuple(command_ids) != EXPECTED_IDS
    ):
        raise ValueError("E_REVIEW_B_CONFIG")
    environment = config.get("environment")
    commands = registry.get("commands")
    if (
        not isinstance(environment, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in environment.items()
        )
        or not isinstance(commands, list)
    ):
        raise ValueError("E_REVIEW_B_REGISTRY")
    environment = review_environment(config)
    mapped: dict[str, dict[str, object]] = {}
    for row in commands:
        if not isinstance(row, dict) or not isinstance(row.get("command_id"), str):
            raise ValueError("E_REVIEW_B_REGISTRY")
        mapped[cast(str, row["command_id"])] = cast(dict[str, object], row)
    if len(mapped) != len(commands) or set(mapped) != set(EXPECTED_IDS):
        raise ValueError("E_REVIEW_B_REGISTRY")
    records: list[dict[str, object]] = []
    for command_id in EXPECTED_IDS:
        command = mapped[command_id]
        if (
            command.get("kind") != "review-leaf"
            or command.get("network") != "DENY"
            or command.get("authenticated_operator_access") != "DENY"
            or command.get("provider_access") != "DENY"
        ):
            raise ValueError("E_REVIEW_B_REGISTRY")
        argv, cwd = command.get("argv"), command.get("cwd")
        if (
            not isinstance(argv, list)
            or not argv
            or not isinstance(cwd, str)
            or not os.path.isabs(cwd)
        ):
            raise ValueError("E_REVIEW_B_REGISTRY")
        if not all(isinstance(token, str) and token for token in argv):
            raise ValueError("E_REVIEW_B_REGISTRY")
        completed = execute(argv, cwd=cwd, env=environment, capture_output=True)
        stdout = bytes(getattr(completed, "stdout", b""))
        stderr = bytes(getattr(completed, "stderr", b""))
        exit_code = getattr(completed, "returncode", None)
        if exit_code != command.get("expected_exit"):
            raise ValueError("E_REVIEW_B_COMMAND")
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
        COMMAND_DOMAIN
        + rfc8785.dumps(cast(Any, sorted(records, key=lambda item: str(item["command_id"]))))
    ).hexdigest()
    return {"result": "PASS", "commands": records, "commands_executed_root": root}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run_review_b_checks(
                json.loads(args.config.read_text()), json.loads(args.registry.read_text())
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
