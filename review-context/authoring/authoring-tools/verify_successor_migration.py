"""Verify successor migration at initial and final checkpoints."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


INITIAL_OWNER = "V636-MIG0-T03"
INITIAL_ACCEPTED_MODIFIERS = {"V636-MIG0-T04", "V636-MIG0-T05"}
INITIAL_DOMAIN = b"HD636/MIGRATION/v1\0"
FINAL_DOMAIN = b"HD636/MIGRATION-FINAL/v1\0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(record: dict[str, object]) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _relative(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("E_MIGRATION_PATH")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("E_MIGRATION_PATH")
    return Path(*path.parts)


def _target(root: Path, value: object) -> Path:
    return root / _relative(value)


def _load(path: Path) -> dict[str, object]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"E_MIGRATION_JSON:{path}") from error
    if not isinstance(result, dict):
        raise ValueError(f"E_MIGRATION_JSON:{path}")
    return result


def _evidence(root: Path, task_id: str) -> tuple[dict[str, object], str]:
    path = root / f"{task_id}.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"E_MIGRATION_EVIDENCE:{task_id}")
    record = _load(path)
    if record.get("result") != "PASS" or record.get("task_id", task_id) != task_id:
        raise ValueError(f"E_MIGRATION_EVIDENCE:{task_id}")
    return record, _sha256(path)


def _entry_index(path: Path) -> dict[str, dict[str, object]]:
    entries = _load(path).get("entries")
    if not isinstance(entries, list):
        raise ValueError("E_MIGRATION_OWNERSHIP")
    result: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or entry["path"] in result:
            raise ValueError("E_MIGRATION_OWNERSHIP")
        result[entry["path"]] = entry
    return result


def _modifiers(entry: dict[str, object]) -> list[str]:
    values = entry.get("modifying_tasks", [])
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("E_MIGRATION_OWNERSHIP")
    return values


def _allowed_token(token: str, allowed: list[object]) -> bool:
    return any(isinstance(value, str) and (token == value or value.endswith("/") and token.startswith(value)) for value in allowed)


def _scan_legacy(root: Path, policy: dict[str, object]) -> None:
    pattern, entries = policy.get("token_pattern"), policy.get("source_entries")
    additional = policy.get("additional_fixture_literals", [])
    if (
        not isinstance(pattern, str)
        or not isinstance(entries, list)
        or not isinstance(additional, list)
        or any(not isinstance(value, str) for value in additional)
    ):
        raise ValueError("E_MIGRATION_POLICY")
    matcher = re.compile(pattern)
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("allowed_literals"), list):
            raise ValueError("E_MIGRATION_POLICY")
        logical = entry.get("path")
        if not isinstance(logical, str) or logical in seen:
            raise ValueError("E_MIGRATION_POLICY")
        seen.add(logical)
        path = _target(root, logical)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"E_MIGRATION_MISSING:{logical}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"E_MIGRATION_UTF8:{logical}") from error
        allowed = [*entry["allowed_literals"], *additional]
        for token in matcher.findall(text):
            if not _allowed_token(token, allowed):
                raise ValueError(f"E_MIGRATION_LEGACY:{logical}:{token}")
    fixtures = policy.get("immutable_fixture_files", [])
    if not isinstance(fixtures, list):
        raise ValueError("E_MIGRATION_POLICY")
    for fixture in fixtures:
        if not isinstance(fixture, dict) or not isinstance(fixture.get("sha256"), str):
            raise ValueError("E_MIGRATION_POLICY")
        path = _target(root, fixture.get("path"))
        if not path.is_file() or path.is_symlink() or _sha256(path) != fixture["sha256"]:
            raise ValueError(f"E_MIGRATION_FIXTURE:{fixture.get('path')}")


def _source_identity(registry_path: Path) -> str:
    source = registry_path.with_name("migration-source.v1.json")
    if source.is_file():
        record = _load(source)
        commit, tree = record.get("source_commit"), record.get("source_tree_oid")
        if isinstance(commit, str) and isinstance(tree, str):
            return f"{commit}:{tree}"
    return _sha256(registry_path)


def _root_hash(root: Path, relative: str, field: str) -> str:
    path = root / relative
    if path.is_file() and not path.is_symlink():
        try:
            value = _load(path).get(field)
        except ValueError:
            value = None
        if isinstance(value, str) and value:
            return value
    return hashlib.sha256(b"").hexdigest()


def _initial_receipt(root: Path, registry_path: Path) -> dict[str, object]:
    registry = root / "runtime/task-command-registry.json"
    return {
        "schema_version": "migration-receipt/v1",
        "source_identity": _source_identity(registry_path),
        "destination_root": "runtime",
        "rebinding_registry_sha256": _sha256(registry_path),
        "vendor_root": _root_hash(root, "runtime/schema-lock.json", "vendor_tree_sha256"),
        "command_registry_root": _sha256(registry) if registry.is_file() else hashlib.sha256(b"").hexdigest(),
        "legacy_scan_result": "PASS",
    }


def _with_hash(receipt: dict[str, object], domain: bytes) -> dict[str, object]:
    result = dict(receipt)
    result["content_hash"] = hashlib.sha256(domain + _canonical(result)).hexdigest()
    return result


def _write_or_match(path: Path, receipt: dict[str, object]) -> None:
    if path.exists():
        if path.is_symlink() or _load(path) != receipt:
            raise ValueError(f"E_MIGRATION_RECEIPT:{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _accepted(evidence_root: Path, task_id: str) -> bool:
    try:
        _evidence(evidence_root, task_id)
    except ValueError:
        return False
    return True


def _bound_modifier(evidence_root: Path, tasks: list[str] | set[str], logical: str, digest: str) -> tuple[str, str] | None:
    for task in reversed(list(tasks)):
        if task != INITIAL_OWNER and _accepted(evidence_root, task):
            evidence, evidence_hash = _evidence(evidence_root, task)
            output_hashes = evidence.get("output_hashes")
            if isinstance(output_hashes, dict) and output_hashes.get(logical) == digest:
                return task, evidence_hash
    return None


def _require_initial_patches(
    registry: dict[str, object], registry_path: Path, root: Path,
    ownership: dict[str, dict[str, object]], evidence_root: Path, *, final: bool
) -> None:
    patches = registry.get("patches")
    if not isinstance(patches, list):
        raise ValueError("E_MIGRATION_PATCHES")
    initial_evidence, _ = _evidence(evidence_root, INITIAL_OWNER)
    if initial_evidence.get("version_rebinding_registry_sha256") != _sha256(registry_path) or initial_evidence.get("hash_guarded_patch_count") != len(patches):
        raise ValueError("E_MIGRATION_REBIND_EVIDENCE")
    seen: set[str] = set()
    for patch in patches:
        if not isinstance(patch, dict) or not isinstance(patch.get("path"), str) or patch["path"] in seen:
            raise ValueError("E_MIGRATION_PATCHES")
        logical = patch["path"]
        seen.add(logical)
        entry = ownership.get(logical)
        if entry is None or INITIAL_OWNER not in _modifiers(entry):
            raise ValueError(f"E_MIGRATION_MODIFIER:{logical}")
        target = _target(root, logical)
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"E_MIGRATION_MISSING:{logical}")
        expected = patch.get("after_sha256")
        if not isinstance(expected, str):
            raise ValueError("E_MIGRATION_PATCHES")
        digest = _sha256(target)
        if digest == expected:
            continue
        allowed = [task for task in _modifiers(entry) if task in INITIAL_ACCEPTED_MODIFIERS]
        if not final and _bound_modifier(evidence_root, allowed, logical, digest) is None:
            raise ValueError(f"E_MIGRATION_HASH:{logical}")


def _final_owner(
    logical: str, digest: str, expected: str | None, owner: str | None,
    entry: dict[str, object], evidence_root: Path
) -> tuple[str, str]:
    if expected is not None and digest == expected and isinstance(owner, str):
        _, evidence_hash = _evidence(evidence_root, owner)
        return owner, evidence_hash
    modifier = _bound_modifier(evidence_root, _modifiers(entry), logical, digest)
    if modifier is not None:
        return modifier
    raise ValueError(f"E_MIGRATION_UNACCEPTED_MODIFIER:{logical}")


def _native_lock_rows(
    root: Path, policy: dict[str, object], ownership: dict[str, dict[str, object]], evidence_root: Path
) -> list[dict[str, object]]:
    if "final_native_lock_policy" not in policy:
        return []
    try:
        evidence, evidence_hash = _evidence(evidence_root, "V636-MIG0-T07")
    except ValueError as error:
        raise ValueError("E_MIGRATION_NATIVE_LOCK") from error
    lock_hashes = evidence.get("native_lock_hashes")
    if not isinstance(lock_hashes, dict):
        raise ValueError("E_MIGRATION_NATIVE_LOCK")
    rows: list[dict[str, object]] = []
    for logical in ("runtime/uv.lock", "runtime/pnpm-lock.yaml"):
        target, entry = _target(root, logical), ownership.get(logical)
        if entry is None or "V636-MIG0-T07" not in _modifiers(entry) or not target.is_file() or target.is_symlink():
            raise ValueError(f"E_MIGRATION_NATIVE_LOCK:{logical}")
        digest = _sha256(target)
        if lock_hashes.get(logical) != digest:
            raise ValueError(f"E_MIGRATION_NATIVE_LOCK:{logical}")
        rows.append({"path": logical, "sha256": digest, "basis": "NATIVE_LOCK_RECEIPT", "owner_task": "V636-MIG0-T07", "evidence_sha256": evidence_hash})
    return rows


def _final_receipt(
    registry: dict[str, object], registry_path: Path, root: Path,
    ownership: dict[str, dict[str, object]], evidence_root: Path,
    normative_map_path: Path | None
) -> dict[str, object]:
    policy = registry.get("final_legacy_policy")
    if not isinstance(policy, dict):
        raise ValueError("E_MIGRATION_POLICY")
    _scan_legacy(root, policy)
    patches = {p["path"]: p for p in registry.get("patches", []) if isinstance(p, dict) and isinstance(p.get("path"), str)}
    paths = {e["path"] for e in policy.get("source_entries", []) if isinstance(e, dict) and isinstance(e.get("path"), str)} | set(patches)
    fixtures = {e["path"] for e in policy.get("immutable_fixture_files", []) if isinstance(e, dict) and isinstance(e.get("path"), str)}
    rows: list[dict[str, object]] = []
    for logical in sorted(paths | fixtures, key=lambda value: value.encode("utf-8")):
        target, entry = _target(root, logical), ownership.get(logical)
        if entry is None or not target.is_file() or target.is_symlink():
            raise ValueError(f"E_MIGRATION_OUTPUT:{logical}")
        digest, patch = _sha256(target), patches.get(logical)
        source = entry.get("source")
        source_hash = source.get("sha256") if isinstance(source, dict) else None
        fixture = next((item for item in policy.get("immutable_fixture_files", []) if item.get("path") == logical), {})
        expected = fixture.get("sha256") if logical in fixtures else patch.get("after_sha256") if patch is not None else source_hash
        owner = INITIAL_OWNER if patch is not None and digest == patch.get("after_sha256") else entry.get("creation_owner")
        owner, evidence_hash = _final_owner(logical, digest, expected if isinstance(expected, str) else None, owner if isinstance(owner, str) else None, entry, evidence_root)
        basis = "IMMUTABLE_FIXTURE" if logical in fixtures else "PINNED_REBOUND" if patch is not None and patch.get("after_sha256") == digest else "ACCEPTED_MODIFIER"
        rows.append({"path": logical, "sha256": digest, "basis": basis, "owner_task": owner, "evidence_sha256": evidence_hash})
    if normative_map_path is not None:
        mapping = _load(normative_map_path)
        mapped = [*mapping.get("inherited_entries", []), *mapping.get("plan_entries", [])]
        if any(not isinstance(item, dict) for item in mapped) or not isinstance(mapping.get("vendor_prefix"), str):
            raise ValueError("E_MIGRATION_MAP")
        prefix = _relative(mapping["vendor_prefix"])
        for item in mapped:
            source_relative = _relative(item.get("plan_source"))
            if source_relative.parts[0] != "docs":
                raise ValueError("E_MIGRATION_MAP")
            logical = (prefix / _relative(item.get("vendor_relative"))).as_posix()
            source, target, entry = root / "pack" / source_relative, _target(root, logical), ownership.get(logical)
            if entry is None or not source.is_file() or not target.is_file() or source.read_bytes() != target.read_bytes():
                raise ValueError(f"E_MIGRATION_MAP:{logical}")
            digest = _sha256(target)
            owner, evidence_hash = _final_owner(logical, digest, _sha256(source), entry.get("creation_owner") if isinstance(entry.get("creation_owner"), str) else None, entry, evidence_root)
            existing = next((row for row in rows if row["path"] == logical), None)
            if existing is not None:
                if (
                    existing["sha256"] != digest
                    or existing["owner_task"] != owner
                    or existing["evidence_sha256"] != evidence_hash
                ):
                    raise ValueError(f"E_MIGRATION_OUTPUT_DUPLICATE:{logical}")
                continue
            rows.append({"path": logical, "sha256": digest, "basis": "MAPPED_CONFIG", "owner_task": owner, "evidence_sha256": evidence_hash})
    rows.extend(_native_lock_rows(root, policy, ownership, evidence_root))
    if len({row["path"] for row in rows}) != len(rows):
        raise ValueError("E_MIGRATION_OUTPUT_DUPLICATE")
    rows.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    receipt = _initial_receipt(root, registry_path)
    receipt.update({"schema_version": "final-migration-receipt/v1", "checked_outputs": rows, "authorized_production_phases": "NONE"})
    return _with_hash(receipt, FINAL_DOMAIN)


def verify_successor_migration(
    registry_path: Path, receipt_path: Path, *, stage: str = "initial",
    root: Path = Path.cwd(), ownership_path: Path | None = None,
    normative_map_path: Path | None = None, evidence_root: Path | None = None
) -> dict[str, object]:
    registry = _load(registry_path)
    ownership_path = ownership_path or registry_path.with_name("artifact-ownership.v1.json")
    evidence_root = evidence_root or root.parent / "authoring-evidence" / "hybrid-discovery-v6.3.6"
    ownership = _entry_index(ownership_path)
    policy = registry.get("final_legacy_policy")
    if not isinstance(policy, dict):
        raise ValueError("E_MIGRATION_POLICY")
    _require_initial_patches(registry, registry_path, root, ownership, evidence_root, final=stage == "final")
    _scan_legacy(root, policy)
    if stage == "initial":
        receipt = _with_hash(_initial_receipt(root, registry_path), INITIAL_DOMAIN)
    elif stage == "final":
        receipt = _final_receipt(registry, registry_path, root, ownership, evidence_root, normative_map_path)
    else:
        raise ValueError("E_MIGRATION_STAGE")
    _write_or_match(receipt_path, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--stage", choices=("initial", "final"), default="initial")
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--ownership", type=Path)
    parser.add_argument("--normative-map", type=Path)
    parser.add_argument("--task-evidence-root", type=Path)
    args = parser.parse_args()
    root = Path.cwd()
    if args.runtime is not None:
        runtime = args.runtime.resolve()
        if runtime.name != "runtime" or runtime.parent != root.resolve():
            raise ValueError("E_MIGRATION_RUNTIME")
    print(json.dumps(verify_successor_migration(args.registry, args.receipt, stage=args.stage, root=root, ownership_path=args.ownership, normative_map_path=args.normative_map, evidence_root=args.task_evidence_root), sort_keys=True))


if __name__ == "__main__":
    main()
