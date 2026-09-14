from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = Path("/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring")


def load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "declaration_gate", ROOT / "authoring-tools/issue_declaration_gate.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeclarationGateTests(unittest.TestCase):
    def test_declaration_gate_checks_ownership_without_requiring_materialized_symbols(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "declaration.json"
            result = tool.issue_declaration_complete_receipt(
                ROOT / "pack/docs/tasks/task-manifest.v6.3.6.json",
                ROOT / "pack/docs/registries/artifact-ownership.v1.json",
                ROOT / "pack/docs/registries/task-command-registry.v1.json",
                output,
                authoring_root=CONTRACT_ROOT,
            )
            self.assertEqual(result["gate"], "DECLARATION_COMPLETE")
            self.assertEqual(result["command_count"], 222)
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(output.read_text())["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
