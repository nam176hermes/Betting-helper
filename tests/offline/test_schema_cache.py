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
