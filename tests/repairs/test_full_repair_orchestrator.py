"""Full repair orchestration must use every registered owner and mutation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from moj_discovery.durability_release import validate_full_durability_release
from tools import run_indexeddb_crash_matrix as full
from tools import verify_repair_evidence as evidence_gate

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


def _clock_report() -> dict[str, Any]:
    entries = json.loads(
        (PACK / "docs/registries/clock-vector-coverage.v1.json").read_text()
    )["entries"]
    ids = [row["vector_id"] for row in entries]
    return {
        "result": "PASS",
        "required_vector_ids": ids,
        "records": [{"case_id": case_id, "status": "PASS"} for case_id in ids],
        "mutation_records": [
            {"case_id": name, "source_vector_id": ids[0], "detected": True,
             "executed": True, "verified": True}
            for name in full.required_clock_mutation_ids()
        ],
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
    def clock(*args: object, **kwargs: object) -> dict[str, Any]:
        calls.append("clock")
        return _clock_report()

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


@pytest.mark.parametrize(
    "damage", ["missing", "duplicate", "survivor", "unverified", "control-linkage", "control-bytes"]
)
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
    elif damage == "unverified":
        target[0]["verified"] = False
    elif damage == "control-bytes":
        target[0]["control"] = {**reports["SQLITE_TRANSACTION"]["records"][0], "substituted": True}
    else:
        target[0]["source_vector_id"] = "SQL-07-AFTER-COMMIT-BEFORE-ACK-SEND"

    def verify_owner(_: str, row: dict[str, Any], __: dict[str, Any]) -> None:
        if row.get("verified") is not True:
            raise ValueError("E_FULL_MUTATION_UNVERIFIED")

    monkeypatch.setattr(full, "_verify_owner_mutation", verify_owner)
    monkeypatch.setattr(full, "_verify_clock_mutation", lambda *args: None)
    clock_report = _clock_report()
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
    clock_report = _clock_report()
    with pytest.raises(ValueError, match="E_OWNER_MUTATION_BINDING"):
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


def test_mutation_campaign_cannot_omit_its_positive_controls(
    monkeypatch: pytest.MonkeyPatch,
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
    for report in reports.values():
        report["records"] = []
        report["executed_vector_ids"] = []
    clock_report = {
        "records": [],
        "required_vector_ids": [],
        "mutation_records": [
            {"case_id": name, "detected": True, "executed": True}
            for name in full.required_clock_mutation_ids()
        ],
    }
    monkeypatch.setattr(full, "_verify_owner_mutation", lambda *args: None)
    monkeypatch.setattr(full, "_verify_clock_mutation", lambda *args: None)
    with pytest.raises(ValueError, match="E_FULL_CONTROL"):
        full.validate_full_mutation_reports(PACK, reports, clock_report)


def test_release_rejects_mutation_campaign_with_different_control_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required = ["one"]
    evidence = [{"case_id": "one", "status": "PASS", "value": "governed"}]
    mutation_evidence: dict[str, Any] = {
        "owner_reports": {
            "only": {
                "records": [{"case_id": "one", "status": "PASS", "value": "different"}],
                "executed_vector_ids": ["one"],
            }
        },
        "clock_report": {"records": []},
    }
    monkeypatch.setattr("tools.verify_repair_evidence.full_required_ids", lambda: required)
    monkeypatch.setattr(
        "tools.verify_repair_evidence.aggregate_repair_evidence",
        lambda *_: {"legacy_full_qualification": "PASS"},
    )
    monkeypatch.setattr(
        full,
        "validate_full_mutation_reports",
        lambda *_: {"required": 105, "verified": 105, "survivors": 0, "complete": True},
    )
    monkeypatch.setattr(
        full,
        "full_control_records",
        lambda *_: mutation_evidence["owner_reports"]["only"]["records"],
    )
    with pytest.raises(ValueError, match="E_DURABILITY_MUTATION_CONTROL"):
        validate_full_durability_release(
            required,
            required,
            mutation_survivors=0,
            evidence=evidence,
            mutation_evidence=mutation_evidence,
        )


def test_arbitrary_rehashed_retained_browser_graph_is_rejected(tmp_path: Path) -> None:
    extension = tmp_path / "test-extension"
    (extension / "src").mkdir(parents=True)
    names = {
        "indexeddb-crash-child.js",
        "repair-probe.js",
        "src/canonical.js",
        "src/canonicalize.js",
        "src/errors.js",
        "src/spool.js",
    }
    for name in names:
        path = extension / name
        path.write_text(
            'import value from "./canonicalize.js";' if name == "src/canonical.js" else name
        )
    modules = {
        name: hashlib.sha256((extension / name).read_bytes()).hexdigest() for name in names
    }
    binding = {"before": modules, "after": modules}
    binding_path = tmp_path / "typescript-execution-binding.json"
    binding_path.write_text(json.dumps(binding, sort_keys=True, separators=(",", ":")))
    row = {
        "case_directory": str(tmp_path),
        "identity": {"module_sha256": modules["src/spool.js"]},
        "module_hashes": modules,
        "typescript_execution_binding": binding,
        "typescript_execution_binding_artifact": {
            "path": str(binding_path),
            "sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        },
    }
    with pytest.raises(ValueError, match="E_TEST_GRAPH"):
        evidence_gate._verify_retained_typescript_graph(
            row, evidence_gate.capture_binding(), "E_TEST_GRAPH"
        )


def test_typescript_compile_binding_covers_extended_config_and_compiler_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = evidence_gate.capture_binding()
    baseline = evidence_gate._typescript_compile_binding(current)
    original_sha = evidence_gate._sha

    def changed_base_config(path: Path) -> str:
        if path == evidence_gate.ROOT / "extension/tsconfig.json":
            return "1" * 64
        return original_sha(path)

    monkeypatch.setattr(evidence_gate, "_sha", changed_base_config)
    assert evidence_gate._typescript_compile_binding(current) != baseline

    monkeypatch.setattr(evidence_gate, "_sha", original_sha)

    def changed_compiler_payload(path: Path) -> str:
        if path == evidence_gate.ROOT / "extension/node_modules/typescript/lib/_tsc.js":
            return "2" * 64
        return original_sha(path)

    monkeypatch.setattr(evidence_gate, "_sha", changed_compiler_payload)
    assert evidence_gate._typescript_compile_binding(current) != baseline
