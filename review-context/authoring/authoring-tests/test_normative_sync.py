from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "normative_sync", ROOT / "authoring-tools/sync_normative_bundle.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode & 0o777) for path in sorted(root.rglob("*")) if path.is_file()}


class NormativeSyncTests(unittest.TestCase):
    def _paths(self, root: Path) -> tuple[Path, Path, Path]:
        return ROOT / "pack/docs", ROOT / "pack/docs/registries/normative-source-map.v1.json", root / "schema-lock.json"

    def test_runtime_vendor_bytes_equal_pack_normative_bytes(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, mapping, lock = self._paths(root)
            destination = root / "vendor/hybrid-discovery-v6.3.6"
            result = tool.synchronize_normative_bundle(source, mapping, destination, lock)
            binding = json.loads(mapping.read_text(encoding="utf-8"))
            expected_count = len(binding["inherited_entries"]) + len(binding["plan_entries"])
            self.assertEqual(result["file_count"], expected_count)
            copied = destination / "docs/schemas/task-card-v6.3.6.schema.json"
            self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), hashlib.sha256((source / "schemas/task-card-v6.3.6.schema.json").read_bytes()).hexdigest())
            self.assertEqual(json.loads(lock.read_text())["vendor_path"], "vendor/hybrid-discovery-v6.3.6")

    def test_check_is_read_only_and_rejects_drift(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, mapping, lock = self._paths(root)
            destination = root / "vendor/hybrid-discovery-v6.3.6"
            tool.synchronize_normative_bundle(source, mapping, destination, lock)
            before = snapshot(destination), lock.read_bytes()
            self.assertEqual(tool.synchronize_normative_bundle(source, mapping, destination, lock, check=True)["result"], "PASS")
            self.assertEqual(before, (snapshot(destination), lock.read_bytes()))
            target = destination / "docs/schemas/task-card-v6.3.6.schema.json"
            target.write_bytes(b"tampered")
            tampered = snapshot(destination), lock.read_bytes()
            with self.assertRaisesRegex(ValueError, "E_NORMATIVE_DRIFT"):
                tool.synchronize_normative_bundle(source, mapping, destination, lock, check=True)
            self.assertEqual(tampered, (snapshot(destination), lock.read_bytes()))
            target.write_bytes(before[0][target.relative_to(destination).as_posix()][0])
            extra = destination / "unexpected.json"
            extra.write_text("{}")
            with self.assertRaisesRegex(ValueError, "E_NORMATIVE_DRIFT"):
                tool.synchronize_normative_bundle(source, mapping, destination, lock, check=True)

    def test_check_rejects_lock_or_link_tamper_without_repair(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, mapping, lock = self._paths(root)
            destination = root / "vendor/hybrid-discovery-v6.3.6"
            tool.synchronize_normative_bundle(source, mapping, destination, lock)
            lock.write_text("{}")
            with self.assertRaisesRegex(ValueError, "E_NORMATIVE_LOCK"):
                tool.synchronize_normative_bundle(source, mapping, destination, lock, check=True)
            tool.synchronize_normative_bundle(source, mapping, destination, lock)
            target = destination / "docs/schemas/task-card-v6.3.6.schema.json"
            linked = root / "linked-outside-vendor"
            os.link(target, linked)
            with self.assertRaisesRegex(ValueError, "E_NORMATIVE_DRIFT"):
                tool.synchronize_normative_bundle(source, mapping, destination, lock, check=True)


if __name__ == "__main__":
    unittest.main()
