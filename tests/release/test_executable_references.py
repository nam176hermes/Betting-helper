import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.vendor import pack_root
from tests.seal.test_pack_assembly import (
    current_chain as assembly_chain,
)
from tools.run_command_registry import candidate_commands, validate_registry
from tools.verify_executable_references import verify_executable_references

ROOT = Path(__file__).parents[2]


def _replace_mapped_json_or_source(
    destination: Path,
    locator: str,
    raw: bytes,
    named_relative: str,
) -> None:
    """Coherently rehash a disposable transport, never actual qualification data."""
    manifest_path = destination / "evidence/retained-artifact-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    row = next(row for row in manifest["files"] if row["recorded_locator"] == locator)
    (destination / "evidence/retained" / row["copied_relative_path"]).write_bytes(raw)
    (destination / named_relative).write_bytes(raw)
    row.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    manifest_path.write_text(json.dumps(manifest))


@pytest.fixture
def current_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    # Approved small real manifest, BEFORE official fixture sync/qualification.
    # Both LIVE vendor and copied source retain identical governing declarations.
    from tests.release import test_descendant_repository_qualification as receipt_tests

    sync = receipt_tests._sync_fixture_sources

    def projected_sync(source: Path, pack: Path, *args: Any) -> None:
        path = pack / "docs/tasks/task-manifest.v6.3.6.json"
        manifest = json.loads(path.read_bytes())
        manifest["tasks"] = [
            task
            for task in manifest["tasks"]
            if task["task_id"]
            in {
                "V636-BOOT0-T01",
                "V636-BOOT0-T02",
                "V636-BOOT0-T03",
                "V636-P00-T03",
                "V636-P06-T01",
                "V636-P07-T01",
                "V636-P07-T02",
                "V636-P07-T03",
                "V636-P09-T01",
            }
        ]
        assert len(manifest["tasks"]) == 9
        path.write_text(json.dumps(manifest))
        sync(source, pack, *args)

    monkeypatch.setattr(receipt_tests, "_sync_fixture_sources", projected_sync)
    chain = assembly_chain.__wrapped__(tmp_path, monkeypatch)
    print(
        "TEST_ONLY nine actual task rows qualified before transport; not full source qualification"
    )
    return chain


def test_mapped_python_symbol_keeps_recorded_language(tmp_path: Path) -> None:
    from tools.verify_executable_references import _symbol

    transported = tmp_path / "content.bin"
    transported.write_text("def present():\n    return 1\n")
    assert _symbol(transported, "present", recorded_suffix=".py")
    assert not _symbol(transported, "missing", recorded_suffix=".py")


def test_current_reference_context_cannot_fall_back_to_legacy(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="E_EXECUTABLE_REFERENCE"):
        verify_executable_references(tmp_path, tmp_path, artifacts=object())


def test_sealed_references_use_recorded_context_without_original_roots(
    current_chain: dict[str, Any],
) -> None:
    import shutil

    from tests.seal.test_pack_assembly import _assemble
    from tools.assemble_review_pack import load_sealed_assembly_context
    from tools.qualify_descendant_repository import verify_descendant_qualification_receipt

    chain = current_chain
    config = chain["config"]
    destination = chain["directory"] / "delivered"
    _assemble(chain, destination)
    shutil.rmtree(config.governed_source_pack.parent)
    shutil.rmtree(config.evidence_root)
    shutil.rmtree(chain["directory"] / "inert")
    # Issuance config is inside the LIVE runtime; deleting it would dirty the
    # required current Git checkout. SEALED still must use its separate .bin copy.
    copied_config, artifacts = load_sealed_assembly_context(
        destination,
        destination / "docs/configs/full-verifier-controller.v2.json",
        str(config.source_path),
        destination / "evidence/retained-artifact-manifest.json",
        destination / "evidence/retained",
    )
    assert (
        verify_descendant_qualification_receipt(
            chain["root"],
            config.descendant_repository_receipt,
            pack=config.governed_source_pack,
            config=copied_config,
            artifacts=artifacts,
        )
        == chain["receipt"]
    )
    assert (
        verify_executable_references(
            chain["root"],
            destination,
            sealed=True,
            config=copied_config,
            artifacts=artifacts,
        )["result"]
        == "PASS"
    )
    # Rehash both the named and .bin copies: transport integrity alone cannot
    # rescue a nonexistent Python symbol or a malformed Python AST.
    locator = str(
        config.governed_source_pack.parent / "plan-input/bootstrap/create_authoring_workspace.py"
    )
    named = "authoring-source/bootstrap/create_authoring_workspace.py"
    original_python = (destination / named).read_bytes()
    for raw in (b"def unrelated():\n    pass\n", b"def broken(:\n"):
        _replace_mapped_json_or_source(destination, locator, raw, named)
        copied_config, artifacts = load_sealed_assembly_context(
            destination,
            destination / "docs/configs/full-verifier-controller.v2.json",
            str(config.source_path),
            destination / "evidence/retained-artifact-manifest.json",
            destination / "evidence/retained",
        )
        with pytest.raises(ValueError, match="E_EXECUTABLE_REFERENCE"):
            verify_executable_references(
                chain["root"], destination, sealed=True, config=copied_config, artifacts=artifacts
            )
    _replace_mapped_json_or_source(destination, locator, original_python, named)
    relative = "docs/tasks/task-manifest.v6.3.6.json"
    original_manifest = (destination / relative).read_bytes()
    for damage in ("pointer", "command", "path", "reference-shape"):
        manifest = json.loads(original_manifest)
        task = manifest["tasks"][0]
        if damage == "pointer":
            task["exact_schema_refs"] = [
                "pack/docs/configs/full-verifier-controller.v2.json#/missing"
            ]
        elif damage == "command":
            task["exact_command_ids"] = ["UNDECLARED_COMMAND"]
        elif damage == "path":
            task["exact_files"] = ["pack/docs/../outside.py"]
        else:
            task["exact_files"] = None
        _replace_mapped_json_or_source(
            destination,
            str(config.governed_source_pack / relative),
            json.dumps(manifest).encode(),
            relative,
        )
        # Malformed governing references now fail at the independent LIVE
        # metadata binding, even when the disposable union is coherently rehashed.
        from tools.retained_artifact_io import RetainedArtifactIO

        artifacts = RetainedArtifactIO.from_manifest(
            json.loads((destination / "evidence/retained-artifact-manifest.json").read_bytes()),
            destination / "evidence/retained",
        )
        with pytest.raises(ValueError, match="E_EXECUTABLE_REFERENCE"):
            verify_executable_references(
                chain["root"], destination, sealed=True, config=copied_config, artifacts=artifacts
            )


def test_current_registered_assembly_and_reference_cli_inputs(
    current_chain: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sys

    from tools import assemble_review_pack as assembly
    from tools import verify_executable_references as references

    chain, config = current_chain, current_chain["config"]
    destination = chain["directory"] / "cli-pack"
    registry = json.loads(
        (config.governed_source_pack / "docs/registries/task-command-registry.v1.json").read_bytes()
    )
    review = json.loads(
        (
            config.governed_source_pack / "docs/registries/review-command-registry.v1.json"
        ).read_bytes()
    )
    for command_id, module in (("VERIFY_V636_P09_T01", assembly), ("A_CHECK_SOURCE", references)):
        command = next(
            row
            for row in [*registry["commands"], *review["commands"]]
            if row["command_id"] == command_id
        )
        tool_index = next(
            index
            for index, token in enumerate(command["argv"])
            if token.endswith("tools/" + module.__name__.split(".")[-1] + ".py")
        )
        argv = command["argv"][tool_index:]
        values = {
            "--source": str(config.governed_source_pack),
            "--destination": str(destination),
            "--pack": str(destination),
            "--config": str(
                config.source_path
                if module is assembly
                else destination / "docs/configs/full-verifier-controller.v2.json"
            ),
            "--recorded-config": str(config.source_path),
            "--retained-manifest": str(destination / "evidence/retained-artifact-manifest.json"),
            "--retained-root": str(destination / "evidence/retained"),
        }
        for flag, value in values.items():
            if flag in argv:
                argv[argv.index(flag) + 1] = value
        monkeypatch.setattr(sys, "argv", argv)
        module.main()
        assert "PASS" in capsys.readouterr().out
        if module is references:
            for invalid in (argv[:-2], ["tool", "--mode", "candidate", *argv[3:]]):
                monkeypatch.setattr(sys, "argv", invalid)
                with pytest.raises(ValueError, match="E_EXECUTABLE_REFERENCE"):
                    module.main()


def test_sealed_references_never_exempt_required_post_p06_inputs(
    current_chain: dict[str, Any],
) -> None:
    from tests.seal.test_pack_assembly import _assemble, _load

    chain = current_chain
    destination = chain["directory"] / "required-input"
    _assemble(chain, destination)
    config, artifacts = _load(chain, destination)
    for path in (config.candidate_issuance_evidence, config.descendant_repository_receipt):
        physical = artifacts.physical_path(
            str(path), recorded_boundary=artifacts.recorded_boundary(str(path))
        )
        raw = physical.read_bytes()
        physical.unlink()
        try:
            with pytest.raises(ValueError, match="E_EXECUTABLE_REFERENCE"):
                verify_executable_references(
                    chain["root"], destination, sealed=True, config=config, artifacts=artifacts
                )
        finally:
            physical.write_bytes(raw)


def test_every_executable_reference_resolves_without_placeholder() -> None:
    if pack_root(ROOT) == ROOT / "vendor/hybrid-discovery-v6.3.6":
        assert len(candidate_commands(validate_registry(ROOT / "task-command-registry.json"))) == 45
        return
    result = verify_executable_references()
    assert result["result"] == "PASS"
    assert isinstance(result["command_count"], int)
    assert result["command_count"] >= 45

    with pytest.raises(ValueError, match="E_EXECUTABLE_REFERENCE"):
        verify_executable_references(runtime_root=Path("/missing"))


@pytest.mark.parametrize(
    "source, present",
    [
        ("// testSecurityBoundary\nexport const other = 1;", False),
        ('export const text = "testSecurityBoundary";', False),
        ("export function testSecurityBoundaryRenamed() {}", False),
        ("export function testSecurityBoundary() {}", True),
        ("export const testSecurityBoundary = () => {};", True),
    ],
)
def test_typescript_reference_requires_declaration(
    tmp_path: Path, source: str, present: bool
) -> None:
    from tools.verify_executable_references import _symbol

    path = tmp_path / "transport.bin"
    path.write_text(source)
    assert _symbol(path, "testSecurityBoundary", recorded_suffix=".ts") is present


def test_typescript_reference_uses_projected_node_without_mise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shutil import which

    from tools.verify_executable_references import _symbol

    binary = which("node")
    assert binary is not None
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "node").symlink_to(Path(binary).resolve())
    monkeypatch.setenv("PATH", str(bin_dir))
    source = tmp_path / "transport.bin"
    source.write_text("export const testSecurityBoundary = () => {};\n")
    assert _symbol(source, "testSecurityBoundary", recorded_suffix=".ts")
    assert not _symbol(source, "missing", recorded_suffix=".ts")
