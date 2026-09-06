"""Validate the closed cybersecurity command and attack coverage registries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify_cybersecurity_command_registry(
    registry: dict[str, object], matrix: dict[str, object], runtime_root: Path | None = None
) -> dict[str, object]:
    commands = registry.get("commands")
    attacks = matrix.get("entries")
    if (
        not isinstance(commands, list)
        or not isinstance(attacks, list)
        or len(commands) != 14
        or len(attacks) != 14
    ):
        raise ValueError("E_CYBERSECURITY_REGISTRY")
    command_ids = set()
    for command in commands:
        if (
            not isinstance(command, dict)
            or not isinstance(command.get("command_id"), str)
            or command["command_id"] in command_ids
            or not isinstance(command.get("argv"), list)
            or not command["argv"]
            or command.get("required") is not True
            or command.get("expected_exit") != 0
            or any(
                command.get(key) != "DENY"
                for key in ("network", "authenticated_operator_access", "provider_access")
            )
        ):
            raise ValueError("E_CYBERSECURITY_REGISTRY")
        command_ids.add(command["command_id"])
    runtime_root = (runtime_root or Path.cwd()).resolve()
    attack_ids: set[object] = set()
    for entry in attacks:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(field), str) and entry[field]
            for field in (
                "source",
                "positive_vector_id",
                "negative_vector_id",
                "mutation_vector_id",
                "proof",
            )
        ):
            raise ValueError("E_CYBERSECURITY_REGISTRY")
        relative = Path(str(entry["source"]))
        if relative.parts and relative.parts[0] == "runtime":
            relative = Path(*relative.parts[1:])
        source = (runtime_root / relative).resolve()
        if runtime_root not in source.parents or not source.is_file():
            raise ValueError("E_CYBERSECURITY_REGISTRY")
        text = source.read_text()
        if any(
            str(entry[field]) not in text
            for field in ("positive_vector_id", "negative_vector_id", "mutation_vector_id")
        ):
            raise ValueError("E_CYBERSECURITY_REGISTRY")
        attack_ids.add(entry.get("command_id"))
    if attack_ids != command_ids:
        raise ValueError("E_CYBERSECURITY_REGISTRY")
    return {"result": "PASS", "security_area_count": len(command_ids)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--matrix", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            verify_cybersecurity_command_registry(
                json.loads(args.registry.read_text()), json.loads(args.matrix.read_text())
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
