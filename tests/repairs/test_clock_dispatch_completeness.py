"""Every governed ID keeps a terminal row; missing primitives remain held."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import run_clock_vector_qualification as runner

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"


def test_exact_registry_dispatch_and_unimplemented_lifecycle(tmp_path: Path) -> None:
    registry = json.loads((PACK / "docs/registries/clock-vector-coverage.v1.json").read_text())
    ids = [entry["vector_id"] for entry in registry["entries"]]
    assert set(runner.DISPATCH) == set(ids)
    result = runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path)
    assert result["registry_version"] == registry["schema_version"]
    assert result["required_vector_ids"] == ids
    rows = result["records"]
    assert [row["case_id"] for row in rows] == ids
    assert len(rows) == len(set(ids))
    assert result["result"] == "HOLD"
    for row in rows:
        assert row["family"] in {
            "RAW_SAMPLE", "SERIALIZED_MAPPING_VALIDATION", "LIFECYCLE_AND_COHERENCE",
        }
        if row["case_id"].startswith(("CLOSE-", "RELEASE-", "SELECT-", "CANDIDATE-")):
            assert row["status"] == "NOT_IMPLEMENTED"
            assert row["executed"] is False
            assert row["observed_error"]


def test_unknown_id_or_missing_source_cannot_increment_coverage(tmp_path: Path) -> None:
    for relative in ("docs/registries/clock-vector-coverage.v1.json",
                     "docs/vectors/inherited/clock-coherence-v6.2.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PACK / relative).read_bytes())
    path = tmp_path / "docs/registries/clock-vector-coverage.v1.json"
    registry = json.loads(path.read_text())
    registry["entries"][0]["vector_id"] = "UNKNOWN"
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="E_CLOCK_COVERAGE"):
        runner.run_clock_vector_qualification(tmp_path, ROOT)
