"""Validate declaration-stage task semantics without inspecting future symbols."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]


BAD = re.compile(r"(?i)(?:\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|\.\.\.|<[^>]+>|\$\{|\$\(|`)")
TASK_AUTHORITIES = {"PLAN_AUTHORING", "DISCOVERY_IMPLEMENTATION", "REVIEW_TOOLING", "EXTERNAL_REVIEW"}
AUTHORING_ROOT = "/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/"


def _owned_path(value: object) -> object:
    if not isinstance(value, str):
        return value
    return value.removeprefix(AUTHORING_ROOT).removeprefix(str(Path.cwd()) + "/")


def validate_task_manifest_semantics(
    manifest: dict[str, object], commands: list[dict[str, object]], owned_paths: set[str]
) -> dict[str, object]:
    if manifest.get("authority") != "PLAN_ONLY" or manifest.get("authorized_production_phases") != "NONE":
        raise ValueError("E_PRODUCTION_AUTHORITY")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or manifest.get("declared_task_count") != len(tasks):
        raise ValueError("E_TASK_COUNT")
    command_ids: set[str] = set()
    for command in commands:
        command_id = command.get("command_id")
        argv = command.get("argv")
        if not isinstance(command_id, str) or command_id in command_ids or not isinstance(argv, list) or not argv:
            raise ValueError("E_COMMAND_SHAPE")
        if any(
            not isinstance(token, str)
            or not token.strip()
            or (index == 0 or argv[index - 1] != "-c") and BAD.search(token)
            for index, token in enumerate(argv)
        ):
            raise ValueError("E_COMMAND_PLACEHOLDER")
        if any(command.get(key) != "DENY" for key in ("network", "provider_access", "authenticated_operator_access")):
            raise ValueError("E_COMMAND_AUTHORITY")
        command_ids.add(command_id)
    seen: set[str] = set()
    for task in tasks:
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or task_id in seen:
            raise ValueError("E_TASK_ID")
        if task.get("authority") not in TASK_AUTHORITIES:
            raise ValueError("E_TASK_AUTHORITY")
        dependencies = task.get("dependencies")
        if not isinstance(dependencies, list) or any(dependency not in seen for dependency in dependencies):
            raise ValueError("E_DEPENDENCY_UNKNOWN_OR_FUTURE")
        rollback = task.get("rollback")
        if not isinstance(rollback, list) or not rollback or any(not isinstance(item, str) or not item.strip() for item in rollback):
            raise ValueError("E_EMPTY_ROLLBACK")
        refs = task.get("exact_command_ids")
        if not isinstance(refs, list) or not refs or any(reference not in command_ids for reference in refs):
            raise ValueError("E_TASK_COMMAND")
        for field in ("outputs", "exact_files", "evidence_artifacts"):
            for path in task.get(field, []):
                if _owned_path(path) not in owned_paths:
                    raise ValueError("E_UNOWNED")
        seen.add(task_id)
    return {"result": "PASS", "task_count": len(tasks), "command_count": len(command_ids)}


def _load_commands(paths: list[Path]) -> list[dict[str, object]]:
    return [command for path in paths for command in json.loads(path.read_text(encoding="utf-8"))["commands"]]


def _owned_paths(path: Path) -> set[str]:
    return {entry["path"] for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]}


def _validate_contract_inputs(
    commands: list[dict[str, object]], command_io_path: Path, vectors_path: Path
) -> None:
    command_io = json.loads(command_io_path.read_text(encoding="utf-8"))["commands"]
    io_ids = {row["command_id"] for row in command_io}
    if len(io_ids) != len(command_io) or any(command["command_id"] not in io_ids for command in commands):
        raise ValueError("E_COMMAND_IO")
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    negatives = {row["id"] for row in vectors["cases"]}
    if not {"PRODUCTION", "UNKNOWN_DEP", "FUTURE_DEP", "EMPTY_ROLLBACK", "COUNT_MISMATCH", "UNOWNED_FILE", "PLACEHOLDER_TODO"} <= negatives:
        raise ValueError("E_NEGATIVE_VECTOR_COVERAGE")
    if vectors["positive_review_vector"] != {
        "id": "REVIEW-READY-YES-SCOPE0-NO",
        "READY_TO_IMPLEMENT_DISCOVERY_PACK": "YES",
        "SAFE_TO_FREEZE_SCOPE0": "NO",
        "AUTHORIZED_PRODUCTION_PHASES": "NONE",
    }:
        raise ValueError("E_POSITIVE_VECTOR")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--commands", required=True, type=Path)
    parser.add_argument("--review-commands", required=True, type=Path)
    parser.add_argument("--security-commands", required=True, type=Path)
    parser.add_argument("--ownership", required=True, type=Path)
    parser.add_argument("--vectors", required=True, type=Path)
    parser.add_argument("--command-io", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    if list(Draft202012Validator(schema).iter_errors(manifest)):
        raise ValueError("E_TASK_SCHEMA")
    paths = [
        args.commands,
        args.review_commands,
        args.security_commands,
        args.command_io.with_name("baseline-replay-command-registry.v1.json"),
    ]
    commands = _load_commands(paths)
    _validate_contract_inputs(commands, args.command_io, args.vectors)
    print(json.dumps(validate_task_manifest_semantics(manifest, commands, _owned_paths(args.ownership)), sort_keys=True))


if __name__ == "__main__":
    main()
