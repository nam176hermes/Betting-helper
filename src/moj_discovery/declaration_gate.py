"""Issue the MATERIALIZED_CONTRACTS_VALID gate from sealed, materialized inputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .artifact_ownership import validate_artifact_lifecycle
from .task_contracts import validate_task_manifest_semantics


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("E_DECLARATION_INPUT")
    return value


def _commands(registries: Path) -> list[dict[str, object]]:
    return [
        command
        for name in (
            "task-command-registry.v1.json",
            "review-command-registry.v1.json",
            "cybersecurity-command-registry.v1.json",
            "baseline-replay-command-registry.v1.json",
        )
        for command in _load(registries / name)["commands"]
    ]


def _resolve_pointer(document: object, pointer: object) -> bool:
    if not isinstance(pointer, str) or not pointer.startswith("#/"):
        return False
    value = document
    for part in pointer[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return True


def _validate_schema_references(plan_root: Path) -> int:
    references = _load(
        plan_root / "docs/registries/schema-reference-registry.v1.json"
    )["references"]
    if not isinstance(references, list):
        raise ValueError("E_SCHEMA_REFERENCE")
    seen: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("E_SCHEMA_REFERENCE")
        logical_name = reference.get("logical_name")
        relative = reference.get("plan_source_path")
        pointer = reference.get("json_pointer")
        if (
            not isinstance(logical_name, str)
            or not isinstance(relative, str)
            or not relative.startswith("pack/docs/")
            or logical_name in seen
        ):
            raise ValueError("E_SCHEMA_REFERENCE")
        schema = _load(plan_root / relative.removeprefix("pack/"))
        if not _resolve_pointer(schema, pointer):
            raise ValueError("E_SCHEMA_POINTER")
        seen.add(logical_name)
    return len(seen)


def issue_declaration_complete_receipt(plan_root: Path) -> dict[str, object]:
    """Return a MATERIALIZED_CONTRACTS_VALID receipt without creating future evidence."""
    registry_root = plan_root / "docs/registries"
    ownership = _load(registry_root / "artifact-ownership.v1.json")
    manifest = _load(plan_root / "docs/tasks/task-manifest.v6.3.6.json")
    schema = _load(plan_root / "docs/schemas/artifact-ownership.schema.json")
    commands = _commands(registry_root)
    owned = {entry["path"] for entry in ownership["entries"]}
    validate_task_manifest_semantics(manifest, commands, owned)
    validate_artifact_lifecycle(
        ownership,
        manifest,
        authoring_root=Path(__file__).resolve().parents[3],
        schema=schema,
    )
    schema_reference_count = _validate_schema_references(plan_root)
    payload = {
        "schema_version": "materialized-contracts-valid/v1",
        "gate": "MATERIALIZED_CONTRACTS_VALID",
        "result": "PASS",
        "task_count": len(manifest["tasks"]),
        "artifact_count": len(ownership["entries"]),
        "command_count": len({command["command_id"] for command in commands}),
        "schema_reference_count": schema_reference_count,
        "authorized_production_phases": "NONE",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = hashlib.sha256(
        b"HD636/MATERIALIZED-CONTRACTS/v1\0" + raw
    ).hexdigest()
    return payload
