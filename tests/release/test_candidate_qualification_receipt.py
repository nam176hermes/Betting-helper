import hashlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from tools import build_candidate_qualification_receipt as receipt_builder
from tools import run_command_registry
from tools.build_candidate_qualification_receipt import build_candidate_qualification_receipt
from tools.full_verifier_config import load_controller_config
from tools.retained_artifact_io import RetainedArtifactIO
from tools.run_full_repair_qualification import write_closed_inventory

CONFIG = Path("vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json")


def test_part_b_compiler_input_binding_and_exact_output_inventory() -> None:
    root = Path.cwd()
    ownership = json.loads((root / (
        "vendor/hybrid-discovery-v6.3.6/docs/registries/artifact-ownership.v1.json"
    )).read_text())["entries"]
    sources = [row for row in ownership if row["classification"] == "EXTERNAL_INPUT"
               and row["source"]["binding"].startswith("PART_B_SOURCE_COMMIT:")]
    assert len(sources) == 23
    for row in sources:
        path = root / row["path"].removeprefix("runtime/")
        assert row["source"]["path"] == str(path)
        assert row["source"]["binding"].endswith(
            ":sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        )
    assert run_command_registry.collect_generated_outputs(root)


def test_historical_three_argument_api_is_strict_and_cannot_downgrade_current_source(
    tmp_path: Path,
) -> None:
    # Synthetic historical API fixture only: no commands or BOOT0 are executed.
    source = tmp_path / "historical"
    source.mkdir()
    git = shutil.which("git")
    assert git is not None
    raw = subprocess.check_output(  # noqa: S603 -- read-only audited registry fixture.
        [git, "show", "7cd7ab14652458608386d940bdc7764910044f6a:task-command-registry.json"]
    )
    registry_path = source / "task-command-registry.json"
    registry_path.write_bytes(raw)
    vendored = source / (
        "vendor/hybrid-discovery-v6.3.6/docs/registries/task-command-registry.v1.json"
    )
    vendored.parent.mkdir(parents=True)
    vendored.write_bytes(raw)
    registry = run_command_registry.validate_registry(registry_path)
    rows = [
        {**{key: command[key] for key in ("command_id", "argv", "cwd", "expected_exit")},
         "exit_code": command["expected_exit"], "passed": True,
         "stdout_sha256": hashlib.sha256(b"").hexdigest(), "stdout_size_bytes": "0",
         "stderr_sha256": hashlib.sha256(b"").hexdigest(), "stderr_size_bytes": "0"}
        for command in run_command_registry.candidate_commands(registry)
    ]
    evidence: dict[str, Any] = {"schema_version": "candidate-command-results/v1",
                "production_authority": "NONE", "results": rows}
    evidence_path = tmp_path / "historical-evidence.json"
    evidence_path.write_text(json.dumps(evidence))
    receipt_path = tmp_path / "historical-receipt.json"
    historical: dict[str, object] = {
        "schema_version": "candidate-qualification-receipt/v1", "production_authority": "NONE",
        "command_result_root": hashlib.sha256(
            b"HD636/CANDIDATE-COMMAND-RESULTS/v1\0"
            + json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "command_evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "command_ids": [row["command_id"] for row in rows],
        "inventory": [
            {"path": path.relative_to(source).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(),
             "size": str(len(raw)), "mode": "100644"}
            for path in (registry_path, vendored)
        ],
    }
    receipt_builder.validate_candidate_qualification_receipt(source, evidence_path, historical)
    receipt = build_candidate_qualification_receipt(source, evidence_path, receipt_path)
    assert receipt == historical
    assert receipt["schema_version"] == "candidate-qualification-receipt/v1"
    assert len(cast(list[object], receipt["inventory"])) == 2
    receipt_builder.validate_candidate_qualification_receipt(source, evidence_path, receipt)
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        receipt_builder.validate_candidate_qualification_receipt(Path.cwd(), evidence_path, receipt)
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        build_candidate_qualification_receipt(
            Path.cwd(), evidence_path, tmp_path / "downgrade.json"
        )
    for change in ("missing", "failed", "mixed", "authority"):
        damaged = deepcopy(evidence)
        if change == "missing":
            damaged["results"].pop()
        elif change == "failed":
            damaged["results"][0]["passed"] = False
        elif change == "mixed":
            damaged["schema_version"] = "candidate-command-results/v3"
        else:
            damaged["production_authority"] = "PRODUCTION"
        evidence_path.write_text(json.dumps(damaged))
        with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
            build_candidate_qualification_receipt(source, evidence_path, tmp_path / "invalid.json")
    evidence_path.write_text(json.dumps(evidence))
    (source / "stale.txt").write_text("changed source")
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        receipt_builder.validate_candidate_qualification_receipt(source, evidence_path, receipt)
    current = {**receipt, "schema_version": "candidate-qualification-receipt/v2"}
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        receipt_builder.validate_candidate_qualification_receipt(source, evidence_path, current)
    evidence_path.unlink()
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        receipt_builder.validate_candidate_qualification_receipt(source, evidence_path, receipt)


def test_candidate_receipt_cli_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_candidate_qualification_receipt.py", "--help"],
        cwd=Path.cwd(),
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode()


def test_coherent_current_v1_rows_cannot_downgrade_descendant_contract(tmp_path: Path) -> None:
    # Synthetic descriptor-only forgery with every current command row internally coherent.
    source = tmp_path / "current-descendant"
    names = [
        "task-command-registry.json",
        "vendor/hybrid-discovery-v6.3.6/docs/registries/task-command-registry.v1.json",
        "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json",
    ]
    for name in names:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(name).read_bytes())
    registry = run_command_registry.validate_registry(source / names[0])
    rows = [
        {**{key: command[key] for key in ("command_id", "argv", "cwd", "expected_exit")},
         "exit_code": command["expected_exit"], "passed": True,
         "stdout_sha256": hashlib.sha256(b"").hexdigest(), "stdout_size_bytes": "0",
         "stderr_sha256": hashlib.sha256(b"").hexdigest(), "stderr_size_bytes": "0"}
        for command in run_command_registry.candidate_commands(registry)
    ]
    evidence = run_command_registry.build_candidate_command_results(registry, rows)
    assert evidence["schema_version"] == "candidate-command-results/v1"
    evidence_path = tmp_path / "coherent-current-v1.json"
    evidence_path.write_text(json.dumps(evidence))
    receipt: dict[str, object] = {
        "schema_version": "candidate-qualification-receipt/v1", "production_authority": "NONE",
        "command_result_root": hashlib.sha256(
            b"HD636/CANDIDATE-COMMAND-RESULTS/v1\0"
            + json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "command_evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "command_ids": [row["command_id"] for row in rows],
        "inventory": [
            {"path": name, "sha256": hashlib.sha256((source / name).read_bytes()).hexdigest(),
             "size": str((source / name).stat().st_size), "mode": "100644"}
            for name in sorted(names)
        ],
    }
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        receipt_builder.validate_candidate_qualification_receipt(source, evidence_path, receipt)
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        build_candidate_qualification_receipt(source, evidence_path, tmp_path / "forbidden.json")
    assert not (tmp_path / "forbidden.json").exists()


def _evidence() -> dict[str, object]:
    config = load_controller_config(CONFIG)
    registry = run_command_registry.validate_registry(Path("task-command-registry.json"))
    rows: list[dict[str, object]] = []
    for command in run_command_registry.effective_candidate_commands(registry, config):
        rows.append(
            {
                "command_id": command["command_id"],
                "argv": command["argv"],
                "cwd": command["cwd"],
                "expected_exit": command["expected_exit"],
                "exit_code": command["expected_exit"],
                "passed": True,
                "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                "stdout_size_bytes": "0",
                "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_size_bytes": "0",
            }
        )
    evidence = run_command_registry.build_candidate_command_results(registry, rows, config)
    evidence["schema_version"] = "candidate-command-results/v3"
    evidence["external_authoring_result"] = {
        "argv": list(config.external_authoring_argv),
        "cwd": str(config.external_authoring_cwd),
        "exit_code": 0,
        "passed": True,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_size_bytes": "0",
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_size_bytes": "0",
    }
    return evidence


def test_receipt_rejects_skipped_command_live_evidence_or_production_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(_evidence(), sort_keys=True, separators=(",", ":")))

    config = load_controller_config(CONFIG)
    inventory = {"head": "1" * 40, "tree": "2" * 40, "entries": []}
    monkeypatch.setattr(receipt_builder, "_inventory", lambda *_args: inventory)
    monkeypatch.setattr(receipt_builder, "_validate_proof_coverage", lambda _config: {})
    monkeypatch.setattr(receipt_builder, "_proof_coverage_sha256", lambda _config: "3" * 64)
    receipt = build_candidate_qualification_receipt(
        Path.cwd(), evidence, tmp_path / "receipt.json", config
    )
    assert len(cast(list[str], receipt["command_ids"])) == 45
    assert receipt["inventory"]

    invalid = _evidence()
    invalid["production_authority"] = "PRODUCTION"
    evidence.write_text(json.dumps(invalid, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        build_candidate_qualification_receipt(Path.cwd(), evidence, tmp_path / "bad.json", config)

    forged = _evidence()
    forged["generated_outputs"][0]["sha256"] = "f" * 64  # type: ignore[index]
    evidence.write_text(json.dumps(forged, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        build_candidate_qualification_receipt(
            Path.cwd(), evidence, tmp_path / "forged-generated.json", config
        )


def test_candidate_inventory_is_exact_clean_git_tree_not_ignored_workspace(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    assert git is not None
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(  # noqa: S603 - resolved local Git test fixture.
        [git, "init", "-b", "main"], cwd=source, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603 - resolved local Git test fixture.
        [git, "config", "user.name", "Receipt Test"],
        cwd=source,
        check=True,
    )
    subprocess.run(  # noqa: S603 - resolved local Git test fixture.
        [git, "config", "user.email", "receipt@example.invalid"],
        cwd=source,
        check=True,
    )
    (source / ".gitignore").write_text(".local/\n")
    (source / "source.txt").write_text("governed\n")
    subprocess.run([git, "add", "."], cwd=source, check=True)  # noqa: S603
    subprocess.run(  # noqa: S603 - resolved local Git test fixture.
        [git, "commit", "-m", "fixture"], cwd=source, check=True
    )
    (source / ".local").mkdir()
    (source / ".local/evidence.json").write_text("scratch")

    inventory = __import__(
        "tools.build_candidate_qualification_receipt", fromlist=["_inventory"]
    )._inventory(source)
    assert [row["path"] for row in inventory["entries"]] == [
        ".gitignore",
        "source.txt",
    ]
    assert (
        inventory["head"]
        == subprocess.check_output(  # noqa: S603 - resolved local Git test fixture.
            [git, "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
    )

    (source / "source.txt").write_text("dirty\n")
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        __import__(
            "tools.build_candidate_qualification_receipt", fromlist=["_inventory"]
        )._inventory(source)


def test_proof_coverage_rejects_forged_empty_rows(tmp_path: Path) -> None:
    original = load_controller_config(CONFIG)
    proof_path = tmp_path / "proof.json"
    config = replace(
        original,
        evidence_root=tmp_path,
        proof_coverage_evidence=proof_path,
    )
    proof_path.write_text(
        json.dumps(
            {
                "schema_version": "proof-coverage-result/v2",
                "result": "PASS",
                "production_authority": "NONE",
                "control_count": 18,
                "controller_binding": config.binding(),
                "evidence": [{}] * 18,
            }
        )
    )
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        receipt_builder._validate_proof_coverage(config)


def test_recorded_candidate_proof_replays_from_sanctioned_sealed_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_config = CONFIG
    original = load_controller_config(source_config)
    recorded_pack = Path("/recorded/authoring/pack")
    recorded_evidence = Path("/recorded/evidence")
    config = replace(
        original,
        governed_source_pack=recorded_pack,
        evidence_root=recorded_evidence,
        proof_coverage_evidence=recorded_evidence / "proof.json",
    )
    matrix_source = (
        source_config.parents[1]
        / "registries/proof-coverage-matrix.v1.json"
    )
    matrix = json.loads(matrix_source.read_text())
    candidate_entries = [
        row for row in matrix["entries"] if row["stage"] == "CANDIDATE"
    ]
    fixture = tmp_path / "original"
    fixture.mkdir()
    sources: list[tuple[Path, str, str]] = []
    matrix_copy = fixture / "matrix.json"
    matrix_copy.write_bytes(matrix_source.read_bytes())
    matrix_locator = recorded_pack / "docs/registries/proof-coverage-matrix.v1.json"
    sources.append((matrix_copy, str(matrix_locator), str(recorded_pack)))
    evidence_rows: list[dict[str, str]] = []
    artifact_copies: dict[str, Path] = {}
    for ordinal, entry in enumerate(candidate_entries):
        locator = str(entry["evidence_artifact"])
        source = artifact_copies.get(locator)
        if source is None:
            source = fixture / f"evidence-{ordinal}.json"
            source.write_text(
                json.dumps(
                    {"result": "PASS", "controller_binding": config.binding()},
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            artifact_copies[locator] = source
            sources.append(
                (source, locator, "/home/thenam176/betting-helper")
            )
        evidence_rows.append(
            {
                "requirement_id": str(entry["requirement_id"]),
                "path": locator,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    proof = {
        "result": "PASS",
        "control_count": 18,
        "schema_version": "proof-coverage-result/v2",
        "production_authority": "NONE",
        "controller_binding": config.binding(),
        "evidence": evidence_rows,
    }
    proof_copy = fixture / "proof.json"
    proof_copy.write_text(json.dumps(proof, sort_keys=True, separators=(",", ":")))
    sources.append(
        (proof_copy, str(config.proof_coverage_evidence), str(recorded_evidence))
    )
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    inventory = sealed / "inventory.json"
    manifest = write_closed_inventory(sources, inventory)
    artifacts = RetainedArtifactIO.from_manifest(manifest, sealed / "retained")
    invalid_artifacts: list[RetainedArtifactIO] = []
    for name, changed_rows in (
        ("omitted", evidence_rows[:-1]),
        ("duplicate", [*evidence_rows[:-1], evidence_rows[0]]),
    ):
        changed = {**proof, "evidence": changed_rows}
        changed_copy = fixture / f"proof-{name}.json"
        changed_copy.write_text(json.dumps(changed, sort_keys=True, separators=(",", ":")))
        changed_sealed = tmp_path / f"sealed-{name}"
        changed_sealed.mkdir()
        changed_inventory = changed_sealed / "inventory.json"
        changed_manifest = write_closed_inventory(
            [
                *sources[:-1],
                (
                    changed_copy,
                    str(config.proof_coverage_evidence),
                    str(recorded_evidence),
                ),
            ],
            changed_inventory,
        )
        invalid_artifacts.append(
            RetainedArtifactIO.from_manifest(changed_manifest, changed_sealed / "retained")
        )
    shutil.rmtree(fixture)

    monkeypatch.setattr(
        "tools.verify_proof_coverage._verify_full_repair_proof", lambda *_args: None
    )
    assert receipt_builder._validate_proof_coverage(config, artifacts) == proof
    for changed_artifacts in invalid_artifacts:
        with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
            receipt_builder._validate_proof_coverage(config, changed_artifacts)
