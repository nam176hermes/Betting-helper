"""Full repair orchestration must use every registered owner and mutation."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import replace
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
    entries = json.loads((PACK / "docs/registries/clock-vector-coverage.v1.json").read_text())[
        "entries"
    ]
    ids = [row["vector_id"] for row in entries]
    return {
        "result": "PASS",
        "required_vector_ids": ids,
        "records": [{"case_id": case_id, "status": "PASS"} for case_id in ids],
        "mutation_records": [
            {
                "case_id": name,
                "source_vector_id": ids[0],
                "detected": True,
                "executed": True,
                "verified": True,
            }
            for name in full.required_clock_mutation_ids()
        ],
    }


def test_full_runner_wires_every_owner_in_registry_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    damage: str,
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
            mutation_summary={"required": 105, "verified": 105, "survivors": 0, "complete": True},
        )
    with pytest.raises(ValueError, match="E_DURABILITY_MUTATION_EVIDENCE_REQUIRED"):
        validate_full_durability_release(
            required,
            required,
            mutation_survivors=0,
            evidence=[{"case_id": "one"}],
            mutation_summary={"required": 105, "verified": 105, "survivors": 0, "complete": True},
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
    modules = {name: hashlib.sha256((extension / name).read_bytes()).hexdigest() for name in names}
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


def test_full_repair_closed_inventory_replays_without_original_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import verify_full_repair_qualification as verifier
    from tools.full_verifier_config import QualificationEvidenceConfig, load_controller_config
    from tools.run_full_repair_qualification import _write_closed_inventory

    source_config = Path(
        "/home/thenam176/betting-helper/authoring-controller-config-worktree/pack/"
        "docs/configs/full-verifier-controller.v2.json"
    )
    original = load_controller_config(source_config)
    evidence = tmp_path / "evidence"
    aggregate = evidence / "aggregate.json"
    inventory = evidence / "inventory.json"
    aggregate.parent.mkdir()
    campaign = evidence / "campaign"
    campaign.mkdir()
    artifact = campaign / "actual.json"
    artifact.write_text('{"observed":1}')
    aggregate.write_text(
        json.dumps(
            {
                "result": "PASS",
                "artifact": {
                    "path": str(artifact),
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                },
            }
        )
    )
    qualification = QualificationEvidenceConfig(
        full_repair_aggregate=aggregate,
        full_repair_inventory=inventory,
        environment_qualification_aggregate=evidence / "environment.json",
        environment_qualification_inventory=evidence / "environment-inventory.json",
        p03_proof=evidence / "p03.json",
        p04_proof=evidence / "p04.json",
    )
    config = replace(original, qualification_evidence=qualification)
    manifest = _write_closed_inventory(aggregate, campaign, inventory, config)
    aggregate_copy = next(
        inventory.parent / "retained" / row["copied_relative_path"]
        for row in manifest["files"]
        if row["recorded_locator"] == str(aggregate)
    )
    shutil.rmtree(campaign)
    aggregate.unlink()
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        verifier,
        "_semantic_validation",
        lambda value, artifacts: (
            seen.append(value)
            if artifacts.read_bytes(str(artifact), recorded_boundary=str(campaign))
            == b'{"observed":1}'
            else pytest.fail("wrong retained bytes")
        ),
    )
    proof = verifier.verify_full_repair_qualification(aggregate_copy, inventory, config)
    assert proof["result"] == "PASS"
    assert seen == [json.loads(aggregate_copy.read_text())]

    original_manifest = inventory.read_bytes()
    changed_manifest = json.loads(original_manifest)
    extra = inventory.parent / "retained/files/extra.bin"
    extra.write_bytes(b"undeclared")
    changed_manifest["files"].append(
        {
            "recorded_locator": str(campaign / "undeclared.json"),
            "recorded_boundary": str(campaign),
            "copied_relative_path": "files/extra.bin",
            "size_bytes": len(b"undeclared"),
            "sha256": hashlib.sha256(b"undeclared").hexdigest(),
        }
    )
    inventory.write_text(json.dumps(changed_manifest, sort_keys=True))
    with pytest.raises(ValueError, match="E_FULL_REPAIR_QUALIFICATION"):
        verifier.verify_full_repair_qualification(aggregate_copy, inventory, config)
    inventory.write_bytes(original_manifest)
    extra.unlink()

    aggregate_copy.write_text('{"result":"PASS","forged":true}')
    with pytest.raises(ValueError, match="E_FULL_REPAIR_QUALIFICATION"):
        verifier.verify_full_repair_qualification(aggregate_copy, inventory, config)


def test_release_revalidation_preserves_retained_artifact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.run_indexeddb_crash_matrix as matrix
    import tools.verify_repair_evidence as repair
    from moj_discovery.durability_release import validate_full_durability_release

    required = repair.full_required_ids()
    evidence = [{"case_id": case_id} for case_id in required]
    sentinel = object()
    calls: list[object] = []

    def aggregate(_required: object, actual: object, *, artifacts: object = None) -> dict[str, str]:
        assert actual == evidence
        calls.append(artifacts)
        return {"legacy_full_qualification": "PASS"}

    def mutations(
        _pack: object,
        _owners: object,
        _clock: object,
        *,
        artifacts: object = None,
    ) -> dict[str, object]:
        calls.append(artifacts)
        return {"required": 105, "verified": 105, "survivors": 0, "complete": True}

    monkeypatch.setattr(repair, "aggregate_repair_evidence", aggregate)
    monkeypatch.setattr(matrix, "full_control_records", lambda *_args: evidence)
    monkeypatch.setattr(matrix, "validate_full_mutation_reports", mutations)
    result = validate_full_durability_release(
        required,
        required,
        mutation_survivors=0,
        evidence=evidence,
        mutation_evidence={"owner_reports": {}, "clock_report": {}},
        artifacts=sentinel,
    )
    assert result["result"] == "PASS"
    assert calls == [sentinel, sentinel]


def test_closed_inventory_comes_only_from_recursive_references(tmp_path: Path) -> None:
    from tools.run_full_repair_qualification import collect_retained_sources

    campaign = tmp_path / "campaign"
    campaign.mkdir()
    referenced = campaign / "observed.json"
    unreferenced = campaign / "unreferenced.txt"
    referenced.write_text("observed")
    unreferenced.write_text("not evidence")
    descriptor = {
        "path": str(referenced),
        "sha256": hashlib.sha256(referenced.read_bytes()).hexdigest(),
    }
    sources = collect_retained_sources(
        {"records": [{"artifact": descriptor}]},
        retained_boundaries=(campaign,),
        live_roots=(ROOT,),
    )
    assert sources == [(referenced, str(referenced), str(campaign))]


def test_closed_inventory_alias_reuse_is_consistent_and_conflicts_fail(
    tmp_path: Path,
) -> None:
    from tools.run_full_repair_qualification import collect_retained_sources

    campaign = tmp_path / "campaign"
    campaign.mkdir()
    artifact = campaign / "observed.json"
    artifact.write_text("observed")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    descriptor = {"path": str(artifact), "sha256": digest}
    sources = collect_retained_sources(
        {"first": descriptor, "second": dict(descriptor)},
        retained_boundaries=(campaign,),
        live_roots=(ROOT,),
    )
    assert sources == [(artifact, str(artifact), str(campaign))]
    with pytest.raises(ValueError, match="E_FULL_REPAIR_QUALIFICATION"):
        collect_retained_sources(
            {"first": descriptor, "second": {**descriptor, "sha256": "0" * 64}},
            retained_boundaries=(campaign,),
            live_roots=(ROOT,),
        )


def test_closed_inventory_excludes_verified_live_prerequisite(tmp_path: Path) -> None:
    from tools.run_full_repair_qualification import collect_retained_sources

    campaign = tmp_path / "campaign"
    campaign.mkdir()
    source = ROOT / "tools/run_full_repair_qualification.py"
    descriptor = {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    assert collect_retained_sources(
        {"entrypoint": descriptor}, retained_boundaries=(campaign,), live_roots=(ROOT,)
    ) == []

    executable_link = tmp_path / "python"
    executable_link.symlink_to(Path(sys.executable).resolve())
    executable = {
        "path": str(executable_link),
        "sha256": hashlib.sha256(executable_link.read_bytes()).hexdigest(),
    }
    assert collect_retained_sources(
        {"executable": executable},
        retained_boundaries=(campaign,),
        live_roots=(tmp_path,),
    ) == []


def test_inventory_writer_collapses_only_consistent_windows_posix_aliases(
    tmp_path: Path,
) -> None:
    from tools.run_full_repair_qualification import write_closed_inventory

    source = tmp_path / "source.json"
    source.write_text("same")
    inventory = tmp_path / "evidence/inventory.json"
    inventory.parent.mkdir()
    manifest = write_closed_inventory(
        [
            (
                source,
                r"C:\Users\thenam\Documents\run\same.json",
                r"C:\Users\thenam\Documents\run",
            ),
            (
                source,
                "/mnt/c/Users/thenam/Documents/run/same.json",
                "/mnt/c/Users/thenam/Documents/run",
            ),
        ],
        inventory,
    )
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["recorded_locator"] == (
        "/mnt/c/Users/thenam/Documents/run/same.json"
    )

    other = tmp_path / "other.json"
    other.write_text("different")
    conflicting = tmp_path / "conflicting/inventory.json"
    conflicting.parent.mkdir()
    with pytest.raises(ValueError, match="E_FULL_REPAIR_QUALIFICATION"):
        write_closed_inventory(
            [
                (
                    source,
                    r"C:\Users\thenam\Documents\run\same.json",
                    r"C:\Users\thenam\Documents\run",
                ),
                (
                    other,
                    "/mnt/c/Users/thenam/Documents/run/same.json",
                    "/mnt/c/Users/thenam/Documents/run",
                ),
            ],
            conflicting,
        )


@pytest.mark.parametrize("owner", ["BROWSER_LOOPBACK_ACK", "INDEXEDDB_SPOOL_ONLY"])
def test_browser_owner_module_graph_is_explicit_closed_inventory(
    tmp_path: Path, owner: str
) -> None:
    from tools.retained_artifact_io import RetainedArtifactIO
    from tools.run_full_repair_qualification import (
        collect_retained_sources,
        write_closed_inventory,
    )

    case = tmp_path / "original" / owner.lower()
    extension = case / "test-extension"
    (extension / "src").mkdir(parents=True)
    compiled = tmp_path / "compiled"
    subprocess.run(  # noqa: S603 -- content-bound local compiler and fixed argv.
        [
            str(evidence_gate._resolved_node_executable()),
            str(ROOT / "extension/node_modules/typescript/lib/tsc.js"),
            "-p",
            "tsconfig.test.json",
            "--outDir",
            str(compiled),
        ],
        cwd=ROOT / "extension",
        check=True,
        capture_output=True,
        timeout=120,
    )
    copies = {
        "indexeddb-crash-child.js": compiled / "test-harness/indexeddb-crash-child.js",
        "repair-probe.js": compiled / "test-harness/repair-probe.js",
        "src/errors.js": compiled / "src/errors.js",
        "src/spool.js": compiled / "src/spool.js",
    }
    for name, source in copies.items():
        target = extension / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    canonical = (compiled / "src/canonical.js").read_text().replace(
        'from "canonicalize"', 'from "./canonicalize.js"'
    )
    (extension / "src/canonical.js").write_text(canonical)
    shutil.copy2(
        ROOT / "extension/node_modules/canonicalize/lib/canonicalize.js",
        extension / "src/canonicalize.js",
    )
    names = {
        "indexeddb-crash-child.js",
        "repair-probe.js",
        "src/canonical.js",
        "src/canonicalize.js",
        "src/errors.js",
        "src/spool.js",
    }
    modules = {
        name: hashlib.sha256((extension / name).read_bytes()).hexdigest()
        for name in names
    }
    binding = {"before": modules, "after": modules}
    binding_path = case / "typescript-execution-binding.json"
    binding_path.write_text(json.dumps(binding, sort_keys=True, separators=(",", ":")))
    row = {
        "qualification_scope": owner,
        "case_directory": str(case),
        "identity": {"module_sha256": modules["src/spool.js"]},
        "module_hashes": modules,
        "typescript_execution_binding": binding,
        "typescript_execution_binding_artifact": {
            "path": str(binding_path),
            "sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        },
    }
    sources = collect_retained_sources(
        row, retained_boundaries=(case,), live_roots=(ROOT,)
    )
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    inventory_path = sealed / "inventory.json"
    manifest = write_closed_inventory(sources, inventory_path)
    artifacts = RetainedArtifactIO.from_manifest(manifest, sealed / "retained")
    expected_locators = {str(extension / name) for name in names} | {str(binding_path)}
    assert {item["recorded_locator"] for item in manifest["files"]} == expected_locators
    shutil.rmtree(tmp_path / "original")

    token = evidence_gate._RETAINED_ARTIFACTS.set(artifacts)
    try:
        evidence_gate._verify_retained_typescript_graph(
            row, evidence_gate.capture_binding(), "E_TEST_GRAPH"
        )
        module = artifacts.physical_path(
            str(extension / "src/spool.js"), recorded_boundary=str(case)
        )
        original = module.read_bytes()
        held = module.with_suffix(".held")
        module.rename(held)
        with pytest.raises(ValueError, match="E_TEST_GRAPH|E_RETAINED_ARTIFACT"):
            evidence_gate._verify_retained_typescript_graph(
                row, evidence_gate.capture_binding(), "E_TEST_GRAPH"
            )
        held.rename(module)
        module.write_bytes(original + b"\n// tampered")
        with pytest.raises(ValueError, match="E_TEST_GRAPH|E_RETAINED_ARTIFACT"):
            evidence_gate._verify_retained_typescript_graph(
                row, evidence_gate.capture_binding(), "E_TEST_GRAPH"
            )
        module.write_bytes(original)
    finally:
        evidence_gate._RETAINED_ARTIFACTS.reset(token)
