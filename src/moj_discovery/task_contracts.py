"""Validate declaration-stage task semantics without inspecting future symbols."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

BAD = re.compile(r"(?i)(?:\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|\.\.\.|<[^>]+>|\$\{|\$\(|`)")
TASK_AUTHORITIES = {
    "PLAN_AUTHORING",
    "DISCOVERY_IMPLEMENTATION",
    "REVIEW_TOOLING",
    "EXTERNAL_REVIEW",
}


def validate_task_manifest_semantics(
    manifest: dict[str, object], commands: list[dict[str, object]], owned_paths: set[str]
) -> dict[str, object]:
    if (
        manifest.get("authority") != "PLAN_ONLY"
        or manifest.get("authorized_production_phases") != "NONE"
    ):
        raise ValueError("E_PRODUCTION_AUTHORITY")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or manifest.get("declared_task_count") != len(tasks):
        raise ValueError("E_TASK_COUNT")
    command_ids: set[str] = set()
    for command in commands:
        command_id = command.get("command_id")
        argv = command.get("argv")
        if (
            not isinstance(command_id, str)
            or command_id in command_ids
            or not isinstance(argv, list)
            or not argv
        ):
            raise ValueError("E_COMMAND_SHAPE")
        if any(
            not isinstance(token, str)
            or not token.strip()
            or (index == 0 or argv[index - 1] != "-c")
            and BAD.search(token)
            for index, token in enumerate(argv)
        ):
            raise ValueError("E_COMMAND_PLACEHOLDER")
        if any(
            command.get(key) != "DENY"
            for key in ("network", "provider_access", "authenticated_operator_access")
        ):
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
        if not isinstance(dependencies, list) or any(
            dependency not in seen for dependency in dependencies
        ):
            raise ValueError("E_DEPENDENCY_UNKNOWN_OR_FUTURE")
        rollback = task.get("rollback")
        if (
            not isinstance(rollback, list)
            or not rollback
            or any(not isinstance(item, str) or not item.strip() for item in rollback)
        ):
            raise ValueError("E_EMPTY_ROLLBACK")
        command_refs = task.get("exact_command_ids")
        if (
            not isinstance(command_refs, list)
            or not command_refs
            or any(reference not in command_ids for reference in command_refs)
        ):
            raise ValueError("E_TASK_COMMAND")
        for field in ("outputs", "exact_files", "evidence_artifacts"):
            for path in task.get(field, []):
                normalized = path
                if isinstance(path, str) and path not in owned_paths:
                    matches = {
                        owned
                        for owned in owned_paths
                        if not PurePosixPath(owned).is_absolute() and path.endswith("/" + owned)
                    }
                    normalized = next(iter(matches)) if len(matches) == 1 else path
                if normalized not in owned_paths:
                    raise ValueError("E_UNOWNED")
        seen.add(task_id)
    return {"result": "PASS", "task_count": len(tasks), "command_count": len(command_ids)}
