from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load() -> object:
    path = ROOT / "authoring-tools/apply_full_verifier_followup.py"
    spec = importlib.util.spec_from_file_location("controller_amendment", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generates_owned_receipt_dag_and_complete_compiler_output_map(tmp_path: Path) -> None:
    tool = _load()
    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "pack", pack)
    result = tool.apply_full_verifier_followup(pack)
    assert result["result"] == "PASS"
    assert tool.apply_full_verifier_followup(pack)["changed"] == 0

    tasks = json.loads((pack / "docs/tasks/task-manifest.v6.3.6.json").read_text())["tasks"]
    by_task = {task["task_id"]: task for task in tasks}
    assert by_task["V636-P07-T02"]["dependencies"] == ["V636-P07-T01"]
    assert by_task["V636-P07-T03"]["dependencies"] == ["V636-P07-T02"]
    assert by_task["V636-P07-T01"]["outputs"]
    assert by_task["V636-P07-T02"]["outputs"]
    assert by_task["V636-P07-T03"]["outputs"]

    ownership = json.loads((pack / "docs/registries/artifact-ownership.v1.json").read_text())
    owned = {entry["path"]: entry for entry in ownership["entries"]}
    for relative in (
        "runtime/extension/dist/contracts/clock-coherence.js",
        "runtime/extension/.test-build/src/contracts/clock-coherence.js",
        "runtime/extension/.test-build/test-harness/repair-probe.js",
        "runtime/extension/.test-build/test/repairs/clock-raw-input.test.js",
        "runtime/extension/.test-build/test/repairs/spool-persistence.test.js",
    ):
        assert relative in owned
        assert owned[relative]["classification"] == "GENERATED_OUTPUT"
        assert owned[relative]["source"]["path"].endswith(".ts")

    command_io = json.loads((pack / "docs/registries/command-io.v1.json").read_text())
    io = {entry["command_id"]: entry for entry in command_io["commands"]}
    assert io["ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT"]["outputs"]
    assert io["VERIFY_EXTERNAL_AUTHORING_SOURCES"]["input_directories"]
    assert io["VERIFY_V636_P07_T01"]["outputs"]
    assert io["VERIFY_V636_P07_T02"]["outputs"]
    assert io["VERIFY_V636_P07_T03"]["outputs"]
