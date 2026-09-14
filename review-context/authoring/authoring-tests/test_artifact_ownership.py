from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = Path("/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring")


def load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "ownership", ROOT / "authoring-tools/validate_artifact_ownership.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArtifactOwnershipTests(unittest.TestCase):
    def test_every_referenced_artifact_has_one_creation_owner(self) -> None:
        tool = load_tool()
        registry = json.loads((ROOT / "pack/docs/registries/artifact-ownership.v1.json").read_text())
        tasks = json.loads((ROOT / "pack/docs/tasks/task-manifest.v6.3.6.json").read_text())
        schema = json.loads((ROOT / "pack/docs/schemas/artifact-ownership.schema.json").read_text())
        result = tool.validate_artifact_ownership(registry, tasks, CONTRACT_ROOT, schema)
        self.assertGreater(result["artifact_count"], 900)
        cases = [
            (lambda value: value["entries"].append(copy.deepcopy(value["entries"][0])), "E_OWNER_DUPLICATE"),
            (lambda value: value["entries"][0].update(creation_owner=""), "E_OWNER_SCHEMA"),
            (lambda value: value["entries"][0].update(source={}), "E_OWNER_SOURCE"),
            (lambda value: value["entries"][0].update(creation_owner="V636-UNKNOWN"), "E_OWNER_UNKNOWN"),
            (lambda value: value["entries"][0].update(creation_owner="V636-P10-T04"), "E_CONSUMER_BEFORE_OWNER"),
        ]
        for mutate, error in cases:
            with self.subTest(error=error):
                changed = copy.deepcopy(registry)
                mutate(changed)
                with self.assertRaisesRegex(ValueError, error):
                    tool.validate_artifact_ownership(changed, tasks, CONTRACT_ROOT, schema)


if __name__ == "__main__":
    unittest.main()
