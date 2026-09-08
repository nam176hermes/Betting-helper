"""A descendant receipt preserves ancestry without recreating BOOT0."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tools.qualify_descendant_repository import descendant_repository_identity

ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONFIG = Path(
    "/home/thenam176/betting-helper/authoring-controller-config-worktree/pack/"
    "docs/configs/full-verifier-controller.v2.json"
)


def _git(root: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git is not None
    return subprocess.check_output(  # noqa: S603 -- local disposable Git fixture.
        [git, "-C", str(root), *args], text=True, stderr=subprocess.PIPE,
    ).strip()


def _repository(directory: Path, object_format: str = "sha1") -> tuple[Path, str]:
    root = directory / "runtime"
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main", "--object-format=" + object_format)
    _git(root, "config", "user.name", "Descendant Test")
    _git(root, "config", "user.email", "descendant@example.invalid")
    ancestor = _commit(root, "audited.txt", "audited")
    _commit(root, "repair.txt", "repair")
    return root, ancestor


def _config(directory: Path, root: Path, ancestor: str) -> Any:
    from tools.full_verifier_config import load_controller_config

    payload = json.loads(SOURCE_CONFIG.read_bytes())
    pack = directory / "authoring/pack"
    evidence = directory / "evidence"
    evidence.mkdir()
    payload.update(
        current_checkout_root=str(root), governed_source_pack=str(pack),
        evidence_root=str(evidence), audited_runtime_ancestor=ancestor,
        external_authoring_tests=str(directory / "authoring/authoring-tests"),
        external_authoring_command={
            "cwd": str(directory / "authoring"),
            "argv": ["uv", "run", "--frozen", "--offline", "python", "-I", "-B", "tests.py"],
        },
    )
    for key, value in payload["receipts"].items():
        payload["receipts"][key] = str(evidence / Path(value).name)
    for key, value in payload["qualification_evidence"].items():
        parent = evidence if key in {"p03_proof", "p04_proof"} else evidence / key
        payload["qualification_evidence"][key] = str(parent / Path(value).name)
    source = pack / "docs/configs/full-verifier-controller.v2.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(payload, sort_keys=True))
    path = directory / "controller.json"
    path.write_bytes(source.read_bytes())
    return load_controller_config(path)


def _write(path: Path, value: object) -> bytes:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


@pytest.fixture
def actual_matrix_candidate_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    from tools import build_candidate_qualification_receipt as candidate
    from tools import run_command_registry as commands
    from tools import verify_proof_coverage as proof

    root, ancestor = _repository(tmp_path)
    tracked = _git(ROOT, "ls-files").splitlines()
    copied_bytes = 0
    for relative in tracked:
        original = ROOT / relative
        assert original.is_file() and not original.is_symlink()
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        copied_bytes += target.stat().st_size
    _git(root, "add", "--force", "--", *tracked)
    _git(root, "commit", "-m", "disposable current inventory")
    pnpm = shutil.which("pnpm")
    assert pnpm is not None
    subprocess.run(  # noqa: S603 -- official compiler, disposable fixture output only.
        [pnpm, "--dir", str(ROOT / "extension"), "exec", "tsc", "-p", "tsconfig.test.json",
         "--outDir", str(root / "extension/.test-build")],
        cwd=ROOT, check=True, capture_output=True,
    )
    print(f"fixture tracked_files={len(tracked)} copied_bytes={copied_bytes}")
    config = _config(tmp_path, root, ancestor)
    source_pack = SOURCE_CONFIG.parents[2]
    source_map = source_pack / "docs/registries/normative-source-map.v1.json"
    mapping = json.loads(source_map.read_bytes())
    for entry in [*mapping["inherited_entries"], *mapping["plan_entries"]]:
        relative = entry["plan_source"]
        target = config.governed_source_pack / relative
        if relative == "docs/configs/full-verifier-controller.v2.json":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_pack / relative, target)
    shutil.copy2(source_map, config.governed_source_pack / source_map.relative_to(source_pack))

    matrix_relative = "docs/registries/proof-coverage-matrix.v1.json"
    source_raw = (source_pack / matrix_relative).read_bytes()
    source_matrix = json.loads(source_raw)
    matrix = deepcopy(source_matrix)
    locators: dict[str, str] = {}
    for entry in matrix["entries"]:
        if entry["stage"] != "CANDIDATE":
            continue
        original = Path(entry["evidence_artifact"])
        assert original.is_absolute() and original.name not in {"", ".", ".."}
        target = str(config.evidence_root / original.name)
        assert target not in locators.values() or locators.get(str(original)) == target
        locators[str(original)] = target
        entry["evidence_artifact"] = target
    restored = deepcopy(matrix)
    for original, derived in zip(source_matrix["entries"], restored["entries"], strict=True):
        if original["stage"] == "CANDIDATE":
            derived["evidence_artifact"] = original["evidence_artifact"]
    assert restored == source_matrix
    assert len(matrix["entries"]) == 18
    (tmp_path / "source-matrix-witness.json").write_bytes(source_raw)
    print("fixture source_matrix_sha256=" + hashlib.sha256(source_raw).hexdigest())
    _write(config.governed_source_pack / matrix_relative, matrix)

    vendor = root / "vendor/hybrid-discovery-v6.3.6"
    for name, path in (
        ("RUNTIME_ROOT", root), ("VENDOR_ROOT", vendor),
        ("SCHEMA_PATH", vendor / "docs/schemas/command-registry.schema.json"),
        ("TOPOLOGY_PATH", vendor / "docs/registries/verification-topology.v1.json"),
    ):
        monkeypatch.setattr(commands, name, path)

    qualification = config.qualification_evidence
    assert qualification is not None
    calls: list[tuple[str, Path, Path, object]] = []
    for path in (
        qualification.full_repair_aggregate, qualification.full_repair_inventory,
        qualification.environment_qualification_aggregate,
        qualification.environment_qualification_inventory,
    ):
        _write(path, {"fixture_boundary": path.parent.name})

    def read(path: Path, artifacts: Any) -> bytes:
        return candidate._read_bytes(path, artifacts)

    def full_boundary(
        aggregate: Path, inventory: Path, passed: Any, *, artifacts: Any = None,
    ) -> Any:
        # Permitted semantic boundary only: no controls or mutations are executed here.
        assert passed == config
        for actual, recorded in (
            (aggregate, qualification.full_repair_aggregate),
            (inventory, qualification.full_repair_inventory),
        ):
            expected = recorded if artifacts is None else artifacts.physical_path(
                str(recorded), recorded_boundary=artifacts.recorded_boundary(str(recorded)),
            )
            assert actual == expected
        calls.append(("full", aggregate, inventory, artifacts))
        raw = read(qualification.full_repair_aggregate, artifacts)
        manifest = json.loads(read(qualification.full_repair_inventory, artifacts))
        json.loads(raw)
        return {
            "schema_version": "full-repair-clock-proof/v1", "result": "PASS",
            "production_authority": "NONE", "controller_binding": config.binding(),
            "aggregate_sha256": hashlib.sha256(raw).hexdigest(),
            "evidence_root_sha256": hashlib.sha256(candidate._canonical(manifest)).hexdigest(),
            "control_count": 111, "clock_control_count": 65,
            "mutation_count": 105, "mutation_survivors": 0,
        }

    def environment_boundary(
        aggregate: Path, inventory: Path, passed: Any, *, artifacts: Any = None,
    ) -> Any:
        assert passed == config
        assert aggregate == qualification.environment_qualification_aggregate
        assert inventory == qualification.environment_qualification_inventory
        calls.append(("environment", aggregate, inventory, artifacts))
        raw, manifest = read(aggregate, artifacts), read(inventory, artifacts)
        json.loads(raw)
        json.loads(manifest)
        return {
            "result": "PARTIAL_HOLD", "aggregate_sha256": hashlib.sha256(raw).hexdigest(),
            "evidence_root_sha256": hashlib.sha256(manifest).hexdigest(),
        }

    monkeypatch.setattr(
        "tools.verify_full_repair_qualification.verify_full_repair_qualification", full_boundary,
    )
    monkeypatch.setattr(
        "tools.run_environment_qualification.verify_environment_qualification_evidence",
        environment_boundary,
    )
    full = full_boundary(
        qualification.full_repair_aggregate, qualification.full_repair_inventory, config,
    )
    for entry in matrix["entries"]:
        if entry["stage"] == "CANDIDATE":
            value = {"result": "PASS", "controller_binding": config.binding()}
            if entry["command_id"] == "TEST_V636_P03_T07":
                value = {
                    **full, "schema_version": "full-repair-qualification/v1",
                    "clock_proof_pending": True,
                }
            elif entry["command_id"] == "TEST_V636_P04_T04":
                value = full
            _write(Path(entry["evidence_artifact"]), value)
    _write(config.proof_coverage_evidence, proof.verify_proof_coverage_matrix(
        matrix, config.evidence_root, "CANDIDATE", config,
    ))
    registry = commands.validate_registry(root / "task-command-registry.json")
    stream_fields = {
        "stdout_sha256": hashlib.sha256(b"").hexdigest(), "stdout_size_bytes": "0",
        "stderr_sha256": hashlib.sha256(b"").hexdigest(), "stderr_size_bytes": "0",
    }
    results = [{
        **{key: command[key] for key in ("command_id", "argv", "cwd", "expected_exit")},
        "exit_code": command["expected_exit"], "passed": True, **stream_fields,
    } for command in commands.effective_candidate_commands(registry, config)]
    evidence = commands.build_candidate_command_results(registry, results, config)
    evidence.update(schema_version="candidate-command-results/v3", external_authoring_result={
        "argv": list(config.external_authoring_argv), "cwd": str(config.external_authoring_cwd),
        "exit_code": 0, "passed": True, **stream_fields,
    })
    _write(config.candidate_command_evidence, evidence)
    candidate.build_candidate_qualification_receipt(
        root, config.candidate_command_evidence, config.candidate_qualification_receipt, config,
    )
    calls.clear()
    return {
        "root": root, "ancestor": ancestor, "config": config, "matrix": matrix,
        "source_matrix": source_matrix, "source_raw": source_raw, "calls": calls,
        "full": full, "directory": tmp_path,
    }


def test_descendant_issue_rereads_canonical_bytes_and_returns_owned_record(
    actual_matrix_candidate_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config = chain["config"]
    output = config.descendant_repository_receipt
    synced: list[tuple[int, int]] = []
    fsync = os.fsync

    def sync_owned(descriptor: int) -> None:
        info = os.fstat(descriptor)
        synced.append((info.st_dev, info.st_ino))
        fsync(descriptor)

    monkeypatch.setattr(qualifier.os, "fsync", sync_owned)
    receipt = qualifier.issue_descendant_qualification_receipt(chain["root"], config, output)
    assert output.read_bytes() == qualifier._canonical(receipt) + b"\n"
    assert output.lstat().st_nlink == 1 and not output.is_symlink()
    assert synced == [(output.stat().st_dev, output.stat().st_ino)]
    assert qualifier.verify_descendant_qualification_receipt(
        chain["root"], output, pack=config.governed_source_pack, config=config,
    ) == receipt
    assert {name for name, *_ in chain["calls"]} == {"full", "environment"}
    assert all(artifacts is None for *_, artifacts in chain["calls"])
    assert receipt["full_repair_evidence_root_sha256"] == chain["full"]["evidence_root_sha256"]


@pytest.fixture
def issued_chain(actual_matrix_candidate_chain: dict[str, Any]) -> dict[str, Any]:
    from tools import qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config = chain["config"]
    chain["receipt"] = qualifier.issue_descendant_qualification_receipt(
        chain["root"], config, config.descendant_repository_receipt,
    )
    return chain


def _verify(chain: dict[str, Any], artifacts: Any = None) -> dict[str, object]:
    from tools import qualify_descendant_repository as qualifier

    config = chain["config"]
    return qualifier.verify_descendant_qualification_receipt(
        chain["root"], config.descendant_repository_receipt,
        pack=config.governed_source_pack, config=config, artifacts=artifacts,
    )


@pytest.fixture
def sealed_chain(issued_chain: dict[str, Any]) -> dict[str, Any]:
    from tools.full_verifier_config import load_controller_config
    from tools.retained_artifact_io import RetainedArtifactIO
    from tools.run_full_repair_qualification import write_closed_inventory

    chain = issued_chain
    config = chain["config"]
    pack = config.governed_source_pack
    source_map = pack / "docs/registries/normative-source-map.v1.json"
    mapping = json.loads(source_map.read_bytes())
    qualification = config.qualification_evidence
    paths = {
        config.source_path, source_map, config.candidate_qualification_receipt,
        config.candidate_command_evidence, config.proof_coverage_evidence,
        config.descendant_repository_receipt,
        qualification.full_repair_aggregate, qualification.full_repair_inventory,
        qualification.environment_qualification_aggregate,
        qualification.environment_qualification_inventory,
        *(pack / row["plan_source"] for row in
          [*mapping["inherited_entries"], *mapping["plan_entries"]]),
        *(Path(row["evidence_artifact"]) for row in chain["matrix"]["entries"]
          if row["stage"] == "CANDIDATE"),
    }
    sealed = chain["directory"] / "sealed"
    sealed.mkdir()
    manifest = write_closed_inventory([
        (path, str(path), str(
            pack if path.is_relative_to(pack) else config.evidence_root
            if path.is_relative_to(config.evidence_root) else chain["directory"]
        )) for path in sorted(paths)
    ], sealed / "inventory.json")
    artifacts = RetainedArtifactIO.from_manifest(manifest, sealed / "retained")
    print(f"fixture retained_files={len(paths)} retained_bytes="
          f"{sum(row['size_bytes'] for row in manifest['files'])}")
    # These are this test's disposable roots only; runtime remains the live bound checkout.
    shutil.rmtree(config.evidence_root)
    shutil.rmtree(config.governed_source_pack)
    config.source_path.unlink()
    physical = artifacts.physical_path(
        str(config.source_path), recorded_boundary=str(chain["directory"]),
    )
    sealed_config = load_controller_config(
        physical, mode="SEALED", artifacts=artifacts, recorded_locator=str(config.source_path),
    )
    assert sealed_config == config
    chain.update(config=sealed_config, artifacts=artifacts, manifest=manifest, physical=physical)
    return chain


def test_descendant_sealed_check_only_survives_original_root_removal(
    sealed_chain: dict[str, Any],
) -> None:
    chain = sealed_chain
    config, artifacts = chain["config"], chain["artifacts"]
    chain["calls"].clear()
    assert _verify(chain, artifacts) == chain["receipt"]
    assert [name for name, *_ in chain["calls"]] == ["full", "full", "full", "environment"]
    assert all(context is artifacts for *_, context in chain["calls"])
    assert not config.source_path.exists()
    assert not config.evidence_root.exists()
    assert not config.governed_source_pack.exists()
    matrix_path = config.governed_source_pack / "docs/registries/proof-coverage-matrix.v1.json"
    assert json.loads(artifacts.read_bytes(
        str(matrix_path), recorded_boundary=artifacts.recorded_boundary(str(matrix_path)),
    )) == chain["matrix"]

    source_map = config.governed_source_pack / "docs/registries/normative-source-map.v1.json"
    mapping = json.loads(artifacts.read_bytes(
        str(source_map), recorded_boundary=str(config.governed_source_pack),
    ))
    input_classes = {
        str(config.source_path), str(source_map), str(matrix_path),
        str(config.governed_source_pack / mapping["inherited_entries"][0]["plan_source"]),
        str(config.governed_source_pack / mapping["plan_entries"][0]["plan_source"]),
        str(config.governed_source_pack / "docs/configs/full-verifier-controller.v2.json"),
        *(row["recorded_locator"] for row in chain["manifest"]["files"]
          if Path(row["recorded_locator"]).is_relative_to(config.evidence_root)),
    }
    # Every input class and every eligible matrix artifact is independently damaged.
    for row in chain["manifest"]["files"]:
        if row["recorded_locator"] not in input_classes:
            continue
        copied = artifacts.physical_root / row["copied_relative_path"]
        raw = copied.read_bytes()
        for damage in ("remove", "tamper"):
            if damage == "remove":
                copied.unlink()
            else:
                copied.write_bytes(raw + b"changed")
            try:
                with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                    _verify(chain, artifacts)
            finally:
                copied.write_bytes(raw)
    assert _verify(chain, artifacts) == chain["receipt"]


def test_descendant_sealed_context_rejects_config_locator_hash_and_argv_drift(
    sealed_chain: dict[str, Any],
) -> None:
    from tools import qualify_descendant_repository as qualifier
    from tools.full_verifier_config import load_controller_config
    from tools.retained_artifact_io import RetainedArtifactIO

    chain = sealed_chain
    config, artifacts = chain["config"], chain["artifacts"]
    source_copy = config.governed_source_pack / "docs/configs/full-verifier-controller.v2.json"
    config_locators = (str(config.source_path), str(source_copy))
    copies = [artifacts.physical_path(
        recorded, recorded_boundary=artifacts.recorded_boundary(recorded),
    ) for recorded in config_locators]
    original = {path: path.read_bytes() for path in copies}
    with pytest.raises(ValueError, match="^E_CONTROLLER_CONFIG$"):
        load_controller_config(
            copies[1], mode="SEALED", artifacts=artifacts,
            recorded_locator=str(config.source_path),
        )
    for damage in ("config-bytes", "source-copy", "locator", "physical-identity", "cwd", "argv"):
        manifest = deepcopy(chain["manifest"])
        changed_config = config
        if damage == "locator":
            for row in manifest["files"]:
                if row["recorded_locator"] == str(config.source_path):
                    row["recorded_locator"] += ".wrong"
        elif damage == "physical-identity":
            changed_config = replace(config, source_path=copies[0])
        elif damage in {"cwd", "argv"}:
            payload = json.loads(original[copies[0]])
            command = payload["external_authoring_command"]
            if damage == "cwd":
                command["cwd"] = str(chain["directory"] / "other-authoring")
            else:
                command["argv"].append("--injected")
            for path in copies:
                _write(path, payload)
            for row in manifest["files"]:
                if row["recorded_locator"] in config_locators:
                    raw = (artifacts.physical_root / row["copied_relative_path"]).read_bytes()
                    row.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        else:
            copies[damage == "source-copy"].write_bytes(b"corrupt")
        try:
            context = artifacts if damage in {"config-bytes", "source-copy"} else (
                RetainedArtifactIO.from_manifest(manifest, artifacts.physical_root)
            )
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                qualifier.verify_descendant_qualification_receipt(
                    chain["root"], config.descendant_repository_receipt,
                    pack=config.governed_source_pack, config=changed_config, artifacts=context,
                )
        finally:
            for path, raw in original.items():
                path.write_bytes(raw)


def test_descendant_receipt_rejects_stale_head_tree_and_file_root(
    issued_chain: dict[str, Any],
) -> None:
    chain = issued_chain
    before = chain["receipt"]
    _commit(chain["root"], "successor.txt", "new committed source")
    identity = descendant_repository_identity(chain["root"], chain["ancestor"])
    assert all(identity[key] != before[key] for key in identity)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        _verify(chain)


def test_descendant_receipt_rejects_changed_current_source_or_generated_output(
    issued_chain: dict[str, Any],
) -> None:
    chain = issued_chain
    commands = json.loads(chain["config"].candidate_command_evidence.read_bytes())
    for path in (
        chain["root"] / "repair.txt",
        chain["root"] / commands["generated_outputs"][0]["path"],
    ):
        raw = path.read_bytes()
        path.write_bytes(raw + b"changed")
        try:
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                _verify(chain)
        finally:
            path.write_bytes(raw)


def test_descendant_uses_actual_eighteen_requirement_matrix(
    issued_chain: dict[str, Any],
) -> None:
    chain = issued_chain
    config = chain["config"]
    assert tuple(row["requirement_id"] for row in chain["source_matrix"]["entries"]) == (
        "V631-C1.ACYCLIC_SEAL", "V631-C2.DECLARATION_COMPLETE", "V631-C2.LIFECYCLE_ORDER",
        "V631-C3.MIGRATION_COMPLETE", "V631-C4.EXACT_REFERENCES", "V631-C5.CRASH_COVERAGE",
        "V631-C5.CLOCK_EVALUATION", "V631-C6.CYBERSECURITY_COMPLETE", "R633-01.CLOSURE",
        "R633-02.CLOSURE", "R633-03.CLOSURE", "R633-04.CLOSURE", "R633-05.CLOSURE",
        "R633-06.CLOSURE", "R634-MIGRATION-STAGE.CLOSURE", "R634-PRODUCTION-BUILD.CLOSURE",
        "R634-DEPENDENCY-SETUP.CLOSURE", "R634-EXPORT-INVENTORY.CLOSURE",
    )
    matrix_path = config.governed_source_pack / "docs/registries/proof-coverage-matrix.v1.json"
    artifact = Path(next(row["evidence_artifact"] for row in chain["matrix"]["entries"]
                         if row["stage"] == "CANDIDATE"))
    paths = (config.proof_coverage_evidence, config.candidate_qualification_receipt,
             matrix_path, artifact, config.qualification_evidence.p03_proof,
             config.qualification_evidence.p04_proof)
    originals = {path: path.read_bytes() for path in paths}
    proof = json.loads(originals[paths[0]])
    assert len(proof["evidence"]) == 16 and proof["control_count"] == 18
    assert _verify(chain) == chain["receipt"]
    for damage in (
        "omitted", "duplicate", "reordered", "requirement", "path", "digest",
        "matrix-byte", "evidence-byte", "p03", "p04", "coherent-false",
    ):
        changed = deepcopy(proof)
        if damage == "omitted":
            changed["evidence"].pop()
        elif damage == "duplicate":
            changed["evidence"][-1] = changed["evidence"][0]
        elif damage == "reordered":
            changed["evidence"].reverse()
        elif damage in {"requirement", "path", "digest"}:
            key = {"requirement": "requirement_id", "path": "path", "digest": "sha256"}[damage]
            changed["evidence"][0][key] = "0" * 64
        elif damage == "matrix-byte":
            matrix_path.write_bytes(b"corrupt")
        elif damage == "evidence-byte":
            artifact.write_bytes(b"corrupt")
        elif damage in {"p03", "p04"}:
            path = getattr(config.qualification_evidence, damage + "_proof")
            payload = json.loads(path.read_bytes())
            payload["mutation_count"] = 104
            _write(path, payload)
        else:
            payload = json.loads(artifact.read_bytes())
            payload["result"] = "FAIL"
            raw = _write(artifact, payload)
            for row in changed["evidence"]:
                if row["path"] == str(artifact):
                    row["sha256"] = hashlib.sha256(raw).hexdigest()
        proof_raw = _write(paths[0], changed)
        candidate = json.loads(originals[paths[1]])
        candidate["proof_coverage_sha256"] = hashlib.sha256(proof_raw).hexdigest()
        _write(paths[1], candidate)
        try:
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                _verify(chain)
        finally:
            for path, raw in originals.items():
                path.write_bytes(raw)


def test_descendant_rejects_lock_vendor_and_toolchain_drift(
    issued_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from moj_discovery.pack_verifier import compute_vendor_tree_root
    from tools import qualify_descendant_repository as qualifier

    chain = issued_chain
    root = chain["root"]
    vendor = root / "vendor/hybrid-discovery-v6.3.6"
    for path in (root / "uv.lock", vendor / "docs/registries/normative-source-map.v1.json"):
        raw = path.read_bytes()
        locks_before = qualifier.dependency_lock_hashes(root)
        vendor_before = compute_vendor_tree_root(vendor)
        path.write_bytes(raw + b"\nchanged")
        try:
            if path.name == "uv.lock":
                assert qualifier.dependency_lock_hashes(root) != locks_before
            else:
                assert compute_vendor_tree_root(vendor) != vendor_before
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                _verify(chain)
        finally:
            path.write_bytes(raw)
    called: list[bool] = []

    def failed_toolchain() -> list[str]:
        called.append(True)
        return ["injected installed toolchain mismatch"]

    monkeypatch.setattr(qualifier, "verify_toolchains", failed_toolchain)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        _verify(chain)
    assert called == [True]


def test_descendant_rejects_full_and_environment_evidence_damage(
    issued_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import run_environment_qualification as environment
    from tools import verify_full_repair_qualification as full

    chain = issued_chain
    qualification = chain["config"].qualification_evidence
    for path in (
        qualification.full_repair_aggregate, qualification.full_repair_inventory,
        qualification.environment_qualification_aggregate,
        qualification.environment_qualification_inventory,
    ):
        raw = path.read_bytes()
        for damage in ("missing", "corrupt", "root-change"):
            if damage == "missing":
                path.unlink()
            else:
                path.write_bytes(b"corrupt" if damage == "corrupt" else b'{"changed":true}\n')
            try:
                with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                    _verify(chain)
            finally:
                path.write_bytes(raw)

    # Explicitly permitted boundary records: real recursive owner negatives run separately.
    full_boundary = full.verify_full_repair_qualification
    for key, value in (
        ("controller_binding", {}), ("control_count", 110), ("clock_control_count", 64),
        ("mutation_count", 104), ("mutation_survivors", 1),
        ("evidence_root_sha256", "0" * 64),
    ):
        def damaged_full(
            *args: Any, field: str = key, changed: object = value, **kwargs: Any,
        ) -> Any:
            return {**full_boundary(*args, **kwargs), field: changed}

        with monkeypatch.context() as scoped:
            scoped.setattr(full, "verify_full_repair_qualification", damaged_full)
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                _verify(chain)
    environment_boundary = environment.verify_environment_qualification_evidence

    def damaged_environment(*args: Any, **kwargs: Any) -> Any:
        return {**environment_boundary(*args, **kwargs), "evidence_root_sha256": "0" * 64}

    with monkeypatch.context() as scoped:
        scoped.setattr(
            environment, "verify_environment_qualification_evidence", damaged_environment,
        )
        with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
            _verify(chain)
    for module, name in (
        (full, "verify_full_repair_qualification"),
        (environment, "verify_environment_qualification_evidence"),
    ):
        called: list[bool] = []

        def rejected_owner(*_args: Any, dispatched: list[bool] = called, **_kwargs: Any) -> Any:
            dispatched.append(True)
            raise ValueError("injected recursive owner rejection")

        with monkeypatch.context() as scoped:
            scoped.setattr(module, name, rejected_owner)
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                _verify(chain)
        assert called == [True]


def test_descendant_issue_detects_postwrite_head_tree_status_and_input_drift(
    actual_matrix_candidate_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config, root = chain["config"], chain["root"]
    output = config.descendant_repository_receipt
    qualification = config.qualification_evidence
    targets = {
        "tracked": root / "repair.txt", "staged": root / "repair.txt",
        "candidate": config.candidate_qualification_receipt,
        "proof": config.proof_coverage_evidence, "config": config.source_path,
        "source-copy": (
            config.governed_source_pack / "docs/configs/full-verifier-controller.v2.json"
        ),
        "lock": root / "uv.lock",
        "vendor": (
            root / "vendor/hybrid-discovery-v6.3.6/docs/registries/normative-source-map.v1.json"
        ),
        "full": qualification.full_repair_aggregate,
        "environment": qualification.environment_qualification_inventory,
    }
    capture = qualifier._receipt_record
    for damage in (*targets, "untracked", "head"):
        target = targets.get(damage, root / "new-source.txt")
        raw = target.read_bytes() if target.exists() else None
        calls = 0

        def drift_after_first(
            *args: Any, changed_path: Path = target, kind: str = damage, **kwargs: Any,
        ) -> dict[str, object]:
            nonlocal calls
            calls += 1
            result = capture(*args, **kwargs)
            if calls == 1:
                changed_path.write_bytes(b"changed input\n")
                if kind == "staged":
                    _git(root, "add", "repair.txt")
                elif kind == "head":
                    _git(root, "add", "new-source.txt")
                    _git(root, "commit", "-m", "postwrite successor")
            return result

        with monkeypatch.context() as scoped:
            scoped.setattr(qualifier, "_receipt_record", drift_after_first)
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                qualifier.issue_descendant_qualification_receipt(root, config, output)
        assert calls == 2
        assert not output.exists()
        if raw is not None:
            target.write_bytes(raw)
            if damage == "staged":
                _git(root, "add", "repair.txt")
        elif damage != "head":
            target.unlink()


@pytest.mark.parametrize("kind", ["file", "symlink", "hardlink"])
def test_descendant_issue_preserves_preexisting_symlink_hardlink_and_file(
    tmp_path: Path, kind: str,
) -> None:
    from tools import qualify_descendant_repository as qualifier

    root, ancestor = _repository(tmp_path)
    config = _config(tmp_path, root, ancestor)
    output = config.descendant_repository_receipt
    competitor = config.evidence_root / "competitor.json"
    competitor.write_bytes(b"preexisting competitor\n")
    if kind == "symlink":
        output.symlink_to(competitor)
    elif kind == "hardlink":
        os.link(competitor, output)
    else:
        output.write_bytes(competitor.read_bytes())
    inode = output.lstat().st_ino
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        qualifier.issue_descendant_qualification_receipt(root, config, output)
    assert output.lstat().st_ino == inode
    assert output.read_bytes() == competitor.read_bytes() == b"preexisting competitor\n"


def test_descendant_issue_requires_exact_configured_receipt_and_safe_parent(
    tmp_path: Path,
) -> None:
    from tools import qualify_descendant_repository as qualifier

    root, ancestor = _repository(tmp_path)
    config = _config(tmp_path, root, ancestor)
    for output in (Path("relative.json"), config.evidence_root / "wrong.json",
                   root / "receipt.json", root.parent):
        with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
            qualifier.issue_descendant_qualification_receipt(root, config, output)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        qualifier.verify_descendant_qualification_receipt(
            root, config.descendant_repository_receipt, pack=tmp_path / "wrong-pack", config=config,
        )


def test_descendant_cli_allows_distinct_operation_report_output(
    actual_matrix_candidate_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config = chain["config"]
    report = chain["directory"] / "reports/operation.json"
    assert report != config.descendant_repository_receipt
    monkeypatch.setattr("sys.argv", [
        "qualify_descendant_repository.py", "--root", str(chain["root"]),
        "--config", str(config.source_path), "--receipt", str(config.descendant_repository_receipt),
        "--output", str(report), "--issue",
    ])
    qualifier.main()
    assert report.read_bytes() == config.descendant_repository_receipt.read_bytes()
    assert _verify(chain) == json.loads(report.read_bytes())


@pytest.mark.parametrize("owner", ["full", "environment"])
@pytest.mark.parametrize("damage", ["missing-inventory", "corrupt-inventory", "missing-copy",
                                    "corrupt-copy", "malformed-aggregate"])
def test_real_recursive_validators_reject_malformed_aggregate_and_inventory(
    tmp_path: Path, owner: str, damage: str,
) -> None:
    from tools.run_environment_qualification import verify_environment_qualification_evidence
    from tools.run_full_repair_qualification import write_closed_inventory
    from tools.verify_full_repair_qualification import verify_full_repair_qualification

    root, ancestor = _repository(tmp_path)
    config = _config(tmp_path, root, ancestor)
    qualification = config.qualification_evidence
    aggregate = getattr(qualification, "full_repair_aggregate" if owner == "full" else
                        "environment_qualification_aggregate")
    inventory = getattr(qualification, "full_repair_inventory" if owner == "full" else
                        "environment_qualification_inventory")
    _write(aggregate, {"records": [], "owner_reports": {}, "clock_report": {}})
    inventory.parent.mkdir(parents=True)
    manifest = write_closed_inventory([
        (aggregate, str(aggregate), str(aggregate.parent)),
    ], inventory)
    copied = inventory.parent / "retained" / manifest["files"][0]["copied_relative_path"]
    if damage == "missing-inventory":
        inventory.unlink()
    elif damage == "corrupt-inventory":
        inventory.write_bytes(b"corrupt")
    elif damage == "missing-copy":
        copied.unlink()
    elif damage == "corrupt-copy":
        copied.write_bytes(b"corrupt")
    if owner == "full":
        with pytest.raises(ValueError, match="^E_FULL_REPAIR_QUALIFICATION$"):
            verify_full_repair_qualification(aggregate, inventory, config)
    else:
        with pytest.raises(ValueError, match="^E_ENVIRONMENT_QUALIFICATION$"):
            verify_environment_qualification_evidence(aggregate, inventory, config)


@pytest.mark.parametrize("damage", ["replacement", "symlink", "hardlink", "same-inode-bytes"])
def test_descendant_issue_detects_silent_path_replacement_after_write(
    actual_matrix_candidate_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch, damage: str,
) -> None:
    from tools import qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config = chain["config"]
    output = config.descendant_repository_receipt
    capture = qualifier._receipt_record
    calls = 0
    competitor = output.with_name("competitor.json")
    competitor.write_bytes(b"competitor\n")

    def replace_after_capture(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        result = capture(*args, **kwargs)
        calls += 1
        if calls == 2:
            if damage == "same-inode-bytes":
                output.write_bytes(b"changed owned bytes\n")
            elif damage == "hardlink":
                os.link(output, output.with_name("owned-alias.json"))
            else:
                output.rename(output.with_name("held-owned.json"))
                if damage == "symlink":
                    output.symlink_to(competitor)
                else:
                    output.write_bytes(competitor.read_bytes())
        return result

    monkeypatch.setattr(qualifier, "_receipt_record", replace_after_capture)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        qualifier.issue_descendant_qualification_receipt(chain["root"], config, output)
    assert calls == 2
    assert competitor.read_bytes() == b"competitor\n"
    if damage == "same-inode-bytes":
        assert not output.exists()
    elif damage == "hardlink":
        assert output.stat().st_nlink == 2
    else:
        assert output.read_bytes() == competitor.read_bytes()


def test_descendant_rejects_missing_old_schema_or_malformed_receipt(
    issued_chain: dict[str, Any],
) -> None:
    chain = issued_chain
    output = chain["config"].descendant_repository_receipt
    raw = output.read_bytes()
    for damage in (
        "missing", "repo0", "missing-field", "extra-field", "schema", "identity", "authority",
    ):
        changed = json.loads(raw)
        if damage == "missing":
            output.unlink()
        else:
            if damage == "repo0":
                changed["schema_version"] = "repository-baseline-receipt/v1"
            elif damage == "missing-field":
                changed.pop("repository_tree")
            elif damage == "extra-field":
                changed["unexpected"] = True
            elif damage == "schema":
                changed["schema_version"] = "unknown"
            elif damage == "identity":
                changed["repository_identity_kind"] = "REPO0"
            else:
                changed["production_authority"] = "PRODUCTION"
            _write(output, changed)
        try:
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                _verify(chain)
        finally:
            output.write_bytes(raw)


def test_descendant_rejects_stale_candidate_config_and_command_evidence(
    issued_chain: dict[str, Any],
) -> None:
    chain = issued_chain
    config = chain["config"]
    paths = (config.candidate_qualification_receipt, config.candidate_command_evidence)
    original = {path: path.read_bytes() for path in paths}
    for damage in (
        "candidate-binding", "config-hash", "command-root", "order", "result",
        "external-authoring", "generated-byte-and-hash",
    ):
        candidate, commands = (json.loads(original[path]) for path in paths)
        generated_path = None
        generated_raw = None
        if damage == "candidate-binding":
            candidate["controller_binding"]["evidence_root"] = "/different"
        elif damage == "config-hash":
            candidate["controller_binding"]["config_sha256"] = "0" * 64
        elif damage == "command-root":
            candidate["command_result_root"] = "0" * 64
        elif damage == "order":
            commands["results"].reverse()
        elif damage == "result":
            commands["results"][0]["passed"] = False
        elif damage == "external-authoring":
            commands["external_authoring_result"]["argv"].append("--injected")
        else:
            generated = commands["generated_outputs"][0]
            generated_path = chain["root"] / generated["path"]
            generated_raw = generated_path.read_bytes()
            generated_path.write_bytes(generated_raw + b"\nchanged")
            generated["sha256"] = hashlib.sha256(generated_path.read_bytes()).hexdigest()
            generated["size_bytes"] = str(generated_path.stat().st_size)
        _write(paths[0], candidate)
        _write(paths[1], commands)
        try:
            with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
                _verify(chain)
        finally:
            for path, raw in original.items():
                path.write_bytes(raw)
            if generated_path is not None and generated_raw is not None:
                generated_path.write_bytes(generated_raw)


def test_descendant_identity_rejects_audited_head_wrong_ancestor_and_non_sha1(
    tmp_path: Path,
) -> None:
    root, ancestor = _repository(tmp_path)
    detached = _git(root, "commit-tree", _git(root, "rev-parse", "HEAD^{tree}"), "-m", "unrelated")
    for invalid in (_git(root, "rev-parse", "HEAD"), detached, "f" * 40, "malformed"):
        with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
            descendant_repository_identity(root, invalid)
    sha256_root, _ = _repository(tmp_path / "sha256", "sha256")
    assert _git(sha256_root, "rev-parse", "--show-object-format") == "sha256"
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        descendant_repository_identity(sha256_root, ancestor)


def test_descendant_identity_rejects_nested_root_symlink_and_top_level_alias(
    tmp_path: Path,
) -> None:
    root, ancestor = _repository(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    parent_alias = tmp_path / "parent-alias"
    parent_alias.symlink_to(root.parent, target_is_directory=True)
    for invalid in (nested, alias, parent_alias / root.name, root / ".." / root.name):
        with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
            descendant_repository_identity(invalid, ancestor)


@pytest.mark.parametrize("damage", ["tracked", "staged", "untracked"])
def test_descendant_identity_rejects_dirty_tracked_staged_and_untracked_bytes(
    tmp_path: Path, damage: str,
) -> None:
    root, ancestor = _repository(tmp_path)
    path = root / ("untracked.txt" if damage == "untracked" else "repair.txt")
    path.write_text("changed")
    if damage == "staged":
        _git(root, "add", "repair.txt")
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        descendant_repository_identity(root, ancestor)


@pytest.mark.parametrize("api", ["record", "issue", "verify"])
@pytest.mark.parametrize("damage", range(6))
def test_descendant_public_api_rejects_missing_rebased_or_wrong_root_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: str, damage: int,
) -> None:
    from tools import qualify_descendant_repository as qualifier

    root, ancestor = _repository(tmp_path)
    config = _config(tmp_path, root, ancestor)
    other, _ = _repository(tmp_path / "other")

    def unexpected_identity(*_args: object) -> None:
        pytest.fail("invalid public context reached Git/evidence validation")

    monkeypatch.setattr(qualifier, "descendant_repository_identity", unexpected_identity)
    candidate, path, pack, receipt = (
        (None, root, config.governed_source_pack, config.descendant_repository_receipt),
        (replace(config, external_authoring_argv=("altered",)), root,
         config.governed_source_pack, config.descendant_repository_receipt),
        (replace(config, current_checkout_root=other), other,
         config.governed_source_pack, config.descendant_repository_receipt),
        (config, other, config.governed_source_pack, config.descendant_repository_receipt),
        (replace(config, governed_source_pack=tmp_path / "other-pack"), root,
         tmp_path / "other-pack", config.descendant_repository_receipt),
        (replace(config, descendant_repository_receipt=tmp_path / "other-receipt.json"), root,
         config.governed_source_pack, tmp_path / "other-receipt.json"),
    )[damage]
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        if api == "record":
            qualifier._receipt_record(path, candidate)
        elif api == "issue":
            qualifier.issue_descendant_qualification_receipt(path, candidate, receipt)
        else:
            qualifier.verify_descendant_qualification_receipt(
                path, receipt, pack=pack, config=candidate,
            )
    assert not receipt.exists()


@pytest.mark.parametrize("api", ["issue", "verify"])
def test_descendant_rejects_unconfigured_receipt_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: str,
) -> None:
    from tools import qualify_descendant_repository as qualifier

    root, ancestor = _repository(tmp_path)
    config = _config(tmp_path, root, ancestor)
    alternate = config.evidence_root / "alternate.json"

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unconfigured receipt reached evidence validation")

    monkeypatch.setattr(qualifier, "_receipt_record", unexpected)
    monkeypatch.setattr(qualifier, "_read_evidence", unexpected)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        if api == "issue":
            qualifier.issue_descendant_qualification_receipt(root, config, alternate)
        else:
            qualifier.verify_descendant_qualification_receipt(
                root, alternate, pack=config.governed_source_pack, config=config,
            )
    assert not alternate.exists()


@pytest.mark.parametrize("damage", ["missing-parent", "parent-link", "dangling", "existing"])
def test_descendant_output_requires_existing_canonical_parent_and_absent_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str,
) -> None:
    from tools import qualify_descendant_repository as qualifier
    root, ancestor = _repository(tmp_path)
    config = _config(tmp_path, root, ancestor)
    output = config.descendant_repository_receipt
    if damage == "missing-parent":
        config.evidence_root.rmdir()
    elif damage == "parent-link":
        config.evidence_root.rename(tmp_path / "held-evidence")
        config.evidence_root.symlink_to(tmp_path / "held-evidence", target_is_directory=True)
    elif damage == "dangling":
        output.symlink_to(tmp_path / "nonexistent")
    else:
        output.write_bytes(b"preexisting\n")

    def unexpected(*_args: object) -> None:
        pytest.fail("unsafe output reached receipt capture")

    monkeypatch.setattr(qualifier, "_receipt_record", unexpected)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        qualifier.issue_descendant_qualification_receipt(root, config, output)
    if damage == "missing-parent":
        assert not output.parent.exists()
    elif damage == "dangling":
        assert output.is_symlink()
    elif damage == "existing":
        assert output.read_bytes() == b"preexisting\n"


def _commit(root: Path, name: str, value: str) -> str:
    (root / name).write_text(value)
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "add", name], cwd=root, check=True, capture_output=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [git, "commit", "-m", name], cwd=root, check=True, capture_output=True
    )
    return subprocess.check_output(  # noqa: S603
        [git, "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def test_descendant_identity_accepts_clean_multi_commit_history_and_rejects_drift(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    assert git is not None
    root = tmp_path / "runtime"
    root.mkdir()
    subprocess.run(  # noqa: S603
        [git, "init", "-b", "main"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603
        [git, "config", "user.name", "Descendant Test"], cwd=root, check=True
    )
    subprocess.run(  # noqa: S603
        [git, "config", "user.email", "descendant@example.invalid"],
        cwd=root,
        check=True,
    )
    ancestor = _commit(root, "audited.txt", "audited")
    descendant = _commit(root, "repair.txt", "repair")

    identity = descendant_repository_identity(root, ancestor)
    assert identity["repository_commit"] == descendant
    assert identity["repository_commit"] != ancestor
    assert len(identity["repository_file_root_sha256"]) == 64

    (root / "untracked.txt").write_text("dirty")
    with pytest.raises(ValueError, match="E_DESCENDANT_REPOSITORY"):
        descendant_repository_identity(root, ancestor)
    (root / "untracked.txt").unlink()
    with pytest.raises(ValueError, match="E_DESCENDANT_REPOSITORY"):
        descendant_repository_identity(root, "f" * 40)


def test_receipt_exclusive_create_failure_never_removes_competing_file(
    actual_matrix_candidate_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config = chain["config"]
    output = config.descendant_repository_receipt
    competitor = b"competitor\n"
    capture = qualifier._receipt_record

    def record(*args: Any, **kwargs: Any) -> dict[str, object]:
        result = capture(*args, **kwargs)
        output.write_bytes(competitor)
        return result

    monkeypatch.setattr(qualifier, "_receipt_record", record)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$") as caught:
        qualifier.issue_descendant_qualification_receipt(chain["root"], config, output)
    assert isinstance(caught.value.__cause__, FileExistsError)
    assert output.read_bytes() == competitor


def test_receipt_post_write_replacement_is_not_unlinked(
    actual_matrix_candidate_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config = chain["config"]
    output = config.descendant_repository_receipt
    competitor = b"replacement\n"
    calls = 0
    capture = qualifier._receipt_record

    def record(*args: Any, **kwargs: Any) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            output.rename(output.with_name("held-owned.json"))
            output.write_bytes(competitor)
            config.candidate_qualification_receipt.write_bytes(b"corrupt")
        return capture(*args, **kwargs)

    monkeypatch.setattr(qualifier, "_receipt_record", record)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        qualifier.issue_descendant_qualification_receipt(chain["root"], config, output)
    assert output.read_bytes() == competitor


def test_receipt_post_write_drift_removes_only_owned_output(
    actual_matrix_candidate_chain: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config = chain["config"]
    output = config.descendant_repository_receipt

    def failed_sync(_descriptor: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(qualifier.os, "fsync", failed_sync)
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$") as caught:
        qualifier.issue_descendant_qualification_receipt(chain["root"], config, output)
    assert isinstance(caught.value.__cause__, OSError)
    assert not output.exists()


def test_descendant_record_recursively_validates_full_and_supplemental_proofs(
    actual_matrix_candidate_chain: dict[str, Any],
) -> None:
    import tools.qualify_descendant_repository as qualifier

    chain = actual_matrix_candidate_chain
    config = chain["config"]
    record = qualifier._receipt_record(chain["root"], config)
    assert [name for name, *_ in chain["calls"]] == ["full", "full", "full", "environment"]
    assert record["full_repair_evidence_root_sha256"] == chain["full"]["evidence_root_sha256"]
    _write(config.qualification_evidence.p04_proof, {**chain["full"], "mutation_count": 104})
    with pytest.raises(ValueError, match="^E_DESCENDANT_REPOSITORY$"):
        qualifier._receipt_record(chain["root"], config)
