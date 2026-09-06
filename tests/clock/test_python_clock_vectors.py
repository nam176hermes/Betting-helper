import copy
import json
from pathlib import Path

from moj_discovery.clock_vectors import evaluate_clock_mapping_vector
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)
VECTORS = json.loads((PLAN / "docs/vectors/inherited/clock-coherence-v6.2.json").read_text())


def test_python_evaluator_recomputes_all_positive_and_negative_vectors() -> None:
    golden = evaluate_clock_mapping_vector(VECTORS["golden_mapping"], VECTORS["guardrails"])
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
        result = evaluate_clock_mapping_vector(candidate, VECTORS["guardrails"])
        assert result["accepted"] is negative["mapping_eligible"]
        assert result["error"] == (negative.get("expected_error") or "SOURCE_AGE_UNKNOWN")
