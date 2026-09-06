import copy
import json
from pathlib import Path

from moj_discovery import clock_vectors as clock
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)
VECTORS = json.loads((PLAN / "docs/vectors/inherited/clock-coherence-v6.2.json").read_text())


def test_python_evaluator_recomputes_all_positive_and_negative_vectors() -> None:
    golden = clock.evaluate_clock_mapping_vector(
        VECTORS["golden_mapping"], VECTORS["guardrails"]
    )
    assert golden == {
        "accepted": True,
        "error": "ACCEPT",
        "raw_lower_us": 4800,
        "raw_upper_us": 5200,
        "network_rtt_us": 400,
        "padding_us": 30,
        "offset_interval_us": [4770, 5230],
        "offset_midpoint_us": 5000,
        "base_uncertainty_us": 230,
    }
    for negative in VECTORS["mapping_negative_vectors"]:
        candidate = copy.deepcopy(VECTORS["golden_mapping"])
        candidate.update(negative["mutation"])
        result = clock.evaluate_clock_mapping_vector(candidate, VECTORS["guardrails"])
        assert result["accepted"] is negative["mapping_eligible"]
        assert result["error"] == (negative.get("expected_error") or "SOURCE_AGE_UNKNOWN")


def test_frozen_clock_observation_hash_vectors() -> None:
    positive = VECTORS["canonical_hash_positive_vector"]
    assert clock.verify_clock_observation(
        positive["artifact_type"], positive["record"], vendor=PLAN
    ) == {
        "accepted": True,
        "error": "SCHEMA_VALID_AND_RECOMPUTED_HASH_MATCH",
        "schema_valid": True,
        "computed_hash": "2b63679a94fd4c6d217c3f23f811f77314e82b46baef7902a95e4146efbcee41",
    }
    missing_hash = copy.deepcopy(positive["record"])
    del missing_hash["content_hash"]
    assert clock.verify_clock_observation(
        positive["artifact_type"], missing_hash, vendor=PLAN
    ) == {
        "accepted": False,
        "error": "SCHEMA_INVALID_BEFORE_CANONICAL_HASH",
        "schema_valid": False,
        "computed_hash": None,
    }


def test_frozen_drift_vectors_use_ceiling_and_absolute_distance() -> None:
    for vector in VECTORS["drift_vectors"]:
        assert clock.compute_drift(
            vector["relative_drift_ppm"], vector["source_anchor_us"], vector["x"]
        ) == vector["expected_drift_us"]


def test_frozen_midpoint_vectors_match_overflow_safe_contract() -> None:
    for vector in VECTORS["midpoint_constraint_vectors"]:
        inputs = {key: value for key, value in vector.items() if key not in {"id", "expected"}}
        assert clock.validate_midpoint(inputs)["error"] == vector["expected"]
