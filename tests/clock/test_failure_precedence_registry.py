import json
from pathlib import Path

from moj_discovery.clock_precedence import load_clock_failure_precedence
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)


def test_precedence_registry_is_total_unique_and_shared() -> None:
    result = load_clock_failure_precedence(
        json.loads((PLAN / "docs/registries/clock-failure-precedence.v1.json").read_text()),
        json.loads((PLAN / "docs/registries/clock-vector-coverage.v1.json").read_text()),
        json.loads((PLAN / "docs/vectors/inherited/clock-coherence-v6.2.json").read_text()),
    )
    assert result["negative_mapping_count"] == 16
    assert result["total_named_vectors"] == 65
    assert result["ordered_error_codes"][-1] == "ACCEPT"
