from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "authority_graph", ROOT / "authoring-tools/validate_authority_graph.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthorityGraphTests(unittest.TestCase):
    def test_executable_and_future_graphs_are_disconnected(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "executable.json"
            future = root / "future.json"
            executable.write_text(json.dumps({
                "graph_type": "EXECUTABLE_DISCOVERY_GRAPH",
                "nodes": ["E0"], "edges": [], "terminal": "E0"
            }), encoding="utf-8")
            future.write_text(json.dumps({
                "graph_type": "NON_AUTHORITATIVE_FUTURE_ROADMAP",
                "authority": "NONE", "executable": False,
                "may_start": False, "auto_activate": False,
                "nodes": [{
                    "node_id": "F0B",
                    "graph_type": "NON_AUTHORITATIVE_FUTURE_ROADMAP",
                    "authority": "NONE", "executable": False,
                    "may_start": False, "auto_activate": False
                }],
                "edges": []
            }), encoding="utf-8")
            self.assertEqual(tool.validate_graph_partition(executable, future)["result"], "PASS")
            executable.write_text(json.dumps({
                "graph_type": "EXECUTABLE_DISCOVERY_GRAPH",
                "nodes": ["E0", "F0B"], "edges": [["E0", "F0B"]],
                "terminal": "F0B"
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "E_GRAPH_CROSS_CLASS"):
                tool.validate_graph_partition(executable, future)


if __name__ == "__main__":
    unittest.main()
