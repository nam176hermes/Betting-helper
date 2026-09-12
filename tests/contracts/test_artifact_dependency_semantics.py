from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from moj_discovery.artifact_ownership import validate_artifact_lifecycle
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)


def _inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    return (
        json.loads((PLAN / "docs/registries/artifact-ownership.v1.json").read_text()),
        json.loads((PLAN / "docs/tasks/task-manifest.v6.3.6.json").read_text()),
        json.loads((PLAN / "docs/schemas/artifact-ownership.schema.json").read_text()),
    )


def test_consumer_cannot_precede_creation_owner() -> None:
    registry, manifest, schema = _inputs()
    assert validate_artifact_lifecycle(registry, manifest, schema=schema) == {
        "result": "PASS",
        # Prior inventory (1236) plus eight declared scoped-review artifacts.
        "artifact_count": 1244,
    }
    changed = copy.deepcopy(registry)
    entry = next(row for row in changed["entries"] if row["creation_owner"] == "V636-P01-T02")
    entry["consumers"].append("V636-BOOT0-T02")
    with pytest.raises(ValueError, match="E_CONSUMER_BEFORE_OWNER"):
        validate_artifact_lifecycle(changed, manifest, schema=schema)


def test_lifecycle_rejects_unowned_unknown_and_future_modifier() -> None:
    registry, manifest, schema = _inputs()
    changed = copy.deepcopy(registry)
    entry = next(row for row in changed["entries"] if row["source"] is None)
    entry["creation_owner"] = None
    with pytest.raises(ValueError, match="E_OWNER_MISSING"):
        validate_artifact_lifecycle(changed, manifest, schema=schema)

    changed = copy.deepcopy(registry)
    changed["entries"][0]["modifying_tasks"] = ["UNKNOWN"]
    with pytest.raises(ValueError, match="E_MODIFIER_ORDER"):
        validate_artifact_lifecycle(changed, manifest, schema=schema)
