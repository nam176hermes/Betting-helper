from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tools import run_command_registry, verify_local
from tools.full_verifier_config import load_controller_config

ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONFIG = (
    ROOT / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json"
)
SOURCE_CONFIG_V2 = Path(
    "/home/thenam176/betting-helper/authoring-controller-config-worktree/pack/docs/configs/full-verifier-controller.v2.json"
)


def test_source_owned_controller_config_is_strict_and_fully_consumed() -> None:
    config = load_controller_config(SOURCE_CONFIG)
    assert config.current_checkout_root == ROOT
    assert config.production_authority == "NONE"
    assert (
        verify_local._validate_authoring_tests(
            config.external_authoring_tests, config.external_authoring_source_sha256
        )
        == config.external_authoring_source_sha256
    )
    with pytest.raises(ValueError, match="E_EXTERNAL_AUTHORING_TESTS"):
        verify_local._validate_authoring_tests(config.external_authoring_tests, "0" * 64)

    registry = run_command_registry.validate_registry()
    commands = run_command_registry.effective_candidate_commands(registry, config)
    assert {Path(str(command["cwd"])) for command in commands} == {ROOT}
    normative = next(
        command
        for command in commands
        if command["command_id"] == "QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS"
    )
    pack_index = normative["argv"].index("--pack") + 1
    runtime_index = normative["argv"].index("--runtime") + 1
    assert Path(normative["argv"][pack_index]) == config.governed_source_pack
    assert Path(normative["argv"][runtime_index]) == ROOT
    external = next(
        command
        for command in registry["commands"]
        if command["command_id"] == "VERIFY_EXTERNAL_AUTHORING_SOURCES"
    )
    assert external["argv"] == list(config.external_authoring_argv)
    assert external["cwd"] == str(config.external_authoring_cwd)

    environment = run_command_registry.execution_environment(config)
    assert Path(environment["UV_CACHE_DIR"]) == config.uv_cache
    assert Path(environment["npm_config_store_dir"]) == config.pnpm_store
    assert Path(environment["BH_CHROME_BINARY"]) == config.chrome_path


def test_missing_or_extra_config_field_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(SOURCE_CONFIG.read_text())
    payload.pop("pnpm_store")
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(broken)
    payload = json.loads(SOURCE_CONFIG.read_text())
    payload["unexpected"] = True
    broken.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(broken)


def _write_config_copy(tmp_path: Path, payload: dict[str, object]) -> Path:
    pack = tmp_path / "authoring" / "pack"
    source = pack / "docs/configs/full-verifier-controller.v1.json"
    source.parent.mkdir(parents=True)
    encoded = json.dumps(payload, sort_keys=True).encode()
    source.write_bytes(encoded)
    runtime = tmp_path / "runtime-config.json"
    runtime.write_bytes(encoded)
    return runtime


def test_evidence_and_receipts_cannot_overlap_protected_trees_or_aliases(
    tmp_path: Path,
) -> None:
    payload = json.loads(SOURCE_CONFIG.read_text())
    protected = tmp_path / "protected"
    protected.mkdir()
    payload["current_checkout_root"] = str(protected / "runtime")
    payload["governed_source_pack"] = str(protected / "authoring/pack")
    payload["external_authoring_tests"] = str(protected / "authoring/authoring-tests")
    payload["evidence_root"] = str(protected)
    receipts = payload["receipts"]
    assert isinstance(receipts, dict)
    receipts.update(
        {
            "authoring_repository": str(protected / "authoring-receipt.json"),
            "candidate_command_evidence": str(protected / "runtime/.local/command.json"),
            "candidate_qualification": str(protected / "runtime/.local/receipt.json"),
        }
    )
    config = _write_config_copy(tmp_path, payload)
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(config)

    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    payload["evidence_root"] = str(alias / "evidence")
    for key, name in zip(
        receipts,
        ("authoring.json", "command.json", "coverage.json", "issuance.json", "candidate.json"),
        strict=True,
    ):
        receipts[key] = str(alias / "evidence" / name)
    config = _write_config_copy(tmp_path / "alias-case", payload)
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(config)


def test_candidate_environment_forces_offline_resolution() -> None:
    config = load_controller_config(SOURCE_CONFIG)
    environment = run_command_registry.execution_environment(config)
    assert environment["UV_OFFLINE"] == "1"
    assert environment["npm_config_offline"] == "true"


def test_external_authoring_source_rejects_unbound_conftest(tmp_path: Path) -> None:
    config = load_controller_config(SOURCE_CONFIG)
    root = tmp_path / "authoring"
    shutil.copytree(config.external_authoring_tests, root / "authoring-tests")
    shutil.copytree(
        config.external_authoring_tests.parent / "authoring-tools",
        root / "authoring-tools",
    )
    (root / "authoring-tests/conftest.py").write_text("def pytest_runtest_setup(): pass\n")
    with pytest.raises(ValueError, match="E_EXTERNAL_AUTHORING_TESTS"):
        verify_local._validate_authoring_tests(
            root / "authoring-tests", config.external_authoring_source_sha256
        )


def test_external_authoring_environment_drops_python_and_pytest_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_controller_config(SOURCE_CONFIG)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "attacker"))
    environment = verify_local._external_authoring_environment(config)
    assert "PYTEST_ADDOPTS" not in environment
    assert "PYTHONPATH" not in environment
    python_index = config.external_authoring_argv.index("python")
    assert config.external_authoring_argv[python_index + 1] == "-I"
    assert config.external_authoring_argv[python_index + 2] == "-B"


def test_external_authoring_suite_is_executed_with_declared_argv_and_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_controller_config(SOURCE_CONFIG)
    seen: list[tuple[list[str], Path, dict[str, str]]] = []

    def run(argv: list[str], **kwargs: object) -> object:
        seen.append((argv, Path(str(kwargs["cwd"])), kwargs["env"]))  # type: ignore[arg-type]
        return type("Completed", (), {"returncode": 0, "stdout": b"ok", "stderr": b""})()

    monkeypatch.setattr(verify_local.subprocess, "run", run)
    record = verify_local._execute_external_authoring_suite(config)
    assert record["passed"] is True
    assert seen == [
        (
            list(config.external_authoring_argv),
            config.external_authoring_cwd,
            verify_local._external_authoring_environment(config),
        )
    ]
    assert str(config.external_authoring_tests) in config.external_authoring_argv


def test_candidate_receipt_is_postcondition_not_preflight_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_controller_config(SOURCE_CONFIG)
    seen: list[Path] = []

    def configured(identifier: str, path: Path | None, *, directory: bool) -> dict[str, object]:
        assert path is not None
        seen.append(path)
        return {"prerequisite_id": identifier, "path": str(path), "status": "PASS"}

    monkeypatch.setattr(verify_local, "_configured_path", configured)
    monkeypatch.setattr(verify_local, "sync_pack_assets", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_local, "_validate_bootstrap_receipt", lambda *_a: None)
    monkeypatch.setattr(verify_local, "_validate_authoring_tests", lambda *_a: None)
    monkeypatch.setattr(verify_local, "_validate_cache", lambda *_a: None)
    monkeypatch.setattr(verify_local.os, "access", lambda *_a: True)
    monkeypatch.setattr(verify_local, "_sha256_file", lambda _path: config.chrome_sha256)

    prerequisites = verify_local._full_prerequisites(config)
    assert all(item["status"] == "PASS" for item in prerequisites)
    assert config.candidate_qualification_receipt not in seen
    assert config.candidate_command_evidence not in seen


def test_failed_controller_cannot_be_promoted_by_stale_candidate_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = load_controller_config(SOURCE_CONFIG)
    monkeypatch.setattr(
        verify_local,
        "_full_prerequisites",
        lambda _config: [{"prerequisite_id": "all", "status": "PASS", "path": None}],
    )
    monkeypatch.setattr(verify_local, "_delegate_controller", lambda _config: 7)
    monkeypatch.setattr(
        verify_local,
        "_validate_candidate_postcondition",
        lambda _config: (_ for _ in ()).throw(AssertionError("must not validate stale receipt")),
    )

    assert verify_local._run_full(config) == 7
    assert json.loads(capsys.readouterr().out.splitlines()[0])["status"] == "READY"


def test_controller_preserves_t01_t02_t03_order_and_stops_before_issuance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = load_controller_config(SOURCE_CONFIG)
    config = replace(
        original,
        evidence_root=tmp_path,
        candidate_command_evidence=tmp_path / "V636-P07-T01.json",
        proof_coverage_evidence=tmp_path / "V636-P07-T02.json",
        candidate_issuance_evidence=tmp_path / "V636-P07-T03.json",
        candidate_qualification_receipt=tmp_path / "CANDIDATE_QUALIFICATION.json",
    )
    commands = [
        {"command_id": command_id, "cwd": str(ROOT), "argv": [command_id], "expected_exit": 0}
        for command_id in (
            "VERIFY_V636_P07_T01",
            "VERIFY_V636_P07_T02",
            "VERIFY_V636_P07_T03",
        )
    ]
    monkeypatch.setattr(
        verify_local,
        "_execute_external_authoring_suite",
        lambda _config: {"passed": True},
    )
    monkeypatch.setattr(verify_local, "_validate_bootstrap_receipt", lambda *_a: None)
    monkeypatch.setattr(verify_local, "_validate_authoring_tests", lambda *_a: None)
    monkeypatch.setattr(
        run_command_registry,
        "validate_registry",
        lambda: {"commands": commands},
    )
    seen: list[str] = []

    def evaluate(command: dict[str, object], **_kwargs: object) -> dict[str, object]:
        command_id = str(command["command_id"])
        seen.append(command_id)
        if command_id == "VERIFY_V636_P07_T01":
            config.candidate_command_evidence.write_text("{}")
        return {
            "command_id": command_id,
            "passed": command_id != "VERIFY_V636_P07_T02",
        }

    monkeypatch.setattr(run_command_registry, "evaluate_invocation", evaluate)
    assert verify_local._delegate_controller(config) == 1
    assert seen == ["VERIFY_V636_P07_T01", "VERIFY_V636_P07_T02"]
    assert not config.candidate_qualification_receipt.exists()


@pytest.mark.parametrize("drift", ["source", "dirty"])
def test_post_external_authoring_drift_blocks_t01(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    original = load_controller_config(SOURCE_CONFIG)
    authoring = tmp_path / "authoring"
    shutil.copytree(original.external_authoring_tests, authoring / "authoring-tests")
    shutil.copytree(
        original.external_authoring_tests.parent / "authoring-tools",
        authoring / "authoring-tools",
    )
    config = replace(original, external_authoring_tests=authoring / "authoring-tests")
    seen: list[str] = []

    def external(_config: object) -> dict[str, object]:
        if drift == "source":
            (authoring / "authoring-tests/conftest.py").write_text("# post-suite drift\n")
        return {"passed": True}

    def receipt(*_args: object) -> None:
        if drift == "dirty":
            raise ValueError("receipt content mismatch")

    monkeypatch.setattr(verify_local, "_execute_external_authoring_suite", external)
    monkeypatch.setattr(verify_local, "_validate_bootstrap_receipt", receipt)
    monkeypatch.setattr(
        run_command_registry,
        "validate_registry",
        lambda: seen.append("T01-visible") or {"commands": []},
    )

    assert verify_local._delegate_controller(config) == 1
    assert seen == []


def _write_v2_config_copy(tmp_path: Path) -> Path:
    payload = json.loads(SOURCE_CONFIG_V2.read_text())
    pack = tmp_path / "authoring/pack"
    runtime = tmp_path / "runtime"
    evidence = tmp_path / "evidence"
    external = tmp_path / "authoring/authoring-tests"
    payload.update(
        current_checkout_root=str(runtime),
        governed_source_pack=str(pack),
        evidence_root=str(evidence),
        external_authoring_tests=str(external),
    )
    receipts = payload["receipts"]
    assert isinstance(receipts, dict)
    for key, value in receipts.items():
        receipts[key] = str(evidence / Path(str(value)).name)
    qualification = payload["qualification_evidence"]
    assert isinstance(qualification, dict)
    for key, value in qualification.items():
        qualification[key] = str(evidence / "qualification" / key / Path(str(value)).name)
    source = pack / "docs/configs/full-verifier-controller.v2.json"
    source.parent.mkdir(parents=True)
    encoded = json.dumps(payload, sort_keys=True).encode()
    source.write_bytes(encoded)
    candidate = tmp_path / "runtime-config.v2.json"
    candidate.write_bytes(encoded)
    return candidate


def test_v2_controller_preserves_exact_descendant_and_qualification_binding(
    tmp_path: Path,
) -> None:
    path = _write_v2_config_copy(tmp_path)
    config = load_controller_config(path)
    payload = json.loads(path.read_text())
    assert config.schema_version == "full-verifier-controller/v2"
    assert config.audited_runtime_ancestor == "7cd7ab14652458608386d940bdc7764910044f6a"
    assert config.descendant_repository_receipt == Path(
        payload["receipts"]["descendant_repository"]
    )
    assert config.qualification_evidence.full_repair_aggregate == Path(
        payload["qualification_evidence"]["full_repair_aggregate"]
    )
    binding = config.binding()
    assert binding["schema_version"] == "full-verifier-controller-binding/v2"
    assert binding["audited_runtime_ancestor"] == config.audited_runtime_ancestor
    assert binding["qualification_evidence"] == payload["qualification_evidence"]
    assert binding["receipts"]["descendant_repository"] == str(config.descendant_repository_receipt)


def test_v2_controller_rejects_mixed_or_incomplete_descendant_fields(tmp_path: Path) -> None:
    path = _write_v2_config_copy(tmp_path)
    payload = json.loads(path.read_text())
    for damage in ("missing-audited", "missing-qualification", "extra-repo0"):
        changed = json.loads(json.dumps(payload))
        if damage == "missing-audited":
            changed.pop("audited_runtime_ancestor")
        elif damage == "missing-qualification":
            changed["qualification_evidence"].pop("p04_proof")
        else:
            changed["repo0_receipt"] = "forbidden"
        source = (
            Path(changed["governed_source_pack"]) / "docs/configs/full-verifier-controller.v2.json"
        )
        encoded = json.dumps(changed, sort_keys=True).encode()
        source.write_bytes(encoded)
        path.write_bytes(encoded)
        with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
            load_controller_config(path)


def _retained_manifest(recorded: str, boundary: str, content: bytes) -> dict[str, object]:
    return {
        "schema_version": "retained-artifact-manifest/v1",
        "recorded_boundaries": [boundary],
        "files": [
            {
                "recorded_locator": recorded,
                "recorded_boundary": boundary,
                "copied_relative_path": "files/input.json",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }


def test_retained_artifact_io_maps_windows_and_wsl_aliases_without_fallback(
    tmp_path: Path,
) -> None:
    from tools.retained_artifact_io import RetainedArtifactIO

    content = b'{"actual":true}'
    physical = tmp_path / "closure"
    copied = physical / "files/input.json"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(content)
    recorded = "/mnt/c/Users/thenam/Documents/run/input.json"
    boundary = "/mnt/c/Users/thenam/Documents/run"
    artifacts = RetainedArtifactIO.from_manifest(
        _retained_manifest(recorded, boundary, content), physical
    )

    assert artifacts.read_bytes(recorded, recorded_boundary=boundary) == content
    assert (
        artifacts.read_bytes(
            r"C:\Users\thenam\Documents\run\input.json",
            recorded_boundary=r"C:\Users\thenam\Documents\run",
        )
        == content
    )
    assert (
        artifacts.read_bytes(
            r"\\wsl.localhost\Ubuntu\mnt\c\Users\thenam\Documents\run\input.json",
            recorded_boundary=r"\\wsl.localhost\Ubuntu\mnt\c\Users\thenam\Documents\run",
        )
        == content
    )
    copied.write_bytes(b"changed")
    with pytest.raises(ValueError, match="E_RETAINED_ARTIFACT"):
        artifacts.read_bytes(recorded, recorded_boundary=boundary)


def test_retained_artifact_io_rejects_non_closed_or_aliased_manifests(
    tmp_path: Path,
) -> None:
    from tools.retained_artifact_io import RetainedArtifactIO

    content = b"evidence"
    physical = tmp_path / "closure"
    copied = physical / "files/input.json"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(content)
    recorded = "/mnt/c/Users/thenam/Documents/run/input.json"
    boundary = "/mnt/c/Users/thenam/Documents/run"
    base = _retained_manifest(recorded, boundary, content)

    for damage in ("extra", "duplicate-locator", "escaping-target", "symlink", "hardlink"):
        manifest = json.loads(json.dumps(base))
        if damage == "extra":
            (physical / "extra.txt").write_text("undeclared")
        elif damage == "duplicate-locator":
            manifest["files"].append(
                {
                    **manifest["files"][0],
                    "recorded_locator": r"C:\Users\thenam\Documents\run\input.json",
                    "copied_relative_path": "files/other.json",
                }
            )
            (physical / "files/other.json").write_bytes(content)
        elif damage == "escaping-target":
            manifest["files"][0]["copied_relative_path"] = "../outside.json"
        elif damage == "symlink":
            copied.unlink()
            os.symlink(tmp_path / "outside.json", copied)
        else:
            alias = tmp_path / "hardlink.json"
            os.link(copied, alias)
        with pytest.raises(ValueError, match="E_RETAINED_ARTIFACT"):
            RetainedArtifactIO.from_manifest(manifest, physical)
        if damage == "extra":
            (physical / "extra.txt").unlink()
        elif damage == "duplicate-locator":
            (physical / "files/other.json").unlink()
        elif damage == "symlink":
            copied.unlink()
            copied.write_bytes(content)
        elif damage == "hardlink":
            alias.unlink()

    artifacts = RetainedArtifactIO.from_manifest(base, physical)
    with pytest.raises(ValueError, match="E_RETAINED_ARTIFACT"):
        artifacts.read_bytes("/undeclared/input.json", recorded_boundary="/undeclared")

    original_files = physical / "files-original"
    (physical / "files").rename(original_files)
    outside_files = tmp_path / "outside-files"
    outside_files.mkdir()
    (outside_files / "input.json").write_bytes(content)
    os.symlink(outside_files, physical / "files")
    with pytest.raises(ValueError, match="E_RETAINED_ARTIFACT"):
        artifacts.physical_path(recorded, recorded_boundary=boundary)


def test_sealed_v2_controller_reads_only_manifest_authorized_copies(
    tmp_path: Path,
) -> None:
    from tools.retained_artifact_io import RetainedArtifactIO

    config_path = _write_v2_config_copy(tmp_path / "fixture")
    payload = json.loads(config_path.read_text())
    raw = config_path.read_bytes()
    recorded_config = "/review/config/full-verifier-controller.v2.json"
    recorded_source = (
        payload["governed_source_pack"] + "/docs/configs/full-verifier-controller.v2.json"
    )
    closure = tmp_path / "closure"
    (closure / "config").mkdir(parents=True)
    (closure / "config/controller.json").write_bytes(raw)
    (closure / "config/source-copy.json").write_bytes(raw)
    rows = []
    for locator, boundary, relative in (
        (recorded_config, "/review", "config/controller.json"),
        (recorded_source, payload["governed_source_pack"], "config/source-copy.json"),
    ):
        rows.append(
            {
                "recorded_locator": locator,
                "recorded_boundary": boundary,
                "copied_relative_path": relative,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    artifacts = RetainedArtifactIO.from_manifest(
        {
            "schema_version": "retained-artifact-manifest/v1",
            "recorded_boundaries": ["/review", payload["governed_source_pack"]],
            "files": rows,
        },
        closure,
    )
    config_path.unlink()
    source_copy = (
        Path(payload["governed_source_pack"]) / "docs/configs/full-verifier-controller.v2.json"
    )
    source_copy.unlink()

    sealed = load_controller_config(
        closure / "config/controller.json",
        mode="SEALED",
        artifacts=artifacts,
        recorded_locator=recorded_config,
    )
    assert sealed.binding()["qualification_evidence"] == payload["qualification_evidence"]
    (closure / "config/source-copy.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(
            closure / "config/controller.json",
            mode="SEALED",
            artifacts=artifacts,
            recorded_locator=recorded_config,
        )


def test_controller_modes_reject_mixed_live_and_sealed_inputs(tmp_path: Path) -> None:
    path = _write_v2_config_copy(tmp_path)
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(path, mode="SEALED")
    with pytest.raises(ValueError, match="E_CONTROLLER_CONFIG"):
        load_controller_config(path, artifacts=object(), recorded_locator=str(path))
