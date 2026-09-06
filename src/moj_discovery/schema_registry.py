import json
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing import Registry, Resource

from .errors import ContractNotImplementedError
from .schema_formats import STRICT_FORMAT_CHECKER


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
    schema = json.loads(schema_path.read_text())
    resources: list[tuple[str, Resource[dict[str, object]]]] = []
    for path in sorted((vendor / "schemas").glob("*.json")):
        resource = json.loads(path.read_text())
        assert isinstance(resource, dict)
        resource_id = resource.get("$id")
        assert isinstance(resource_id, str)
        resources.append((resource_id, Resource.from_contents(resource)))
    registry: Registry[dict[str, object]] = Registry().with_resources(resources)
    Draft202012Validator(
        schema,
        registry=registry,
        format_checker=STRICT_FORMAT_CHECKER,
    ).validate(artifact)
