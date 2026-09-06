"""Fail-closed MATERIALIZATION_COMPLETE gate for the sealed authoring inventory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator


def _fail(code: str, path: str = "") -> None:
    raise ValueError(f"E_MATERIALIZATION_COMPLETE:{code}{':' + path if path else ''}")


def _safe_file(root: Path, relative: str) -> Path | None:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            return None
    return current if current.is_file() else None


def _read_json(path: Path, code: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _fail(code)
    if not isinstance(value, dict):
        _fail(code)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_is_valid(entry: dict[str, object]) -> bool:
    source = entry["source"]
    classification = entry["classification"]
    if classification in {"BASELINE_INPUT", "PLAN_SEED", "GENERATED_OUTPUT"}:
        return (
            isinstance(source, dict)
            and set(source) == {"path"}
            and isinstance(source["path"], str)
            and bool(source["path"].strip())
        )
    if classification == "BASELINE_COPY":
        return (
            isinstance(source, dict)
            and set(source) == {"path", "sha256"}
            and isinstance(source["path"], str)
            and isinstance(source["sha256"], str)
            and len(source["sha256"]) == 64
            and all(char in "0123456789abcdef" for char in source["sha256"])
        )
    if classification in {"TASK_OUTPUT", "EVIDENCE_OUTPUT"}:
        return source is None
    if classification == "EXTERNAL_INPUT":
        return (
            isinstance(source, dict)
            and set(source) in (
                {"path", "binding"},
                {"path", "binding", "creation_owner", "creation_command"},
            )
            and all(isinstance(value, str) and value.strip() for value in source.values())
        )
    return False


def _verify_plan_closure(plan_root: Path, expected_manifest_hash: str) -> None:
    manifest_path = _safe_file(plan_root, "MANIFEST_SHA256.json")
    if manifest_path is None or _sha256(manifest_path) != expected_manifest_hash:
        _fail("BOOTSTRAP")
    manifest = _read_json(manifest_path, "MANIFEST")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        _fail("MANIFEST")
    listed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            _fail("MANIFEST")
        relative = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or relative in listed
        ):
            _fail("MANIFEST")
        file_path = _safe_file(plan_root, relative)
        if file_path is None or file_path.stat().st_size != size or _sha256(file_path) != digest:
            _fail("MANIFEST", relative)
        listed.add(relative)
    actual: set[str] = set()
    for candidate in plan_root.rglob("*"):
        if candidate.is_symlink():
            _fail("PLAN_SYMLINK")
        if candidate.is_file():
            actual.add(candidate.relative_to(plan_root).as_posix())
    if actual != listed | {"MANIFEST_SHA256.json"}:
        _fail("MANIFEST_CLOSURE")


def validate_materialization_complete(root: Path) -> dict[str, object]:
    """Validate every required artifact without consuming deferred external outputs."""
    if root.is_symlink() or not root.is_dir():
        _fail("ROOT")
    runtime_root = root.resolve()
    authoring_root = runtime_root.parent
    plan_root = authoring_root / "plan-input"
    bootstrap_path = _safe_file(authoring_root, ".bootstrap/authoring-workspace-receipt.json")
    if bootstrap_path is None or plan_root.is_symlink() or not plan_root.is_dir():
        _fail("BOOTSTRAP")
    bootstrap = _read_json(bootstrap_path, "BOOTSTRAP")
    if (
        bootstrap.get("authoring_root") != str(authoring_root)
        or bootstrap.get("plan_input_root") != str(plan_root)
        or not isinstance(bootstrap.get("manifest_sha256"), str)
    ):
        _fail("BOOTSTRAP")
    _verify_plan_closure(plan_root, bootstrap["manifest_sha256"])

    ownership_path = _safe_file(plan_root, "docs/registries/artifact-ownership.v1.json")
    schema_path = _safe_file(plan_root, "docs/schemas/artifact-ownership.schema.json")
    tasks_path = _safe_file(plan_root, "docs/tasks/task-manifest.v6.3.6.json")
    if ownership_path is None or schema_path is None or tasks_path is None:
        _fail("DECLARATION_INPUT")
    ownership = _read_json(ownership_path, "OWNERSHIP")
    schema = _read_json(schema_path, "OWNERSHIP_SCHEMA")
    schema = {**schema, "$ref": "#/$defs/ArtifactOwnershipRegistry"}
    if list(Draft202012Validator(schema).iter_errors(ownership)):
        _fail("OWNERSHIP_SCHEMA")
    task_manifest = _read_json(tasks_path, "TASKS")
    tasks = task_manifest.get("tasks")
    if not isinstance(tasks, list):
        _fail("TASKS")
    order = {
        task["task_id"]: index
        for index, task in enumerate(tasks)
        if isinstance(task, dict) and isinstance(task.get("task_id"), str)
    }
    if len(order) != len(tasks) or "V636-P01-T06" not in order:
        _fail("TASKS")
    cutoff = order["V636-P01-T06"]

    entries = ownership.get("entries")
    if not isinstance(entries, list):
        _fail("OWNERSHIP")
    paths: set[str] = set()
    materialized = 0
    deferred = 0
    for entry in entries:
        if not isinstance(entry, dict):
            _fail("ENTRY")
        path = entry.get("path")
        owner = entry.get("creation_owner")
        if not isinstance(path, str) or not path or path in paths or not _source_is_valid(entry):
            _fail("ENTRY", path if isinstance(path, str) else "")
        paths.add(path)
        if owner is None:
            if entry["source"] is None:
                _fail("UNOWNED", path)
        elif not isinstance(owner, str) or owner not in order:
            _fail("UNKNOWN_OWNER", path)
        for field, code in (
            ("modifying_tasks", "MODIFIER"),
            ("consumers", "CONSUMER"),
        ):
            for task_id in entry[field]:
                if task_id not in order:
                    _fail(code, path)
                if owner is not None and order[task_id] < order[owner]:
                    _fail("CONSUMER_BEFORE_OWNER", path)
        qualification = entry["qualification_owner"]
        if qualification is not None:
            if qualification not in order or owner is not None and order[qualification] < order[owner]:
                _fail("QUALIFICATION", path)

        if not entry["materialization_required"]:
            deferred += 1
            continue
        if PurePosixPath(path).is_absolute() or owner is not None and order[owner] > cutoff:
            _fail("FUTURE_OWNER", path)
        target = _safe_file(authoring_root, path)
        if target is None:
            _fail("MISSING", path)
        classification = entry["classification"]
        source = entry["source"]
        if classification == "BASELINE_COPY":
            assert isinstance(source, dict)
            source_path = Path(source["path"])
            if not source_path.is_file() or source_path.is_symlink() or _sha256(source_path) != source["sha256"]:
                _fail("BASELINE_SOURCE", path)
        elif classification == "PLAN_SEED":
            assert isinstance(source, dict)
            source_path = _safe_file(authoring_root, source["path"])
            if source_path is None or source_path.read_bytes() != target.read_bytes():
                _fail("PLAN_SEED", path)
        materialized += 1

    receipt = {
        "schema_version": "materialization-complete/v2",
        "gate": "MATERIALIZATION_COMPLETE",
        "result": "PASS",
        "artifact_root": str(runtime_root),
        "authoring_root": str(authoring_root),
        "plan_input_manifest_sha256": bootstrap["manifest_sha256"],
        "materialized_artifact_count": materialized,
        "deferred_artifact_count": deferred,
        "authorized_production_phases": "NONE",
    }
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["content_hash"] = hashlib.sha256(b"HD636/MATERIALIZATION/v1\\0" + payload).hexdigest()
    return receipt
