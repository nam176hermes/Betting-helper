import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from jsonschema import ValidationError  # type: ignore[import-untyped]

from moj_discovery.governance import _published_schema_registry, _record_validates
from moj_discovery.schema_registry import validate_artifact

VENDOR = Path("vendor/hybrid-discovery-v6.3.6").resolve()


def _authorization_record() -> dict[str, object]:
    vectors = json.loads((VENDOR / "vectors/authorization-v1.json").read_text())
    return cast(dict[str, object], vectors["base_record"])


def _durability_record() -> dict[str, object]:
    vectors = json.loads((VENDOR / "vectors/durability-crash-v1.json").read_text())
    return cast(dict[str, object], vectors["canonical_hash_positive_vector"]["record"])


def _invalid_date_time(record: dict[str, object]) -> None:
    record["issued_at"] = "2030-99-99T00:00:00Z"


def _invalid_uri(record: dict[str, object]) -> None:
    browser_binding = record["browser_binding"]
    assert isinstance(browser_binding, dict)
    browser_binding["origin"] = "https://%"


def _invalid_uuid(record: dict[str, object]) -> None:
    position = record["position"]
    assert isinstance(position, dict)
    generation_key = position["generation_key"]
    assert isinstance(generation_key, dict)
    stream = generation_key["stream"]
    assert isinstance(stream, dict)
    stream["browser_run_id"] = "not-a-uuid"


FORMAT_CASES = [
    ("authorization-records.schema.json", _authorization_record, _invalid_date_time),
    ("authorization-records.schema.json", _authorization_record, _invalid_uri),
    ("durability-records.schema.json", _durability_record, _invalid_uuid),
]


@pytest.mark.parametrize(("schema_name", "record_factory", "mutate"), FORMAT_CASES)
def test_bootstrap_schema_validation_enforces_formats(
    schema_name: str,
    record_factory: Callable[[], dict[str, object]],
    mutate: Callable[[dict[str, object]], None],
) -> None:
    record = copy.deepcopy(record_factory())
    validate_artifact(record, schema_name, bootstrap_only=True, vendor=VENDOR)
    mutate(record)

    with pytest.raises(ValidationError):
        validate_artifact(record, schema_name, bootstrap_only=True, vendor=VENDOR)


@pytest.mark.parametrize(("schema_name", "record_factory", "mutate"), FORMAT_CASES)
def test_governance_schema_validation_enforces_formats(
    schema_name: str,
    record_factory: Callable[[], dict[str, object]],
    mutate: Callable[[dict[str, object]], None],
) -> None:
    record = copy.deepcopy(record_factory())
    mutate(record)
    schema = json.loads((VENDOR / "schemas" / schema_name).read_text())
    schema_ref = schema["$id"]
    case = {"record_schema_ref": schema_ref, "record": record}

    assert not _record_validates(case, _published_schema_registry(VENDOR))
