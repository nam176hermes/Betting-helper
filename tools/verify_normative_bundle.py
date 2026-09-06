import argparse
import hashlib
import sys
import unicodedata
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moj_discovery.canonical import parse_strict_json
from moj_discovery.vendor import verify_vendored_assets
from tools.sync_pack_assets import MANIFEST, _tree_files


def _relative(value: object, *, prefix: str = "") -> str:
    if not isinstance(value, str) or "\\" in value or not value.startswith(prefix):
        raise ValueError("E_NORMATIVE:PATH")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(
            part in {"", ".", ".."} or unicodedata.normalize("NFC", part) != part
            for part in path.parts
        )
    ):
        raise ValueError("E_NORMATIVE:PATH")
    return value


def _object(path: Path) -> dict[str, object]:
    value = parse_strict_json(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"E_NORMATIVE:OBJECT:{path}")
    return value


def _pointer(document: object, pointer: object) -> None:
    if not isinstance(pointer, str) or not pointer.startswith("#/"):
        raise ValueError("E_NORMATIVE:POINTER")
    value = document
    for part in pointer[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise ValueError("E_NORMATIVE:POINTER")
        value = value[part]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normative_entries(pack: Path, vendor: Path) -> dict[str, tuple[dict[str, object], bytes]]:
    source_map = _object(pack / "docs/registries/normative-source-map.v1.json")
    if (
        source_map.get("schema_version") != "normative-source-map/v1"
        or source_map.get("owner_phase") != "MIG0"
        or source_map.get("vendor_prefix") != "runtime/vendor/hybrid-discovery-v6.3.6/"
        or source_map.get("plan_namespace") != "docs/"
    ):
        raise ValueError("E_NORMATIVE:MAP")
    inherited = source_map.get("inherited_entries")
    plan_entries = source_map.get("plan_entries")
    overrides = source_map.get("graph_overrides")
    if (
        not isinstance(inherited, list)
        or not isinstance(plan_entries, list)
        or not isinstance(overrides, list)
    ):
        raise ValueError("E_NORMATIVE:MAP")
    override_paths = {_relative(item) for item in overrides}
    if override_paths != {
        "graphs/executable-discovery-graph.v1.json",
        "graphs/non-authoritative-future-roadmap.v1.json",
    }:
        raise ValueError("E_NORMATIVE:MAP")
    pack_files = {path.relative_to(pack).as_posix(): path for path in _tree_files(pack)}
    vendor_files = {path.relative_to(vendor).as_posix(): path for path in _tree_files(vendor)}
    effective: dict[str, tuple[dict[str, object], bytes]] = {}
    sources: set[str] = set()
    for raw in [*inherited, *plan_entries]:
        if not isinstance(raw, dict):
            raise ValueError("E_NORMATIVE:MAP")
        source = _relative(raw.get("plan_source"), prefix="docs/")
        destination = _relative(raw.get("vendor_relative"))
        if source in sources or source not in pack_files:
            raise ValueError("E_NORMATIVE:MAP")
        sources.add(source)
        source_bytes = pack_files[source].read_bytes()
        source_hash = raw.get("source_sha256")
        normalized_hash = raw.get("plan_sha256")
        expected = source_bytes
        expected_hash = normalized_hash if normalized_hash is not None else source_hash
        if expected_hash is not None and (
            not isinstance(expected_hash, str) or _sha256(expected) != expected_hash
        ):
            raise ValueError("E_NORMATIVE:SOURCE_HASH")
        if destination in effective and destination not in override_paths:
            raise ValueError("E_NORMATIVE:COLLISION")
        effective[destination] = (raw, expected)
    if set(vendor_files) != set(effective) | {MANIFEST}:
        raise ValueError("E_NORMATIVE:FILE_SET")
    for destination, (_, expected) in effective.items():
        if vendor_files[destination].read_bytes() != expected:
            raise ValueError(f"E_NORMATIVE:BYTES:{destination}")
    return effective


def _verify_schema_references(
    pack: Path,
    vendor: Path,
    entries: dict[str, tuple[dict[str, object], bytes]],
) -> None:
    registry = _object(pack / "docs/registries/schema-reference-registry.v1.json")
    references = registry.get("references")
    if (
        registry.get("schema_version") != "schema-reference-registry/v2"
        or not isinstance(references, list)
    ):
        raise ValueError("E_NORMATIVE:SCHEMA_REFERENCE")
    prefix = "runtime/vendor/hybrid-discovery-v6.3.6/"
    names: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("E_NORMATIVE:SCHEMA_REFERENCE")
        name = reference.get("logical_name")
        plan_path = _relative(
            reference.get("plan_source_path"), prefix="pack/docs/"
        ).removeprefix("pack/")
        runtime_path = _relative(
            reference.get("materialized_runtime_path"), prefix=prefix
        ).removeprefix(prefix)
        if (
            not isinstance(name, str)
            or name in names
            or plan_path != runtime_path
            or runtime_path not in entries
        ):
            raise ValueError("E_NORMATIVE:SCHEMA_REFERENCE")
        names.add(name)
        source = _object(pack / plan_path)
        materialized = _object(vendor / runtime_path)
        Draft202012Validator.check_schema(source)
        Draft202012Validator.check_schema(materialized)
        if (pack / plan_path).read_bytes() != (vendor / runtime_path).read_bytes():
            raise ValueError("E_NORMATIVE:SCHEMA_BYTES")
        _pointer(source, reference.get("json_pointer"))


def _verify_cdp_lock(pack: Path, vendor: Path) -> None:
    lock = _object(pack / "docs/inherited/v6.2/security/cdp-protocol-lock.v1.json")
    files = lock.get("files")
    if not isinstance(files, list):
        raise ValueError("E_NORMATIVE:CDP")
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("E_NORMATIVE:CDP")
        relative = _relative(item.get("path"))
        path = vendor / "cdp" / relative
        if (
            not path.is_file()
            or path.stat().st_size != item.get("size_bytes")
            or _sha256(path.read_bytes()) != item.get("sha256")
        ):
            raise ValueError(f"E_NORMATIVE:CDP:{relative}")


def _verify_task_manifest(pack: Path) -> None:
    plan = _object(pack / "plan-manifest.json")
    schema = _object(pack / "docs/schemas/task-card-v6.3.6.schema.json")
    tasks = _object(pack / "docs/tasks/task-manifest.v6.3.6.json")
    error = next(
        Draft202012Validator(schema)
        .evolve(schema={"$ref": "#/$defs/TaskManifestV636"})
        .iter_errors(tasks),
        None,
    )
    task_rows = tasks.get("tasks")
    if error is not None or (
        plan.get("schema_version") != "hybrid-discovery-v6.3.6-plan/v1"
        or plan.get("authorized_production_phases") != "NONE"
        or plan.get("task_manifest") != "docs/tasks/task-manifest.v6.3.6.json"
        or plan.get("task_schema")
        != "pack/docs/schemas/task-card-v6.3.6.schema.json#/$defs/TaskManifestV636"
        or plan.get("task_count") != tasks.get("declared_task_count")
        or not isinstance(task_rows, list)
        or plan.get("task_count") != len(task_rows)
    ):
        raise ValueError("E_NORMATIVE:PLAN:BINDING")


def verify_normative_bundle(pack: Path, runtime: Path) -> None:
    pack = pack.resolve()
    runtime = runtime.resolve()
    vendor = runtime / "vendor/hybrid-discovery-v6.3.6"
    entries = _normative_entries(pack, vendor)
    verify_vendored_assets(runtime)
    _verify_schema_references(pack, vendor, entries)
    _verify_cdp_lock(pack, vendor)
    _verify_task_manifest(pack)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    verify_normative_bundle(args.pack, args.runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
