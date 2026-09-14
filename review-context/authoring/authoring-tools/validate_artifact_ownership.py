"""Check declaration-stage producers, sources, and consumers fail closed."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _source_valid(entry: dict[str, object]) -> bool:
    source = entry["source"]
    classification = entry["classification"]
    if classification in {"BASELINE_INPUT", "PLAN_SEED", "GENERATED_OUTPUT"}:
        return isinstance(source, dict) and set(source) == {"path"} and isinstance(source["path"], str) and bool(source["path"].strip())
    if classification == "BASELINE_COPY":
        return (
            isinstance(source, dict)
            and set(source) == {"path", "sha256"}
            and isinstance(source["path"], str)
            and bool(source["path"].strip())
            and isinstance(source["sha256"], str)
            and bool(SHA256.fullmatch(source["sha256"]))
        )
    if classification in {"TASK_OUTPUT", "EVIDENCE_OUTPUT"}:
        return source is None
    if classification == "EXTERNAL_INPUT":
        return isinstance(source, dict) and set(source) in (
            {"path", "binding"},
            {"path", "binding", "creation_owner", "creation_command"},
        ) and all(isinstance(value, str) and value.strip() for value in source.values())
    return False


def _path(value: str, authoring_root: Path) -> str:
    return value.split("::", 1)[0].removeprefix(str(authoring_root) + "/")


def validate_artifact_ownership(
    registry: dict[str, object],
    manifest: dict[str, object],
    authoring_root: Path = Path.cwd(),
    schema: dict[str, object] | None = None,
) -> dict[str, object]:
    if schema is not None:
        closed = {**schema, "$ref": "#/$defs/ArtifactOwnershipRegistry"}
        if list(Draft202012Validator(closed).iter_errors(registry)):
            raise ValueError("E_OWNER_SCHEMA")
    tasks = manifest["tasks"]
    order = {task["task_id"]: index for index, task in enumerate(tasks)}
    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise ValueError("E_OWNER_REGISTRY")
    paths: set[str] = set()
    owned: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("E_OWNER_SCHEMA")
        path = entry.get("path")
        if not isinstance(path, str) or not path or path in paths:
            raise ValueError("E_OWNER_DUPLICATE")
        paths.add(path)
        owned[path] = entry
        if not _source_valid(entry):
            raise ValueError(f"E_OWNER_SOURCE:{path}")
        owner = entry.get("creation_owner")
        if owner is None:
            if not entry["source"]:
                raise ValueError(f"E_OWNER_MISSING:{path}")
        elif not isinstance(owner, str) or not owner.strip() or owner not in order:
            raise ValueError(f"E_OWNER_UNKNOWN:{path}")
        for modifier in entry.get("modifying_tasks", []):
            if not isinstance(modifier, str) or modifier not in order or owner is not None and order[modifier] < order[owner]:
                raise ValueError(f"E_MODIFIER_ORDER:{path}")
        qualification = entry.get("qualification_owner")
        if qualification is not None and (
            not isinstance(qualification, str)
            or qualification not in order
            or owner is not None and order[qualification] < order[owner]
        ):
            raise ValueError(f"E_QUALIFICATION_ORDER:{path}")
        for consumer in entry.get("consumers", []):
            if not isinstance(consumer, str) or consumer not in order:
                raise ValueError(f"E_CONSUMER_UNKNOWN:{path}")
            if owner is not None and order[consumer] < order[owner]:
                raise ValueError(f"E_CONSUMER_BEFORE_OWNER:{path}")
    for task in tasks:
        task_id = task["task_id"]
        for field in ("outputs", "exact_files", "evidence_artifacts"):
            for value in task[field]:
                path = _path(value, authoring_root)
                entry = owned.get(path)
                if entry is None:
                    raise ValueError(f"E_UNOWNED:{value}")
                if field == "outputs" and task_id not in {entry["creation_owner"], *entry["modifying_tasks"]}:
                    raise ValueError(f"E_OUTPUT_OWNER:{value}")
                if task_id not in entry["consumers"] and task_id != entry["creation_owner"]:
                    raise ValueError(f"E_CONSUMER_UNDECLARED:{value}")
    return {"result": "PASS", "artifact_count": len(entries)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--commands", required=True, type=Path)
    parser.add_argument("--review-commands", required=True, type=Path)
    parser.add_argument("--security-commands", required=True, type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    manifest = json.loads(args.tasks.read_text(encoding="utf-8"))
    schema = json.loads((args.registry.parents[1] / "schemas/artifact-ownership.schema.json").read_text(encoding="utf-8"))
    print(json.dumps(validate_artifact_ownership(registry, manifest, schema=schema), sort_keys=True))


if __name__ == "__main__":
    main()
