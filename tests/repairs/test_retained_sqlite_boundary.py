from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from moj_discovery.vendor import pack_root
from tools.retained_artifact_io import RetainedArtifactIO
from tools.run_full_repair_qualification import collect_retained_sources, write_closed_inventory
from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix
from tools.verify_repair_evidence import (
    _RETAINED_ARTIFACTS,
    _sqlite_descriptor,
    _sqlite_file,
    aggregate_repair_evidence,
)

ROOT = Path(__file__).parents[2]


def test_live_sqlite_artifact_rejects_parent_traversal_and_links(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    valid = case / "valid.json"
    valid.write_text("{}")
    digest = hashlib.sha256(valid.read_bytes()).hexdigest()
    row = {"case_directory": str(case)}
    assert _sqlite_file(row, str(valid), digest, "E_TEST") == valid

    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    outside_digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="E_TEST"):
        _sqlite_file(row, str(case / "../outside.json"), outside_digest, "E_TEST")
    linked = case / "linked.json"
    os.symlink(outside, linked)
    with pytest.raises(ValueError, match="E_TEST"):
        _sqlite_file(row, str(linked), outside_digest, "E_TEST")
    parent = case / "linked-parent"
    os.symlink(tmp_path, parent)
    with pytest.raises(ValueError, match="E_TEST"):
        _sqlite_file(row, str(parent / "outside.json"), outside_digest, "E_TEST")


def test_sqlite_descriptor_replays_from_copy_without_original_root(tmp_path: Path) -> None:
    case = tmp_path / "original" / "case"
    case.mkdir(parents=True)
    original = case / "actual.json"
    original.write_text(json.dumps({"actual": 1}))
    data = original.read_bytes()
    closure = tmp_path / "closure"
    copied = closure / "files/actual.json"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(data)
    artifacts = RetainedArtifactIO.from_manifest(
        {
            "schema_version": "retained-artifact-manifest/v1",
            "recorded_boundaries": [str(case)],
            "files": [
                {
                    "recorded_locator": str(original),
                    "recorded_boundary": str(case),
                    "copied_relative_path": "files/actual.json",
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            ],
        },
        closure,
    )
    row = {"case_directory": str(case)}
    descriptor = {"path": str(original), "sha256": hashlib.sha256(data).hexdigest()}
    shutil.rmtree(tmp_path / "original")
    token = _RETAINED_ARTIFACTS.set(artifacts)
    try:
        assert _sqlite_descriptor(row, descriptor, "E_TEST") == {"actual": 1}
    finally:
        _RETAINED_ARTIFACTS.reset(token)


def test_real_release_revalidation_reads_sqlite_copy_without_original_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.run_indexeddb_crash_matrix as matrix
    import tools.verify_repair_evidence as repair
    from tools import verify_full_repair_qualification as verifier

    case = tmp_path / "original" / "case"
    case.mkdir(parents=True)
    original = case / "actual.json"
    original.write_text(json.dumps({"actual": 1}))
    data = original.read_bytes()
    closure = tmp_path / "closure"
    copied = closure / "files/actual.json"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(data)
    artifacts = RetainedArtifactIO.from_manifest(
        {
            "schema_version": "retained-artifact-manifest/v1",
            "recorded_boundaries": [str(case)],
            "files": [
                {
                    "recorded_locator": str(original),
                    "recorded_boundary": str(case),
                    "copied_relative_path": "files/actual.json",
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            ],
        },
        closure,
    )
    descriptor = {"path": str(original), "sha256": hashlib.sha256(data).hexdigest()}
    row = {"case_directory": str(case)}
    required = repair.full_required_ids()
    records = [{"case_id": case_id} for case_id in required]
    verified_mutations = {"required": 105, "verified": 105, "survivors": 0, "complete": True}

    def aggregate(
        _required: object, actual: object, *, artifacts: object = None
    ) -> dict[str, object]:
        assert actual == records
        token = repair._RETAINED_ARTIFACTS.set(artifacts)
        try:
            assert repair._sqlite_descriptor(row, descriptor, "E_TEST") == {"actual": 1}
        finally:
            repair._RETAINED_ARTIFACTS.reset(token)
        return {
            "result": "PASS",
            "legacy_full_qualification": "PASS",
            "status_counts": {"PASS": 111},
        }

    monkeypatch.setattr(repair, "aggregate_repair_evidence", aggregate)
    monkeypatch.setattr(matrix, "full_control_records", lambda *_args: records)
    monkeypatch.setattr(
        matrix,
        "validate_full_mutation_reports",
        lambda *_args, artifacts=None: verified_mutations,
    )
    shutil.rmtree(tmp_path / "original")
    verifier._semantic_validation(
        {
            "result": "PASS",
            "records": records,
            "owner_reports": {},
            "clock_report": {},
            "release_gate": {
                "result": "PASS",
                "declared_count": 111,
                "mutation_survivors": 0,
            },
        },
        artifacts,
    )


def test_real_sqlite_reader_replays_closed_copy_without_original_root(
    tmp_path: Path,
) -> None:
    pack = pack_root(ROOT)
    entry = next(
        row
        for row in json.loads(
            (pack / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if row["harness"] == "SQLITE_TRANSACTION"
    )
    workspace = tmp_path / "original"
    report = run_sqlite_crash_matrix(
        pack, workspace, entries=[entry], include_mutations=False
    )
    row = report["records"][0]
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    inventory_path = sealed / "inventory.json"
    sources = collect_retained_sources(
        row,
        retained_boundaries=(workspace,),
        live_roots=(ROOT,),
    )
    manifest = write_closed_inventory(sources, inventory_path)
    artifacts = RetainedArtifactIO.from_manifest(manifest, sealed / "retained")

    shutil.rmtree(workspace)
    result = aggregate_repair_evidence([row["case_id"]], [row], artifacts=artifacts)
    assert result["errors"] == []
    assert result["result"] == "PASS", result
