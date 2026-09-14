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
        "successor_migration", ROOT / "authoring-tools/verify_successor_migration.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


class SuccessorMigrationReceiptTests(unittest.TestCase):
    def test_final_legacy_scan_accepts_only_declared_fixture_literals(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "runtime/consumer.py"
            source.parent.mkdir(parents=True)
            source.write_text("docs/fixtures/inherited/v6.2/fixture.json")
            policy = {
                "token_pattern": r"[A-Za-z0-9_:/.-]*v6\.2[A-Za-z0-9_:/.-]*",
                "source_entries": [{"path": "runtime/consumer.py", "allowed_literals": []}],
                "additional_fixture_literals": [
                    "docs/fixtures/inherited/v6.2/fixture.json"
                ],
                "immutable_fixture_files": [],
            }
            tool._scan_legacy(root, policy)
            source.write_text("docs/fixtures/inherited/v6.2/other.json")
            with self.assertRaisesRegex(ValueError, "E_MIGRATION_LEGACY"):
                tool._scan_legacy(root, policy)

    def test_migration_receipt_accounts_for_every_active_legacy_reference(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "runtime/active.txt"
            target.parent.mkdir()
            before, after = b"v6.2", b"v6.3.6"
            target.write_bytes(after)
            registry = {
                "patches": [{"path": "runtime/active.txt", "before_sha256": hashlib.sha256(before).hexdigest(), "after_sha256": hashlib.sha256(after).hexdigest()}],
                "final_legacy_policy": {"token_pattern": r"[A-Za-z0-9_:/.-]*(?:v6\.2|v6\.3\.[12345]|V63[12345])[A-Za-z0-9_:/.-]*", "source_entries": [{"path": "runtime/active.txt", "allowed_literals": []}], "immutable_fixture_files": []},
            }
            registry_path = root / "registry.json"
            write_json(registry_path, registry)
            ownership_path = root / "ownership.json"
            ownership = {"entries": [{"path": "runtime/active.txt", "creation_owner": "V636-MIG0-T02", "modifying_tasks": ["V636-MIG0-T03", "V636-MIG0-T04", "V636-P01-T01"]}]}
            write_json(ownership_path, ownership)
            evidence = root / "evidence"
            evidence.mkdir()
            write_json(evidence / "V636-MIG0-T03.json", {"result": "PASS", "task_id": "V636-MIG0-T03", "version_rebinding_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(), "hash_guarded_patch_count": 1})
            receipt = root / "migration-receipt.json"
            self.assertEqual(tool.verify_successor_migration(registry_path, receipt, root=root, ownership_path=ownership_path, evidence_root=evidence)["legacy_scan_result"], "PASS")

            ownership["entries"][0]["modifying_tasks"] = []
            write_json(ownership_path, ownership)
            with self.assertRaisesRegex(ValueError, "E_MIGRATION_MODIFIER"):
                tool.verify_successor_migration(registry_path, root / "r633.json", root=root, ownership_path=ownership_path, evidence_root=evidence)

            ownership["entries"][0]["modifying_tasks"] = ["V636-MIG0-T03", "V636-MIG0-T04", "V636-P01-T01"]
            write_json(ownership_path, ownership)
            target.write_text("adapted", encoding="utf-8")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            write_json(evidence / "V636-MIG0-T04.json", {"result": "PASS", "task_id": "V636-MIG0-T04", "output_hashes": {"runtime/active.txt": digest}})
            self.assertEqual(tool.verify_successor_migration(registry_path, root / "r634-fixed.json", root=root, ownership_path=ownership_path, evidence_root=evidence)["legacy_scan_result"], "PASS")
            (evidence / "V636-MIG0-T04.json").unlink()
            with self.assertRaisesRegex(ValueError, "E_MIGRATION_HASH"):
                tool.verify_successor_migration(registry_path, root / "r634-old.json", root=root, ownership_path=ownership_path, evidence_root=evidence)

            target.write_text("v6.2", encoding="utf-8")
            write_json(evidence / "V636-MIG0-T04.json", {"result": "PASS", "task_id": "V636-MIG0-T04", "output_hashes": {"runtime/active.txt": hashlib.sha256(target.read_bytes()).hexdigest()}})
            with self.assertRaisesRegex(ValueError, "E_MIGRATION_LEGACY"):
                tool.verify_successor_migration(registry_path, root / "legacy.json", root=root, ownership_path=ownership_path, evidence_root=evidence)

    def test_final_mode_binds_native_lock_hashes_to_mig0_t07_evidence(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            for name in ("uv.lock", "pnpm-lock.yaml"):
                (runtime / name).write_text(name, encoding="utf-8")
            registry_path = root / "registry.json"
            write_json(registry_path, {"patches": [], "final_legacy_policy": {"token_pattern": "v6\\.2", "source_entries": [], "immutable_fixture_files": [], "final_native_lock_policy": "BOUND"}})
            ownership_path = root / "ownership.json"
            write_json(ownership_path, {"entries": [{"path": f"runtime/{name}", "creation_owner": "V636-MIG0-T02", "modifying_tasks": ["V636-MIG0-T07"]} for name in ("uv.lock", "pnpm-lock.yaml")]})
            evidence = root / "evidence"
            evidence.mkdir()
            write_json(evidence / "V636-MIG0-T03.json", {"result": "PASS", "task_id": "V636-MIG0-T03", "version_rebinding_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(), "hash_guarded_patch_count": 0})
            with self.assertRaisesRegex(ValueError, "E_MIGRATION_NATIVE_LOCK"):
                tool.verify_successor_migration(registry_path, root / "missing.json", stage="final", root=root, ownership_path=ownership_path, evidence_root=evidence)
            write_json(evidence / "V636-MIG0-T07.json", {"result": "PASS", "task_id": "V636-MIG0-T07", "native_lock_hashes": {f"runtime/{name}": hashlib.sha256((runtime / name).read_bytes()).hexdigest() for name in ("uv.lock", "pnpm-lock.yaml")}})
            receipt = tool.verify_successor_migration(registry_path, root / "final.json", stage="final", root=root, ownership_path=ownership_path, evidence_root=evidence)
            self.assertEqual(receipt["checked_outputs"][0]["basis"], "NATIVE_LOCK_RECEIPT")

    def test_final_mode_maps_docs_sources_under_pack_docs(self) -> None:
        tool = load_tool()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "pack/docs/registries/example.json"
            source.parent.mkdir(parents=True)
            source.write_text('{"result":"PASS"}', encoding="utf-8")
            target = root / "runtime/vendor/example/docs/registries/example.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(source.read_bytes())
            registry_path = root / "registry.json"
            write_json(registry_path, {"patches": [], "final_legacy_policy": {"token_pattern": "v6\\.2", "source_entries": [], "immutable_fixture_files": [{"path": "runtime/vendor/example/docs/registries/example.json", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}})
            mapping_path = root / "map.json"
            write_json(mapping_path, {"vendor_prefix": "runtime/vendor/example/", "inherited_entries": [], "plan_entries": [{"plan_source": "docs/registries/example.json", "vendor_relative": "docs/registries/example.json"}]})
            ownership_path = root / "ownership.json"
            write_json(ownership_path, {"entries": [{"path": "runtime/vendor/example/docs/registries/example.json", "creation_owner": "V636-MIG0-T04", "modifying_tasks": []}]})
            evidence = root / "evidence"
            evidence.mkdir()
            write_json(evidence / "V636-MIG0-T03.json", {"result": "PASS", "task_id": "V636-MIG0-T03", "version_rebinding_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(), "hash_guarded_patch_count": 0})
            write_json(evidence / "V636-MIG0-T04.json", {"result": "PASS", "task_id": "V636-MIG0-T04"})
            receipt = tool.verify_successor_migration(registry_path, root / "final.json", stage="final", root=root, ownership_path=ownership_path, normative_map_path=mapping_path, evidence_root=evidence)
            self.assertEqual(receipt["checked_outputs"][0]["path"], "runtime/vendor/example/docs/registries/example.json")
            self.assertEqual(len(receipt["checked_outputs"]), 1)


if __name__ == "__main__":
    unittest.main()
