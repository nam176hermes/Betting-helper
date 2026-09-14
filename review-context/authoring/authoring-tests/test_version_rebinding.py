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
        "rebind_successor", ROOT / "authoring-tools/rebind_successor.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VersionRebindingTests(unittest.TestCase):
    def test_every_rebinding_is_declared_and_idempotent(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "runtime/example.txt"
            target.parent.mkdir()
            target.write_text("v6.2\n", encoding="utf-8")
            before, after = b"v6.2\n", b"v6.3.6\n"
            registry = root / "rebindings.json"
            registry.write_text(json.dumps({"patches": [{
                "path": "runtime/example.txt",
                "before_sha256": hashlib.sha256(before).hexdigest(),
                "after_sha256": hashlib.sha256(after).hexdigest(),
                "replacements": [{"old": "v6.2", "new": "v6.3.6"}],
            }]}), encoding="utf-8")
            self.assertEqual(tool.apply_rebinding_plan(registry, root)["changed_paths"], 1)
            self.assertEqual(tool.apply_rebinding_plan(registry, root)["changed_paths"], 0)
            self.assertEqual(target.read_bytes(), after)


if __name__ == "__main__":
    unittest.main()
