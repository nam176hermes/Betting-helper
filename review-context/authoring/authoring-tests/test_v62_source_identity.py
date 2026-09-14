from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "v62_source", ROOT / "authoring-tools/verify_v62_source.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V62SourceIdentityTests(unittest.TestCase):
    def test_v62_source_matches_frozen_identity(self) -> None:
        tool = load_tool()
        config_path = ROOT / "pack/docs/registries/migration-source.v1.json"
        inventory_path = ROOT / "pack/docs/registries/baseline-source-files.v1.json"
        self.assertEqual(tool.verify_v62_source(config_path, inventory_path)["file_count"], 209)
        with TemporaryDirectory() as directory:
            config = json.loads(config_path.read_text())
            config["source_commit"] = "0" * 40
            changed = Path(directory) / "migration-source.json"
            changed.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "E_SOURCE_COMMIT"):
                tool.verify_v62_source(changed, inventory_path)


if __name__ == "__main__":
    unittest.main()
