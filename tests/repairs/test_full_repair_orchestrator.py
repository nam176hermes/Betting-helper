"""Full repair orchestration must use every registered owner and mutation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from moj_discovery.durability_release import validate_full_durability_release
from tools import run_indexeddb_crash_matrix as full

ROOT = Path(__file__).parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"


def _registry() -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
            "entries"
        ],
    )


def _report(harness: str) -> dict[str, Any]:
    entries = [row for row in _registry() if row["harness"] == harness]
    records = [{"case_id": row["vector_id"], "status": "PASS"} for row in entries]
    mutations = [
        {
            "vector_id": mutation_id,
            "source_vector_id": row["vector_id"],
            "detected": True,
            "verified": True,
        }
        for row in entries
        for mutation_id in row["mutation_vector_ids"]
    ]
    return {
        "result": "PASS",
        "records": records,
        "executed_vector_ids": [row["case_id"] for row in records],
        "mutation_results": mutations,
    }


def test_full_runner_wires_every_owner_in_registry_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def owner(name: str, harness: str):  # type: ignore[no-untyped-def]
        def run(*args: object, **kwargs: object) -> dict[str, Any]:
            calls.append(name)
            return _report(harness)

        return run

    monkeypatch.setattr(
        "tools.run_sqlite_crash_matrix.run_sqlite_crash_matrix",
        owner("sql", "SQLITE_TRANSACTION"),
    )
    monkeypatch.setattr(full, "run_indexeddb_crash_matrix", owner("indexeddb", "CHROME_INDEXEDDB"))
    monkeypatch.setattr(
        "tools.run_loopback_ack_crash_matrix.run_loopback_ack_crash_matrix",
        owner("ack", "LOOPBACK_ACK"),
    )
    monkeypatch.setattr(
        "tools.run_gap_coherence_crash_matrix.run_gap_coherence_crash_matrix",
        owner("gap", "GAP_GENERATION_COHERENCE"),
    )
    monkeypatch.setattr(
        "tools.run_destruction_crash_matrix.run_destruction_crash_matrix",
        owner("destruction", "WHOLE_RUN_DESTRUCTION"),
    )
    clock_ids = json.loads(
        (PACK / "docs/registries/clock-vector-coverage.v1.json").read_text()
    )["entries"]

    def clock(*args: object, **kwargs: object) -> dict[str, Any]:
        calls.append("clock")
        return {
            "result": "PASS",
            "records": [{"case_id": row["vector_id"], "status": "PASS"} for row in clock_ids],
            "mutation_records": [
                {"case_id": name, "detected": True, "executed": True, "verified": True}
                for name in full.required_clock_mutation_ids()
            ],
        }

    monkeypatch.setattr(
        "tools.run_clock_vector_qualification.run_clock_vector_qualification", clock
    )
    monkeypatch.setattr(
        "tools.verify_repair_evidence.aggregate_repair_evidence",
        lambda required, records: {
            "result": "PASS",
            "legacy_full_qualification": "PASS",
            "qualification_scope": "FULL",
            "required_id_set_complete": [row["case_id"] for row in records] == required,
            "status_counts": {"PASS": len(records)},
            "errors": [],
        },
    )
    monkeypatch.setattr(full, "_verify_owner_mutation", lambda *args: None)
    monkeypatch.setattr(full, "_verify_clock_mutation", lambda *args: None)

    result = full.run_full_repair_evidence(PACK, ROOT, tmp_path / "full")

    assert calls == ["sql", "indexeddb", "ack", "gap", "destruction", "clock"]
    assert result["result"] == "PASS"
    assert len(result["records"]) == 111
    assert result["mutation_summary"] == {
        "required": 105,
        "verified": 105,
        "survivors": 0,
        "complete": True,
    }


@pytest.mark.parametrize("damage", ["missing", "duplicate", "survivor", "unverified"])
def test_registered_mutation_damage_fails_closed(
    damage: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports = {
        harness: _report(harness)
        for harness in {
            "SQLITE_TRANSACTION",
            "CHROME_INDEXEDDB",
            "LOOPBACK_ACK",
            "GAP_GENERATION_COHERENCE",
            "WHOLE_RUN_DESTRUCTION",
        }
    }
    target = reports["SQLITE_TRANSACTION"]["mutation_results"]
    if damage == "missing":
        target.pop()
    elif damage == "duplicate":
        target[-1] = dict(target[0])
    elif damage == "survivor":
        target[0]["detected"] = False
    else:
        target[0]["verified"] = False

    def verify_owner(_: str, row: dict[str, Any], __: dict[str, Any]) -> None:
        if row.get("verified") is not True:
            raise ValueError("E_FULL_MUTATION_UNVERIFIED")

    monkeypatch.setattr(full, "_verify_owner_mutation", verify_owner)
    monkeypatch.setattr(full, "_verify_clock_mutation", lambda *args: None)
    clock_report = {
        "mutation_records": [
            {"case_id": name, "detected": True, "executed": True}
            for name in full.required_clock_mutation_ids()
        ]
    }
    with pytest.raises(ValueError, match="E_FULL_MUTATION"):
        full.validate_full_mutation_reports(PACK, reports, clock_report)


def test_bare_verified_markers_are_not_recursive_evidence() -> None:
    reports = {
        harness: _report(harness)
        for harness in {
            "SQLITE_TRANSACTION",
            "CHROME_INDEXEDDB",
            "LOOPBACK_ACK",
            "GAP_GENERATION_COHERENCE",
            "WHOLE_RUN_DESTRUCTION",
        }
    }
    clock_report = {
        "mutation_records": [
            {"case_id": name, "detected": True, "executed": True, "verified": True}
            for name in full.required_clock_mutation_ids()
        ]
    }
    with pytest.raises(ValueError, match="E_FULL_MUTATION_OWNER_UNSUPPORTED"):
        full.validate_full_mutation_reports(PACK, reports, clock_report)


def test_release_requires_exact_full_ids_and_complete_mutation_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required = ["one", "two"]
    monkeypatch.setattr("tools.verify_repair_evidence.full_required_ids", lambda: required)
    monkeypatch.setattr(
        "tools.verify_repair_evidence.aggregate_repair_evidence",
        lambda *_: {"legacy_full_qualification": "PASS"},
    )
    with pytest.raises(ValueError, match="E_DURABILITY_EXECUTION_COVERAGE"):
        validate_full_durability_release(
            ["invented"],
            ["invented"],
            mutation_survivors=0,
            evidence=[{"case_id": "one"}],
            mutation_summary={"required": 105, "verified": 105, "survivors": 0,
                              "complete": True},
        )
    with pytest.raises(ValueError, match="E_DURABILITY_MUTATION_EVIDENCE_REQUIRED"):
        validate_full_durability_release(
            required,
            required,
            mutation_survivors=0,
            evidence=[{"case_id": "one"}],
            mutation_summary={"required": 105, "verified": 105, "survivors": 0,
                              "complete": True},
        )
