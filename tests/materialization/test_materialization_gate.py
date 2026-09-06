import hashlib
import json
from pathlib import Path

import pytest

from moj_discovery.materialization_gate import validate_materialization_complete
from moj_discovery.vendor import plan_root, verify_vendored_assets

ROOT = Path(__file__).parents[2]


def _write_fixture(tmp_path: Path, owner: object = "V636-P01-T02") -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "declared.py").write_text("pass\n", encoding="utf-8")
    plan = tmp_path / "plan-input"
    (plan / "docs/registries").mkdir(parents=True)
    (plan / "docs/schemas").mkdir(parents=True)
    (plan / "docs/tasks").mkdir(parents=True)
    tasks = {
        "tasks": [
            {"task_id": "V636-BOOT0-T02"},
            {"task_id": "V636-P01-T02"},
            {"task_id": "V636-P01-T06"},
            {"task_id": "V636-P02-T01"},
        ]
    }
    (plan / "docs/tasks/task-manifest.v6.3.6.json").write_text(json.dumps(tasks))
    (plan / "docs/schemas/artifact-ownership.schema.json").write_text(
        json.dumps({"$defs": {"ArtifactOwnershipRegistry": {"type": "object"}}})
    )
    entry = {
        "path": "runtime/declared.py",
        "classification": "TASK_OUTPUT",
        "creation_owner": owner,
        "modifying_tasks": [],
        "materialization_required": True,
        "source": None,
        "qualification_owner": None,
        "consumers": [owner]
        if isinstance(owner, str) and owner.endswith("P02-T01")
        else ["V636-P01-T06"],
    }
    (plan / "docs/registries/artifact-ownership.v1.json").write_text(
        json.dumps({"schema_version": "artifact-ownership/v2", "entries": [entry]})
    )
    entries = [
        {
            "path": path.relative_to(plan).as_posix(),
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(plan.rglob("*"))
        if path.is_file()
    ]
    manifest = {"schema_version": "manifest-sha256/v1", "entries": entries}
    (plan / "MANIFEST_SHA256.json").write_text(json.dumps(manifest))
    (tmp_path / ".bootstrap").mkdir()
    (tmp_path / ".bootstrap/authoring-workspace-receipt.json").write_text(
        json.dumps(
            {
                "authoring_root": str(tmp_path),
                "plan_input_root": str(plan),
                "manifest_sha256": hashlib.sha256(
                    (plan / "MANIFEST_SHA256.json").read_bytes()
                ).hexdigest(),
            }
        )
    )
    return runtime


def test_materialization_gate_records_exact_artifact_root() -> None:
    if plan_root(ROOT) == ROOT / "vendor/hybrid-discovery-v6.3.6":
        assert verify_vendored_assets(ROOT)
        return
    receipt = validate_materialization_complete(ROOT)
    assert receipt["gate"] == "MATERIALIZATION_COMPLETE"
    assert receipt["result"] == "PASS"
    assert receipt["artifact_root"] == str(ROOT)
    assert receipt["authoring_root"] == str(ROOT.parent)
    assert receipt["materialized_artifact_count"] == 713
    assert receipt["deferred_artifact_count"] == 204
    assert receipt["authorized_production_phases"] == "NONE"


def test_materialization_gate_rejects_missing_or_unowned_artifact(
    tmp_path: Path,
) -> None:
    runtime = _write_fixture(tmp_path)
    (runtime / "declared.py").unlink()
    with pytest.raises(ValueError, match="MISSING:runtime/declared.py"):
        validate_materialization_complete(runtime)

    runtime = _write_fixture(tmp_path / "unowned", None)
    with pytest.raises(ValueError, match="UNOWNED:runtime/declared.py"):
        validate_materialization_complete(runtime)

    runtime = _write_fixture(tmp_path / "future", "V636-P02-T01")
    with pytest.raises(ValueError, match="FUTURE_OWNER:runtime/declared.py"):
        validate_materialization_complete(runtime)


def test_materialization_gate_rejects_bootstrap_binding_tamper(tmp_path: Path) -> None:
    runtime = _write_fixture(tmp_path)
    receipt = tmp_path / ".bootstrap/authoring-workspace-receipt.json"
    value = json.loads(receipt.read_text())
    value["authoring_root"] = "/wrong"
    receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="BOOTSTRAP"):
        validate_materialization_complete(runtime)
