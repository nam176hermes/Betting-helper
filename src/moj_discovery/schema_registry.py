import json
import math
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing import Registry, Resource

from .errors import ContractNotImplementedError
from .schema_formats import STRICT_FORMAT_CHECKER


@lru_cache(maxsize=8)
def _compiled(schema_bytes: bytes, resources_bytes: tuple[bytes, ...]) -> Draft202012Validator:
    resources = []
    for data in resources_bytes:
        resource = json.loads(data)
        assert isinstance(resource, dict) and isinstance(resource.get("$id"), str)
        resources.append((resource["$id"], Resource.from_contents(resource)))
    registry = Registry().with_resources(resources)
    return Draft202012Validator(
        json.loads(schema_bytes), registry=registry, format_checker=STRICT_FORMAT_CHECKER
    )


def _plain_json(value: object) -> bool:
    if type(value) in (str, int, bool) or value is None:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_plain_json(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _plain_json(item) for key, item in value.items())
    return False


@lru_cache(maxsize=16)
def _selected_schema(schema: bytes, kind: str) -> bytes:
    """Prune only branches proven impossible by distinct mandatory const constraints."""
    root = json.loads(schema)
    if (
        not isinstance(root, dict)
        or root.get("$id") != "urn:hybrid-discovery:v6.2:raw-observation:v1"
    ):
        return schema
    selected: dict[str, object] = {}
    try:
        for branch in root["oneOf"]:
            if set(branch) != {"$ref"} or not branch["$ref"].startswith("#/$defs/"):
                return schema
            definition = root["$defs"][branch["$ref"][len("#/$defs/") :]]
            constants = [
                clause["properties"]["observation_kind"]["const"]
                for clause in definition["allOf"]
                if isinstance(clause, dict)
                and isinstance(clause.get("properties"), dict)
                and isinstance(clause["properties"].get("observation_kind"), dict)
                and "const" in clause["properties"]["observation_kind"]
            ]
            if len(constants) != 1 or not isinstance(constants[0], str) or constants[0] in selected:
                return schema
            selected[constants[0]] = branch
    except (KeyError, TypeError):
        return schema
    if kind not in selected:
        return schema
    return json.dumps({**root, "oneOf": [selected[kind]]}).encode()


@lru_cache(maxsize=32)
def _validated_json(data: str, schema: bytes, resources: tuple[bytes, ...]) -> None:
    # Only successful proofs of complete immutable JSON and schema bytes are reusable.
    value = json.loads(data)
    if isinstance(value, dict) and isinstance(value.get("observation_kind"), str):
        schema = _selected_schema(schema, value["observation_kind"])
    _compiled(schema, resources).validate(value)


def validate_artifact(
    artifact: object,
    schema_name: str | None = None,
    *,
    bootstrap_only: bool = False,
    vendor: Path = Path("vendor/hybrid-discovery-v6.3.6"),
) -> None:
    if not bootstrap_only:
        raise ContractNotImplementedError("F0A-T02")
    if schema_name is None:
        raise ValueError("E_SCHEMA:NAME")
    schema_path = (vendor / "schemas" / schema_name).resolve()
    # Every call rereads complete schema bytes; edits invalidate the compiled proof.
    schema = schema_path.read_bytes()
    resources = tuple(path.read_bytes() for path in sorted((vendor / "schemas").glob("*.json")))
    if _plain_json(artifact):
        data = json.dumps(artifact, allow_nan=False)
        if len(data) <= 65536:
            _validated_json(data, schema, resources)
            return
    _compiled(schema, resources).validate(artifact)
