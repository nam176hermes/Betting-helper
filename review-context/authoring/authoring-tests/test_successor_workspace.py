from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "successor_workspace", ROOT / "authoring-tools/create_successor_workspace.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SuccessorWorkspaceTests(unittest.TestCase):
    def test_successor_copy_excludes_git_cache_local_and_evidence(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "kept.txt").write_text("pinned\n", encoding="utf-8")
            (source / ".git").mkdir()
            (source / ".git/config").write_text("must not copy", encoding="utf-8")
            destination = root / "authoring/runtime"
            destination.mkdir(parents=True)
            config_path = root / "paths.json"
            config_path.write_text(json.dumps({"runtime_candidate": str(destination)}), encoding="utf-8")
            payload = b"pinned\n"
            inventory_path = root / "inventory.json"
            inventory_path.write_text(json.dumps({
                "root": str(source),
                "files": [{"path": "kept.txt", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}],
            }), encoding="utf-8")
            self.assertEqual(tool.create_successor_workspace(config_path, inventory_path)["file_count"], 1)
            self.assertEqual((destination / "kept.txt").read_bytes(), payload)
            self.assertFalse((destination / ".git").exists())


if __name__ == "__main__":
    unittest.main()
