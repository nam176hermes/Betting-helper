import json
import os
from pathlib import Path

import pytest
from jsonschema import ValidationError  # type: ignore[import-untyped]

from moj_discovery.schema_registry import validate_artifact


def test_reused_schema_proof_binds_input_types_and_source_bytes(tmp_path: Path) -> None:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    schema = schemas / "probe.json"
    source = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:test:cache",
        "type": "object",
        "additionalProperties": False,
        "required": ["rows"],
        "properties": {"rows": {"type": "array", "items": {"const": "valid"}}},
    }
    schema.write_text(json.dumps(source))

    def check(value: object) -> None:
        validate_artifact(value, "probe.json", bootstrap_only=True, vendor=tmp_path)

    value = {"rows": ["valid"]}
    check(value)
    check(value)
    with pytest.raises(ValidationError):
        check({"rows": ("valid",)})
    value["rows"][0] = "wrong"
    with pytest.raises(ValidationError):
        check(value)
    info = schema.stat()
    schema.write_text(schema.read_text().replace("valid", "other"))
    os.utime(schema, ns=(info.st_atime_ns, info.st_mtime_ns))
    with pytest.raises(ValidationError):
        check({"rows": ["valid"]})


def test_discriminator_optimization_matches_full_schema_and_rejects_ambiguous_union(
    tmp_path: Path,
) -> None:
    from moj_discovery.schema_registry import _compiled, _selected_schema
    from moj_discovery.store import VENDOR
    from tests.offline.test_input_journal import prepared

    _, rows = prepared(tmp_path)
    schema = (VENDOR / "schemas/raw-observation.schema.json").read_bytes()
    resources = tuple(p.read_bytes() for p in sorted((VENDOR / "schemas").glob("*.json")))
    for kind in [
        "TERMINAL",
        "GAP",
        "CLOCK_SAMPLE",
        "LIFECYCLE",
        "APP_STATE",
        "NETWORK_METADATA",
        "DOM_VERIFICATION",
        "unknown",
    ]:
        for patch in [{}, {"unknown": "rejected"}, {"facts": {}}, {"context": {}}]:
            value = {**rows[0], "observation_kind": kind, **patch}
            full = _compiled(schema, resources).is_valid(value)
            selected = _compiled(_selected_schema(schema, kind), resources).is_valid(value)
            assert selected == full
    changed = json.loads(schema)
    changed["$defs"]["GapObservation"]["allOf"][1]["properties"]["observation_kind"]["const"] = (
        "TERMINAL"
    )
    ambiguous = json.dumps(changed).encode()
    assert _selected_schema(ambiguous, "TERMINAL") == ambiguous
