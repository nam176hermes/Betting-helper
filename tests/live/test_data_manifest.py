"""Availability comes from frozen SQLite; no model performance is an input."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from moj_discovery.data_manifest import freeze_dataset_manifest
from tests.live.test_live_replay import frozen_run


def view() -> Any:
    return {
        "selection_basis": "DATA_QUALITY_ONLY",
        "historical_data": "NOT_SUPPLIED",
        "chronological_partitions": [],
    }


def test_empty_dataset_does_not_claim_provenance_or_scope_acceptance() -> None:
    result = freeze_dataset_manifest([], view())
    assert result["has_source_provenance"] is False
    assert result["SCOPE0_READY_FOR_REVIEW"] is False
    assert result["MODEL_ENABLED"] is False and result["MONEY_READY"] == "NO"


def test_actual_synthetic_recording_retains_provenance_without_real_acceptance(
    tmp_path: Any,
    synthetic_book: Any,
    synthetic_provider_response: Any,
) -> None:
    run = frozen_run(tmp_path, synthetic_book, synthetic_provider_response)
    result = freeze_dataset_manifest([run], view())
    assert result["has_source_provenance"] is True
    assert result["SCOPE0_READY_FOR_REVIEW"] is False
    assert result["quality_view"]["runs"][0]["coverage"]["event_count"] == 3
    assert result["quality_view"]["runs"][0]["source_kind"] == "SYNTHETIC"
    assert result["data_rights"] == "REVIEW_REQUIRED"
    assert result["actual_targets"][0]["path"].endswith("live.sqlite3")
    assert result["actual_targets"][0]["sha256"]
    assert "roi" not in str(result["quality_view"]).lower()


@pytest.mark.parametrize("field", ["roi", "model_accuracy", "profit", "stake", "ev"])
def test_performance_and_money_fields_are_rejected(field: str) -> None:
    raw = view()
    raw[field] = 1
    with pytest.raises(ValueError):
        freeze_dataset_manifest([], raw)


def test_partitions_are_chronological_and_do_not_expose_performance() -> None:
    raw = view()
    raw["chronological_partitions"] = [
        {"name": "TRAIN", "start": "2026-01-01", "end": "2026-06-01"},
        {"name": "VALIDATION", "start": "2026-06-01", "end": "2026-07-01"},
        {"name": "TEST", "start": "2026-07-01", "end": "2026-08-01"},
    ]
    assert (
        freeze_dataset_manifest([], raw)["quality_view"]["chronological_partitions"]
        == raw["chronological_partitions"]
    )
    bad = copy.deepcopy(raw)
    bad["chronological_partitions"][1]["start"] = "2026-01-01"
    with pytest.raises(ValueError):
        freeze_dataset_manifest([], bad)
    bad = copy.deepcopy(raw)
    bad["chronological_partitions"][0]["roi"] = 3
    with pytest.raises(ValueError):
        freeze_dataset_manifest([], bad)


def test_rights_are_hash_bound_user_records_without_activating_empty_data(tmp_path: Any) -> None:
    raw = view()
    raw["data_rights_refs"] = []
    for source in ("API_FOOTBALL", "MISE_O_JEU"):
        path = tmp_path / (source + ".json")
        path.write_text(
            json.dumps(
                dict(
                    source=source,
                    status="ACCEPTED",
                    uses=["LOCAL_RECORDING", "RESEARCH"],
                    reviewer_role="USER_DATA_ACCESS_REVIEW",
                    reviewed_at_utc=datetime.now(UTC).isoformat(),
                )
            )
        )
        raw["data_rights_refs"].append(
            dict(
                source=source, path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()
            )
        )
    result = freeze_dataset_manifest([], raw)
    assert result["data_rights"] == "USER_REVIEW_RECORDED"
    assert result["SCOPE0_READY_FOR_REVIEW"] is False
    path.write_text("{}")
    with pytest.raises(ValueError):
        freeze_dataset_manifest([], raw)
