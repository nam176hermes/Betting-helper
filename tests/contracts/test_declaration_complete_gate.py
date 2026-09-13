from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from moj_discovery.declaration_gate import issue_declaration_complete_receipt
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)


def test_materialized_contracts_valid_gate_passes() -> None:
    receipt = issue_declaration_complete_receipt(PLAN)
    assert receipt["gate"] == "MATERIALIZED_CONTRACTS_VALID"
    assert receipt["result"] == "PASS"
    assert receipt["task_count"] == 62
    # Scoped-review inventory plus the declared namespace-projection test.
    assert receipt["artifact_count"] == 1245
    assert receipt["command_count"] == 222
    assert receipt["schema_reference_count"] == 13
    assert receipt["authorized_production_phases"] == "NONE"


def test_declaration_gate_fails_on_unowned_schema_or_command(tmp_path: Path) -> None:
    plan = tmp_path / "plan-input"
    shutil.copytree(PLAN, plan)
    ownership_path = plan / "docs/registries/artifact-ownership.v1.json"
    ownership = json.loads(ownership_path.read_text())
    ownership["entries"] = [
        entry
        for entry in ownership["entries"]
        if entry["path"] != "runtime/src/moj_discovery/task_contracts.py"
    ]
    ownership_path.write_text(json.dumps(ownership))
    with pytest.raises(ValueError, match="E_UNOWNED"):
        issue_declaration_complete_receipt(plan)

    clean_plan = tmp_path / "clean-plan-input"
    shutil.copytree(PLAN, clean_plan)
    references = clean_plan / "docs/registries/schema-reference-registry.v1.json"
    value = json.loads(references.read_text())
    value["references"][0]["json_pointer"] = "#/$defs/Missing"
    references.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="E_SCHEMA_POINTER"):
        issue_declaration_complete_receipt(clean_plan)
