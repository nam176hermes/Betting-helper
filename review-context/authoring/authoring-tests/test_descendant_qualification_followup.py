from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/home/thenam176/betting-helper"
RUNTIME = f"{PREFIX}/discovery-runtime-v6.3.6"
EVIDENCE = f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6-controller"
AUDITED_ANCESTOR = "7cd7ab14652458608386d940bdc7764910044f6a"
REVIEW_PACK = f"{PREFIX}/review-packs/hybrid-discovery-v6.3.6"
TRANSPORT = [
    "--config", f"{REVIEW_PACK}/docs/configs/full-verifier-controller.v2.json",
    "--recorded-config", f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json",
    "--retained-manifest", f"{REVIEW_PACK}/evidence/retained-artifact-manifest.json",
    "--retained-root", f"{REVIEW_PACK}/evidence/retained",
]
REFERENCE_SYMBOLS = {
    "V636-P01-T04": ([
        "runtime/tests/materialization/test_harness_entrypoints.py::test_all_registered_harness_entrypoints_compile_and_emit_contract_not_implemented",
    ], [
        "runtime/tests/materialization/test_harness_entrypoints.py::test_registered_harness_entrypoints_compile_and_unowned_entries_stay_blocked",
    ]),
    "V636-P03-T05": ([
        "runtime/tools/run_sqlite_crash_matrix.py::run_sqlite_crash_matrix",
        "runtime/tests/durability/test_sqlite_process_crash.py::test_sql_transaction_is_all_or_none_after_sigkill",
    ], [
        "runtime/tests/durability/test_sqlite_process_crash.py::test_sql06_checkpoint_is_inside_real_sqlite_commit_io",
        "runtime/tests/durability/test_sqlite_process_crash.py::test_sql_transaction_emits_exact_full_terminal_evidence",
        "runtime/tools/run_sqlite_crash_matrix.py::run_sqlite_crash_matrix",
    ]),
    "V636-P03-T07": ([
        "runtime/src/moj_discovery/durability_release.py::validate_full_durability_release",
        "runtime/tests/durability/test_destruction_and_release.py::test_declared_equals_executed_and_mutation_survivors_zero",
        "runtime/tests/durability/test_owner_mutation_review.py::test_full_qualification_rejects_forged_or_incomplete_evidence",
        "runtime/tools/run_destruction_crash_matrix.py::run_destruction_crash_matrix",
        "runtime/tools/run_full_repair_qualification.py::main",
    ], [
        "runtime/src/moj_discovery/durability_release.py::validate_full_durability_release",
        "runtime/tests/durability/test_destruction_and_release.py::test_declared_equals_executed_and_mutation_survivors_zero",
        "runtime/tests/durability/test_owner_mutation_review.py::test_coherent_review_substitutions_reject",
        "runtime/tools/run_destruction_crash_matrix.py::run_destruction_crash_matrix",
        "runtime/tools/run_full_repair_qualification.py::main",
    ]),
}


def load_tool(name: str = "apply_descendant_qualification_followup") -> object:
    path = ROOT / "authoring-tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


class DescendantQualificationFollowupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool()
        self.baseline_dir = TemporaryDirectory()
        self.addCleanup(self.baseline_dir.cleanup)
        self.baseline_pack = Path(self.baseline_dir.name) / "pack"
        shutil.copytree(ROOT / "pack", self.baseline_pack)
        # Exercise this historical amendment against its exact predecessor bytes.
        pinned = load_tool("prepare_part_b_review_inputs").predecessor(ROOT)
        for name, data in pinned.items():
            path = Path(self.baseline_dir.name) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.tool.apply_descendant_qualification_followup(self.baseline_pack)

    def test_review_descendant_transport_preserves_qualified_execution_identity(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            load_tool("apply_full_verifier_followup").apply_full_verifier_followup(pack)
            self.tool.apply_descendant_qualification_followup(pack)
            review = read(pack / "docs/configs/review-a.v2.json")
            self.assertIn("producer_environment", review)
            projection = review["producer_environment"]
            self.assertEqual(projection["python_environment"], f"{RUNTIME}/.venv")
            self.assertEqual(projection["python_executable"], f"{RUNTIME}/.venv/bin/python3")
            self.assertEqual(projection["node_lookup"], "/home/thenam176/.local/share/mise/shims/node")
            self.assertEqual(projection["mode"], "VERIFIED_READ_ONLY_PROJECTION")
            self.assertIn("path_translation_executable", projection)
            self.assertEqual(projection["path_translation_executable"], "/init")
            self.assertEqual(projection.get("wsl_distro"), "Ubuntu")
            self.assertEqual(projection.get("runtime_unc"), "\\\\wsl.localhost\\Ubuntu" + RUNTIME.replace("/", "\\"))
            self.assertEqual(len(review["input_mounts"]), 5)
            commands = {row["command_id"]: row for row in read(pack / "docs/registries/task-command-registry.v1.json")["commands"]}
            self.assertIn(f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json", commands["VERIFY_V636_P07_T01"]["argv"])
            owned = {row["path"]: row for row in read(pack / "docs/registries/artifact-ownership.v1.json")["entries"]}
            self.assertEqual(owned["runtime/extension/dist/contracts/clock-coherence.js"]["source"]["path"], "runtime/extension/src/contracts/clock-coherence.ts")
            self.assertNotIn("producer_environment", read(pack / "docs/configs/review-a.v1.json"))
            self.assertEqual(
                read(pack / "docs/configs/full-verifier-controller.v2.json")["receipts"]["authoring_repository"],
                f"{EVIDENCE}/bootstrap/authoring-repository-receipt-descendant-source-v2.json",
            )

    def test_p07_materialized_raw_operation_reads_its_declared_vendor_matrix(self) -> None:
        with TemporaryDirectory() as directory:
            pack, runtime = Path(directory) / "source/pack", Path(directory) / "runtime"
            shutil.copytree(self.baseline_pack, pack)
            self.tool.apply_descendant_qualification_followup(pack)
            registry_path = pack / "docs/registries/task-command-registry.v1.json"
            original = read(registry_path)
            registry = copy.deepcopy(original)
            row = next(r for r in registry["commands"] if r["command_id"] == "VERIFY_V636_P07_T02")

            def transport(token: str) -> str:
                return str(runtime) + token[len(RUNTIME):] if token == RUNTIME or token.startswith(RUNTIME + "/") else token

            row["cwd"], row["argv"] = transport(row["cwd"]), [transport(token) for token in row["argv"]]
            restored = copy.deepcopy(registry)
            restored_row = next(r for r in restored["commands"] if r["command_id"] == "VERIFY_V636_P07_T02")
            restored_row["cwd"] = RUNTIME
            restored_row["argv"] = [RUNTIME + token[len(str(runtime)):] if token == str(runtime) or token.startswith(str(runtime) + "/") else token for token in row["argv"]]
            self.assertEqual(restored, original)  # Only this declared runtime path prefix is transported.
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            vendor = runtime / "vendor/hybrid-discovery-v6.3.6"
            load_tool("sync_normative_bundle").synchronize_normative_bundle(
                pack / "docs", pack / "docs/registries/normative-source-map.v1.json",
                vendor, runtime / "schema-lock.json",
            )
            output = runtime / "task-command-registry.json"
            load_tool("build_task_command_registry").build_task_command_registry(
                read(pack / "docs/tasks/task-manifest.v6.3.6.json"), registry_path,
                pack / "docs/configs", output, review_config_profile="current",
            )
            self.assertEqual(output.read_bytes(), registry_path.read_bytes())
            self.assertEqual((vendor / "docs/registries/task-command-registry.v1.json").read_bytes(), output.read_bytes())
            materialized = next(r for r in read(output)["commands"] if r["command_id"] == "VERIFY_V636_P07_T02")
            operand = materialized["argv"][materialized["argv"].index("--matrix") + 1]
            selected = (Path(materialized["cwd"]) / operand).resolve()
            expected = vendor / "docs/registries/proof-coverage-matrix.v1.json"
            self.assertEqual(selected, expected)  # Raw controller dispatch: no candidate rebind.
            self.assertEqual(selected.read_bytes(), (pack / "docs/registries/proof-coverage-matrix.v1.json").read_bytes())

    def test_p07_vendor_read_retains_source_dependency_and_existing_owner(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            relative = "runtime/vendor/hybrid-discovery-v6.3.6/docs/registries/proof-coverage-matrix.v1.json"
            before = {r["path"]: r for r in read(pack / "docs/registries/artifact-ownership.v1.json")["entries"]}
            self.tool.apply_descendant_qualification_followup(pack)
            tasks = {r["task_id"]: r for r in read(pack / "docs/tasks/task-manifest.v6.3.6.json")["tasks"]}
            io = {r["command_id"]: r for r in read(pack / "docs/registries/command-io.v1.json")["commands"]}
            owned = {r["path"]: r for r in read(pack / "docs/registries/artifact-ownership.v1.json")["entries"]}
            for path in (relative, "pack/docs/registries/proof-coverage-matrix.v1.json"):
                self.assertIn(path, tasks["V636-P07-T02"]["inputs"])
                self.assertIn(path, io["VERIFY_V636_P07_T02"]["inputs"])
                self.assertIn("V636-P07-T02", owned[path]["consumers"])
            self.assertEqual(set(owned), set(before))
            self.assertEqual(owned[relative], {**before[relative], "consumers": sorted(set(before[relative]["consumers"]) | {"V636-P07-T02"})})

    def test_p07_exact_legacy_predecessor_and_current_rows_are_idempotent(self) -> None:
        current = next(r for r in read(self.baseline_pack / "docs/registries/task-command-registry.v1.json")["commands"] if r["command_id"] == "VERIFY_V636_P07_T02")
        current["argv"][current["argv"].index("--matrix") + 1] = f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/registries/proof-coverage-matrix.v1.json"
        predecessor = copy.deepcopy(current)
        predecessor["argv"][predecessor["argv"].index("--matrix") + 1] = "../pack/docs/registries/proof-coverage-matrix.v1.json"
        legacy = copy.deepcopy(predecessor)
        legacy["argv"][legacy["argv"].index("--config") + 1] = f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json"
        for row, digest in ((legacy, "c436f40181c062d3c1d446e68918d8df6c0335e153a013f151307510818df60f"), (predecessor, "06d076ab3b2af99ff9e5a8b3aca7e1a163098776e47eb8b1b1bbd8938ee85b76"), (current, None)):
            with self.subTest(predecessor=digest), TemporaryDirectory() as directory:
                if digest is not None:
                    self.assertEqual(hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), digest)
                pack = Path(directory) / "pack"
                shutil.copytree(self.baseline_pack, pack)
                path = pack / "docs/registries/task-command-registry.v1.json"
                registry = read(path)
                registry["commands"] = [copy.deepcopy(row) if r["command_id"] == row["command_id"] else r for r in registry["commands"]]
                path.write_text(json.dumps(registry), encoding="utf-8")
                self.tool.apply_descendant_qualification_followup(pack)
                self.assertEqual(next(r for r in read(path)["commands"] if r["command_id"] == row["command_id"]), current)
                before = {p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}
                self.assertEqual(self.tool.apply_descendant_qualification_followup(pack), {"result": "PASS", "changed": 0})
                self.assertEqual({p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}, before)

    def test_p07_unknown_full_rows_fail_before_any_pack_write(self) -> None:
        for field, value in (("cwd", "/unrelated"), ("purpose", "unowned"), ("expected_exit", 1), ("expected_exit", False), ("network", "ALLOW"), ("kind", "verification"), ("matrix", "/unrelated/matrix.json"), ("extra-argument", "--check-only")):
            with self.subTest(field=field, value=value), TemporaryDirectory() as directory:
                pack = Path(directory) / "pack"
                shutil.copytree(self.baseline_pack, pack)
                path = pack / "docs/registries/task-command-registry.v1.json"
                registry = read(path)
                row = next(r for r in registry["commands"] if r["command_id"] == "VERIFY_V636_P07_T02")
                original = json.dumps(row, sort_keys=True, separators=(",", ":"))
                if field == "matrix":
                    row["argv"][row["argv"].index("--matrix") + 1] = value
                elif field == "extra-argument":
                    row["argv"].append(value)
                else:
                    row[field] = value
                self.assertNotEqual(json.dumps(row, sort_keys=True, separators=(",", ":")), original)
                path.write_text(json.dumps(registry), encoding="utf-8")
                before = {p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}
                with self.assertRaisesRegex(ValueError, "^E_DESCENDANT_UNKNOWN_COMMAND:VERIFY_V636_P07_T02$"):
                    self.tool.apply_descendant_qualification_followup(pack)
                self.assertEqual({p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}, before)

    def test_reference_symbol_transitions_are_exact_and_idempotent(self) -> None:
        for current in (False, True):
            with self.subTest(current=current), TemporaryDirectory() as directory:
                pack = Path(directory) / "pack"
                shutil.copytree(self.baseline_pack, pack)
                path = pack / "docs/tasks/task-manifest.v6.3.6.json"
                manifest = read(path)
                for task in manifest["tasks"]:
                    if task["task_id"] in REFERENCE_SYMBOLS:
                        task["exact_symbols"] = REFERENCE_SYMBOLS[task["task_id"]][current]
                path.write_text(json.dumps(manifest))
                self.tool.apply_descendant_qualification_followup(pack)
                tasks = {row["task_id"]: row for row in read(path)["tasks"]}
                for task_id, (_, expected) in REFERENCE_SYMBOLS.items():
                    self.assertEqual(tasks[task_id]["exact_symbols"], expected)
                self.assertEqual(self.tool.apply_descendant_qualification_followup(pack)["changed"], 0)

    def test_reference_unknown_or_partial_symbols_fail_before_writes(self) -> None:
        for task_id, (old, new) in REFERENCE_SYMBOLS.items():
            for damage in (old + ["runtime/unknown.py::unowned"], new[:-1], sorted(set(old + new)), new + new):
                with self.subTest(task_id=task_id, damage=damage), TemporaryDirectory() as directory:
                    pack = Path(directory) / "pack"
                    shutil.copytree(self.baseline_pack, pack)
                    path = pack / "docs/tasks/task-manifest.v6.3.6.json"
                    manifest = read(path)
                    next(row for row in manifest["tasks"] if row["task_id"] == task_id)["exact_symbols"] = damage
                    path.write_text(json.dumps(manifest))
                    before = {p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}
                    with self.assertRaisesRegex(ValueError, f"^E_DESCENDANT_UNKNOWN_SYMBOLS:{task_id}$"):
                        self.tool.apply_descendant_qualification_followup(pack)
                    self.assertEqual({p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}, before)

    def test_reference_pack_inputs_retain_existing_owners_and_producer_output(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            before = {r["path"]: r for r in read(pack / "docs/registries/artifact-ownership.v1.json")["entries"]}
            self.tool.apply_descendant_qualification_followup(pack)
            tasks = {r["task_id"]: r for r in read(pack / "docs/tasks/task-manifest.v6.3.6.json")["tasks"]}
            io = {r["command_id"]: r for r in read(pack / "docs/registries/command-io.v1.json")["commands"]}
            owned = {r["path"]: r for r in read(pack / "docs/registries/artifact-ownership.v1.json")["entries"]}
            for path in (
                "pack/docs/contracts/02-authority-graph.md", "pack/docs/receipts/source-provenance.v1.json",
                "pack/docs/receipts/declaration-complete.v1.json", "pack/docs/receipts/migration-receipt.v1.json",
            ):
                with self.subTest(path=path):
                    self.assertIn(path, tasks["V636-P09-T01"]["inputs"])
                    self.assertIn(path, io["VERIFY_V636_P09_T01"]["inputs"])
                    self.assertNotIn(path, tasks["V636-P09-T01"]["outputs"])
                    self.assertNotIn(path, io["VERIFY_V636_P09_T01"]["outputs"])
                    self.assertEqual(owned[path], {**before[path], "consumers": sorted(set(before[path]["consumers"]) | {"V636-P09-T01"})})
            self.assertEqual(set(owned), set(before))
            self.assertEqual(io["VERIFY_V636_P00_T01"]["outputs"], ["pack/docs/receipts/source-provenance.v1.json"])
            self.assertEqual(io["VERIFY_V636_P00_T02"]["outputs"], [])

    def test_transport_retains_six_exact_receipt_inputs_with_canonical_owners(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            ownership_path = pack / "docs/registries/artifact-ownership.v1.json"
            before = {row["path"]: row for row in read(ownership_path)["entries"]}
            self.tool.apply_descendant_qualification_followup(pack)
            tasks = {row["task_id"]: row for row in read(pack / "docs/tasks/task-manifest.v6.3.6.json")["tasks"]}
            io = {row["command_id"]: row for row in read(pack / "docs/registries/command-io.v1.json")["commands"]}
            owned = {row["path"]: row for row in read(ownership_path)["entries"]}
            receipts = {
                f"{PREFIX}/plan-input/.receipts/hybrid-discovery-v6.3.6-plan-input.json": "V636-BOOT0-T01",
                f"{PREFIX}/hybrid-discovery-v6.3.6-authoring/.bootstrap/authoring-workspace-receipt.json": "V636-BOOT0-T02",
                f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6/bootstrap/authoring-repository-receipt.json": "V636-BOOT0-T03",
                f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T02.json": "V636-P01-T02",
                f"{EVIDENCE}/bootstrap/authoring-repository-receipt-descendant-source-v2.json": "V636-MIG0-T08",
                f"{EVIDENCE}/bootstrap/authoring-repository-receipt.json": "V636-MIG0-T08",
            }
            for locator, owner in receipts.items():
                with self.subTest(locator=locator):
                    self.assertIn(locator, tasks["V636-P09-T01"]["inputs"])
                    self.assertIn(locator, io["VERIFY_V636_P09_T01"]["inputs"])
                    canonical = locator.removeprefix(f"{PREFIX}/hybrid-discovery-v6.3.6-authoring/")
                    self.assertEqual(owned[canonical]["creation_owner"], owner)
                    expected = {**before[canonical], "consumers": sorted(set(before[canonical]["consumers"]) | {"V636-P09-T01"})}
                    self.assertEqual(owned[canonical], expected)
                    self.assertNotIn(locator, tasks["V636-P09-T01"]["outputs"])
                    self.assertNotIn(locator, io["VERIFY_V636_P09_T01"]["outputs"])
            self.assertNotIn(f"{PREFIX}/hybrid-discovery-v6.3.6-authoring/.bootstrap/authoring-workspace-receipt.json", owned)
            self.assertEqual(set(owned), set(before))

    def test_transport_p09_command_outputs_match_task_creation_owners(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            self.tool.apply_descendant_qualification_followup(pack)
            tasks = {row["task_id"]: row for row in read(pack / "docs/tasks/task-manifest.v6.3.6.json")["tasks"]}
            io = {row["command_id"]: row for row in read(pack / "docs/registries/command-io.v1.json")["commands"]}
            owned = {row["path"]: row for row in read(pack / "docs/registries/artifact-ownership.v1.json")["entries"]}
            for task_id, expected in {
                "V636-P09-T02": {"pack/GOVERNED_CONTENT_ROOT.json"},
                "V636-P09-T03": {"pack/SELF_REVIEW_REPORT.json", "pack/SELF_REVIEW_REPORT.md"},
                "V636-P09-T04": {"pack/MANIFEST_SHA256.json"},
            }.items():
                with self.subTest(task_id=task_id):
                    self.assertEqual(set(tasks[task_id]["outputs"]), expected)
                    if task_id == "V636-P09-T04":
                        expected |= {f"{REVIEW_PACK}{suffix}" for suffix in (".zip", ".zip.sha256", ".seal-attestation.json")}
                    self.assertEqual(set(io["VERIFY_" + task_id.replace("-", "_")]["outputs"]), expected)
                    for path in expected:
                        self.assertEqual(owned[path]["creation_owner"], task_id)

    def test_transport_commands_emit_exact_sealed_context_without_authority_execution(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            self.tool.apply_descendant_qualification_followup(pack)
            commands = {
                row["command_id"]: row
                for name in ("task-command-registry.v1.json", "review-command-registry.v1.json")
                for row in read(pack / "docs/registries" / name)["commands"]
            }
            expected = {
                "VERIFY_V636_P09_T01": [
                    "python3.12", "-B", "tools/assemble_review_pack.py", "--source",
                    f"{PREFIX}/authoring-controller-config-worktree/pack", "--destination", REVIEW_PACK,
                    "--config", TRANSPORT[3], *TRANSPORT[4:],
                ],
                "VERIFY_V636_P09_T02": [
                    "python3.12", "-B", "tools/compute_governed_content_root.py", "--pack", REVIEW_PACK,
                    "--registry", f"{REVIEW_PACK}/docs/registries/seal-exclusions.v1.json",
                ],
                "VERIFY_V636_P09_T03": [
                    "python3.12", "-B", "tools/build_self_review.py", "--governed-root",
                    f"{REVIEW_PACK}/GOVERNED_CONTENT_ROOT.json", "--repository-receipt",
                    f"{REVIEW_PACK}/docs/receipts/descendant-repository-qualification-receipt.json",
                    "--output-dir", REVIEW_PACK, *TRANSPORT,
                ],
                "VERIFY_V636_P09_T04": [
                    "python3.12", "-B", "tools/seal_review_pack.py", "--pack", REVIEW_PACK,
                    *TRANSPORT, "--zip", f"{REVIEW_PACK}.zip", "--sidecar", f"{REVIEW_PACK}.zip.sha256",
                    "--attestation", f"{REVIEW_PACK}.seal-attestation.json",
                ],
                "A_CHECK_SOURCE": [
                    "uv", "run", "--frozen", "--offline", "python", "tools/verify_executable_references.py",
                    "--mode", "sealed-review", "--pack", REVIEW_PACK, *TRANSPORT,
                ],
                "A_CHECK_EVIDENCE": [
                    "uv", "run", "--frozen", "--offline", "python", "tools/verify_proof_coverage.py",
                    "--matrix", f"{REVIEW_PACK}/docs/registries/proof-coverage-matrix.v1.json",
                    "--stage", "SEALED", "--evidence-root", f"{REVIEW_PACK}/evidence",
                    "--attestation", f"{REVIEW_PACK}.seal-attestation.json", "--zip", f"{REVIEW_PACK}.zip",
                    "--sidecar", f"{REVIEW_PACK}.zip.sha256", *TRANSPORT,
                ],
                "A_CHECK_DESCENDANT": [
                    "uv", "run", "--frozen", "--offline", "python", "tools/qualify_descendant_repository.py",
                    "--root", RUNTIME, *TRANSPORT[:2], "--check-only", "--receipt",
                    f"{REVIEW_PACK}/docs/receipts/descendant-repository-qualification-receipt.json",
                    "--pack", REVIEW_PACK, *TRANSPORT[2:],
                ],
            }
            for command_id, argv in expected.items():
                with self.subTest(command_id=command_id):
                    self.assertEqual(commands[command_id]["argv"], argv)
                    self.assertEqual(commands[command_id]["cwd"], RUNTIME)
                    self.assertEqual(commands[command_id]["network"], "DENY")

    def test_transport_source_closure_is_owned_and_finite(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            self.tool.apply_descendant_qualification_followup(pack)
            tasks = {row["task_id"]: row for row in read(pack / "docs/tasks/task-manifest.v6.3.6.json")["tasks"]}
            ownership = {row["path"]: row for row in read(pack / "docs/registries/artifact-ownership.v1.json")["entries"]}
            expected = {
                "pack/evidence/retained-artifact-manifest.json", "pack/evidence/retained",
                "pack/evidence/V636-P07-T01.json", "pack/evidence/V636-P07-T02.json",
                "pack/evidence/V636-P07-T03.json", "pack/evidence/CANDIDATE_QUALIFICATION.json",
            }
            self.assertTrue(expected <= set(tasks["V636-P09-T01"]["outputs"]))
            for path in expected:
                self.assertEqual(ownership[path]["creation_owner"], "V636-P09-T01")
            matrix = read(pack / "docs/registries/proof-coverage-matrix.v1.json")["entries"]
            for row in matrix:
                if row["stage"] == "CANDIDATE":
                    target = "pack/" + row["sealed_evidence_path"]
                    self.assertIn(target, tasks["V636-P09-T01"]["outputs"])
                    self.assertEqual(ownership[target]["creation_owner"], "V636-P09-T01")
                    self.assertIn(row["evidence_artifact"], tasks["V636-P09-T01"]["inputs"])
            exports = read(pack / "docs/registries/delivery-map.v1.json")["authoring_source_exports"]
            bootstrap = [row for row in exports if row["source"].startswith("plan-input/bootstrap/")]
            self.assertEqual({Path(row["source"]).name for row in bootstrap}, {
                "create_authoring_workspace.py", "initialize_authoring_repository.py",
                "verify_extracted_plan.py", "extract_plan.py", "test_bootstrap_tools.py",
            })
            for row in bootstrap:
                self.assertEqual(row["destination"], "pack/authoring-source/bootstrap/" + Path(row["source"]).name)
                self.assertEqual(row["owner"], "V636-P09-T01")

    def test_transport_io_keeps_b_registry_separate_and_declares_metadata_reads(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            untouched = {
                name: (pack / "docs" / name).read_bytes() for name in (
                    "registries/cybersecurity-command-registry.v1.json", "configs/review-b.v1.json",
                    "configs/review-b.v2.json", "schemas/command-registry.schema.json",
                )
            }
            self.tool.apply_descendant_qualification_followup(pack)
            io = {row["command_id"]: row for row in read(pack / "docs/registries/command-io.v1.json")["commands"]}
            for command_id in ("VERIFY_V636_P10_T02", "REVIEW_B_PREPARE", "REVIEW_B_FINALIZE", "REVIEW_AGGREGATE"):
                with self.subTest(command_id=command_id):
                    self.assertTrue({
                        "runtime/review-config/review-a.v2.json", "pack/docs/configs/review-a.v2.json",
                        "pack/docs/registries/review-command-registry.v1.json",
                        "pack/docs/registries/cybersecurity-command-registry.v1.json",
                    } <= set(io[command_id]["inputs"]))
                    self.assertIn(f"{REVIEW_PACK}/evidence/retained", io[command_id]["input_directories"])
            self.assertIn("runtime/review-config/review-aggregation.v2.json", io["REVIEW_AGGREGATE"]["inputs"])
            self.assertNotIn("runtime/review-config/review-aggregation.v1.json", io["REVIEW_AGGREGATE"]["inputs"])
            for name, raw in untouched.items():
                self.assertEqual((pack / "docs" / name).read_bytes(), raw)

    def test_transport_matrix_changes_only_candidate_recorded_paths(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            matrix = pack / "docs/registries/proof-coverage-matrix.v1.json"
            before = read(matrix)
            self.tool.apply_descendant_qualification_followup(pack)
            after = read(matrix)
            self.assertEqual(len(after["entries"]), 18)
            eligible = [row for row in after["entries"] if row["stage"] == "CANDIDATE"]
            self.assertEqual(len(eligible), 16)
            self.assertEqual(len({row["evidence_artifact"] for row in eligible}), 11)
            for old, new in zip(before["entries"], after["entries"], strict=True):
                if old["stage"] == "CANDIDATE":
                    self.assertEqual(new["evidence_artifact"], EVIDENCE + "/" + Path(old["evidence_artifact"]).name)
                    old["evidence_artifact"] = new["evidence_artifact"]
                self.assertEqual(new, old)

    def test_transport_unknown_predecessor_fails_before_any_source_write(self) -> None:
        ids = (
            "VERIFY_V636_P09_T01", "VERIFY_V636_P09_T02", "VERIFY_V636_P09_T03", "VERIFY_V636_P09_T04",
            "A_CHECK_SOURCE", "A_CHECK_EVIDENCE", "A_CHECK_DESCENDANT",
        )
        for command_id in ids:
            for field, value in (
                ("cwd", "/unrelated"), ("purpose", "unowned"), ("kind", "operation"),
                ("network", "ALLOW"), ("argv", ["python3", "unowned.py"]),
            ):
                with self.subTest(command_id=command_id, field=field), TemporaryDirectory() as directory:
                    pack = Path(directory) / "pack"
                    shutil.copytree(self.baseline_pack, pack)
                    name = "review-command-registry.v1.json" if command_id.startswith("A_") else "task-command-registry.v1.json"
                    path = pack / "docs/registries" / name
                    registry = read(path)
                    row = next(row for row in registry["commands"] if row["command_id"] == command_id)
                    row[field] = value if row.get(field) != value else "invalid-kind"
                    path.write_text(json.dumps(registry))
                    before = {p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}
                    with self.assertRaisesRegex(ValueError, f"E_DESCENDANT_UNKNOWN_COMMAND:{command_id}"):
                        self.tool.apply_descendant_qualification_followup(pack)
                    self.assertEqual({p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}, before)

    def test_transport_accepts_exact_source_predecessors_and_preserves_historical_branches(self) -> None:
        witnesses = {
            "VERIFY_V636_P09_T01": "ec1b06127319ddc41fb2b19c20dc77ee8e3d14d125e7b8d767cb94b7e8a3eedc",
            "VERIFY_V636_P09_T02": "3a74ab4b5d2be55d470853cb987198a3339649041bf64a0b62f7b4ab253c34f1",
            "VERIFY_V636_P09_T03": "2c4886e9eabd656c704418979bfd6abe5da66386a0d7ae456621543dcd58ac4e",
            "VERIFY_V636_P09_T04": "8789fdfd71dd3fe5d698ad5dda4a77ec80c9bda728cdc79a6ececcdabac4fb60",
            "A_CHECK_SOURCE": "6f56d3a7cc893660d2d58d8046af0127e0e0b30489c2b6a1c4a0f66ed399de1e",
            "A_CHECK_EVIDENCE": "76dc973cb7d8f9a809f5662806029827816334d700dffdbf6e77ec0833df7b79",
            "A_CHECK_DESCENDANT": "5f6865f69e8825ed20502496bd5b472e932d826d1e683831ccf5cbcb52be82e5",
        }
        for historical in (False, True):
            with self.subTest(historical=historical), TemporaryDirectory() as directory:
                pack = Path(directory) / "pack"
                shutil.copytree(self.baseline_pack, pack)
                self.tool.apply_descendant_qualification_followup(pack)
                for name in ("task-command-registry.v1.json", "review-command-registry.v1.json"):
                    path = pack / "docs/registries" / name
                    registry = read(path)
                    for row in registry["commands"]:
                        command_id = row["command_id"]
                        if command_id not in witnesses:
                            continue
                        argv = row["argv"]
                        if command_id == "VERIFY_V636_P09_T01":
                            argv = argv[:argv.index("--retained-manifest")]
                        elif command_id in {"A_CHECK_DESCENDANT", "A_CHECK_SOURCE"}:
                            argv = argv[:argv.index("--pack")]
                        elif command_id != "VERIFY_V636_P09_T02":
                            start = argv.index("--config")
                            argv = argv[:start] + argv[start + 8:]
                        if command_id in {"VERIFY_V636_P09_T02", "VERIFY_V636_P09_T04"}:
                            row["cwd"] = f"{PREFIX}/hybrid-discovery-v6.3.6-authoring"
                            argv[2] = "runtime/" + argv[2]
                        row["argv"] = argv
                        self.assertEqual(hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), witnesses[command_id])
                        if historical and command_id in {"VERIFY_V636_P09_T01", "VERIFY_V636_P09_T03"}:
                            row["cwd"] = f"{PREFIX}/hybrid-discovery-v6.3.6-authoring"
                            argv[2] = "runtime/" + argv[2]
                            if command_id.endswith("T01"):
                                argv[4] = "pack"
                                del argv[-2:]
                            else:
                                argv[5] = "--repo0-receipt"
                                argv[6] = f"{REVIEW_PACK}/docs/receipts/repo0-baseline-receipt.json"
                    if historical and name == "review-command-registry.v1.json":
                        registry["commands"] = [r for r in registry["commands"] if r["command_id"] != "A_CHECK_DESCENDANT"]
                    path.write_text(json.dumps(registry))
                self.assertEqual(self.tool.apply_descendant_qualification_followup(pack)["result"], "PASS")
                before = {p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}
                self.assertEqual(self.tool.apply_descendant_qualification_followup(pack), {"result": "PASS", "changed": 0})
                self.assertEqual({p.relative_to(pack): p.read_bytes() for p in pack.rglob("*") if p.is_file()}, before)

    def test_transport_finalizers_consume_results_only_at_their_creation_phase(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            self.tool.apply_descendant_qualification_followup(pack)
            io = {r["command_id"]: r for r in read(pack / "docs/registries/command-io.v1.json")["commands"]}
            owned = {r["path"]: r for r in read(pack / "docs/registries/artifact-ownership.v1.json")["entries"]}
            for role in ("A", "B"):
                self.assertEqual(io[f"REVIEW_{role}_FINALIZE"]["consumers"], ["V636-P10-T03"])
                path = f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-{role.lower()}/result.json"
                self.assertNotIn("V636-P10-T01", owned[path]["consumers"])
                self.assertNotIn("V636-P10-T02", owned[path]["consumers"])

    def test_generator_is_idempotent_and_preserves_legacy_controller(self) -> None:
        legacy = (self.baseline_pack / "docs/configs/full-verifier-controller.v1.json").read_bytes()
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            (pack / "docs/configs/full-verifier-controller.v2.json").unlink()
            first = self.tool.apply_descendant_qualification_followup(pack)
            second = self.tool.apply_descendant_qualification_followup(pack)
            self.assertGreater(first["changed"], 0)
            self.assertEqual(second, {"result": "PASS", "changed": 0})
            self.assertEqual((pack / "docs/configs/full-verifier-controller.v1.json").read_bytes(), legacy)

    def test_generator_rejects_an_unknown_command_contract(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            registry_path = pack / "docs/registries/task-command-registry.v1.json"
            registry = read(registry_path)
            command = next(
                row for row in registry["commands"] if row["command_id"] == "VERIFY_V636_P08_T01"
            )
            command["argv"] = ["python3", "unowned-surrogate.py"]
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "E_DESCENDANT_UNKNOWN_COMMAND"):
                self.tool.apply_descendant_qualification_followup(pack)

    def test_generator_rejects_changed_command_shapes_before_writing(self) -> None:
        mutations = (
            ("VERIFY_V636_P08_T01", "cwd", "/unrelated"),
            ("VERIFY_V636_P08_T01", "network", "ALLOW"),
            (
                "VERIFY_V636_P08_T01",
                "argv",
                ["python3", "unowned-surrogate.py", "--comment", "tools/qualify_descendant_repository.py"],
            ),
            (
                "VERIFY_V636_P08_T01",
                "argv",
                [
                    "uv", "run", "--frozen", "--offline", "python",
                    "tools/qualify_descendant_repository.py", "--root", "/unrelated",
                ],
            ),
        )
        for command_id, field, value in mutations:
            with self.subTest(command_id=command_id, field=field), TemporaryDirectory() as directory:
                pack = Path(directory) / "pack"
                shutil.copytree(self.baseline_pack, pack)
                registry_path = pack / "docs/registries/task-command-registry.v1.json"
                registry = read(registry_path)
                command = next(row for row in registry["commands"] if row["command_id"] == command_id)
                command[field] = value
                registry_path.write_text(json.dumps(registry), encoding="utf-8")
                before = {
                    path.relative_to(pack).as_posix(): path.read_bytes()
                    for path in pack.rglob("*") if path.is_file()
                }
                with self.assertRaisesRegex(ValueError, "E_DESCENDANT_UNKNOWN_COMMAND"):
                    self.tool.apply_descendant_qualification_followup(pack)
                after = {
                    path.relative_to(pack).as_posix(): path.read_bytes()
                    for path in pack.rglob("*") if path.is_file()
                }
                self.assertEqual(after, before)

    def test_generator_accepts_the_exact_legacy_p08_shape(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            registry_path = pack / "docs/registries/task-command-registry.v1.json"
            registry = read(registry_path)
            command = next(
                row for row in registry["commands"] if row["command_id"] == "VERIFY_V636_P08_T01"
            )
            command.update(
                cwd=f"{PREFIX}/hybrid-discovery-v6.3.6-authoring",
                argv=[
                    "python3.12", "-B", "runtime/tools/export_zero_parent_candidate.py",
                    "--source", "runtime", "--destination", RUNTIME, "--candidate-receipt",
                    f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6/CANDIDATE_QUALIFICATION.json",
                    "--ownership", "pack/docs/registries/artifact-ownership.v1.json",
                ],
                purpose="Run exact authoring verifier for V636-P08-T01",
            )
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            self.assertEqual(self.tool.apply_descendant_qualification_followup(pack)["result"], "PASS")

    def test_generator_rejects_a_changed_review_command_before_writing(self) -> None:
        with TemporaryDirectory() as directory:
            pack = Path(directory) / "pack"
            shutil.copytree(self.baseline_pack, pack)
            registry_path = pack / "docs/registries/review-command-registry.v1.json"
            registry = read(registry_path)
            command = next(
                row for row in registry["commands"] if row["command_id"] == "REVIEW_AGGREGATE"
            )
            command["authenticated_operator_access"] = "ALLOW"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            before = {
                path.relative_to(pack).as_posix(): path.read_bytes()
                for path in pack.rglob("*") if path.is_file()
            }
            with self.assertRaisesRegex(ValueError, "E_DESCENDANT_UNKNOWN_COMMAND"):
                self.tool.apply_descendant_qualification_followup(pack)
            after = {
                path.relative_to(pack).as_posix(): path.read_bytes()
                for path in pack.rglob("*") if path.is_file()
            }
            self.assertEqual(after, before)

    def test_current_controller_and_proof_rows_bind_real_qualification_outputs(self) -> None:
        config = read(self.baseline_pack / "docs/configs/full-verifier-controller.v2.json")
        self.assertEqual(config["schema_version"], "full-verifier-controller/v2")
        self.assertEqual(config["audited_runtime_ancestor"], AUDITED_ANCESTOR)
        evidence = config["qualification_evidence"]
        self.assertEqual(
            set(evidence),
            {
                "full_repair_aggregate",
                "full_repair_inventory",
                "environment_qualification_aggregate",
                "environment_qualification_inventory",
                "p03_proof",
                "p04_proof",
            },
        )
        self.assertTrue(all(str(path).startswith(EVIDENCE + "/") for path in evidence.values()))
        self.assertNotEqual(
            config["receipts"]["authoring_repository"],
            read(self.baseline_pack / "docs/configs/full-verifier-controller.v1.json")["receipts"]["authoring_repository"],
        )
        self.assertEqual(
            config["receipts"]["descendant_repository"],
            f"{EVIDENCE}/DESCENDANT_REPOSITORY_QUALIFICATION.json",
        )

        proof = read(self.baseline_pack / "docs/registries/proof-coverage-matrix.v1.json")["entries"]
        self.assertEqual(len(proof), 18)
        by_requirement = {row["requirement_id"]: row for row in proof}
        self.assertEqual(
            by_requirement["V631-C5.CRASH_COVERAGE"]["evidence_artifact"], evidence["p03_proof"]
        )
        self.assertEqual(
            by_requirement["V631-C5.CLOCK_EVALUATION"]["evidence_artifact"], evidence["p04_proof"]
        )

    def test_current_commands_are_descendant_only_and_execute_real_p03_p04(self) -> None:
        registry = read(self.baseline_pack / "docs/registries/task-command-registry.v1.json")
        commands = {row["command_id"]: row for row in registry["commands"]}
        p03 = commands["TEST_V636_P03_T07"]["argv"]
        p04 = commands["TEST_V636_P04_T04"]["argv"]
        self.assertIn("tools/run_full_repair_qualification.py", p03)
        self.assertIn("tools/verify_full_repair_qualification.py", p04)
        self.assertNotIn("pytest", p03)
        self.assertNotIn("pytest", p04)

        p08_ids = [f"VERIFY_V636_P08_T0{index}" for index in range(1, 4)]
        p08_argv = [commands[command_id]["argv"] for command_id in p08_ids]
        flattened = " ".join(token for argv in p08_argv for token in argv).lower()
        self.assertNotIn("zero_parent", flattened)
        self.assertNotIn("zero-parent", flattened)
        self.assertIn("--preflight", p08_argv[0])
        self.assertIn("--issue", p08_argv[1])
        self.assertIn("--check-only", p08_argv[2])

        tasks = {row["task_id"]: row for row in read(self.baseline_pack / "docs/tasks/task-manifest.v6.3.6.json")["tasks"]}
        self.assertEqual(tasks["V636-P04-T04"]["dependencies"], ["V636-P03-T07", "V636-P04-T03"])
        self.assertEqual(tasks["V636-P08-T02"]["dependencies"], ["V636-P08-T01"])
        self.assertEqual(tasks["V636-P08-T03"]["dependencies"], ["V636-P08-T02"])
        for task_id in ("V636-P08-T01", "V636-P08-T02", "V636-P08-T03"):
            task_text = json.dumps(tasks[task_id]).lower()
            self.assertNotIn("zero-parent", task_text)
            self.assertNotIn("zero_parent", task_text)
            self.assertEqual(
                tasks[task_id]["tests_first"],
                ["runtime/tests/release/test_descendant_repository_qualification.py"],
            )
        self.assertNotIn("repo0", tasks["V636-P09-T01"]["objective"].lower())
        self.assertNotIn("repo0", tasks["V636-P09-T03"]["objective"].lower())
        self.assertEqual(commands["VERIFY_V636_P09_T01"]["cwd"], RUNTIME)
        self.assertIn(
            f"{PREFIX}/authoring-controller-config-worktree/pack",
            commands["VERIFY_V636_P09_T01"]["argv"],
        )
        self.assertEqual(commands["VERIFY_V636_P09_T03"]["cwd"], RUNTIME)
        self.assertIn(
            f"{PREFIX}/review-packs/hybrid-discovery-v6.3.6/docs/receipts/descendant-repository-qualification-receipt.json",
            commands["VERIFY_V636_P09_T03"]["argv"],
        )

    def test_current_review_configs_share_descendant_identity(self) -> None:
        review_a = read(self.baseline_pack / "docs/configs/review-a.v2.json")
        review_b = read(self.baseline_pack / "docs/configs/review-b.v2.json")
        self.assertEqual(review_a["schema_version"], "review-config/v2")
        self.assertEqual(review_b["schema_version"], "review-config/v2")
        self.assertIn("A_CHECK_DESCENDANT", review_a["mechanical_command_ids"])
        self.assertNotIn("A_CHECK_BASELINE", review_a["mechanical_command_ids"])
        self.assertEqual(review_a["repository_identity"], review_b["repository_identity"])
        self.assertEqual(review_a["repository_identity"]["kind"], "DESCENDANT")
        self.assertEqual(
            review_a["repository_identity"]["receipt"],
            f"{PREFIX}/review-packs/hybrid-discovery-v6.3.6/docs/receipts/descendant-repository-qualification-receipt.json",
        )

        task_commands = {
            row["command_id"]: row
            for row in read(self.baseline_pack / "docs/registries/task-command-registry.v1.json")["commands"]
        }
        self.assertIn("review-config/review-a.v2.json", task_commands["VERIFY_V636_P10_T01"]["argv"])
        self.assertIn("review-config/review-b.v2.json", task_commands["VERIFY_V636_P10_T02"]["argv"])
        self.assertIn(
            "review-config/review-aggregation.v2.json",
            task_commands["VERIFY_V636_P10_T04"]["argv"],
        )
        mig = task_commands["V636_MIG0_T08_BINDINGS"]
        self.assertEqual(mig["argv"][-2:], ["--review-config-profile", "current"])

        registry = read(self.baseline_pack / "docs/registries/review-command-registry.v1.json")
        commands = {row["command_id"]: row for row in registry["commands"]}
        argv = commands["A_CHECK_DESCENDANT"]["argv"]
        self.assertIn("tools/qualify_descendant_repository.py", argv)
        self.assertIn("--check-only", argv)
        self.assertNotIn("qualify_zero_parent_baseline.py", argv)

    def test_new_paths_have_one_owner_and_command_io_is_explicit(self) -> None:
        config = read(self.baseline_pack / "docs/configs/full-verifier-controller.v2.json")
        ownership = read(self.baseline_pack / "docs/registries/artifact-ownership.v1.json")["entries"]
        by_path: dict[str, list[dict[str, object]]] = {}
        for row in ownership:
            by_path.setdefault(row["path"], []).append(row)
        expected_paths = {
            "authoring-tools/apply_descendant_qualification_followup.py",
            "authoring-tests/test_descendant_qualification_followup.py",
            "pack/docs/configs/full-verifier-controller.v2.json",
            "pack/docs/schemas/descendant-repository-qualification-receipt.schema.json",
            "pack/docs/schemas/full-verifier-controller.schema.json",
            *config["qualification_evidence"].values(),
            config["receipts"]["authoring_repository"],
            config["receipts"]["descendant_repository"],
        }
        for path in expected_paths:
            with self.subTest(path=path):
                self.assertEqual(len(by_path.get(path, [])), 1)
                self.assertTrue(by_path[path][0]["creation_owner"])
        for path in (
            "pack/docs/contracts/07-command-and-config-lifecycle.md",
            "pack/docs/registries/task-command-registry.v1.json",
            "pack/docs/schemas/review-result.schema.json",
            "pack/docs/tasks/task-manifest.v6.3.6.json",
        ):
            self.assertIn("V636-MIG0-T08", by_path[path][0]["modifying_tasks"])

        io = {row["command_id"]: row for row in read(self.baseline_pack / "docs/registries/command-io.v1.json")["commands"]}
        self.assertIn(config["qualification_evidence"]["full_repair_aggregate"], io["TEST_V636_P03_T07"]["outputs"])
        self.assertIn(config["qualification_evidence"]["p03_proof"], io["TEST_V636_P03_T07"]["outputs"])
        self.assertIn(config["qualification_evidence"]["full_repair_aggregate"], io["TEST_V636_P04_T04"]["inputs"])
        self.assertIn(config["qualification_evidence"]["p04_proof"], io["TEST_V636_P04_T04"]["outputs"])
        self.assertIn(config["receipts"]["descendant_repository"], io["VERIFY_V636_P08_T02"]["outputs"])
        self.assertIn(config["receipts"]["descendant_repository"], io["VERIFY_V636_P08_T03"]["inputs"])

        current_configs = {
            "runtime/review-config/review-a.v2.json",
            "runtime/review-config/review-b.v2.json",
            "runtime/review-config/review-aggregation.v2.json",
            "runtime/review-config/review-authority.v1.json",
        }
        self.assertTrue(current_configs.issubset(set(io["V636_MIG0_T08_BINDINGS"]["outputs"])))
        self.assertIn("runtime/review-config/review-a.v2.json", io["VERIFY_V636_P10_T01"]["inputs"])
        self.assertIn("runtime/review-config/review-b.v2.json", io["VERIFY_V636_P10_T02"]["inputs"])
        self.assertIn(
            "runtime/review-config/review-aggregation.v2.json",
            io["VERIFY_V636_P10_T04"]["inputs"],
        )

        candidate = f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json"
        p07_evidence = {f"{EVIDENCE}/V636-P07-T0{index}.json" for index in range(1, 4)}
        for command_id in ("VERIFY_V636_P08_T01", "VERIFY_V636_P08_T02", "VERIFY_V636_P08_T03"):
            self.assertIn(candidate, io[command_id]["inputs"])
            self.assertTrue(p07_evidence.issubset(set(io[command_id]["inputs"])))
        self.assertTrue(({candidate} | p07_evidence).issubset(set(io["VERIFY_V636_P09_T01"]["inputs"])))
        self.assertTrue(({candidate} | p07_evidence).issubset(set(io["VERIFY_V636_P09_T03"]["inputs"])))

        supplemental = io["CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT"]
        self.assertEqual(
            set(supplemental["outputs"]),
            {
                config["qualification_evidence"]["environment_qualification_aggregate"],
                config["qualification_evidence"]["environment_qualification_inventory"],
            },
        )
        retained = by_path["runtime/tools/retained_artifact_io.py"][0]
        self.assertEqual(retained["creation_owner"], "V636-P03-T07")
        self.assertIn("runtime/tools/retained_artifact_io.py", io["TEST_V636_P03_T07"]["inputs"])

    def test_identity_schemas_keep_explicit_legacy_and_descendant_branches(self) -> None:
        schemas = (
            ("self-review-record.schema.json", "SelfReviewRecord", True),
            ("external-seal-attestation.schema.json", "ExternalSealAttestation", True),
            ("review-launch-authorization.schema.json", "ReviewLaunchAuthorization", True),
            ("review-execution-receipt.schema.json", "ReviewExecutionReceipt", False),
            ("review-result.schema.json", "ImplementationReviewResult", True),
        )
        for filename, logical_name, legacy_has_repo0 in schemas:
            with self.subTest(schema=filename):
                schema = read(self.baseline_pack / "docs/schemas" / filename)
                branch = schema["$defs"][logical_name]
                refs = [item["$ref"] for item in branch["oneOf"]]
                self.assertEqual(len(refs), 2)
                legacy = schema["$defs"][refs[0].rsplit("/", 1)[-1]]
                current = schema["$defs"][refs[1].rsplit("/", 1)[-1]]
                self.assertEqual("repo0_receipt_sha256" in legacy["properties"], legacy_has_repo0)
                self.assertNotIn("repository_qualification_receipt_sha256", legacy["properties"])
                self.assertNotIn("repo0_receipt_sha256", current["properties"])
                self.assertIn("repository_qualification_receipt_sha256", current["properties"])
                self.assertEqual(current["properties"]["repository_identity_kind"], {"const": "DESCENDANT"})

    def test_external_seal_current_branch_is_runtime_only_and_candidate_bound(self) -> None:
        schema = read(self.baseline_pack / "docs/schemas/external-seal-attestation.schema.json")
        validator = Draft202012Validator(
            {"$schema": schema["$schema"], "$ref": "#/$defs/ExternalSealAttestation", "$defs": schema["$defs"]}
        )
        current = schema["$defs"]["DescendantExternalSealAttestation"]
        self.assertEqual(current["properties"]["artifact_type"], {"const": "RUNTIME_PACK"})
        self.assertIn("candidate_receipt_sha256", current["required"])
        instance = {
            "schema_version": "external-seal-attestation/v7",
            "artifact_type": "RUNTIME_PACK",
            "artifact": "runtime.zip",
            "authorized_production_phases": "NONE",
            "created_at": "2026-09-07T00:00:00Z",
            "zip_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "governed_content_root": "c" * 64,
            "self_review_markdown_sha256": "d" * 64,
            "self_review_json_sha256": "e" * 64,
            "task_manifest_sha256": "f" * 64,
            "candidate_receipt_sha256": "1" * 64,
            "repository_qualification_receipt_sha256": "2" * 64,
            "repository_identity_kind": "DESCENDANT",
            "repository_commit_oid": "3" * 40,
            "repository_tree_oid": "4" * 40,
            "repository_file_tree_root_sha256": "5" * 64,
        }
        self.assertEqual(list(validator.iter_errors(instance)), [])
        missing_candidate = copy.deepcopy(instance)
        missing_candidate.pop("candidate_receipt_sha256")
        self.assertTrue(list(validator.iter_errors(missing_candidate)))
        plan = copy.deepcopy(instance)
        plan["artifact_type"] = "PLAN"
        self.assertTrue(list(validator.iter_errors(plan)))
        legacy_plan = {
            key: value
            for key, value in instance.items()
            if key
            not in {
                "candidate_receipt_sha256",
                "repository_qualification_receipt_sha256",
                "repository_identity_kind",
                "repository_commit_oid",
                "repository_tree_oid",
                "repository_file_tree_root_sha256",
            }
        }
        legacy_plan["schema_version"] = "external-seal-attestation/v6"
        legacy_plan["artifact_type"] = "PLAN"
        self.assertEqual(list(validator.iter_errors(legacy_plan)), [])

    def test_self_review_schema_accepts_each_identity_branch_and_rejects_mixed_identity(self) -> None:
        schema = read(self.baseline_pack / "docs/schemas/self-review-record.schema.json")
        validator = Draft202012Validator(
            {
                "$schema": schema["$schema"],
                "$ref": "#/$defs/SelfReviewRecord",
                "$defs": schema["$defs"],
            }
        )
        legacy = {
            "schema_version": "runtime-self-review/v1",
            "governed_content_root": "root",
            "repo0_receipt_sha256": "legacy",
            "candidate_qualification_sha256": "candidate",
            "task_manifest_sha256": "tasks",
            "command_result_root": "commands",
            "checks": [{}],
            "authority_granted": "NONE",
        }
        current = {
            "schema_version": "runtime-self-review/v2",
            "governed_content_root": "root",
            "repository_qualification_receipt_sha256": "a" * 64,
            "repository_identity_kind": "DESCENDANT",
            "repository_commit_oid": "b" * 40,
            "repository_tree_oid": "c" * 40,
            "repository_file_tree_root_sha256": "d" * 64,
            "candidate_qualification_sha256": "candidate",
            "task_manifest_sha256": "tasks",
            "command_result_root": "commands",
            "checks": [{}],
            "authority_granted": "NONE",
        }
        self.assertEqual(list(validator.iter_errors(legacy)), [])
        self.assertEqual(list(validator.iter_errors(current)), [])
        mixed = copy.deepcopy(current)
        mixed["repo0_receipt_sha256"] = "legacy"
        self.assertTrue(list(validator.iter_errors(mixed)))
        wrong_version = copy.deepcopy(current)
        wrong_version["schema_version"] = "runtime-self-review/v1"
        self.assertTrue(list(validator.iter_errors(wrong_version)))

    def test_controller_schema_accepts_exact_v1_and_v2_but_rejects_mixed_fields(self) -> None:
        schema = read(self.baseline_pack / "docs/schemas/full-verifier-controller.schema.json")
        validator = Draft202012Validator(
            {
                "$schema": schema["$schema"],
                "$ref": "#/$defs/FullVerifierController",
                "$defs": schema["$defs"],
            }
        )
        legacy = read(self.baseline_pack / "docs/configs/full-verifier-controller.v1.json")
        current = read(self.baseline_pack / "docs/configs/full-verifier-controller.v2.json")
        self.assertEqual(list(validator.iter_errors(legacy)), [])
        self.assertEqual(list(validator.iter_errors(current)), [])
        mixed = copy.deepcopy(legacy)
        mixed["audited_runtime_ancestor"] = AUDITED_ANCESTOR
        self.assertTrue(list(validator.iter_errors(mixed)))
        wrong_version = copy.deepcopy(current)
        wrong_version["schema_version"] = "full-verifier-controller/v1"
        self.assertTrue(list(validator.iter_errors(wrong_version)))

    def test_delivery_and_normative_maps_export_the_amendment(self) -> None:
        delivery = read(self.baseline_pack / "docs/registries/delivery-map.v1.json")
        exports = {row["source"] for row in delivery["authoring_source_exports"]}
        self.assertIn("authoring-tools/apply_descendant_qualification_followup.py", exports)
        self.assertIn("authoring-tests/test_descendant_qualification_followup.py", exports)
        normative = read(self.baseline_pack / "docs/registries/normative-source-map.v1.json")
        plan_sources = {row["plan_source"] for row in normative["plan_entries"]}
        self.assertIn("docs/configs/full-verifier-controller.v2.json", plan_sources)
        self.assertIn("docs/schemas/descendant-repository-qualification-receipt.schema.json", plan_sources)

        rows = []
        for entry in sorted(delivery["authoring_source_exports"], key=lambda item: item["source"].encode()):
            payload = (ROOT / entry["source"]).read_bytes()
            rows.append(
                f"{entry['source']}\0{len(payload)}\0{hashlib.sha256(payload).hexdigest()}\n".encode()
            )
        expected = hashlib.sha256(b"".join(rows)).hexdigest()
        config = read(self.baseline_pack / "docs/configs/full-verifier-controller.v2.json")
        self.assertEqual(config["external_authoring_source_sha256"], expected)


if __name__ == "__main__":
    unittest.main()
