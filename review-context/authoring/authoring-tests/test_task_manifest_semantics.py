from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "task_manifest", ROOT / "authoring-tools/validate_task_manifest.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskManifestSemanticsTests(unittest.TestCase):
    def test_task_manifest_rejects_placeholders_unknown_dependencies_and_production_authority(self) -> None:
        tool = load_tool()
        manifest = json.loads((ROOT / "pack/docs/tasks/task-manifest.v6.3.6.json").read_text())
        commands = [
            command
            for name in (
                "task-command-registry.v1.json",
                "review-command-registry.v1.json",
                "cybersecurity-command-registry.v1.json",
                "baseline-replay-command-registry.v1.json",
            )
            for command in json.loads((ROOT / "pack/docs/registries" / name).read_text())["commands"]
        ]
        owned_paths = {
            entry["path"]
            for entry in json.loads((ROOT / "pack/docs/registries/artifact-ownership.v1.json").read_text())["entries"]
        }
        self.assertEqual(
            tool.validate_task_manifest_semantics(manifest, commands, owned_paths),
            {"result": "PASS", "task_count": 62, "command_count": 222},
        )
        cases = [
            (lambda value: value.update(authorized_production_phases="PAPER"), "E_PRODUCTION_AUTHORITY"),
            (lambda value: value["tasks"][1].update(dependencies=["UNKNOWN"]), "E_DEPENDENCY_UNKNOWN_OR_FUTURE"),
            (lambda value: value["tasks"][0].update(rollback=[]), "E_EMPTY_ROLLBACK"),
            (lambda value: value.update(declared_task_count=0), "E_TASK_COUNT"),
        ]
        for mutate, error in cases:
            with self.subTest(error=error):
                changed = copy.deepcopy(manifest)
                mutate(changed)
                with self.assertRaisesRegex(ValueError, error):
                    tool.validate_task_manifest_semantics(changed, commands, owned_paths)
        changed_commands = copy.deepcopy(commands)
        changed_commands[0]["argv"] = ["TODO"]
        with self.assertRaisesRegex(ValueError, "E_COMMAND_PLACEHOLDER"):
            tool.validate_task_manifest_semantics(manifest, changed_commands, owned_paths)
        changed = copy.deepcopy(manifest)
        changed["tasks"][0]["exact_files"].append("runtime/unowned.py")
        with self.assertRaisesRegex(ValueError, "E_UNOWNED"):
            tool.validate_task_manifest_semantics(changed, commands, owned_paths)


if __name__ == "__main__":
    unittest.main()
