from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from moj_discovery.durability_registry import validate_crash_harness_registry
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)


def _inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    return (
        json.loads((PLAN / "docs/registries/crash-harness-registry.v1.json").read_text()),
        json.loads((PLAN / "docs/registries/crash-child-command-registry.v1.json").read_text()),
        json.loads((PLAN / "docs/vectors/inherited/durability-crash-v6.2.json").read_text()),
    )


def test_every_normative_vector_has_one_process_execution_mapping() -> None:
    registry, children, vectors = _inputs()
    assert validate_crash_harness_registry(registry, children, vectors) == {
        "result": "PASS",
        "case_count": 46,
        "harness_count": 5,
    }
    changed = copy.deepcopy(registry)
    changed["entries"].pop()
    with pytest.raises(ValueError, match="E_CRASH_COVERAGE"):
        validate_crash_harness_registry(changed, children, vectors)
    changed = copy.deepcopy(registry)
    changed["entries"][0]["child_command_id"] = "UNKNOWN"
    with pytest.raises(ValueError, match="E_CRASH_CHILD"):
        validate_crash_harness_registry(changed, children, vectors)
