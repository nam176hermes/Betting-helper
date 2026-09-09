import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_offline_inventory_and_ci_are_explicit() -> None:
    registry = json.loads((ROOT / "registries/offline-cases.json").read_text())
    assert [row["case_id"] for row in registry["cases"]] == [f"OFF-{i:02d}" for i in range(1, 28)]
    workflow = json.loads((ROOT / ".github/workflows/offline-slice.yml").read_text())
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert set(workflow["jobs"]) == {"portable-unit", "browser-integration"}
    portable = str(workflow["jobs"]["portable-unit"])
    assert "tests/offline/test_protocol.py" in portable
    assert "tsconfig.test.json" in portable
    browser = str(workflow["jobs"]["browser-integration"])
    assert "workflow_dispatch" in browser and "--scenario acceptance" in browser
    assert "authoring-tests" in workflow["name"]
    ts = json.loads((ROOT / "extension/tsconfig.test.json").read_text())
    assert "src/**/*.ts" in ts["include"] and "test/**/*.ts" in ts["include"]
