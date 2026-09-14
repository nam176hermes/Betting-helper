from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def tool():
    spec = importlib.util.spec_from_file_location(
        "part_b_inputs", ROOT / "authoring-tools/prepare_part_b_review_inputs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_inputs_preserve_history_and_reject_drift(tmp_path):
    m = tool()
    # Read the immutable predecessor, not the outputs under review, as the oracle.
    source = tmp_path / "authoring"
    source.mkdir()
    for name in (
        "authoring-tools",
        "authoring-tests",
        "plan-input",
        "authoring-fixtures",
    ):
        shutil.copytree(
            ROOT / name, source / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    originals = m.predecessor(ROOT)
    for name, data in originals.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    spec = m.targets(source, runtime, tmp_path / "evidence", tmp_path / "host")
    expected = m.build(source, originals, spec, "a" * 64)
    m.materialize(source, originals, expected)
    m.materialize(source, originals, expected)
    v1 = "pack/docs/configs/review-a.v1.json"
    assert (source / v1).read_bytes() == originals[v1]
    assert (
        source / "pack/docs/registries/baseline-replay-command-registry.v1.json"
    ).read_bytes() == originals[
        "pack/docs/registries/baseline-replay-command-registry.v1.json"
    ]
    a = json.loads((source / "pack/docs/configs/review-a.v2.json").read_text())
    assert a["input_roots"][1] == str(runtime)
    assert a["producer_environment"]["path_translation_sha256"] == "a" * 64
    assert a["network"] == "DENY" and len(a["input_mounts"]) == 5
    assert all(row["mode"] == "READ_ONLY" for row in a["input_mounts"])
    registry = json.loads(
        (source / "pack/docs/registries/task-command-registry.v1.json").read_text()
    )
    bindings = next(
        r for r in registry["commands"] if r["command_id"] == "V636_MIG0_T08_BINDINGS"
    )
    assert (
        Path(bindings["cwd"]) / bindings["argv"][bindings["argv"].index("--output") + 1]
        == runtime / "task-command-registry.json"
    )
    for filename, key in (
        ("registries/reviewer-role-registry.v1.json", "authoring_root_excluded"),
        ("security/review-trust-root.v1.json", "private_key_must_not_exist_under"),
    ):
        values = json.loads((source / "pack/docs" / filename).read_text())[key]
        assert (
            str(source) == values if isinstance(values, str) else str(source) in values
        )
    cfg = json.loads(
        (source / "pack/docs/configs/full-verifier-controller.v2.json").read_text()
    )
    assert cfg["current_checkout_root"] == str(runtime)
    assert cfg["governed_source_pack"] == str(source / "pack")
    assert cfg["external_authoring_command"]["cwd"] == str(source)
    assert all(not Path(p).exists() for p in cfg["receipts"].values())
    assert cfg["production_authority"] == "NONE"
    ownership = json.loads(
        (source / "pack/docs/registries/artifact-ownership.v1.json").read_text()
    )["entries"]
    before_paths = {
        row["path"] for row in json.loads(originals[
            "pack/docs/registries/artifact-ownership.v1.json"
        ])["entries"]
    }
    compiler = {row["path"]: row for row in ownership
                if row["classification"] == "GENERATED_OUTPUT"
                and row["path"].startswith("runtime/extension/")
                and row["path"] not in before_paths}
    assert len(compiler) == 37
    assert compiler["runtime/extension/dist/live/capture.js"]["source"] == {
        "path": "runtime/extension/src/live/capture.ts"
    }
    assert compiler["runtime/extension/.test-build/test/live/capture.test.js"]["source"] == {
        "path": "runtime/extension/test/live/capture.test.ts"
    }
    assert not any("/dist/test/" in path for path in compiler)
    assert a["producer_environment"]["native_dependency_root"].endswith(
        "native-dependency-closure-ef63da26-f87f-45ab-af76-dd2b9ef02c08"
    )
    changed = source / "pack/docs/configs/review-b.v2.json"
    changed.write_text("{}\n")
    with pytest.raises(ValueError, match="E_PART_B_INPUT_DRIFT"):
        m.materialize(source, originals, expected)
    assert changed.read_text() == "{}\n"


def test_overlapping_or_symlinked_roots_and_changed_predecessor_reject(tmp_path):
    m = tool()
    source = tmp_path / "source"
    source.mkdir()
    link = tmp_path / "link"
    link.symlink_to(source, target_is_directory=True)
    for runtime in (source, source / "child", link):
        with pytest.raises(ValueError, match="E_PART_B_INPUT_ROOT"):
            m.targets(source, runtime, tmp_path / "evidence", tmp_path / "host")
    fixture = source / "authoring-fixtures/part-b-review-predecessor.json"
    fixture.parent.mkdir()
    fixture.write_text("{}")
    with pytest.raises(ValueError, match="E_PART_B_PREDECESSOR"):
        m.predecessor(source)
    compiler = source / "authoring-fixtures/part-b-compiler-inputs.json"
    compiler.write_text("{}")
    with pytest.raises(ValueError, match="E_PART_B_COMPILER_INPUTS"):
        m.extend_compiler_ownership(source, {}, str(tmp_path / "runtime"))


def test_export_parent_alias_rejects_before_materialization(tmp_path):
    m = tool()
    source = tmp_path / "source"
    source.mkdir()
    for name in (
        "authoring-tools",
        "authoring-tests",
        "authoring-fixtures",
        "plan-input",
    ):
        (source / name).symlink_to(ROOT / name, target_is_directory=True)
    target = m.targets(
        source, tmp_path / "runtime", tmp_path / "evidence", tmp_path / "host"
    )
    with pytest.raises(ValueError, match="E_PART_B_EXPORT"):
        m.build(source, m.predecessor(ROOT), target, "a" * 64)
    assert not (source / "pack").exists()
