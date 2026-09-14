from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "command_registry", ROOT / "authoring-tools/build_task_command_registry.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CommandRegistryGenerationTests(unittest.TestCase):
    def test_registry_has_exact_successor_paths_and_no_placeholders(self) -> None:
        tool = load_tool()
        manifest = json.loads((ROOT / "pack/docs/tasks/task-manifest.v6.3.6.json").read_text())
        source = json.loads((ROOT / "pack/docs/registries/task-command-registry.v1.json").read_text())
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.json"
            source_path.write_text(json.dumps(source), encoding="utf-8")
            configs = root / "configs"
            configs.mkdir()
            names = ("review-a.v1.json", "review-b.v1.json", "review-aggregation.v1.json", "review-authority.v1.json")
            for name in names:
                (configs / name).write_text("{}", encoding="utf-8")
            output = root / "runtime/task-command-registry.json"
            result = tool.build_task_command_registry(manifest, source_path, configs, output)
            self.assertEqual(result["command_count"], len(source["commands"]))
            self.assertEqual(result["review_config_count"], 4)
            self.assertEqual(json.loads(output.read_text())["schema_version"], "command-registry/v1")
            for name in names:
                self.assertEqual((output.parent / "review-config" / name).read_bytes(), b"{}")
            changed = copy.deepcopy(source)
            changed["commands"][0]["argv"] = ["${COMMAND}"]
            source_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "E_COMMAND_PLACEHOLDER"):
                tool.build_task_command_registry(manifest, source_path, configs, root / "other.json")
            source_path.write_text(json.dumps(source), encoding="utf-8")
            (configs / "review-authority.v1.json").unlink()
            with self.assertRaisesRegex(ValueError, "E_REVIEW_CONFIG:review-authority.v1.json"):
                tool.build_task_command_registry(manifest, source_path, configs, root / "missing.json")

    def test_current_profile_materializes_the_current_review_chain(self) -> None:
        tool = load_tool()
        manifest = json.loads((ROOT / "pack/docs/tasks/task-manifest.v6.3.6.json").read_text())
        source = ROOT / "pack/docs/registries/task-command-registry.v1.json"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "runtime/task-command-registry.json"
            result = tool.build_task_command_registry(
                manifest,
                source,
                ROOT / "pack/docs/configs",
                output,
                review_config_profile="current",
            )
            self.assertEqual(result["review_config_profile"], "current")
            self.assertEqual(result["review_config_count"], 4)
            for name in (
                "review-a.v2.json",
                "review-b.v2.json",
                "review-aggregation.v2.json",
                "review-authority.v1.json",
            ):
                self.assertEqual(
                    (output.parent / "review-config" / name).read_bytes(),
                    (ROOT / "pack/docs/configs" / name).read_bytes(),
                )
            self.assertFalse((output.parent / "review-config/review-a.v1.json").exists())

    def test_scoped_profile_preserves_current_and_adds_both_v3_roles(self) -> None:
        tool = load_tool()
        manifest = json.loads((ROOT / "pack/docs/tasks/task-manifest.v6.3.6.json").read_text())
        with TemporaryDirectory() as directory:
            output = Path(directory) / "runtime/task-command-registry.json"
            result = tool.build_task_command_registry(
                manifest, ROOT / "pack/docs/registries/task-command-registry.v1.json",
                ROOT / "pack/docs/configs", output, review_config_profile="scoped",
            )
            self.assertEqual(result["review_config_count"], 6)
            for role in ("a", "b"):
                for version in (2, 3):
                    name = f"review-{role}.v{version}.json"
                    self.assertEqual((output.parent / "review-config" / name).read_bytes(),
                                     (ROOT / "pack/docs/configs" / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
