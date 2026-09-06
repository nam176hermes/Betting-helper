import json
import shutil
from hashlib import sha256
from pathlib import Path

import pytest
from referencing.exceptions import Unresolvable

from moj_discovery.governance import validate_canonical_registry, validate_schema_closure

ROOT = Path(__file__).parents[2]


def _copied_runtime(tmp_path: Path, name: str) -> tuple[Path, Path]:
    runtime = tmp_path / name
    vendor = runtime / "vendor/hybrid-discovery-v6.3.6"
    shutil.copytree(ROOT / "vendor/hybrid-discovery-v6.3.6", vendor)
    (runtime / "task-command-registry.json").parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "task-command-registry.json", runtime / "task-command-registry.json")
    return runtime, vendor


def _write_current_registry(runtime: Path, vendor: Path, value: dict[str, object]) -> None:
    content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    for path in (
        runtime / "task-command-registry.json",
        vendor / "docs/registries/task-command-registry.v1.json",
    ):
        path.write_bytes(content)


def test_normative_schemas_are_closed() -> None:
    validate_schema_closure()


def test_canonical_registry_is_partitioned_and_bound(tmp_path: Path) -> None:
    validate_canonical_registry()

    runtime, vendor = _copied_runtime(tmp_path, "wrong-current-shape")
    current = json.loads((runtime / "task-command-registry.json").read_text())
    current["verification_commands"] = current.pop("commands")
    _write_current_registry(runtime, vendor, current)
    with pytest.raises(AssertionError):
        validate_canonical_registry(vendor, runtime)

    runtime, vendor = _copied_runtime(tmp_path, "root-mismatch")
    registry_path = runtime / "task-command-registry.json"
    registry_path.write_bytes(registry_path.read_bytes() + b"\n")
    with pytest.raises(AssertionError):
        validate_canonical_registry(vendor, runtime)

    runtime, vendor = _copied_runtime(tmp_path, "missing-successor")
    current = json.loads((runtime / "task-command-registry.json").read_text())
    current["commands"] = [
        command
        for command in current["commands"]
        if command["command_id"] != "QUALIFY_INHERITED_BOOTSTRAP_PY"
    ]
    _write_current_registry(runtime, vendor, current)
    with pytest.raises(AssertionError):
        validate_canonical_registry(vendor, runtime)

    runtime, vendor = _copied_runtime(tmp_path, "bad-obligation")
    inherited_path = vendor / "docs/registries/inherited-baseline-qualification.v1.json"
    inherited = json.loads(inherited_path.read_text())
    inherited["inherited_command_obligations"][0]["role"] = "EXECUTION_ALIAS"
    inherited_path.write_text(json.dumps(inherited))
    with pytest.raises(AssertionError):
        validate_canonical_registry(vendor, runtime)

    runtime, vendor = _copied_runtime(tmp_path, "historical-hash")
    fixture = vendor / "docs/fixtures/inherited/v6.2/task-command-registry.json"
    fixture.write_bytes(fixture.read_bytes() + b"\n")
    with pytest.raises(AssertionError):
        validate_canonical_registry(vendor, runtime)

    runtime, vendor = _copied_runtime(tmp_path, "historical-id")
    fixture = vendor / "docs/fixtures/inherited/v6.2/task-command-registry.json"
    historical = json.loads(fixture.read_text())
    historical["verification_commands"] = [
        command
        for command in historical["verification_commands"]
        if command["command_id"] != "PRE-NODE-CANONICAL-VECTORS"
    ]
    fixture_bytes = json.dumps(historical, sort_keys=True, separators=(",", ":")).encode()
    fixture.write_bytes(fixture_bytes)
    inherited_path = vendor / "docs/registries/inherited-baseline-qualification.v1.json"
    inherited = json.loads(inherited_path.read_text())
    pinned = next(
        item
        for item in inherited["fixtures"]
        if item["runtime_vendor_relative"]
        == "docs/fixtures/inherited/v6.2/task-command-registry.json"
    )
    pinned["size"] = len(fixture_bytes)
    pinned["sha256"] = sha256(fixture_bytes).hexdigest()
    inherited_path.write_text(json.dumps(inherited))
    with pytest.raises(AssertionError):
        validate_canonical_registry(vendor, runtime)


def test_unpublished_schema_reference_is_rejected(tmp_path: Path) -> None:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "closed.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "urn:hybrid-discovery:v6.2:test-closed:v1",
                "type": "object",
                "properties": {"child": {"$ref": "urn:hybrid-discovery:v6.2:missing:v1"}},
                "additionalProperties": False,
            }
        )
    )
    with pytest.raises(Unresolvable):
        validate_schema_closure(tmp_path)
