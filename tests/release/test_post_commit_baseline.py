import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.qualify_zero_parent_baseline import _normative_source_set, _registry
from tools.run_command_registry import candidate_commands, validate_registry

RUNTIME = Path(__file__).resolve().parents[2]
FINAL_ROOT = "/home/thenam176/betting-helper/discovery-runtime-v6.3.6"


def test_normative_source_set_uses_normalized_plan_hashes(tmp_path: Path) -> None:
    source = tmp_path / "docs/source.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"{}")
    registry = tmp_path / "docs/registries/normative-source-map.v1.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": "normative-source-map/v1",
                "owner_phase": "MIG0",
                "inherited_entries": [],
                "plan_entries": [
                    {
                        "plan_source": "docs/source.json",
                        "vendor_relative": "docs/source.json",
                        "source_sha256": "0" * 64,
                        "plan_sha256": hashlib.sha256(b"{}").hexdigest(),
                    }
                ],
            }
        )
    )

    _map_hash, _source_root, count = _normative_source_set(tmp_path)

    assert count == "1"


def test_normative_source_set_replays_from_closed_copy_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    from tools.retained_artifact_io import RetainedArtifactIO

    pack = tmp_path / "original-pack"
    source = pack / "docs/source.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"{}")
    registry = pack / "docs/registries/normative-source-map.v1.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": "normative-source-map/v1",
                "owner_phase": "MIG0",
                "inherited_entries": [],
                "plan_entries": [
                    {
                        "plan_source": "docs/source.json",
                        "vendor_relative": "docs/source.json",
                        "plan_sha256": hashlib.sha256(b"{}").hexdigest(),
                    }
                ],
            }
        )
    )
    expected = _normative_source_set(pack)
    closure = tmp_path / "closure"
    copied_registry = closure / "files/map.json"
    copied_source = closure / "files/source.json"
    copied_registry.parent.mkdir(parents=True)
    copied_registry.write_bytes(registry.read_bytes())
    copied_source.write_bytes(source.read_bytes())
    manifest = {
        "schema_version": "retained-artifact-manifest/v1",
        "recorded_boundaries": [str(pack)],
        "files": [
            {
                "recorded_locator": str(registry),
                "recorded_boundary": str(pack),
                "copied_relative_path": "files/map.json",
                "size_bytes": copied_registry.stat().st_size,
                "sha256": hashlib.sha256(copied_registry.read_bytes()).hexdigest(),
            },
            {
                "recorded_locator": str(source),
                "recorded_boundary": str(pack),
                "copied_relative_path": "files/source.json",
                "size_bytes": copied_source.stat().st_size,
                "sha256": hashlib.sha256(copied_source.read_bytes()).hexdigest(),
            },
        ],
    }
    artifacts = RetainedArtifactIO.from_manifest(manifest, closure)
    shutil.rmtree(pack)

    assert _normative_source_set(pack, artifacts=artifacts) == expected
    copied_source.write_bytes(b'{"tampered":true}')
    with pytest.raises(ValueError, match="E_RETAINED_ARTIFACT"):
        _normative_source_set(pack, artifacts=artifacts)


def test_baseline_qualifier_cli_resolves_runtime_modules(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "baseline-replay-command-registry/v1",
                "commands": [],
                "runtime_root": str(root),
                "source_registry": "pack/docs/registries/task-command-registry.v1.json",
                "rule": "test",
            }
        )
    )
    completed = subprocess.run(  # noqa: S603 - fixed local interpreter and argv
        [
            "/usr/bin/python3.12",
            "tools/qualify_zero_parent_baseline.py",
            "--root",
            str(root),
            "--receipt",
            str(tmp_path / "receipt.json"),
            "--registry",
            str(registry),
        ],
        cwd=RUNTIME,
        capture_output=True,
    )
    assert b"ModuleNotFoundError" not in completed.stderr


def _runtime_with_current_registry(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    vendor = root / "vendor/hybrid-discovery-v6.3.6/docs/registries"
    vendor.mkdir(parents=True)
    (root / "task-command-registry.json").write_bytes(
        (RUNTIME / "task-command-registry.json").read_bytes()
    )
    (vendor / "task-command-registry.v1.json").write_bytes(
        (RUNTIME / "task-command-registry.json").read_bytes()
    )
    return root


def test_full_registry_replays_in_actual_committed_repository(tmp_path: Path) -> None:
    root = _runtime_with_current_registry(tmp_path)
    registry = tmp_path / "pack/docs/registries/baseline-replay-command-registry.v1.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        (
            RUNTIME / "vendor/hybrid-discovery-v6.3.6/docs/registries/"
            "baseline-replay-command-registry.v1.json"
        )
        .read_text()
        .replace(FINAL_ROOT, str(root))
    )

    commands = _registry(registry, root)

    assert len(commands) == 45
    assert all(
        "hybrid-discovery-v6.3.6-authoring" not in token
        for command in commands
        for token in command["argv"]
    )
    normative = next(
        command for command in commands
        if command["command_id"] == "BASELINE__QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS"
    )
    assert "/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6" in normative["argv"]
    assert [command["command_id"] for command in commands] == [
        f"BASELINE__{command['command_id']}"
        for command in candidate_commands(validate_registry(root / "task-command-registry.json"))
    ]

    mutated = json.loads(registry.read_text())
    mutated["commands"][0]["argv"] = ["true"]
    registry.write_text(json.dumps(mutated))
    with pytest.raises(ValueError, match="E_ZERO_PARENT_BASELINE"):
        _registry(registry, root)
