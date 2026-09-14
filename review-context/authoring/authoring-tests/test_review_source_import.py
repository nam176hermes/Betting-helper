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
        "review_sources", ROOT / "authoring-tools/import_review_sources.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewSourceImportTests(unittest.TestCase):
    def test_review_sources_match_frozen_hashes(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory) / "pack"
            (root / "docs/registries").mkdir(parents=True)
            payload = b"immutable review\n"
            source = root / "docs/reviews/review.md"
            source.parent.mkdir(parents=True)
            source.write_bytes(payload)
            config = {
                "plan_review_import": "pack/docs/reviews/review.md",
                "v6_3_1_plan_review_input_sha256": hashlib.sha256(payload).hexdigest(),
                "required_plan_source_files": [
                    {
                        "path": "docs/reviews/review.md",
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
            config_path = root / "docs/registries/source-inputs.v1.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = tool.import_review_sources(config_path)
            self.assertEqual(result["verified_files"], 1)
            receipt = root / "docs/receipts/source-provenance.v1.json"
            self.assertEqual(json.loads(receipt.read_text())["result"], "PASS")
            source.write_text("mutated review!!\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "E_SOURCE_HASH"):
                tool.import_review_sources(config_path)


if __name__ == "__main__":
    unittest.main()
