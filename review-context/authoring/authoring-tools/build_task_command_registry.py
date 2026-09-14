"""Materialize the current command registry and review configs from frozen sources."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

BAD = re.compile(r"(?i)(?:\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|\.\.\.|<[^>]+>|\$\{|\$\(|`)")
REVIEW_CONFIG_PROFILES = {
    "legacy": (
        "review-a.v1.json",
        "review-b.v1.json",
        "review-aggregation.v1.json",
        "review-authority.v1.json",
    ),
    "current": (
        "review-a.v2.json",
        "review-b.v2.json",
        "review-aggregation.v2.json",
        "review-authority.v1.json",
    ),
    "scoped": (
        "review-a.v2.json", "review-b.v2.json", "review-aggregation.v2.json",
        "review-authority.v1.json", "review-a.v3.json", "review-b.v3.json",
    ),
}


def _validate(manifest: dict[str, object], registry: dict[str, object]) -> None:
    commands = registry.get("commands")
    if registry.get("schema_version") != "command-registry/v1" or not isinstance(commands, list):
        raise ValueError("E_COMMAND_REGISTRY")
    ids: set[str] = set()
    for command in commands:
        command_id = command.get("command_id")
        argv = command.get("argv")
        if not isinstance(command_id, str) or command_id in ids or not isinstance(argv, list) or not argv:
            raise ValueError("E_COMMAND_REGISTRY")
        if "hybrid-discovery-v6.2" in str(command.get("cwd", "")) or any(
            not isinstance(token, str) or not token.strip() or (index == 0 or argv[index - 1] != "-c") and BAD.search(token)
            for index, token in enumerate(argv)
        ):
            raise ValueError("E_COMMAND_PLACEHOLDER")
        if any(command.get(key) != "DENY" for key in ("network", "provider_access", "authenticated_operator_access")):
            raise ValueError("E_COMMAND_AUTHORITY")
        ids.add(command_id)
    if any(command_id not in ids and not command_id.startswith("REVIEW_") for task in manifest["tasks"] for command_id in task["exact_command_ids"]):
        raise ValueError("E_COMMAND_REFERENCE")


def build_task_command_registry(
    manifest: dict[str, object],
    source_registry: Path,
    review_config_source: Path,
    output: Path,
    *,
    review_config_profile: str = "legacy",
) -> dict[str, object]:
    try:
        review_configs = REVIEW_CONFIG_PROFILES[review_config_profile]
    except KeyError as error:
        raise ValueError(f"E_REVIEW_CONFIG_PROFILE:{review_config_profile}") from error
    registry = json.loads(source_registry.read_text(encoding="utf-8"))
    _validate(manifest, registry)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_registry, output)
    config_root = output.parent / "review-config"
    for name in review_configs:
        source = review_config_source / name
        if not source.is_file():
            raise ValueError(f"E_REVIEW_CONFIG:{name}")
        config_root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, config_root / name)
    return {
        "result": "PASS",
        "command_count": len(registry["commands"]),
        "review_config_count": len(review_configs),
        "review_config_profile": review_config_profile,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-registry", required=True, type=Path)
    parser.add_argument("--review-config-source", required=True, type=Path)
    parser.add_argument(
        "--review-config-profile",
        choices=tuple(REVIEW_CONFIG_PROFILES),
        default="legacy",
    )
    args = parser.parse_args()
    manifest = json.loads(args.tasks.read_text(encoding="utf-8"))
    print(
        json.dumps(
            build_task_command_registry(
                manifest,
                args.source_registry,
                args.review_config_source,
                args.output,
                review_config_profile=args.review_config_profile,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
