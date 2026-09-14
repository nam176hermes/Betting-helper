"""Materialize the user-approved W00-W12 amendment from its pinned predecessor.

This declares current source validation. It never changes historical receipts or
grants provider, operator, signing or production authority.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

BASE = "2aeadf705955889a9c2f75c27cbee92dfe64cbde"
PREDECESSOR_SHA256 = "895c283e683aa34a37bf4a4ba55c0a3c11b301bee6f469cc9b97c344946a115c"
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = "/home/thenam176/betting-helper/part-b-candidate"
AUTHORING = "/home/thenam176/betting-helper/authoring-part-b-review-inputs"
EVIDENCE = "/home/thenam176/betting-helper/authoring-evidence/part-b-review-blockers-r24"
REVIEW_HOST = "/home/thenam176/betting-helper/part-b-review-host-r24"
OLD_REVIEW_HOST = "/home/thenam176/betting-helper/part-b-review-host"
OLD_EVIDENCE = "/home/thenam176/betting-helper/authoring-evidence/part-b-seal-qualification"
CONTRACT = "pack/docs/contracts/part-b-one-ready.v1.json"
SECURITY_CONTRACT = "pack/docs/contracts/10-part-b-security-surface.md"
SECURITY_TEXT = """# Current Part B security qualification surface

This W00-W12 source amendment binds current qualification to the delivered
live-v2 package and the still-denied legacy entrypoint. It grants no live or
production authority and changes no historical receipt. The legacy v1 all-source
scanner remains available unchanged in meaning; its rejection of unsupported
Part A/live modules is not a successful v1 product qualification.

The allow oracle in the six security leaves and the first inherited capability
bootstrap test now consumes `extension/test/security/current-surface.ts`.
Every existing named test, denied vector and mutation remains mandatory. The
adapter executes current bootstrap/CDP/target denial, checks the existing manifest,
and scans an explicit current-source closure containing bootstrap.ts, errors.ts,
security/cdp-broker.ts and security/target-policy.ts. Any new import or privilege
in that closure must fail or receive a new declared amendment. No copy of old
green source replaces current bytes; its current compiled closure is scanned too.
Legacy product implementation remains
NOT_QUALIFIED; the synthetic-only RawObservation gate remains closed to live data.

The same adapter builds the actual Part B extension through the canonical
`build_live_extension` owner and imports all four current live TypeScript test
modules. The six security command IDs and their deny/mutation mappings remain
unchanged. P05-T09 owns the explicit inherited allow-oracle adaptation and its
compiler output. Its complete compile, current security leaves, inherited corpus
and TEST_RELEASE_TOOLS (including all tests/live) must pass on frozen bytes.

The inherited Python capability allow test consumes that same current adapter;
its existing named tests and negative vector cases remain mandatory. The custody
identifier guard parses every non-comment TypeScript leaf token with the pinned
compiler, including private identifiers, regex literals and template fragments;
it retains decoded names, rejects malformed syntax, and matches acknowledged-record
deletion names without mistaking the word backend for an acknowledgement. All
automatic archive, backup, compaction, restore and individual-deletion negatives
remain enforced. The schema-format test adapts only its disposable SpoolRecord
to the current observation ID format and recomputes its hash before format
mutations. Historical vector bytes, hashes and test symbols remain unchanged.

`contracts/live_readonly/v1/package-policy.json` independently declares finite
modules/assets, entrypoints, manifest, Chrome owners, exact fixed WebSocket routes,
storage owner and isolated operator reader. `verify_live_package` checks emitted
code without executing it, requires the exact file set and import closure, rejects
test/harness additions and the declared capability escape corpus, and checks selected-tab/frame
script injection shape. Ambient .d.ts files emit no production .js file.
The builder cannot auto-adopt newly discovered live modules. This check is
STATIC_PACKAGE_BOUNDARY_ONLY; this finite grammar is not a general JavaScript
noninterference proof, and integrity hashes alone are not behavioral proof.

Current protocol/role/schema/fixture binding, storage durability, budgets,
credential nonleakage and actual isolated-browser tests remain separate required
obligations. UI DOM writes stay in extension documents; operator capture stays
read-only. Changed shared source requires fresh Part A regressions. Browser
requirements cannot be discharged by mocks. Current host signing, separate fresh
human reviewer sessions, accepted provider/profile/platform evidence and bounded
user-terminal live consent remain mandatory. Models and money remain disabled.
"""
NEW_AUTHORING = (
    "authoring-tools/prepare_one_ready_inputs.py",
    "authoring-tools/validate_current_phase_inputs.py",
    "authoring-tests/test_one_ready_inputs.py",
    "authoring-tests/test_current_phase_inputs.py",
    "authoring-fixtures/part-b-one-ready-predecessor.json",
    "authoring-fixtures/part-b-review-launch-source.json",
    "authoring-fixtures/part-b-security-surface-source.json",
)
AUTHORING_EDITS = (
    "authoring-tools/build_task_command_registry.py",
    "authoring-tests/test_command_registry_generation.py",
    "authoring-tools/issue_declaration_gate.py",
    "authoring-tests/test_declaration_gate.py",
    "authoring-tests/test_task_manifest_semantics.py",
)
# Explicit authorization inventory, never inferred from compiler/test observations.
RUNTIME_FILES = (
    'tools/verify_test_discovery.py',
    'tools/verify_executable_references.py',
    'src/moj_discovery/executable_gate.py',
    'src/moj_discovery/review_aggregation.py',
    'tests/release/test_executable_references.py',
    'tests/release/test_executable_complete_gate.py',
    'tests/release/test_verification_topology.py',
    'tests/review/test_descendant_namespace_projection.py',
    ".contract-stub-registry.json",
    "docs/execution/PART_B_PROGRESS.md",
    "src/moj_discovery/canonical.py",
    "src/moj_discovery/review_authorization.py",
    "src/moj_discovery/governance.py",
    "src/moj_discovery/secrets_local.py",
    "src/moj_discovery/windows_credential_store.py",
    "src/moj_discovery/live_config.py",
    "src/moj_discovery/live_intent.py",
    "src/moj_discovery/live_preflight_batched.py",
    "src/moj_discovery/operator_profile.py",
    "src/moj_discovery/providers/api_football.py",
    "src/moj_discovery/live_service.py",
    "tools/phase_evidence.py",
    "tools/gap_coherence_crash_child.py",
    "tools/verify_local.py",
    "tools/run_command_registry.py",
    "tools/verify_proof_coverage.py",
    "tools/full_verifier_config.py",
    "tools/prepare_review_workspace.py",
    "tools/issue_review_launch_authorization.py",
    "tools/run_review_a_checks.py",
    "tools/run_review_b_checks.py",
    "tools/finalize_review.py",
    "tools/aggregate_reviews.py",
    "tools/assemble_review_pack.py",
    "tools/seal_review_pack.py",
    "tools/build_candidate_qualification_receipt.py",
    "tools/run_environment_qualification.py",
    "tools/native_environment_probe.py",
    "tools/verify_repair_evidence.py",
    "tools/verify_full_repair_qualification.py",
    "tests/repairs/test_clock_validation_batch.py",
    "tests/repairs/test_full_repair_orchestrator.py",
    "tools/windows_credential_helper.py",
    "tools/run_with_api_football_key.py",
    "tools/run_live_readonly.py",
    "tools/launch_part_b.py",
    "tools/package_part_b.py",
    "tools/verify_live_package.py",
    "tools/qualify_live_platform.py",
    "tools/qualify_live_readonly.py",
    "tools/verify_part_b.py",
    "tools/probe_football_provider.py",
    "tools/prepare_part_b_intent.py",
    "tools/live_preflight_batched.py",
    "contracts/live_readonly/v1/config.schema.json",
    "contracts/live_readonly/v1/package-policy.json",
    "review-config/review-a.v2.json",
    "review-config/review-b.v2.json",
    "review-config/review-a.v3.json",
    "review-config/review-b.v3.json",
    "review-config/review-aggregation.v2.json",
    "review-config/review-authority.v1.json",
    "tests/repairs/test_phase_evidence.py",
    "tests/repairs/test_pipe_browser_qualification.py",
    "tests/bootstrap/test_capability_reachability.py",
    "tests/bootstrap/test_schema_format_checker.py",
    "tests/security/test_no_archive_policy.py",
    "tests/security/test_bubblewrap_isolation.py",
    "tests/live/test_live_spool_bridge.py",
    "tests/durability/test_gap_generation_process_crash.py",
    "tests/repairs/test_full_verifier_controller_config.py",
    "tests/release/test_candidate_qualification_receipt.py",
    "tests/release/test_candidate_command_registry.py",
    "tests/release/test_full_proof_coverage.py",
    "tests/release/test_descendant_repository_qualification.py",
    "tests/seal/test_pack_assembly.py",
    "tests/seal/test_self_review_binding.py",
    "tests/seal/test_deterministic_seal.py",
    "tests/review/test_review_b_runner.py",
    "tests/review/test_review_launch_authorization.py",
    "tests/review/test_review_workspace_isolation.py",
    "tests/review/test_review_aggregation_and_self_review.py",
    "tests/contracts/test_artifact_dependency_semantics.py",
    "tests/contracts/test_declaration_complete_gate.py",
    "tests/contracts/test_task_manifest_semantics.py",
    "tests/live/test_windows_credential_store.py",
    "tests/live/test_part_b_launcher.py",
    "tests/live/test_part_b_package.py",
    "tests/live/test_part_b_inventory.py",
    "tests/live/test_secret_entry.py",
    "tests/live/test_secret_nonleakage.py",
    "tests/live/test_run_intents.py",
    "tests/live/test_live_preflight_batched.py",
    "tests/live/test_admitted_live_bindings.py",
    "tests/live/test_workspace_projection.py",
    "tests/live/test_platform_binding.py",
    "tests/live/test_live_qualification.py",
    "tests/live/test_live_security.py",
    "tests/live/test_live_contracts.py",
    "extension/manifest.live.json",
    "extension/tools/verify-capability-graph.ts",
    "extension/test/security/current-surface.ts",
    "extension/test/security/capability-reachability.bootstrap.test.ts",
    "extension/test/security/cdp-reachability.test.ts",
    "extension/test/security/dynamic-dispatch.test.ts",
    "extension/test/security/message-smuggling.test.ts",
    "extension/test/security/outbound-network.test.ts",
    "extension/test/security/target-escape.test.ts",
    "extension/test/security/production-build-exclusion.test.ts",
    "extension/src/live/panel.ts",
    "extension/src/live/workspace.ts",
    "extension/src/live/background.ts",
    "extension/src/live/panel.html",
    "extension/src/live/workspace.html",
    "extension/src/live/panel.css",
    "extension/test/live/panel.test.ts",
    "docs/runbooks/INSTALL_PART_B_VI.md",
    "docs/runbooks/RUN_ONE_MATCH_VI.md",
)
PHASES = {
    "V636-MIG0-T06": ["VALIDATE_CURRENT_DESCENDANT_MIGRATION"],
    "V636-P00-T05": ["VALIDATE_CURRENT_DECLARATION"],
    **{f"V636-{task}": [f"TEST_V636_{task.replace('-', '_')}"] for task in (
        "P02-T02", "P03-T02", "P05-T02", "P05-T04", "P05-T05", "P06-T01"
    )},
    "V636-P05-T09": [
        "COMPILE_ALL_TESTS", "COMPILE_PRODUCTION", "TEST_RELEASE_TOOLS",
        "TEST_SECURITY_PY", "TEST_SECURITY_TS", "QUALIFY_INHERITED_BOOTSTRAP_PY",
        "QUALIFY_INHERITED_BOOTSTRAP_TS", "QUALIFY_INHERITED_CANONICAL_PY",
        "QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS", "QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK",
    ],
}


def predecessor(root):
    path = root / "authoring-fixtures/part-b-one-ready-predecessor.json"
    raw = path.read_bytes()
    if path.resolve() != path or path.stat().st_nlink != 1 or hashlib.sha256(raw).hexdigest() != PREDECESSOR_SHA256:
        raise ValueError("E_ONE_READY_PREDECESSOR")
    value = json.loads(raw)
    if value["commit"] != BASE:
        raise ValueError("E_ONE_READY_PREDECESSOR")
    originals = {name: base64.b64decode(data, validate=True) for name, data in value["files"].items()}
    for name, digest in (
        ("part-b-review-launch-source.json", "8e84d4768f5a4315684b44f62627ed9cf5bccfede96c5e18b74388b80b1bcc84"),
        ("part-b-security-surface-source.json", "53a912462a45ed18d6a606a274e71700b958c4b2935228d7b6fa36b636826571"),
    ):
        path = root / "authoring-fixtures" / name
        raw = path.read_bytes()
        if path.resolve() != path or path.stat().st_nlink != 1 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("E_ONE_READY_FOLLOWUP_SOURCE")
        frozen = json.loads(raw)
        data = encode(frozen["document"])
        if frozen["source_commit"] != BASE or hashlib.sha256(data).hexdigest() != frozen["source_sha256"]:
            raise ValueError("E_ONE_READY_FOLLOWUP_SOURCE")
        originals[frozen["path"]] = data
    return originals


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def build(original):
    docs = {name: json.loads(data) for name, data in original.items()}
    def doc(name):
        return docs["pack/docs/" + name]
    # New campaign paths. Historical receipt bytes remain immutable inputs;
    # the current authoring receipt must be issued at its new declared locator.
    def transport(value):
        if isinstance(value, str):
            for old, new in ((OLD_EVIDENCE, EVIDENCE), (OLD_REVIEW_HOST, REVIEW_HOST)):
                value = new if value == old else value.replace(old + "/", new + "/")
            return value
        if isinstance(value, list):
            return [transport(v) for v in value]
        if isinstance(value, dict):
            return {k: transport(v) for k, v in value.items()}
        return value
    docs = transport(docs)
    bindings = next(row for row in doc("registries/task-command-registry.v1.json")["commands"]
                    if row["command_id"] == "V636_MIG0_T08_BINDINGS")
    bindings["argv"][bindings["argv"].index("--review-config-profile") + 1] = "scoped"
    # The current host uses a separately named root. Preserve the legacy branch
    # and old v2 receipts; admit only the two exact current configured locations.
    launch_schema = "pack/docs/schemas/review-launch-authorization.schema.json"
    launch_props = docs[launch_schema]["$defs"]["DescendantReviewLaunchAuthorization"]["properties"]
    for field, configured in (("workspace_root", "workspace_root"), ("allowed_output_root", "output_root")):
        launch_props[field] = {"anyOf": [launch_props[field], {"enum": [
            doc(f"configs/review-{role}.v2.json")[configured] for role in ("a", "b")
        ]}, {"type": "string", "pattern": "^" + REVIEW_HOST + (
            "/workspaces/" if field == "workspace_root" else "/results/"
        ) + "review-[ab]/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"}]}
    launch_props["maximum_duration_seconds"] = {"type": "integer", "enum": [14400, 28800]}
    doc("configs/review-aggregation.v2.json")["maximum_launch_age_seconds"] = 28800
    for role in ("a",):
        doc(f"configs/review-{role}.v2.json")["producer_environment"]["python_executable_sha256"] = "e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f"
    for role in ("a", "b"):
        doc(f"configs/review-{role}.v2.json")["python_runtime"] = {"root": "/home/thenam176/betting-helper/toolchains/review-python-ubuntu-3.12.3-0.17", "sha256": "9226a858b665f6a2fedf67daa92ca5631e45ffee0c0739b26ee3e974f244fe0d"}
        doc(f"configs/review-{role}.v2.json")["environment"]["PYTHONDONTWRITEBYTECODE"] = "1"
    scoped_configs = []
    for role in ("a", "b"):
        name = f"pack/docs/configs/review-{role}.v3.json"
        cfg = json.loads(json.dumps(doc(f"configs/review-{role}.v2.json")))
        cfg.update(schema_version="review-config/v3", scope_input_root=RUNTIME + "/.local/part-b/review-inputs")
        if "producer_environment" in cfg:
            cfg["producer_environment"]["python_executable_sha256"] = "e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f"
        cfg["python_runtime"] = {"root": "/home/thenam176/betting-helper/toolchains/review-python-ubuntu-3.12.3-0.17", "sha256": "9226a858b665f6a2fedf67daa92ca5631e45ffee0c0739b26ee3e974f244fe0d"}
        cfg["environment"]["PYTHONDONTWRITEBYTECODE"] = "1"
        docs[name] = cfg
        scoped_configs.append(name)
    controller = doc("configs/full-verifier-controller.v2.json")
    controller["evidence_root"] = EVIDENCE
    controller["external_authoring_command"]["argv"].append(
        AUTHORING + "/plan-input/bootstrap/test_bootstrap_tools.py"
    )
    tasks = doc("tasks/task-manifest.v6.3.6.json")["tasks"]
    # Retain the existing BOOT0 receipt and the declared current v2 receipt;
    # there is no new bootstrap operation producing this obsolete extra locator.
    next(t for t in tasks if t["task_id"] == "V636-P09-T01")["inputs"].remove(
        EVIDENCE + "/bootstrap/authoring-repository-receipt.json"
    )
    order = {row["task_id"]: i for i, row in enumerate(tasks)}
    entries = doc("registries/artifact-ownership.v1.json")["entries"]
    # These superseded current-campaign locators have no producer. Keep the
    # separately located historical BOOT0 receipt and the actual v2 producer.
    obsolete_receipts = {
        EVIDENCE + "/bootstrap/authoring-repository-receipt.json",
        EVIDENCE + "/bootstrap/authoring-repository-receipt-descendant-source-v1.json",
    }
    migration = next(t for t in tasks if t["task_id"] == "V636-MIG0-T08")
    for field in ("outputs", "exact_files"):
        migration[field] = [p for p in migration[field] if p not in obsolete_receipts]
    entries[:] = [row for row in entries if row["path"] not in obsolete_receipts]
    release = next(t for t in tasks if t["task_id"] == "V636-P05-T09")
    release["exact_symbols"].remove(
        "runtime/tests/release/test_post_commit_baseline.py::test_full_registry_replays_in_actual_committed_repository"
    )
    release["exact_symbols"].extend([
        "runtime/tests/release/test_descendant_repository_qualification.py::test_descendant_uses_actual_eighteen_requirement_matrix",
        "runtime/tests/release/test_descendant_repository_qualification.py::test_descendant_record_recursively_validates_full_and_supplemental_proofs",
    ])
    owned = {row["path"]: row for row in entries}
    approved = {}
    # Retain the existing bootstrap guide as a current declared pack input;
    # this does not execute BOOT0 or change any historical receipt.
    inherited_path = "pack/docs/registries/inherited-baseline-qualification.v1.json"
    for path in (*NEW_AUTHORING, *AUTHORING_EDITS, *scoped_configs, CONTRACT, SECURITY_CONTRACT, inherited_path, launch_schema, "pack/BOOTSTRAP.md", *("runtime/" + p for p in RUNTIME_FILES)):
        owner = "V636-P05-T09" if path.startswith("runtime/") and not path.startswith("runtime/review-config/") else "V636-MIG0-T08"
        if path == "runtime/extension/test/security/current-surface.ts":
            owner = "V636-P01-T02"
        row = owned.get(path)
        if row is None:
            row = {"path": path, "classification": "TASK_OUTPUT", "creation_owner": owner,
                   "modifying_tasks": [], "materialization_required": True, "source": None,
                   "qualification_owner": owner, "consumers": [owner, "V636-P09-T01"]}
            entries.append(row)
            owned[path] = row
        else:
            prior = row["creation_owner"]
            if prior and order[prior] > order[owner]:
                owner = prior
            if owner != prior:
                row["modifying_tasks"] = sorted(set(row["modifying_tasks"]) | {owner}, key=order.get)
            row["consumers"] = sorted(set(row["consumers"]) | {owner}, key=order.get)
        approved[path] = owner
        task = next(t for t in tasks if t["task_id"] == owner)
        for field in ("outputs", "exact_files"):
            task[field] = sorted(set(task[field]) | {path})
    adapter_source = owned["runtime/extension/test/security/current-surface.ts"]
    adapter_source["modifying_tasks"] = ["V636-P05-T09"]
    adapter_source["qualification_owner"] = "V636-P05-T09"
    adapter_source["consumers"] = ["V636-P04-T03", "V636-P05-T09", "V636-P09-T01"]
    for field in ("outputs", "exact_files"):
        task = next(t for t in tasks if t["task_id"] == "V636-P05-T09")
        task[field] = sorted(set(task[field]) | {adapter_source["path"]})
    delivery = doc("registries/delivery-map.v1.json")
    for name in NEW_AUTHORING:
        delivery["authoring_source_exports"].append({"source": name, "destination": "pack/authoring-source/" + name, "owner": "V636-P09-T01"})
    mapping = doc("registries/normative-source-map.v1.json")
    mapping["plan_entries"].append({"plan_source": CONTRACT.removeprefix("pack/"), "vendor_relative": CONTRACT.removeprefix("pack/")})
    mapping["plan_entries"].append({"plan_source": SECURITY_CONTRACT.removeprefix("pack/"), "vendor_relative": SECURITY_CONTRACT.removeprefix("pack/")})
    for path in scoped_configs:
        mapping["plan_entries"].append({"plan_source": path.removeprefix("pack/"), "vendor_relative": path.removeprefix("pack/")})
    for row in docs[inherited_path]["typescript_files"]:
        if row["path"] == "runtime/extension/test/security/capability-reachability.bootstrap.test.ts":
            if row["modification_owner"] is not None:
                raise ValueError("E_ONE_READY_SECURITY_PREDECESSOR")
            row["modification_owner"] = "V636-P05-T09"
    for row in docs[inherited_path]["python_files"]:
        if row["path"] in {
            "runtime/tests/bootstrap/test_capability_reachability.py",
            "runtime/tests/bootstrap/test_schema_format_checker.py",
        }:
            if row["modification_owner"] is not None:
                raise ValueError("E_ONE_READY_SECURITY_PREDECESSOR")
            row["modification_owner"] = "V636-P05-T09"
    row = next(row for row in docs[inherited_path]["source_consumers"]
               if row["path"] == "runtime/src/moj_discovery/governance.py")
    row["modification_owners"].append("V636-P05-T09")
    row["qualification_owner"] = "V636-P05-T09"
    registry = doc("registries/task-command-registry.v1.json")
    next(row for row in registry["commands"] if row["command_id"] == "VERIFY_EXTERNAL_AUTHORING_SOURCES")["argv"] = list(controller["external_authoring_command"]["argv"])
    next(row for row in registry["commands"] if row["command_id"] == "TEST_V636_P05_T05")["argv"].append("tests/review/test_descendant_namespace_projection.py")
    # Historical command meanings are immutable, even when current roots change.
    historical = {r["command_id"]: r for r in json.loads(original["pack/docs/registries/task-command-registry.v1.json"])["commands"]}
    for row in registry["commands"]:
        if row["command_id"] in {"VERIFY_V636_MIG0_T06", "ISSUE_V636_P00_T05"} or row["command_id"].startswith("BOOT0_"):
            row.update(historical[row["command_id"]])
        if row["command_id"] in {f"VERIFY_V636_P09_T0{i}" for i in range(1, 5)}:
            # Sealing revalidates exact process provenance from the qualified venv.
            if row["argv"][:2] != ["python3.12", "-B"]:
                raise ValueError("E_ONE_READY_SEALING_PREDECESSOR")
            row["argv"] = ["uv", "run", "--frozen", "--offline", "python", *row["argv"][1:]]
    for mode, command_id in (("declaration", "VALIDATE_CURRENT_DECLARATION"), ("migration", "VALIDATE_CURRENT_DESCENDANT_MIGRATION")):
        row = {"command_id": command_id, "cwd": AUTHORING,
               "argv": [RUNTIME + "/.venv/bin/python", "-B", "authoring-tools/validate_current_phase_inputs.py", "--mode", mode, "--runtime", RUNTIME, "--contract", CONTRACT],
               "purpose": "Validate current " + mode + " inputs; preserve historical receipts",
               "expected_exit": 0, "available_at": "MATERIALIZED", "network": "DENY",
               "authenticated_operator_access": "DENY", "provider_access": "DENY", "kind": "verification"}
        registry["commands"].append(row)
        doc("registries/command-io.v1.json")["commands"].append({"command_id": command_id, "consumers": ["V636-MIG0-T08", "V636-P07-T01"], "inputs": [CONTRACT, "authoring-tools/validate_current_phase_inputs.py"], "outputs": [], "input_directories": []})
        next(t for t in tasks if t["task_id"] == "V636-MIG0-T08")["exact_command_ids"].append(command_id)
    # Explicit producer and finite outputs; no guessed evidence directory sweep.
    producer = "ISSUE_CURRENT_PHASE_PROOFS"
    registry["commands"].append({"command_id": producer, "cwd": RUNTIME,
        "argv": ["uv", "run", "--frozen", "--offline", "python", "-m", "tools.phase_evidence", "--config", RUNTIME + "/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"],
        "purpose": "Issue current phase evidence from retained actual registered invocations",
        "expected_exit": 0, "available_at": "MATERIALIZED", "network": "DENY",
        "authenticated_operator_access": "DENY", "provider_access": "DENY", "kind": "operation"})
    io = doc("registries/command-io.v1.json")["commands"]
    checkpoint = EVIDENCE + "/CURRENT_INPUTS.json"
    proof_paths = [EVIDENCE + "/" + phase + ".json" for phase in PHASES]
    io.append({"command_id": producer, "consumers": ["V636-P07-T01"],
        "inputs": [CONTRACT, "runtime/tools/phase_evidence.py", checkpoint, EVIDENCE + "/V636-P07-T01.json"],
        "outputs": proof_paths.copy(), "input_directories": []})
    next(t for t in tasks if t["task_id"] == "V636-P07-T01")["exact_command_ids"].append(producer)
    next(r for r in io if r["command_id"] == "VERIFY_V636_P07_T01")["outputs"].append(checkpoint)
    next(r for r in io if r["command_id"] == "VERIFY_V636_P07_T02")["inputs"].extend(proof_paths)
    release_test = "tests/repairs/test_phase_evidence.py"
    next(r for r in registry["commands"] if r["command_id"] == "TEST_RELEASE_TOOLS")["argv"].extend([release_test, "tests/live"])
    next(r for r in io if r["command_id"] == "TEST_RELEASE_TOOLS")["inputs"].append("runtime/" + release_test)
    next(r for r in io if r["command_id"] == "TEST_RELEASE_TOOLS")["input_directories"].append("runtime/tests/live")

    def output(path, owner, consumers, source=None):
        if path in owned:
            raise ValueError("E_ONE_READY_DUPLICATE:" + path)
        row = {"path": path, "classification": "GENERATED_OUTPUT" if source else "EVIDENCE_OUTPUT",
               "creation_owner": owner, "modifying_tasks": [], "materialization_required": bool(source),
               "source": {"path": source} if source else None,
               "qualification_owner": owner if source else None, "consumers": consumers}
        entries.append(row); owned[path] = row
        task = next(t for t in tasks if t["task_id"] == owner)
        task["outputs"].append(path); task["exact_files"].append(path)
        return row

    vendor_contract = "runtime/vendor/hybrid-discovery-v6.3.6/" + CONTRACT.removeprefix("pack/")
    output(vendor_contract, "V636-MIG0-T08", ["V636-P07-T01", "V636-P09-T01"], CONTRACT)
    next(r for r in io if r["command_id"] == "V636_MIG0_T08_SYNC")["outputs"].append(vendor_contract)
    vendor_security = "runtime/vendor/hybrid-discovery-v6.3.6/" + SECURITY_CONTRACT.removeprefix("pack/")
    output(vendor_security, "V636-MIG0-T08", ["V636-P07-T01", "V636-P09-T01"], SECURITY_CONTRACT)
    next(r for r in io if r["command_id"] == "V636_MIG0_T08_SYNC")["outputs"].append(vendor_security)
    adapter = "runtime/extension/test/security/current-surface.ts"
    compiled_adapter = "runtime/extension/.test-build/test/security/current-surface.js"
    generated = output(compiled_adapter, "V636-P04-T03", ["V636-P05-T09", "V636-P10-T02"], adapter)
    generated["modifying_tasks"] = ["V636-P05-T09"]
    generated["qualification_owner"] = "V636-P05-T09"
    task = next(t for t in tasks if t["task_id"] == "V636-P05-T09")
    task["outputs"].append(compiled_adapter); task["exact_files"].append(compiled_adapter)
    for command_id in ("COMPILE_V636_P04_T03", "COMPILE_ALL_TESTS"):
        row = next(r for r in io if r["command_id"] == command_id)
        row["inputs"].append(adapter); row["outputs"].append(compiled_adapter)
    for command_id in ("TEST_SECURITY_TS", "QUALIFY_INHERITED_BOOTSTRAP_TS", "QUALIFY_INHERITED_BOOTSTRAP_PY"):
        row = next(r for r in io if r["command_id"] == command_id)
        row["inputs"].extend([compiled_adapter, "runtime/tools/verify_live_package.py",
            "runtime/contracts/live_readonly/v1/package-policy.json", SECURITY_CONTRACT])
    for name in (
        "configs/full-verifier-controller.v1.json", "configs/full-verifier-controller.v2.json",
        "configs/review-a.v2.json", "configs/review-aggregation.v2.json", "configs/review-b.v2.json",
        "configs/review-a.v3.json", "configs/review-b.v3.json",
        "schemas/descendant-repository-qualification-receipt.schema.json",
        "schemas/full-verifier-controller.schema.json",
    ):
        destination = "runtime/vendor/hybrid-discovery-v6.3.6/docs/" + name
        output(destination, "V636-MIG0-T08", ["V636-P07-T01", "V636-P09-T01"], "pack/docs/" + name)
        next(r for r in io if r["command_id"] == "V636_MIG0_T08_SYNC")["outputs"].append(destination)
    for role in ("a", "b"):
        path = f"runtime/review-config/review-{role}.v3.json"
        owned[path]["classification"] = "GENERATED_OUTPUT"
        owned[path]["source"] = {"path": f"pack/docs/configs/review-{role}.v3.json"}
        owned[path]["consumers"].extend(["V636-P10-T01", "V636-P10-T02", "V636-P10-T03", "V636-P10-T04"])
        binding_io = next(r for r in io if r["command_id"] == "V636_MIG0_T08_BINDINGS")
        binding_io["outputs"].append(path)
        binding_io["inputs"].append(f"pack/docs/configs/review-{role}.v3.json")
    for path in proof_paths:
        phase = Path(path).stem
        row = output(path, phase, ["V636-P07-T01", "V636-P07-T02", "V636-P09-T01"])
        row["modifying_tasks"] = ["V636-P07-T01"]
    output(checkpoint, "V636-P07-T01", ["V636-P07-T01", "V636-P07-T02", "V636-P09-T01"])
    next(t for t in tasks if t["task_id"] == "V636-P09-T01")["inputs"].append(checkpoint)
    topology = ROOT / "pack/docs/registries/verification-topology.v1.json"
    if topology.resolve() != topology or hashlib.sha256(topology.read_bytes()).hexdigest() != "6dc0db6cb44b731ec06ed271d01b290c897caf423af17ba90a2f4eaca5e2180b":
        raise ValueError("E_ONE_READY_TOPOLOGY")
    command_ids = set(json.loads(topology.read_bytes())["candidate_command_ids"]) | {
        "VALIDATE_CURRENT_DECLARATION", "VALIDATE_CURRENT_DESCENDANT_MIGRATION",
        "CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT", "VERIFY_V636_P07_T01", "VERIFY_V636_P07_T02",
        "VERIFY_V636_P07_T03", producer}
    for command_id in sorted(command_ids):
        command_io = next(r for r in io if r["command_id"] == command_id)
        owner = "V636-P07-T03" if command_id == "VERIFY_V636_P07_T03" else "V636-P07-T02" if command_id == "VERIFY_V636_P07_T02" else "V636-P07-T01"
        for stream in ("stdout", "stderr"):
            path = EVIDENCE + "/command-logs/" + command_id + "." + stream
            output(path, owner, [owner, "V636-P09-T01"])
            next(t for t in tasks if t["task_id"] == "V636-P09-T01")["inputs"].append(path)
            command_io["outputs"].append(path)
            if command_id in {c for phase in PHASES.values() for c in phase}:
                next(r for r in io if r["command_id"] == producer)["inputs"].append(path)
    assembly = next(t for t in tasks if t["task_id"] == "V636-P09-T01")
    assembly_io = next(r for r in io if r["command_id"] == "VERIFY_V636_P09_T01")
    assembly_io["inputs"] = sorted(
        (set(assembly_io["inputs"]) | set(assembly["inputs"]))
        - {EVIDENCE + "/bootstrap/authoring-repository-receipt.json"}
    )
    for row in doc("registries/proof-coverage-matrix.v1.json")["entries"]:
        if row["command_id"] in {"VERIFY_V636_MIG0_T06", "ISSUE_V636_P00_T05"}:
            row["command_id"] = "VALIDATE_CURRENT_DESCENDANT_MIGRATION" if row["command_id"] == "VERIFY_V636_MIG0_T06" else "VALIDATE_CURRENT_DECLARATION"
    docs[CONTRACT] = {"schema_version": "part-b-one-ready/v1", "scope": "PB-00..PB-24/W00..W12",
        "production_authority": "NONE", "adopted_source": {"commit": "6d0d1c96bc8b7bddc9651d5bcd5a90b511ba8867", "tree": "c73cca5eee550a10bd70cbbecf1819cb08bccc21", "qualification": "NOT_INFERRED"},
        "approved_files": approved, "phases": PHASES, "security_surface_contract": SECURITY_CONTRACT,
        "historical_migration": "pack/docs/receipts/migration-receipt.v1.json",
        "historical_migration_sha256": "6e7f44ad27dc62144ba6039db906f874e9da4b5fb5f85fac1367c26ced7916dc",
        "historical_checks": ["authoring-tests/test_successor_migration_receipt.py", "authoring-tests/test_declaration_gate.py"],
        "key_storage": "WINDOWS_CREDENTIAL_MANAGER", "entry": "WINDOWS_SHORTCUT_PLUS_EXTENSION",
        "scoped_review": {"config": "review-config/v3", "authorization": "review-launch-authorization/v2",
            "binding": "SEALED_PROMPT_TEMPLATE_AND_CANONICAL_SCOPE_INPUTS_VIA_PROMPT_SHA256",
            "run_roots": "FRESH_UUID_V4", "leaf_evidence": "HOST_OWNED_EXCLUSIVE_RECORDS",
            "p10_setup_override": {"applies_to": "INTERACTIVE_V3_HOST_ENTRYPOINTS_ONLY",
                "replaces": "FIXED_V2_OPERATION_ARGV_AND_OUTPUT_LOCATORS_IN_05_REVIEWER_INDEPENDENCE",
                "preserves": ["SEALED_PREPARATION_AND_MECHANICAL_COMMAND_IDS", "DISTINCT_ROLES_AND_RUNS",
                    "FRESH_HUMAN_SESSIONS", "HOST_SIGNING_CUSTODY", "READ_ONLY_INPUTS", "NETWORK_DENY",
                    "CURRENT_QUALIFICATION", "EXPIRY_AND_REVOCATION"]},
            "host_entrypoints": {"launch": "tools/issue_review_launch_authorization.py",
                "prepare_execute": "tools/prepare_review_workspace.py", "finalize": "tools/finalize_review.py",
                "candidate_aggregate": "tools/aggregate_reviews.py",
                "config_selection": "EXACT_MATERIALIZED_V3_TEMPLATE",
                "scope_selection": "EXPLICIT_LOCAL_JSON_WITH_COMPLETE_PATH_HASH_MAPPING",
                "output_selection": "ONLY_TEMPLATE_PREFIX_PLUS_CANONICAL_UUID4",
                "legacy_task_commands": "PRESERVED_V2_GENERAL_REVIEW_ONLY"},
            "resolved_outputs": {"workspace": REVIEW_HOST + "/workspaces/review-{role}/{review_run_id}",
                "result": REVIEW_HOST + "/results/review-{role}/{review_run_id}",
                "authorization": REVIEW_HOST + "/authorizations/{review_run_id}.json",
                "scope_inputs": RUNTIME + "/.local/part-b/review-inputs/{review_run_id}",
                "host_execution": "CONFIGURED_AUTHORITY_PUBLIC_KEY_PARENT/executions/{review_run_id}"},
            "python_runtime_projection": {"config_field": "python_runtime", "mount_mode": "READ_ONLY", "role": "QUALIFIED_INTERPRETER_DEPENDENCY_NOT_EXTRA_REVIEW_DATA", "verification": "COMPLETE_SOURCE_TREE_HASH_AND_NO_UNVALIDATED_BYTECODE", "prepared_interpreter": "EXACT_DECLARED_ROOT/bin/python3.12", "host_os_libraries": "STILL_PLATFORM_DEPENDENCIES"},
            "lifetime_amendment": {"new_v3_launch_seconds": 28800, "accepted_signed_descendant_seconds": [14400, 28800], "legacy_v1_seconds": 14400, "aggregate_delay_seconds": 3600, "overrides": "05-reviewer-independence.md fixed four-hour rule for new scoped launches only", "existing_authorizations_extended": False},
            "reuse": "SAME_OPERATION_ONLY_WITH_BYTE_RECHECK", "authority": "NONE"}}
    return {**{name: encode(value) for name, value in docs.items()}, SECURITY_CONTRACT: SECURITY_TEXT.encode()}


def materialize(root, original, expected):
    for name, data in expected.items():
        path = root / name
        if path.resolve() != path or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1 or path.read_bytes() not in (original.get(name), data))):
            raise ValueError("E_ONE_READY_DRIFT:" + name)
        if not path.exists() and name in original:
            raise ValueError("E_ONE_READY_DRIFT:" + name)
    for name, data in expected.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            temporary = path.with_suffix(path.suffix + ".one-ready-tmp")
            with temporary.open("xb") as stream:
                stream.write(data)
            temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--previous-report", type=Path)
    parser.add_argument("--previous-report-sha256")
    parser.add_argument("--freeze-source-binding", action="store_true")
    args = parser.parse_args()
    original = predecessor(ROOT)
    expected = build(original)
    if args.previous_report:
        raw = args.previous_report.read_bytes()
        if args.previous_report.resolve() != args.previous_report or hashlib.sha256(raw).hexdigest() != args.previous_report_sha256:
            raise ValueError("E_ONE_READY_PREVIOUS_REPORT")
        previous = json.loads(raw)
        if previous["kind"] != "DECLARED_INPUT_AMENDMENT_NOT_QUALIFICATION" or previous["predecessor"] != BASE:
            raise ValueError("E_ONE_READY_PREVIOUS_REPORT")
        for name, digest in previous["files"].items():
            if name not in expected or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise ValueError("E_ONE_READY_DRIFT:" + name)
            original[name] = (ROOT / name).read_bytes()
    elif args.previous_report_sha256:
        raise ValueError("E_ONE_READY_PREVIOUS_REPORT")
    if args.freeze_source_binding:
        delivery = json.loads(expected["pack/docs/registries/delivery-map.v1.json"])
        rows = []
        for entry in sorted(delivery["authoring_source_exports"], key=lambda r: r["source"].encode()):
            name = entry["source"]
            path = ROOT / name
            if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
                raise ValueError("E_ONE_READY_SOURCE")
            data = path.read_bytes()
            rows.append(f"{name}\0{len(data)}\0{hashlib.sha256(data).hexdigest()}\n".encode())
        name = "pack/docs/configs/full-verifier-controller.v2.json"
        cfg = json.loads(expected[name])
        cfg["external_authoring_source_sha256"] = hashlib.sha256(b"".join(rows)).hexdigest()
        expected[name] = encode(cfg)
    materialize(ROOT, original, expected)
    with args.report.open("x") as stream:
        json.dump({"kind": "DECLARED_INPUT_AMENDMENT_NOT_QUALIFICATION", "predecessor": BASE,
                   "files": {name: hashlib.sha256(data).hexdigest() for name, data in expected.items()}, "authority": "NONE"}, stream, indent=2)
        stream.write("\n")
    print("ONE_READY_INPUTS_DECLARED; AUTHORITY=NONE")


if __name__ == "__main__":
    main()
