import json
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moj_discovery.governance import validate_schema_closure
from moj_discovery.vendor import pack_root

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)
VENDOR = ROOT / "vendor/hybrid-discovery-v6.3.6"


def _pointer_value(document: object, pointer: str) -> object:
    assert pointer.startswith("#/")
    value = document
    for part in pointer[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        assert isinstance(value, dict) and part in value
        value = value[part]
    return value


def _validate_registry(schema_name: str, definition: str, registry_name: str) -> None:
    schema = json.loads((PACK / "docs/schemas" / schema_name).read_text())
    registry = json.loads((PACK / "docs/registries" / registry_name).read_text())
    Draft202012Validator(schema["$defs"][definition]).validate(registry)


def test_all_schema_pointers_registries_and_vectors_resolve() -> None:
    references = json.loads(
        (PACK / "docs/registries/schema-reference-registry.v1.json").read_text()
    )["references"]
    for reference in references:
        source = PACK / reference["plan_source_path"].removeprefix("pack/")
        assert source.is_file()
        assert _pointer_value(json.loads(source.read_text()), reference["json_pointer"])

    for schema_path in (PACK / "docs/schemas").glob("*.json"):
        Draft202012Validator.check_schema(json.loads(schema_path.read_text()))
    validate_schema_closure(VENDOR)

    _validate_registry(
        "command-registry.schema.json",
        "CommandRegistry",
        "task-command-registry.v1.json",
    )
    _validate_registry(
        "proof-coverage.schema.json",
        "ProofCoverageMatrix",
        "proof-coverage-matrix.v1.json",
    )

    crash_registry = json.loads(
        (PACK / "docs/registries/crash-harness-registry.v1.json").read_text()
    )
    assert crash_registry["source_case_count"] == len(crash_registry["entries"]) == 46
    precedence = json.loads((PACK / "docs/registries/clock-failure-precedence.v1.json").read_text())
    assert precedence["negative_mapping_count"] == len(precedence["negative_vectors"]) == 16
