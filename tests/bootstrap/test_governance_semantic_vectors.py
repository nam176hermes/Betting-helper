import copy
import json
import shutil
from pathlib import Path

import pytest

from moj_discovery.governance import validate_semantic_vector_file
from moj_discovery.semantic_vectors import semantic_vector_error

VENDOR = Path("vendor/hybrid-discovery-v6.3.6")


def _copy_semantic_vendor(tmp_path: Path, vector_name: str) -> Path:
    vendor = tmp_path / "vendor"
    shutil.copytree(VENDOR / "schemas", vendor / "schemas")
    shutil.copytree(VENDOR / "registries", vendor / "registries")
    (vendor / "vectors").mkdir()
    source = json.loads((VENDOR / "vectors" / vector_name).read_text())
    (vendor / "vectors" / vector_name).write_text(json.dumps(source))
    return vendor


def _vendor_with_mutated_error(tmp_path: Path, vector_name: str, case_id: str) -> Path:
    vendor = _copy_semantic_vendor(tmp_path, vector_name)
    candidate = json.loads((vendor / "vectors" / vector_name).read_text())
    case = next(item for item in candidate["counterexamples"] if item["case_id"] == case_id)
    case["expected_error"] = "E_FAKE"
    (vendor / "vectors" / vector_name).write_text(json.dumps(candidate))
    return vendor


@pytest.mark.parametrize(
    ("vector_name", "case_id"),
    [
        ("scope-semantic-v1.json", "SCOPE-REJECT-COMPETITION-MISMATCH"),
        ("scope-semantic-v1.json", "SCOPE-REJECT-H1-HALFTIME"),
        ("review-semantic-v1.json", "REVIEW-REJECT-DUPLICATE-FINDING-ID"),
        ("review-semantic-v1.json", "CAPABILITY-REJECT-SUPPORTED-NO-EVIDENCE"),
    ],
)
def test_declared_semantic_error_drift_is_rejected(
    tmp_path: Path, vector_name: str, case_id: str
) -> None:
    vendor = _vendor_with_mutated_error(tmp_path, vector_name, case_id)

    with pytest.raises(AssertionError):
        validate_semantic_vector_file(vector_name, vendor)


@pytest.mark.parametrize(
    ("vector_name", "registry_name", "mutation"),
    [
        (
            "scope-semantic-v1.json",
            "scope0-input-policy.v1.json",
            ("wildcard_pointers_permitted", True),
        ),
        (
            "review-semantic-v1.json",
            "required-discovery-decisions.v1.json",
            ("decision_count", 17),
        ),
        (
            "review-semantic-v1.json",
            "discovery-capability-consumers.v1.json",
            ("production_authority", "PAPER"),
        ),
    ],
)
def test_exact_semantic_registry_drift_is_rejected(
    tmp_path: Path,
    vector_name: str,
    registry_name: str,
    mutation: tuple[str, object],
) -> None:
    vendor = _copy_semantic_vendor(tmp_path, vector_name)
    path = vendor / "registries" / registry_name
    registry = json.loads(path.read_text())
    registry[mutation[0]] = mutation[1]
    path.write_text(json.dumps(registry))

    with pytest.raises(AssertionError):
        validate_semantic_vector_file(vector_name, vendor)


def _scope_fixture() -> tuple[dict[str, object], dict[str, object]]:
    data = json.loads((VENDOR / "vectors/scope-semantic-v1.json").read_text())
    base = next(item for item in data["valid_records"] if item["case_id"] == "SCOPE-VALID-FROZEN")
    policy = json.loads((VENDOR / "registries/scope0-input-policy.v1.json").read_text())
    return base, policy


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("scope_input_view_binding", "0" * 64, "E_SCOPE_EVIDENCE_HASH"),
        ("performance_input_denial", ["RESULT_DATA"], "E_SCOPE_PERFORMANCE_DENIAL"),
        ("contamination_lineage", "1", "E_SCOPE_CONTAMINATION"),
    ],
)
def test_additional_scope_predicates_are_executable(
    field: str, value: object, expected_error: str
) -> None:
    base, policy = _scope_fixture()
    candidate = copy.deepcopy(base)
    record = candidate["record"]
    assert isinstance(record, dict)
    nested = record[field]
    assert isinstance(nested, dict)
    if field == "scope_input_view_binding":
        nested["content_hash"] = value
    elif field == "performance_input_denial":
        nested["denied_category_codes"] = value
    else:
        nested["test_access_events"] = value

    assert (
        semantic_vector_error("scope-semantic-v1.json", base, candidate, scope_policy=policy)
        == expected_error
    )


@pytest.mark.parametrize("mutation", ["reverse_h1", "reverse_live_intervals"])
def test_scope_evaluation_bands_require_canonical_chronology(mutation: str) -> None:
    base, policy = _scope_fixture()
    candidate = copy.deepcopy(base)
    record = candidate["record"]
    assert isinstance(record, dict)
    evaluation_bands = record["evaluation_bands"]
    assert isinstance(evaluation_bands, dict)
    h1 = evaluation_bands["H1"]
    assert isinstance(h1, list)
    if mutation == "reverse_h1":
        h1.reverse()
    else:
        h1[:] = [
            {
                "band_id": "band:h1-late",
                "fixture_phase": "FIRST_HALF",
                "start_minute": "30",
                "end_minute": "45",
                "admission_code": "ADMITTED_FIRST_HALF",
            },
            {
                "band_id": "band:h1-early",
                "fixture_phase": "FIRST_HALF",
                "start_minute": "0",
                "end_minute": "30",
                "admission_code": "ADMITTED_FIRST_HALF",
            },
        ]

    assert (
        semantic_vector_error("scope-semantic-v1.json", base, candidate, scope_policy=policy)
        == "E_SCOPE_BAND_ORDER"
    )
