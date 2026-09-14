"""Generate the source-owned descendant qualification contract.

This is a post-baseline source amendment.  It deliberately leaves every v1
configuration and the historical zero-parent tooling in place while replacing
only the current v6.3.6 execution path with an explicit descendant branch.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

PREFIX = "/home/thenam176/betting-helper"
AUTHORING = f"{PREFIX}/authoring-controller-config-worktree"
RUNTIME = f"{PREFIX}/discovery-runtime-v6.3.6"
EVIDENCE = f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6-controller"
REVIEW_PACK = f"{PREFIX}/review-packs/hybrid-discovery-v6.3.6"
AUDITED_ANCESTOR = "7cd7ab14652458608386d940bdc7764910044f6a"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
LEGACY_COMMAND_SHA256 = {
    "TEST_V636_P03_T07": "f4a7c4899e4b3c511995cecc381968a949b5af6486c98e7b9be0b0a33f4e634d",
    "TEST_V636_P04_T04": "a43b21cd20aca4755df2c85dbf58865672d51cc983bfda2d6de627dcb82810e0",
    "VERIFY_V636_P07_T01": "c2dff9a267036aff71b3c033a158f37845783187f8c73eef74dc683deb740f0b",
    "VERIFY_V636_P07_T02": "c436f40181c062d3c1d446e68918d8df6c0335e153a013f151307510818df60f",
    "VERIFY_V636_P07_T03": "b8a24c1647a809a6f84eef76eab75ee22b017b00222d3e5c9fdfd4892e15d387",
    "VERIFY_V636_P08_T01": "84a932179bab782d3fe5745964a60b6c293ca16e10825310dd8061611769e658",
    "VERIFY_V636_P08_T02": "baf75f8cd69de481845565961382972d5e7987149a0d6ad8bc632f345fff5ad6",
    "VERIFY_V636_P08_T03": "cf66da8c6363d3b4a6c529823368f2dfe3d5a9d91f7cf6b3209d729f9d22c7a7",
    "VERIFY_V636_P09_T01": "c50d2ca488c76d8c1102c1a4e8e06f69db9279457a841ea15495ff650f06e266",
    "VERIFY_V636_P09_T03": "87d6868e6b57fc765a37f3ec80a3557840ae296475191f5f2d8f4fa571f05fbf",
    "VERIFY_V636_P10_T01": "88425c70cb39717694b8c2f185987b5794b48f56b092edd05abf06b79879ecbb",
    "VERIFY_V636_P10_T02": "4826c9a1b9fd14ad7f83032051089bd67d04fc3dd093346cf2f145d6413f0982",
    "VERIFY_V636_P10_T04": "dc371c0f2953872c54e2d016902cfcf3775b964639edb5df00425b9ff5b6a71d",
    "ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT": "03c5c5ee0bcb26636c3d4b8a0c3fbe1815c35de01354aeac1d224a18f94fb293",
    "V636_MIG0_T08_BINDINGS": "38c02bcc869b4e5ca0d71d4219fdf7390a277f057f33964ae6d7286d3ca0b572",
    "REVIEW_AGGREGATE": "11f9e714e76673d7ed8993d78e561f891a24cf8c9ef8cf8d5a31ac8b0262eb62",
}
TRANSPORT_PREDECESSOR_SHA256 = {
    "ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT": "ece22c024f4ae6a3679f35a2022bd866a1d445a3184bcd43df7ddd636d2de4c8",
    "VERIFY_V636_P07_T02": "06d076ab3b2af99ff9e5a8b3aca7e1a163098776e47eb8b1b1bbd8938ee85b76",
    "VERIFY_V636_P09_T01": "ec1b06127319ddc41fb2b19c20dc77ee8e3d14d125e7b8d767cb94b7e8a3eedc",
    "VERIFY_V636_P09_T02": "3a74ab4b5d2be55d470853cb987198a3339649041bf64a0b62f7b4ab253c34f1",
    "VERIFY_V636_P09_T03": "2c4886e9eabd656c704418979bfd6abe5da66386a0d7ae456621543dcd58ac4e",
    "VERIFY_V636_P09_T04": "8789fdfd71dd3fe5d698ad5dda4a77ec80c9bda728cdc79a6ececcdabac4fb60",
    "A_CHECK_SOURCE": "6f56d3a7cc893660d2d58d8046af0127e0e0b30489c2b6a1c4a0f66ed399de1e",
    "A_CHECK_EVIDENCE": "76dc973cb7d8f9a809f5662806029827816334d700dffdbf6e77ec0833df7b79",
    "A_CHECK_DESCENDANT": "5f6865f69e8825ed20502496bd5b472e932d826d1e683831ccf5cbcb52be82e5",
}
REFERENCE_SYMBOL_TRANSITIONS = {
    "V636-P01-T04": (
        "50653cfd650fe095d33e85fd619733e61c8457c43f333466f277ee1b379dd93f",
        "a218772210de2c983f4e364a4caec242eda2b97b7d4c644ecc026f1125690835",
        "runtime/tests/materialization/test_harness_entrypoints.py::test_all_registered_harness_entrypoints_compile_and_emit_contract_not_implemented",
        ["runtime/tests/materialization/test_harness_entrypoints.py::test_registered_harness_entrypoints_compile_and_unowned_entries_stay_blocked"],
    ),
    "V636-P03-T05": (
        "d2726fd7eab01886120bd8163755bae90863d48d6ee4f5dd13845617dac6c7a3",
        "abe88dfe8b11a0a0908ff6b43a7db5b0132a065b5d181b79b022ff199b9b16c7",
        "runtime/tests/durability/test_sqlite_process_crash.py::test_sql_transaction_is_all_or_none_after_sigkill",
        ["runtime/tests/durability/test_sqlite_process_crash.py::test_sql06_checkpoint_is_inside_real_sqlite_commit_io",
         "runtime/tests/durability/test_sqlite_process_crash.py::test_sql_transaction_emits_exact_full_terminal_evidence"],
    ),
    "V636-P03-T07": (
        "1a307ba4efb98e8f9e512dd1e8bc024b666e122c2486ede41d0340765605b6ba",
        "5fbb9c695e2179f809f4d553542363e697ca299084667163c1f67ef177ec53b4",
        "runtime/tests/durability/test_owner_mutation_review.py::test_full_qualification_rejects_forged_or_incomplete_evidence",
        ["runtime/tests/durability/test_owner_mutation_review.py::test_coherent_review_substitutions_reject"],
    ),
}


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"E_DESCENDANT_SOURCE:{path}")
    return value


def _dump(path: Path, value: object) -> bool:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if path.is_file() and path.read_bytes() == encoded:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return True


def _write_text(path: Path, value: str) -> bool:
    encoded = value.encode()
    if path.read_bytes() == encoded:
        return False
    path.write_bytes(encoded)
    return True


def _task_output(path: str, owner: str, consumers: list[str]) -> dict[str, object]:
    return {
        "path": path,
        "classification": "TASK_OUTPUT",
        "creation_owner": owner,
        "modifying_tasks": [],
        "materialization_required": True,
        "source": None,
        "qualification_owner": owner,
        "consumers": consumers,
    }


def _evidence_output(path: str, owner: str, consumers: list[str]) -> dict[str, object]:
    return {
        "path": path,
        "classification": "EVIDENCE_OUTPUT",
        "creation_owner": owner,
        "modifying_tasks": [],
        "materialization_required": False,
        "source": None,
        "qualification_owner": None,
        "consumers": consumers,
    }


def _operation(command_id: str, argv: list[str], purpose: str) -> dict[str, object]:
    return {
        "command_id": command_id,
        "cwd": RUNTIME,
        "argv": argv,
        "purpose": purpose,
        "expected_exit": 0,
        "available_at": "MATERIALIZED",
        "network": "DENY",
        "authenticated_operator_access": "DENY",
        "provider_access": "DENY",
        "kind": "operation",
    }


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _require_known_command(
    commands: dict[str, dict[str, object]],
    command_id: str,
    current_shape: dict[str, object],
    *,
    allow_missing: bool = False,
) -> None:
    command = commands.get(command_id)
    if command is None and allow_missing:
        return
    if not isinstance(command, dict) or (
        _canonical_sha256(command) not in {
            _canonical_sha256(current_shape),
            LEGACY_COMMAND_SHA256.get(command_id), TRANSPORT_PREDECESSOR_SHA256.get(command_id)
        }
    ):
        raise ValueError(f"E_DESCENDANT_UNKNOWN_COMMAND:{command_id}")


def _neutral_identity_properties() -> dict[str, object]:
    return {
        "repository_qualification_receipt_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "repository_identity_kind": {"const": "DESCENDANT"},
        "repository_commit_oid": {"type": "string", "pattern": "^[0-9a-f]{40,64}$"},
        "repository_tree_oid": {"type": "string", "pattern": "^[0-9a-f]{40,64}$"},
        "repository_file_tree_root_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
    }


def _replace_repo0_verdict(value: object) -> None:
    if not isinstance(value, dict):
        return
    required = value.get("required")
    if isinstance(required, list):
        value["required"] = [
            "DESCENDANT_REPOSITORY_VALID" if item == "REPO0_BASELINE_VALID" else item
            for item in required
        ]
    properties = value.get("properties")
    if isinstance(properties, dict) and "REPO0_BASELINE_VALID" in properties:
        properties["DESCENDANT_REPOSITORY_VALID"] = properties.pop("REPO0_BASELINE_VALID")
    for child in value.values():
        if isinstance(child, dict):
            _replace_repo0_verdict(child)
        elif isinstance(child, list):
            for item in child:
                _replace_repo0_verdict(item)


def _add_identity_branch(
    schema: dict[str, object], logical_name: str, current_version: str
) -> None:
    definitions = schema["$defs"]
    target = definitions[logical_name]
    if isinstance(target, dict) and "oneOf" in target:
        expected = [
            {"$ref": f"#/$defs/Legacy{logical_name}"},
            {"$ref": f"#/$defs/Descendant{logical_name}"},
        ]
        if target["oneOf"] != expected:
            raise ValueError(f"E_DESCENDANT_SCHEMA_BRANCH:{logical_name}")
        return

    legacy = copy.deepcopy(target)
    current = copy.deepcopy(target)
    required = current.get("required")
    properties = current.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        raise TypeError(f"E_DESCENDANT_SCHEMA_SHAPE:{logical_name}")
    old_fields = {
        "repo0_receipt_sha256",
        "repo0_commit_oid",
        "repo0_tree_oid",
        "repo0_file_tree_root_sha256",
        "baseline_file_root_sha256",
        "baseline_commit",
        "baseline_tree",
    }
    current["required"] = [item for item in required if item not in old_fields]
    for field in old_fields:
        properties.pop(field, None)
    for field, definition in _neutral_identity_properties().items():
        properties[field] = definition
        if field not in current["required"]:
            current["required"].append(field)
    properties["schema_version"] = {"const": current_version}
    current.pop("allOf", None)
    _replace_repo0_verdict(current)

    definitions[f"Legacy{logical_name}"] = legacy
    definitions[f"Descendant{logical_name}"] = current
    definitions[logical_name] = {
        "oneOf": [
            {"$ref": f"#/$defs/Legacy{logical_name}"},
            {"$ref": f"#/$defs/Descendant{logical_name}"},
        ]
    }


def _descendant_receipt_schema() -> dict[str, object]:
    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    oid = {"type": "string", "pattern": "^[0-9a-f]{40,64}$"}
    required = [
        "schema_version",
        "repository_identity_kind",
        "production_authority",
        "audited_ancestor_commit",
        "repository_commit",
        "repository_tree",
        "repository_file_root_sha256",
        "candidate_qualification_sha256",
        "candidate_command_evidence_sha256",
        "proof_coverage_sha256",
        "controller_config_sha256",
        "command_result_root",
        "candidate_inventory_sha256",
        "toolchain_versions",
        "lockfile_hashes",
        "vendor_root_sha256",
        "normative_source_map_sha256",
        "normative_source_set_root",
        "normative_source_set_count",
        "full_repair_aggregate_sha256",
        "full_repair_evidence_root_sha256",
        "environment_qualification_aggregate_sha256",
        "environment_qualification_evidence_root_sha256",
    ]
    properties: dict[str, object] = {field: copy.deepcopy(digest) for field in required}
    properties.update(
        {
            "schema_version": {"const": "descendant-repository-qualification-receipt/v1"},
            "repository_identity_kind": {"const": "DESCENDANT"},
            "production_authority": {"const": "NONE"},
            "audited_ancestor_commit": copy.deepcopy(oid),
            "repository_commit": copy.deepcopy(oid),
            "repository_tree": copy.deepcopy(oid),
            "toolchain_versions": {"type": "object", "minProperties": 1},
            "lockfile_hashes": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": copy.deepcopy(digest),
            },
            "normative_source_set_count": {"type": "integer", "minimum": 1},
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:hybrid-discovery:v6.3.6:descendant-repository-qualification-receipt",
        "$defs": {
            "DescendantRepositoryQualificationReceipt": {
                "type": "object",
                "required": required,
                "properties": properties,
                "additionalProperties": False,
            }
        },
    }


def _controller_schema() -> dict[str, object]:
    path = {"type": "string", "pattern": "^/[^\\u0000]+$"}
    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    base_required = [
        "schema_version",
        "production_authority",
        "accepted_authoring_ancestor",
        "current_checkout_root",
        "governed_source_pack",
        "evidence_root",
        "external_authoring_tests",
        "external_authoring_source_sha256",
        "external_authoring_command",
        "uv_cache",
        "pnpm_store",
        "chrome",
        "receipts",
    ]
    base_properties: dict[str, object] = {
        "production_authority": {"const": "NONE"},
        "accepted_authoring_ancestor": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
        "current_checkout_root": copy.deepcopy(path),
        "governed_source_pack": copy.deepcopy(path),
        "evidence_root": copy.deepcopy(path),
        "external_authoring_tests": copy.deepcopy(path),
        "external_authoring_source_sha256": copy.deepcopy(digest),
        "external_authoring_command": {
            "type": "object",
            "required": ["cwd", "argv"],
            "properties": {
                "cwd": copy.deepcopy(path),
                "argv": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "uv_cache": copy.deepcopy(path),
        "pnpm_store": copy.deepcopy(path),
        "chrome": {
            "type": "object",
            "required": ["path", "sha256"],
            "properties": {"path": copy.deepcopy(path), "sha256": copy.deepcopy(digest)},
            "additionalProperties": False,
        },
    }
    legacy_receipts = [
        "authoring_repository",
        "candidate_command_evidence",
        "proof_coverage_evidence",
        "candidate_issuance_evidence",
        "candidate_qualification",
    ]
    legacy = {
        "type": "object",
        "required": base_required,
        "properties": {
            **base_properties,
            "schema_version": {"const": "full-verifier-controller/v1"},
            "receipts": {
                "type": "object",
                "required": legacy_receipts,
                "properties": {field: copy.deepcopy(path) for field in legacy_receipts},
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }
    evidence_fields = [
        "full_repair_aggregate",
        "full_repair_inventory",
        "environment_qualification_aggregate",
        "environment_qualification_inventory",
        "p03_proof",
        "p04_proof",
    ]
    current = copy.deepcopy(legacy)
    current["required"] += ["audited_runtime_ancestor", "qualification_evidence"]
    current["properties"]["schema_version"] = {"const": "full-verifier-controller/v2"}
    current["properties"]["audited_runtime_ancestor"] = {
        "const": AUDITED_ANCESTOR
    }
    current["properties"]["qualification_evidence"] = {
        "type": "object",
        "required": evidence_fields,
        "properties": {field: copy.deepcopy(path) for field in evidence_fields},
        "additionalProperties": False,
    }
    current["properties"]["receipts"]["required"].append("descendant_repository")
    current["properties"]["receipts"]["properties"]["descendant_repository"] = copy.deepcopy(path)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:hybrid-discovery:v6.3.6:full-verifier-controller",
        "$defs": {
            "LegacyFullVerifierController": legacy,
            "DescendantFullVerifierController": current,
            "FullVerifierController": {
                "oneOf": [
                    {"$ref": "#/$defs/LegacyFullVerifierController"},
                    {"$ref": "#/$defs/DescendantFullVerifierController"},
                ]
            },
        },
    }


def _authoring_source_hash(delivery: dict[str, object]) -> str:
    rows: list[bytes] = []
    exports = delivery["authoring_source_exports"]
    for entry in sorted(exports, key=lambda item: str(item["source"]).encode()):
        source = str(entry["source"])
        path = SOURCE_ROOT / source
        if not path.is_file():
            raise ValueError(f"E_DESCENDANT_AUTHORING_SOURCE:{source}")
        payload = path.read_bytes()
        rows.append(f"{source}\0{len(payload)}\0{hashlib.sha256(payload).hexdigest()}\n".encode())
    return hashlib.sha256(b"".join(rows)).hexdigest()


def _update_task(task: dict[str, object], **changes: object) -> None:
    task.update(changes)


def apply_descendant_qualification_followup(pack: Path) -> dict[str, object]:
    docs = pack / "docs"
    config_v1_path = docs / "configs/full-verifier-controller.v1.json"
    config_v1 = _read(config_v1_path)
    if config_v1.get("schema_version") != "full-verifier-controller/v1":
        raise ValueError("E_DESCENDANT_EXPECTED_CONTROLLER_V1")

    new_authoring_receipt = f"{EVIDENCE}/bootstrap/authoring-repository-receipt-descendant-source-v2.json"
    descendant_receipt = f"{EVIDENCE}/DESCENDANT_REPOSITORY_QUALIFICATION.json"
    qualification = {
        "full_repair_aggregate": f"{EVIDENCE}/full-repair/aggregate.json",
        "full_repair_inventory": f"{EVIDENCE}/full-repair/inventory.json",
        "environment_qualification_aggregate": f"{EVIDENCE}/environment/environment-aggregate.json",
        "environment_qualification_inventory": f"{EVIDENCE}/environment/inventory.json",
        "p03_proof": f"{EVIDENCE}/V636-P03-T07.json",
        "p04_proof": f"{EVIDENCE}/V636-P04-T04.json",
    }

    delivery_path = docs / "registries/delivery-map.v1.json"
    delivery = _read(delivery_path)
    exports = {row["source"]: row for row in delivery["authoring_source_exports"]}
    for source in (
        "authoring-tools/apply_descendant_qualification_followup.py",
        "authoring-tests/test_descendant_qualification_followup.py",
    ):
        exports[source] = {
            "source": source,
            "destination": f"pack/authoring-source/{source}",
            "owner": "V636-P09-T01",
        }
    for name in (
        "create_authoring_workspace.py", "initialize_authoring_repository.py",
        "verify_extracted_plan.py", "extract_plan.py", "test_bootstrap_tools.py",
    ):
        source = f"plan-input/bootstrap/{name}"
        exports[source] = {
            "source": source,
            "destination": f"pack/authoring-source/bootstrap/{name}",
            "owner": "V636-P09-T01",
        }
    delivery["authoring_source_exports"] = [exports[key] for key in sorted(exports, key=str.encode)]

    config_v2 = copy.deepcopy(config_v1)
    config_v2["schema_version"] = "full-verifier-controller/v2"
    config_v2["audited_runtime_ancestor"] = AUDITED_ANCESTOR
    config_v2["qualification_evidence"] = qualification
    config_v2["receipts"] = copy.deepcopy(config_v1["receipts"])
    config_v2["receipts"]["authoring_repository"] = new_authoring_receipt
    config_v2["receipts"]["descendant_repository"] = descendant_receipt
    config_v2["external_authoring_source_sha256"] = _authoring_source_hash(delivery)

    packed_descendant_receipt = "pack/docs/receipts/descendant-repository-qualification-receipt.json"
    packed_descendant_receipt_absolute = f"{REVIEW_PACK}/docs/receipts/descendant-repository-qualification-receipt.json"
    retained_manifest = "pack/evidence/retained-artifact-manifest.json"
    retained_root = "pack/evidence/retained"
    transport = [
        "--config", f"{REVIEW_PACK}/docs/configs/full-verifier-controller.v2.json",
        "--recorded-config", f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json",
        "--retained-manifest", f"{REVIEW_PACK}/evidence/retained-artifact-manifest.json",
        "--retained-root", f"{REVIEW_PACK}/evidence/retained",
    ]
    review_identity = {"kind": "DESCENDANT", "receipt": packed_descendant_receipt_absolute}
    review_a = _read(docs / "configs/review-a.v1.json")
    review_a["schema_version"] = "review-config/v2"
    review_a["mechanical_command_ids"] = [
        "A_CHECK_DESCENDANT" if item == "A_CHECK_BASELINE" else item
        for item in review_a["mechanical_command_ids"]
    ]
    review_a["repository_identity"] = review_identity
    # Preserve captured executable/argv identities without exposing host shim configuration.
    review_a["producer_environment"] = {
        "schema_version": "review-producer-environment/v1",
        "mode": "VERIFIED_READ_ONLY_PROJECTION",
        "python_environment": f"{RUNTIME}/.venv",
        "python_executable": f"{RUNTIME}/.venv/bin/python3",
        "python_executable_sha256": "1643dacd9feaedc58f3cc581e4d22577dfe25c09b10282936186ccf0f2e61118",
        "node_lookup": "/home/thenam176/.local/share/mise/shims/node",
        "node_executable": "/home/thenam176/.local/share/mise/installs/node/22.23.0/bin/node",
        "node_executable_sha256": "b587d8a062552ab52ecae2a7b0bcd079351d1dc61cf2555fd5994f558274ae58",
        "path_translation_executable": "/init",
        "wsl_distro": "Ubuntu",
        "runtime_unc": "\\\\wsl.localhost\\Ubuntu" + RUNTIME.replace("/", "\\"),
        "path_translation_sha256": "85abd6d52d1a1e602aa6b545c9ac125c9021a3bb8383d337f1d009766d7ea4d2",
        "native_dependency_root": "/mnt/c/Users/thenam/Documents/BettingHelper-Repair-Chrome/native-dependency-closure-b82739f5-1369-4d01-a701-b39a1a8e228b",
        "live_files": [
            "/home/thenam176/.cache/ms-playwright/chromium-1232/chrome-linux64/chrome",
            "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
            *[
                "/mnt/c/Users/thenam/.cache/codex-runtimes/codex-primary-runtime/dependencies/" + name
                for name in ("python/python.exe", "python/python312.dll", "python/DLLs/_sqlite3.pyd", "python/DLLs/sqlite3.dll", "node/bin/node.exe")
            ],
            f"{RUNTIME}/.local/bh-repair/native-wheel-cache/rpds_py-2026.6.3-cp312-cp312-win_amd64.whl",
            *[
                "/mnt/c/Users/thenam/AppData/Local/pip/cache/http-v2/" + name
                for name in (
                    "1/1/2/7/e/1127e3d2d646b8b978b6f86221cfed3abb713e990a117406d3ce6b47.body",
                    "c/9/2/3/4/c92343c66b0dc7638b486b828ba26c07e51fe308e9da38034706d11f.body",
                    "b/1/4/e/c/b14ec1286f8ec83b268f9c52cdccd1001d22496d6e01ba5b4fd8aeb4.body",
                    "9/8/0/6/4/9806464430c23d93c717be0a494a22ece76de403154ebf770ebd0e44.body",
                )
            ],
            "/home/thenam176/.cache/trading-agent/runtime-release-wheelhouse/432cc5e62b703e45f49ad16a9a42a795ce0090ac004a0a2c58af58b5f29e5f5c/typing_extensions-4.16.0-py3-none-any.whl",
            *[
                "/home/thenam176/.cache/uv/archive-v0/Xo7YHE9oUI4WKOJwPLa0q/" + name
                for name in ("rfc8785/__init__.py", "rfc8785/_impl.py", "rfc8785/py.typed", "rfc8785-0.1.4.dist-info/LICENSE", "rfc8785-0.1.4.dist-info/WHEEL", "rfc8785-0.1.4.dist-info/METADATA", "rfc8785-0.1.4.dist-info/RECORD")
            ],
        ],
    }
    review_b = _read(docs / "configs/review-b.v1.json")
    review_b["schema_version"] = "review-config/v2"
    review_b["repository_identity"] = review_identity
    review_aggregation = _read(docs / "configs/review-aggregation.v1.json")
    review_aggregation["schema_version"] = "review-aggregation-config/v2"
    review_aggregation["repository_identity"] = review_identity

    manifest_path = docs / "tasks/task-manifest.v6.3.6.json"
    manifest = _read(manifest_path)
    tasks = {row["task_id"]: row for row in manifest["tasks"]}
    for task_id, (old_hash, new_hash, old_symbol, successors) in REFERENCE_SYMBOL_TRANSITIONS.items():
        symbols = tasks[task_id]["exact_symbols"]
        digest = _canonical_sha256(symbols)
        if digest not in {old_hash, new_hash}:
            raise ValueError(f"E_DESCENDANT_UNKNOWN_SYMBOLS:{task_id}")
        if digest == old_hash:
            tasks[task_id]["exact_symbols"] = sorted((set(symbols) - {old_symbol}) | set(successors))
    mig = tasks["V636-MIG0-T08"]
    new_source_outputs = {
        "authoring-tools/apply_descendant_qualification_followup.py",
        "authoring-tests/test_descendant_qualification_followup.py",
        "pack/docs/configs/full-verifier-controller.v2.json",
        "pack/docs/configs/review-a.v2.json",
        "pack/docs/configs/review-b.v2.json",
        "pack/docs/configs/review-aggregation.v2.json",
        "pack/docs/schemas/descendant-repository-qualification-receipt.schema.json",
        "pack/docs/schemas/full-verifier-controller.schema.json",
        new_authoring_receipt,
    }
    amended_source_outputs = {
        "authoring-tools/build_task_command_registry.py",
        "authoring-tests/test_command_registry_generation.py",
        "authoring-tests/test_declaration_gate.py",
        "authoring-tests/test_task_manifest_semantics.py",
        "pack/docs/contracts/07-command-and-config-lifecycle.md",
        "pack/docs/registries/artifact-ownership.v1.json",
        "pack/docs/registries/command-io.v1.json",
        "pack/docs/registries/delivery-map.v1.json",
        "pack/docs/registries/normative-source-map.v1.json",
        "pack/docs/registries/proof-coverage-matrix.v1.json",
        "pack/docs/registries/review-command-registry.v1.json",
        "pack/docs/registries/schema-reference-registry.v1.json",
        "pack/docs/registries/task-command-registry.v1.json",
        "pack/docs/schemas/external-seal-attestation.schema.json",
        "pack/docs/schemas/review-execution-receipt.schema.json",
        "pack/docs/schemas/review-launch-authorization.schema.json",
        "pack/docs/schemas/review-result.schema.json",
        "pack/docs/schemas/self-review-record.schema.json",
        "pack/docs/tasks/task-manifest.v6.3.6.json",
    }
    early_source_outputs = {
        "pack/docs/configs/full-verifier-controller.v2.json",
        "pack/docs/schemas/full-verifier-controller.schema.json",
    }
    source_outputs = (new_source_outputs | amended_source_outputs) - early_source_outputs
    for field in ("outputs", "exact_files"):
        mig[field] = sorted(
            (set(mig[field]) | source_outputs | {
                "runtime/review-config/review-a.v2.json",
                "runtime/review-config/review-b.v2.json",
                "runtime/review-config/review-aggregation.v2.json",
            })
            - early_source_outputs
        )
    p00_schema = tasks["V636-P00-T03"]
    for field in ("outputs", "exact_files"):
        p00_schema[field] = sorted(set(p00_schema[field]) | early_source_outputs)
    p00_schema["exact_schema_refs"] = sorted(
        set(p00_schema["exact_schema_refs"])
        | {"pack/docs/schemas/full-verifier-controller.schema.json#/$defs/FullVerifierController"}
    )

    _update_task(
        tasks["V636-P03-T07"],
        title="Execute and retain the complete durability qualification campaign",
        objective="Execute all 46 durability controls and their registered mutations exactly once, retain the closed artifact inventory, and issue the P03 proof.",
        outputs=sorted(
            set(tasks["V636-P03-T07"]["outputs"])
            | {
                qualification["full_repair_aggregate"],
                qualification["full_repair_inventory"],
                qualification["p03_proof"],
                qualification["environment_qualification_aggregate"],
                qualification["environment_qualification_inventory"],
                "runtime/tools/run_full_repair_qualification.py",
                "runtime/tools/run_environment_qualification.py",
                "runtime/tools/retained_artifact_io.py",
                "runtime/tests/durability/test_owner_mutation_review.py",
            }
        ),
        exact_files=sorted(
            set(tasks["V636-P03-T07"]["exact_files"])
            | {
                "runtime/tools/run_full_repair_qualification.py",
                "runtime/tools/run_environment_qualification.py",
                "runtime/tools/retained_artifact_io.py",
                "runtime/tests/durability/test_owner_mutation_review.py",
            }
        ),
        exact_symbols=sorted(
            set(tasks["V636-P03-T07"]["exact_symbols"])
            | {
                "runtime/tools/run_full_repair_qualification.py::main",
                "runtime/tests/durability/test_owner_mutation_review.py::test_coherent_review_substitutions_reject",
            }
        ),
        tests_first=["runtime/tests/durability/test_owner_mutation_review.py"],
        evidence_artifacts=[qualification["p03_proof"]],
        exact_command_ids=sorted(
            set(tasks["V636-P03-T07"]["exact_command_ids"])
            | {"CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT"}
        ),
    )
    _update_task(
        tasks["V636-P04-T04"],
        title="Verify clock qualification from the immutable P03 aggregate",
        objective="Verify all 65 clock controls and registered mutations from the exact P03 aggregate without rerunning the campaign, then issue the P04 proof.",
        inputs=[qualification["full_repair_aggregate"], qualification["full_repair_inventory"]],
        outputs=sorted(
            set(tasks["V636-P04-T04"]["outputs"])
            | {
                qualification["p04_proof"],
                "runtime/tools/verify_full_repair_qualification.py",
            }
        ),
        exact_files=sorted(
            set(tasks["V636-P04-T04"]["exact_files"])
            | {
                "runtime/tools/verify_full_repair_qualification.py",
                "runtime/tests/durability/test_owner_mutation_review.py",
            }
        ),
        exact_symbols=sorted(
            set(tasks["V636-P04-T04"]["exact_symbols"])
            | {"runtime/tools/verify_full_repair_qualification.py::main"}
        ),
        tests_first=["runtime/tests/durability/test_owner_mutation_review.py"],
        evidence_artifacts=[qualification["p04_proof"]],
        dependencies=["V636-P03-T07", "V636-P04-T03"],
    )
    p08_updates = {
        "V636-P08-T01": (
            "Preflight descendant repository qualification",
            "Read-only preflight of the current descendant checkout, candidate, config, inventories and audited ancestry.",
            [f"{EVIDENCE}/V636-P08-T01.json"],
            [
                "Audited ancestor, current HEAD/tree, candidate and configured evidence validate read-only",
                "No repository, receipt or tracked file is written",
                "Production authority remains NONE",
            ],
        ),
        "V636-P08-T02": (
            "Issue descendant repository qualification receipt",
            "Exclusively issue the current descendant receipt without creating a repository, baseline or commit.",
            [f"{EVIDENCE}/V636-P08-T02.json", descendant_receipt],
            [
                "Exactly one exclusive descendant receipt is issued from the passing preflight",
                "Repository HEAD, tree and status are unchanged across issuance",
                "Production authority remains NONE",
            ],
        ),
        "V636-P08-T03": (
            "Check descendant repository qualification receipt",
            "Check-only revalidation of the immutable descendant receipt against the current source contract.",
            [f"{EVIDENCE}/V636-P08-T03.json"],
            [
                "Check-only recomputation matches every bound receipt field",
                "Missing, stale, mixed-kind or aliased inputs fail closed",
                "Production authority remains NONE",
            ],
        ),
    }
    for task_id, (title, objective, outputs, acceptance_criteria) in p08_updates.items():
        _update_task(
            tasks[task_id],
            title=title,
            objective=objective,
            inputs=[
                "pack/docs/configs/full-verifier-controller.v2.json",
                *qualification.values(),
                f"{EVIDENCE}/V636-P07-T01.json",
                f"{EVIDENCE}/V636-P07-T02.json",
                f"{EVIDENCE}/V636-P07-T03.json",
                f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json",
            ],
            outputs=outputs,
            exact_files=[
                "runtime/tools/qualify_descendant_repository.py",
                "runtime/tests/release/test_descendant_repository_qualification.py",
            ],
            exact_symbols=["runtime/tools/qualify_descendant_repository.py::main"],
            exact_schema_refs=[
                "pack/docs/schemas/descendant-repository-qualification-receipt.schema.json#/$defs/DescendantRepositoryQualificationReceipt"
            ],
            tests_first=["runtime/tests/release/test_descendant_repository_qualification.py"],
            acceptance_criteria=acceptance_criteria,
            evidence_artifacts=[outputs[0]],
        )
    tasks["V636-P09-T01"]["outputs"] = sorted(
        set(tasks["V636-P09-T01"]["outputs"]) | {packed_descendant_receipt}
    )
    tasks["V636-P09-T01"]["objective"] = (
        "Assemble the governed source, configured evidence closure and the verified descendant "
        "receipt without consulting historical hard-coded roots."
    )
    tasks["V636-P09-T01"]["inputs"] = [
        "pack/docs/configs/full-verifier-controller.v2.json",
        *qualification.values(),
        f"{EVIDENCE}/V636-P07-T01.json",
        f"{EVIDENCE}/V636-P07-T02.json",
        f"{EVIDENCE}/V636-P07-T03.json",
        f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json",
        descendant_receipt,
    ]
    tasks["V636-P09-T03"]["objective"] = (
        "Create Markdown and JSON self-review records binding governed content, the neutral "
        "descendant identity, candidate qualification, task manifest and command-result roots."
    )
    tasks["V636-P09-T03"]["inputs"] = [
        packed_descendant_receipt,
        f"{EVIDENCE}/V636-P07-T01.json",
        f"{EVIDENCE}/V636-P07-T02.json",
        f"{EVIDENCE}/V636-P07-T03.json",
        f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json",
    ]
    tasks["V636-P10-T01"]["exact_command_ids"] = [
        command_id
        for command_id in tasks["V636-P10-T01"]["exact_command_ids"]
        if command_id != "A_CHECK_DESCENDANT"
    ]
    tasks["V636-P10-T01"]["inputs"] = [
        "runtime/review-config/review-a.v2.json",
        packed_descendant_receipt,
    ]
    tasks["V636-P10-T02"]["inputs"] = [
        "runtime/review-config/review-b.v2.json",
        packed_descendant_receipt,
    ]
    tasks["V636-P10-T04"]["inputs"] = [
        "runtime/review-config/review-aggregation.v2.json",
        packed_descendant_receipt,
    ]

    registry_path = docs / "registries/task-command-registry.v1.json"
    registry = _read(registry_path)
    commands = {row["command_id"]: row for row in registry["commands"]}
    vendor_config = f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"
    current_commands: dict[str, dict[str, object]] = {}
    current_commands["TEST_V636_P03_T07"] = _operation(
        "TEST_V636_P03_T07",
        [
            "uv", "run", "--frozen", "--offline", "python",
            "tools/run_full_repair_qualification.py", "--config", vendor_config,
            "--aggregate", qualification["full_repair_aggregate"],
            "--inventory", qualification["full_repair_inventory"],
            "--proof", qualification["p03_proof"],
        ],
        "Execute and retain the exact 111-control and 105-mutation qualification campaign",
    )
    current_commands["TEST_V636_P03_T07"]["kind"] = "verification"
    current_commands["TEST_V636_P04_T04"] = _operation(
        "TEST_V636_P04_T04",
        [
            "uv", "run", "--frozen", "--offline", "python",
            "tools/verify_full_repair_qualification.py", "--config", vendor_config,
            "--aggregate", qualification["full_repair_aggregate"],
            "--inventory", qualification["full_repair_inventory"],
            "--output", qualification["p04_proof"],
        ],
        "Verify the 65 clock records from the exact immutable P03 aggregate",
    )
    current_commands["TEST_V636_P04_T04"]["kind"] = "verification"
    current_commands["VERIFY_V636_P07_T01"] = _operation(
        "VERIFY_V636_P07_T01",
        [
            "uv", "run", "--frozen", "--offline", "python", "tools/run_command_registry.py",
            "--mode", "candidate-qualification", "--registry", "task-command-registry.json",
            "--config", vendor_config, "--output", f"{EVIDENCE}/V636-P07-T01.json",
        ],
        "Run exact verifier for V636-P07-T01",
    )
    current_commands["VERIFY_V636_P07_T02"] = _operation(
        "VERIFY_V636_P07_T02",
        [
            "uv", "run", "--frozen", "--offline", "python", "tools/verify_proof_coverage.py",
            "--matrix", f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/registries/proof-coverage-matrix.v1.json",
            "--evidence-root", EVIDENCE, "--stage", "CANDIDATE", "--config", vendor_config,
            "--output", f"{EVIDENCE}/V636-P07-T02.json",
        ],
        "Run exact verifier for V636-P07-T02",
    )
    current_commands["VERIFY_V636_P07_T03"] = _operation(
        "VERIFY_V636_P07_T03",
        [
            "uv", "run", "--frozen", "--offline", "python",
            "tools/build_candidate_qualification_receipt.py", "--config", vendor_config,
            "--source", RUNTIME, "--command-evidence", f"{EVIDENCE}/V636-P07-T01.json",
            "--output", f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json",
        ],
        "Run exact verifier for V636-P07-T03",
    )
    current_commands["ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT"] = _operation(
        "ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT",
        [
            "python3", "authoring-tools/issue_current_authoring_repository_receipt.py",
            "--root", AUTHORING, "--output", new_authoring_receipt,
            "--accepted-ancestor", "5249e84b57b7bc4d30abc24f41ead64174ab7549",
        ],
        "Issue a receipt for the existing clean descendant authoring repository",
    )
    current_commands["ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT"]["cwd"] = AUTHORING
    p08_base = [
        "uv", "run", "--frozen", "--offline", "python",
        "tools/qualify_descendant_repository.py", "--root", RUNTIME,
        "--config", vendor_config,
    ]
    current_commands["VERIFY_V636_P08_T01"] = _operation(
        "VERIFY_V636_P08_T01",
        p08_base + ["--output", f"{EVIDENCE}/V636-P08-T01.json", "--preflight"],
        "Preflight the current descendant repository without mutation",
    )
    current_commands["VERIFY_V636_P08_T02"] = _operation(
        "VERIFY_V636_P08_T02",
        p08_base + ["--issue", "--receipt", descendant_receipt, "--output", f"{EVIDENCE}/V636-P08-T02.json"],
        "Exclusively issue the descendant repository qualification receipt",
    )
    current_commands["VERIFY_V636_P08_T03"] = _operation(
        "VERIFY_V636_P08_T03",
        p08_base + ["--check-only", "--receipt", descendant_receipt, "--output", f"{EVIDENCE}/V636-P08-T03.json"],
        "Revalidate the descendant receipt without writing repository state",
    )
    current_commands["VERIFY_V636_P09_T01"] = _operation(
        "VERIFY_V636_P09_T01",
        [
            "python3.12", "-B", "tools/assemble_review_pack.py", "--source", f"{AUTHORING}/pack",
            "--destination", REVIEW_PACK, "--config", vendor_config,
            *transport[4:],
        ],
        "Run exact authoring verifier for V636-P09-T01",
    )
    current_commands["VERIFY_V636_P09_T02"] = _operation(
        "VERIFY_V636_P09_T02",
        ["python3.12", "-B", "tools/compute_governed_content_root.py", "--pack", REVIEW_PACK,
         "--registry", f"{REVIEW_PACK}/docs/registries/seal-exclusions.v1.json"],
        "Run exact authoring verifier for V636-P09-T02",
    )
    current_commands["VERIFY_V636_P09_T03"] = _operation(
        "VERIFY_V636_P09_T03",
        [
            "python3.12", "-B", "tools/build_self_review.py",
            "--governed-root", f"{REVIEW_PACK}/GOVERNED_CONTENT_ROOT.json",
            "--repository-receipt", packed_descendant_receipt_absolute,
            "--output-dir", REVIEW_PACK,
            *transport,
        ],
        "Run exact authoring verifier for V636-P09-T03",
    )
    current_commands["VERIFY_V636_P09_T04"] = _operation(
        "VERIFY_V636_P09_T04",
        ["python3.12", "-B", "tools/seal_review_pack.py", "--pack", REVIEW_PACK,
         *transport, "--zip", f"{REVIEW_PACK}.zip", "--sidecar", f"{REVIEW_PACK}.zip.sha256",
         "--attestation", f"{REVIEW_PACK}.seal-attestation.json"],
        "Run exact authoring verifier for V636-P09-T04",
    )
    for role in ("a", "b"):
        command_id = f"VERIFY_V636_P10_T0{1 if role == 'a' else 2}"
        current_commands[command_id] = _operation(
            command_id,
            [
                "uv", "run", "--frozen", "python", "tools/issue_review_launch_authorization.py",
                "--config", f"review-config/review-{role}.v2.json", "--output",
                f"{PREFIX}/review-authorizations/hybrid-discovery-v6.3.6/review-{role}.authorization.json",
            ],
            f"Run exact verifier for V636-P10-T0{1 if role == 'a' else 2}",
        )
    current_commands["VERIFY_V636_P10_T04"] = _operation(
        "VERIFY_V636_P10_T04",
        [
            "uv", "run", "--frozen", "python", "tools/aggregate_reviews.py", "--config",
            "review-config/review-aggregation.v2.json", "--review-a",
            f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-a/result.json", "--receipt-a",
            f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-a/execution-receipt.json",
            "--authorization-a",
            f"{PREFIX}/review-authorizations/hybrid-discovery-v6.3.6/review-a.authorization.json",
            "--review-b", f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-b/result.json",
            "--receipt-b", f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-b/execution-receipt.json",
            "--authorization-b",
            f"{PREFIX}/review-authorizations/hybrid-discovery-v6.3.6/review-b.authorization.json",
            "--output", f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/aggregate/result.json",
        ],
        "Run exact verifier for V636-P10-T04",
    )
    current_commands["V636_MIG0_T08_BINDINGS"] = _operation(
        "V636_MIG0_T08_BINDINGS",
        [
            "python3.12", "-B", "authoring-tools/build_task_command_registry.py",
            "--tasks", "pack/docs/tasks/task-manifest.v6.3.6.json",
            "--output", "runtime/task-command-registry.json",
            "--source-registry", "pack/docs/registries/task-command-registry.v1.json",
            "--review-config-source", "pack/docs/configs",
            "--review-config-profile", "current",
        ],
        "Regenerate MIG0-owned task/config bindings",
    )
    current_commands["V636_MIG0_T08_BINDINGS"]["cwd"] = AUTHORING
    current_commands["V636_MIG0_T08_BINDINGS"]["kind"] = "migration"
    current_commands["CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT"] = _operation(
        "CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT",
        [
            "uv", "run", "--frozen", "--offline", "python",
            "tools/run_environment_qualification.py", "--config", vendor_config,
            "--workspace", f"{EVIDENCE}/environment", "--aggregate",
            qualification["environment_qualification_aggregate"], "--inventory",
            qualification["environment_qualification_inventory"],
        ],
        "Capture the supplemental environment aggregate and closed retained inventory",
    )
    current_commands["CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT"]["kind"] = "verification"
    for command_id, current_shape in current_commands.items():
        _require_known_command(
            commands,
            command_id,
            current_shape,
            allow_missing=command_id == "CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT",
        )
    commands.update(current_commands)
    registry["commands"] = list(commands.values())

    review_registry_path = docs / "registries/review-command-registry.v1.json"
    review_registry = _read(review_registry_path)
    review_commands = {row["command_id"]: row for row in review_registry["commands"]}
    current_a_check = {
        "command_id": "A_CHECK_DESCENDANT",
        "cwd": RUNTIME,
        "argv": [
            "uv", "run", "--frozen", "--offline", "python",
            "tools/qualify_descendant_repository.py", "--root", RUNTIME,
            "--config", f"{REVIEW_PACK}/docs/configs/full-verifier-controller.v2.json",
            "--check-only", "--receipt",
            f"{REVIEW_PACK}/docs/receipts/descendant-repository-qualification-receipt.json",
            "--pack", REVIEW_PACK, *transport[2:],
        ],
        "purpose": "A_CHECK_DESCENDANT",
        "expected_exit": 0,
        "kind": "review-leaf",
        "available_at": "SEALED",
        "network": "DENY",
        "authenticated_operator_access": "DENY",
        "provider_access": "DENY",
    }
    current_aggregate = {
        "command_id": "REVIEW_AGGREGATE",
        "cwd": RUNTIME,
        "argv": [
            "uv", "run", "--frozen", "python", "tools/aggregate_reviews.py", "--config",
            "review-config/review-aggregation.v2.json", "--review-a",
            f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-a/result.json", "--receipt-a",
            f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-a/execution-receipt.json",
            "--authorization-a",
            f"{PREFIX}/review-authorizations/hybrid-discovery-v6.3.6/review-a.authorization.json",
            "--review-b", f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-b/result.json",
            "--receipt-b", f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-b/execution-receipt.json",
            "--authorization-b",
            f"{PREFIX}/review-authorizations/hybrid-discovery-v6.3.6/review-b.authorization.json",
            "--output", f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/aggregate/result.json",
        ],
        "expected_exit": 0,
        "kind": "review-operation",
        "available_at": "SEALED",
        "purpose": "REVIEW_AGGREGATE",
        "network": "DENY",
        "authenticated_operator_access": "DENY",
        "provider_access": "DENY",
    }
    _require_known_command(
        review_commands,
        "A_CHECK_DESCENDANT",
        current_a_check,
        allow_missing=True,
    )
    _require_known_command(review_commands, "REVIEW_AGGREGATE", current_aggregate)
    for command_id, argv in (
        ("A_CHECK_SOURCE", [
            "uv", "run", "--frozen", "--offline", "python", "tools/verify_executable_references.py",
            "--mode", "sealed-review", "--pack", REVIEW_PACK, *transport,
        ]),
        ("A_CHECK_EVIDENCE", [
            "uv", "run", "--frozen", "--offline", "python", "tools/verify_proof_coverage.py",
            "--matrix", f"{REVIEW_PACK}/docs/registries/proof-coverage-matrix.v1.json",
            "--stage", "SEALED", "--evidence-root", f"{REVIEW_PACK}/evidence",
            "--attestation", f"{REVIEW_PACK}.seal-attestation.json", "--zip", f"{REVIEW_PACK}.zip",
            "--sidecar", f"{REVIEW_PACK}.zip.sha256", *transport,
        ]),
    ):
        row = {
            "command_id": command_id, "cwd": RUNTIME, "argv": argv, "purpose": command_id,
            "expected_exit": 0, "kind": "review-leaf", "available_at": "SEALED",
            "network": "DENY", "authenticated_operator_access": "DENY", "provider_access": "DENY",
        }
        _require_known_command(review_commands, command_id, row)
        review_commands[command_id] = row
    review_commands["A_CHECK_DESCENDANT"] = current_a_check
    review_commands["REVIEW_AGGREGATE"] = current_aggregate
    review_registry["commands"] = list(review_commands.values())

    proof_path = docs / "registries/proof-coverage-matrix.v1.json"
    proof = _read(proof_path)
    proof_rows = {row["requirement_id"]: row for row in proof["entries"]}
    proof_rows["V631-C5.CRASH_COVERAGE"].update(
        implementation_symbol="runtime/tools/run_full_repair_qualification.py::main",
        test_file="runtime/tests/durability/test_owner_mutation_review.py",
        command_id="TEST_V636_P03_T07",
        evidence_artifact=qualification["p03_proof"],
        evidence_owner="V636-P03-T07",
    )
    proof_rows["V631-C5.CLOCK_EVALUATION"].update(
        implementation_symbol="runtime/tools/verify_full_repair_qualification.py::main",
        test_file="runtime/tests/durability/test_owner_mutation_review.py",
        command_id="TEST_V636_P04_T04",
        evidence_artifact=qualification["p04_proof"],
        evidence_owner="V636-P04-T04",
    )
    for row in proof["entries"]:
        if row["stage"] == "CANDIDATE":
            old = str(row["evidence_artifact"])
            if Path(old).parent not in {
                Path(f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6"), Path(EVIDENCE)
            }:
                raise ValueError("E_DESCENDANT_PROOF_PATH")
            row["evidence_artifact"] = f"{EVIDENCE}/{Path(old).name}"

    ownership_path = docs / "registries/artifact-ownership.v1.json"
    ownership = _read(ownership_path)
    owned = {row["path"]: row for row in ownership["entries"]}
    for path in new_source_outputs - {new_authoring_receipt} - early_source_outputs:
        owned[path] = _task_output(path, "V636-MIG0-T08", ["V636-MIG0-T08", "V636-P09-T01"])
    for path in early_source_outputs:
        owned[path] = _task_output(path, "V636-P00-T03", ["V636-P00-T03"])
    owned["pack/docs/configs/full-verifier-controller.v2.json"]["consumers"] += [
        "V636-P03-T07",
        "V636-P04-T04",
        "V636-P07-T01",
        "V636-P07-T02",
        "V636-P07-T03",
        "V636-P08-T01",
        "V636-P08-T02",
        "V636-P08-T03",
        "V636-P10-T01",
    ]
    for path in amended_source_outputs:
        if path not in owned:
            raise ValueError(f"E_DESCENDANT_MISSING_OWNERSHIP:{path}")
        modifiers = owned[path]["modifying_tasks"]
        if "V636-MIG0-T08" not in modifiers:
            modifiers.append("V636-MIG0-T08")
        consumers = owned[path]["consumers"]
        if "V636-MIG0-T08" not in consumers:
            consumers.append("V636-MIG0-T08")
    owned[new_authoring_receipt] = _evidence_output(new_authoring_receipt, "V636-MIG0-T08", ["V636-P07-T01"])
    runtime_sources = {
        "runtime/tools/full_verifier_config.py": ("V636-P07-T01", ["V636-P07-T01", "V636-P07-T02", "V636-P07-T03"]),
        "runtime/tools/run_full_repair_qualification.py": ("V636-P03-T07", ["V636-P03-T07", "V636-P07-T01"]),
        "runtime/tools/verify_full_repair_qualification.py": ("V636-P04-T04", ["V636-P04-T04", "V636-P07-T01"]),
        "runtime/tools/qualify_descendant_repository.py": ("V636-P08-T01", ["V636-P08-T01", "V636-P08-T02", "V636-P08-T03", "V636-P10-T01"]),
        "runtime/tools/run_environment_qualification.py": (
            "V636-P03-T07",
            ["V636-P03-T07", "V636-P08-T01", "V636-P09-T01"],
        ),
        "runtime/tools/retained_artifact_io.py": (
            "V636-P03-T07",
            ["V636-P03-T07", "V636-P04-T04", "V636-P07-T01", "V636-P07-T02", "V636-P07-T03", "V636-P08-T01", "V636-P08-T02", "V636-P08-T03", "V636-P09-T01", "V636-P09-T03", "V636-P10-T01", "V636-P10-T02", "V636-P10-T04"],
        ),
        "runtime/tests/release/test_descendant_repository_qualification.py": (
            "V636-P08-T01",
            ["V636-P08-T01", "V636-P08-T02", "V636-P08-T03"],
        ),
        "runtime/tests/durability/test_owner_mutation_review.py": ("V636-P03-T07", ["V636-P03-T07", "V636-P04-T04"]),
    }
    for path, (owner, consumers) in runtime_sources.items():
        owned[path] = _task_output(path, owner, consumers)
    review_config_consumers = {
        "review-a.v2.json": ["V636-P10-T01"],
        "review-b.v2.json": ["V636-P10-T02"],
        "review-aggregation.v2.json": ["V636-P10-T04"],
    }
    for name, consumers in review_config_consumers.items():
        owned[f"runtime/review-config/{name}"] = _task_output(
            f"runtime/review-config/{name}", "V636-MIG0-T08", consumers
        )
    evidence_owners = {
        qualification["full_repair_aggregate"]: ("V636-P03-T07", ["V636-P04-T04", "V636-P07-T02", "V636-P08-T01", "V636-P09-T01"]),
        qualification["full_repair_inventory"]: ("V636-P03-T07", ["V636-P04-T04", "V636-P08-T01", "V636-P09-T01"]),
        qualification["environment_qualification_aggregate"]: ("V636-P03-T07", ["V636-P08-T01", "V636-P09-T01"]),
        qualification["environment_qualification_inventory"]: ("V636-P03-T07", ["V636-P08-T01", "V636-P09-T01"]),
        qualification["p03_proof"]: ("V636-P03-T07", ["V636-P04-T04", "V636-P07-T02", "V636-P08-T01", "V636-P09-T01"]),
        qualification["p04_proof"]: ("V636-P04-T04", ["V636-P07-T02", "V636-P08-T01", "V636-P09-T01"]),
        descendant_receipt: ("V636-P08-T02", ["V636-P08-T03", "V636-P09-T01", "V636-P10-T01"]),
        f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json": (
            "V636-P07-T03",
            ["V636-P08-T01", "V636-P08-T02", "V636-P08-T03", "V636-P09-T01", "V636-P09-T03"],
        ),
    }
    for path, (owner, consumers) in evidence_owners.items():
        owned[path] = _evidence_output(path, owner, consumers)
    owned[packed_descendant_receipt] = _task_output(
        packed_descendant_receipt, "V636-P09-T01", ["V636-P09-T01", "V636-P09-T03", "V636-P10-T01"]
    )
    for task_id in ("V636-P08-T01", "V636-P08-T02", "V636-P08-T03"):
        path = f"{EVIDENCE}/{task_id}.json"
        owned[path] = _evidence_output(path, task_id, [] if task_id == "V636-P08-T03" else ["V636-P08-T03"])
    ownership["entries"] = sorted(owned.values(), key=lambda row: str(row["path"]).encode())

    io_path = docs / "registries/command-io.v1.json"
    command_io = _read(io_path)
    io = {row["command_id"]: row for row in command_io["commands"]}
    io["TEST_V636_P03_T07"] = {
        "command_id": "TEST_V636_P03_T07", "consumers": ["V636-P03-T07"],
        "inputs": ["runtime/tools/run_full_repair_qualification.py", "runtime/tools/retained_artifact_io.py", "pack/docs/configs/full-verifier-controller.v2.json"],
        "outputs": [qualification["full_repair_aggregate"], qualification["full_repair_inventory"], qualification["p03_proof"]],
        "input_directories": [],
    }
    io["TEST_V636_P04_T04"] = {
        "command_id": "TEST_V636_P04_T04", "consumers": ["V636-P04-T04"],
        "inputs": ["runtime/tools/verify_full_repair_qualification.py", "runtime/tools/retained_artifact_io.py", "pack/docs/configs/full-verifier-controller.v2.json", qualification["full_repair_aggregate"], qualification["full_repair_inventory"], qualification["p03_proof"]],
        "outputs": [qualification["p04_proof"]], "input_directories": [],
    }
    io["ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT"]["outputs"] = [new_authoring_receipt]
    io["CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT"] = {
        "command_id": "CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT",
        "consumers": ["V636-P03-T07"],
        "inputs": [
            "runtime/tools/run_environment_qualification.py",
            "runtime/tools/retained_artifact_io.py",
            "pack/docs/configs/full-verifier-controller.v2.json",
        ],
        "outputs": [
            qualification["environment_qualification_aggregate"],
            qualification["environment_qualification_inventory"],
        ],
        "input_directories": [],
    }
    for task_id in ("V636-P07-T01", "V636-P07-T02", "V636-P07-T03"):
        row = io[f"VERIFY_{task_id.replace('-', '_')}"]
        row["inputs"] = [
            "pack/docs/configs/full-verifier-controller.v2.json"
            if path == "pack/docs/configs/full-verifier-controller.v1.json" else path
            for path in row["inputs"]
        ]
        if "pack/docs/configs/full-verifier-controller.v2.json" not in row["inputs"]:
            row["inputs"].append("pack/docs/configs/full-verifier-controller.v2.json")
    p07_matrices = {
        "pack/docs/registries/proof-coverage-matrix.v1.json",
        "runtime/vendor/hybrid-discovery-v6.3.6/docs/registries/proof-coverage-matrix.v1.json",
    }
    tasks["V636-P07-T02"]["inputs"] = sorted(set(tasks["V636-P07-T02"]["inputs"]) | p07_matrices)
    io["VERIFY_V636_P07_T02"]["inputs"] = sorted(set(io["VERIFY_V636_P07_T02"]["inputs"]) | p07_matrices)
    for path in p07_matrices:
        owned[path]["consumers"] = sorted(set(owned[path]["consumers"]) | {"V636-P07-T02"})
    for task_id, mode, outputs in (
        ("V636-P08-T01", "--preflight", [f"{EVIDENCE}/V636-P08-T01.json"]),
        ("V636-P08-T02", "--issue", [f"{EVIDENCE}/V636-P08-T02.json", descendant_receipt]),
        ("V636-P08-T03", "--check-only", [f"{EVIDENCE}/V636-P08-T03.json"]),
    ):
        inputs = [
            "runtime/tools/qualify_descendant_repository.py",
            "runtime/tools/retained_artifact_io.py",
            "pack/docs/configs/full-verifier-controller.v2.json",
            f"{EVIDENCE}/V636-P07-T01.json",
            f"{EVIDENCE}/V636-P07-T02.json",
            f"{EVIDENCE}/V636-P07-T03.json",
            f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json",
            *qualification.values(),
        ]
        if mode == "--check-only":
            inputs.append(descendant_receipt)
        io[f"VERIFY_{task_id.replace('-', '_')}"] = {
            "command_id": f"VERIFY_{task_id.replace('-', '_')}",
            "consumers": [task_id], "inputs": inputs, "outputs": outputs,
            "input_directories": [],
        }
    io["VERIFY_V636_P09_T01"]["inputs"] = [
        "runtime/tools/assemble_review_pack.py",
        "pack/docs/configs/full-verifier-controller.v2.json",
        qualification["full_repair_aggregate"],
        qualification["full_repair_inventory"],
        qualification["environment_qualification_aggregate"],
        qualification["environment_qualification_inventory"],
        qualification["p03_proof"],
        qualification["p04_proof"],
        f"{EVIDENCE}/V636-P07-T01.json",
        f"{EVIDENCE}/V636-P07-T02.json",
        f"{EVIDENCE}/V636-P07-T03.json",
        f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json",
        descendant_receipt,
    ]
    io["VERIFY_V636_P09_T01"]["outputs"] = [packed_descendant_receipt]
    io["VERIFY_V636_P09_T03"]["inputs"] = [
        "pack/GOVERNED_CONTENT_ROOT.json",
        packed_descendant_receipt,
        "runtime/tools/build_self_review.py",
        "runtime/tools/retained_artifact_io.py",
        f"{EVIDENCE}/V636-P07-T01.json",
        f"{EVIDENCE}/V636-P07-T02.json",
        f"{EVIDENCE}/V636-P07-T03.json",
        f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json",
    ]
    io["A_CHECK_DESCENDANT"] = {
        "command_id": "A_CHECK_DESCENDANT",
        "consumers": ["V636-P10-T01"],
        "inputs": [
            "runtime/tools/qualify_descendant_repository.py",
            "pack/docs/configs/full-verifier-controller.v2.json",
            packed_descendant_receipt,
        ],
        "outputs": [],
        "input_directories": [],
    }
    io["V636_MIG0_T08_BINDINGS"]["inputs"] = [
        "authoring-tools/build_task_command_registry.py",
        "pack/docs/tasks/task-manifest.v6.3.6.json",
        "pack/docs/registries/task-command-registry.v1.json",
        "pack/docs/configs/review-a.v2.json",
        "pack/docs/configs/review-b.v2.json",
        "pack/docs/configs/review-aggregation.v2.json",
        "pack/docs/configs/review-authority.v1.json",
    ]
    io["V636_MIG0_T08_BINDINGS"]["outputs"] = [
        "runtime/task-command-registry.json",
        "runtime/review-config/review-a.v2.json",
        "runtime/review-config/review-b.v2.json",
        "runtime/review-config/review-aggregation.v2.json",
        "runtime/review-config/review-authority.v1.json",
    ]
    io["VERIFY_V636_P10_T01"]["inputs"] = [
        "runtime/review-config/review-a.v2.json",
        "runtime/tools/issue_review_launch_authorization.py",
        "runtime/tools/retained_artifact_io.py",
        packed_descendant_receipt,
    ]
    io["VERIFY_V636_P10_T02"]["inputs"] = [
        "runtime/review-config/review-b.v2.json",
        "runtime/tools/issue_review_launch_authorization.py",
        "runtime/tools/retained_artifact_io.py",
        packed_descendant_receipt,
    ]
    io["VERIFY_V636_P10_T04"]["inputs"] = [
        "runtime/review-config/review-aggregation.v2.json",
        "runtime/tools/aggregate_reviews.py",
        "runtime/tools/retained_artifact_io.py",
        packed_descendant_receipt,
        f"{PREFIX}/review-authorizations/hybrid-discovery-v6.3.6/review-a.authorization.json",
        f"{PREFIX}/review-authorizations/hybrid-discovery-v6.3.6/review-b.authorization.json",
        f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-a/execution-receipt.json",
        f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-a/result.json",
        f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-b/execution-receipt.json",
        f"{PREFIX}/reviews/hybrid-discovery-v6.3.6/review-b/result.json",
    ]

    # Finite assembly outputs and read footprints. Transport metadata grants no
    # execution permission: B's cybersecurity registry/config remain untouched.
    retained_source_artifacts = {
        "pack/docs/contracts/02-authority-graph.md", "pack/docs/receipts/source-provenance.v1.json",
        "pack/docs/receipts/declaration-complete.v1.json", "pack/docs/receipts/migration-receipt.v1.json",
    }
    for path in retained_source_artifacts:
        owned[path]["consumers"] = sorted(set(owned[path]["consumers"]) | {"V636-P09-T01"})
    tasks["V636-P09-T01"]["inputs"] = sorted(set(tasks["V636-P09-T01"]["inputs"]) | retained_source_artifacts)
    io["VERIFY_V636_P09_T01"]["inputs"] = sorted(set(io["VERIFY_V636_P09_T01"]["inputs"]) | retained_source_artifacts)
    io["VERIFY_V636_P00_T01"]["outputs"] = ["pack/docs/receipts/source-provenance.v1.json"]
    retained_receipts = {
        f"{PREFIX}/plan-input/.receipts/hybrid-discovery-v6.3.6-plan-input.json",
        f"{PREFIX}/hybrid-discovery-v6.3.6-authoring/.bootstrap/authoring-workspace-receipt.json",
        f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6/bootstrap/authoring-repository-receipt.json",
        f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T02.json",
        new_authoring_receipt,
        f"{EVIDENCE}/bootstrap/authoring-repository-receipt.json",
    }
    for locator in retained_receipts:
        canonical = locator.removeprefix(f"{PREFIX}/hybrid-discovery-v6.3.6-authoring/")
        owned[canonical]["consumers"] = sorted(set(owned[canonical]["consumers"]) | {"V636-P09-T01"})
    tasks["V636-P09-T01"]["inputs"] = sorted(set(tasks["V636-P09-T01"]["inputs"]) | retained_receipts)
    io["VERIFY_V636_P09_T01"]["inputs"] = sorted(set(io["VERIFY_V636_P09_T01"]["inputs"]) | retained_receipts)
    for suffix in ("02", "03", "04"):
        io[f"VERIFY_V636_P09_T{suffix}"]["outputs"] = sorted(
            set(tasks[f"V636-P09-T{suffix}"]["outputs"])
            | ({f"{REVIEW_PACK}{extension}" for extension in (".zip", ".zip.sha256", ".seal-attestation.json")}
               if suffix == "04" else set())
        )
    assembly_outputs = {
        retained_manifest, retained_root, packed_descendant_receipt,
        *(f"pack/evidence/{name}" for name in (
            "V636-P07-T01.json", "V636-P07-T02.json", "V636-P07-T03.json",
            "CANDIDATE_QUALIFICATION.json",
        )),
    }
    for proof_row in proof["entries"]:
        if proof_row["stage"] == "CANDIDATE":
            assembly_outputs.add("pack/" + proof_row["sealed_evidence_path"])
            tasks["V636-P09-T01"]["inputs"].append(proof_row["evidence_artifact"])
            io["VERIFY_V636_P09_T01"]["inputs"].append(proof_row["evidence_artifact"])
    tasks["V636-P09-T01"]["inputs"] = sorted(set(tasks["V636-P09-T01"]["inputs"]))
    io["VERIFY_V636_P09_T01"]["inputs"] = sorted(set(io["VERIFY_V636_P09_T01"]["inputs"]))
    for entry in delivery["authoring_source_exports"]:
        if str(entry["source"]).startswith("plan-input/bootstrap/"):
            assembly_outputs.add(entry["destination"])
            source_entry = owned[entry["source"]]
            source_entry["consumers"] = sorted(set(source_entry["consumers"]) | {"V636-P09-T01"})
            tasks["V636-P09-T01"]["inputs"].append(entry["source"])
            io["VERIFY_V636_P09_T01"]["inputs"].append(entry["source"])
    later_consumers = ["V636-P09-T01", "V636-P09-T03", "V636-P09-T04",
                       "V636-P10-T01", "V636-P10-T02", "V636-P10-T03", "V636-P10-T04"]
    for path in assembly_outputs:
        owned[path] = _task_output(path, "V636-P09-T01", later_consumers)
    tasks["V636-P09-T01"]["outputs"] = sorted(set(tasks["V636-P09-T01"]["outputs"]) | assembly_outputs)
    io["VERIFY_V636_P09_T01"]["outputs"] = sorted(assembly_outputs)
    for criterion in (
        "Verify the configured descendant receipt and exact inputs before exclusive destination creation.",
        "Copy the finite declared source and evidence closure into evidence/retained with its sibling retained-artifact-manifest/v1; preserve original bytes and locator boundaries.",
        "Reject conflicting locator boundaries, unsafe or aliased files, named-copy divergence and protected destination overlap; remove only an owned failed destination.",
        "Revalidate full-repair, supplemental, descendant and normative semantics through the copied SEALED context without original-root fallback.",
    ):
        if criterion not in tasks["V636-P09-T01"]["acceptance_criteria"]:
            tasks["V636-P09-T01"]["acceptance_criteria"].append(criterion)

    context_inputs = {
        "runtime/tools/assemble_review_pack.py", "runtime/tools/retained_artifact_io.py",
        "pack/docs/configs/full-verifier-controller.v2.json", transport[3],
        retained_manifest, packed_descendant_receipt,
    }
    current_readers = {
        "VERIFY_V636_P09_T03": "V636-P09-T03",
        "VERIFY_V636_P09_T04": "V636-P09-T04",
        "A_CHECK_SOURCE": "V636-P10-T01", "A_CHECK_EVIDENCE": "V636-P10-T01",
        "A_CHECK_DESCENDANT": "V636-P10-T01",
        "VERIFY_V636_P10_T01": "V636-P10-T01", "REVIEW_A_PREPARE": "V636-P10-T01",
        "REVIEW_A_FINALIZE": "V636-P10-T03",
        "VERIFY_V636_P10_T02": "V636-P10-T02", "REVIEW_B_PREPARE": "V636-P10-T02",
        "REVIEW_B_FINALIZE": "V636-P10-T03",
        "VERIFY_V636_P10_T04": "V636-P10-T04", "REVIEW_AGGREGATE": "V636-P10-T04",
    }
    for command_id, task_id in current_readers.items():
        row = io[command_id]
        inputs = set(row["inputs"]) | context_inputs
        if task_id.startswith("V636-P10") and not command_id.startswith("A_CHECK_"):
            inputs |= {
                "runtime/tools/issue_review_launch_authorization.py", "runtime/tools/seal_review_pack.py",
                "runtime/review-config/review-a.v2.json", "pack/docs/configs/review-a.v2.json",
                "pack/docs/registries/review-command-registry.v1.json",
                *(str(value) for value in review_a["seal_inputs"].values()),
            }
            if command_id in {"VERIFY_V636_P10_T02", "REVIEW_B_PREPARE", "REVIEW_B_FINALIZE",
                              "VERIFY_V636_P10_T04", "REVIEW_AGGREGATE"}:
                inputs |= {
                    "runtime/review-config/review-b.v2.json", "pack/docs/configs/review-b.v2.json",
                    "pack/docs/registries/cybersecurity-command-registry.v1.json",
                }
        if command_id == "REVIEW_AGGREGATE":
            inputs.discard("runtime/review-config/review-aggregation.v1.json")
            inputs.add("runtime/review-config/review-aggregation.v2.json")
        if task_id == "V636-P09-T04":
            inputs |= {
                "pack/SELF_REVIEW_REPORT.json", "pack/SELF_REVIEW_REPORT.md",
                "pack/GOVERNED_CONTENT_ROOT.json", "pack/docs/tasks/task-manifest.v6.3.6.json",
            }
        row["inputs"] = sorted(inputs)
        row["input_directories"] = sorted(set(row.get("input_directories", [])) | {transport[7]})
        row["consumers"] = sorted(set(row["consumers"]) | {task_id})
        tasks[task_id]["inputs"] = sorted(set(tasks[task_id]["inputs"]) | inputs | {retained_root})
        for path in inputs | {retained_root}:
            if path in owned:
                owned[path]["consumers"] = sorted(set(owned[path]["consumers"]) | {task_id})
    for path, task_ids in {
        "runtime/tools/assemble_review_pack.py": {"V636-P09-T01"},
        "runtime/tools/verify_executable_references.py": {"V636-P09-T01"},
        "runtime/tools/qualify_descendant_repository.py": {"V636-P10-T01"},
    }.items():
        owned[path]["modifying_tasks"] = sorted(set(owned[path]["modifying_tasks"]) | task_ids)
    ownership["entries"] = sorted(owned.values(), key=lambda row: str(row["path"]).encode())
    command_io["commands"] = list(io.values())

    normative_path = docs / "registries/normative-source-map.v1.json"
    normative = _read(normative_path)
    plan_entries = {row["plan_source"]: row for row in normative["plan_entries"]}
    new_normative = {
        "docs/configs/full-verifier-controller.v2.json",
        "docs/configs/review-a.v2.json",
        "docs/configs/review-b.v2.json",
        "docs/configs/review-aggregation.v2.json",
        "docs/schemas/descendant-repository-qualification-receipt.schema.json",
        "docs/schemas/full-verifier-controller.schema.json",
    }
    for source in new_normative:
        plan_entries[source] = {"plan_source": source, "vendor_relative": source}
    normative["plan_entries"] = [plan_entries[key] for key in sorted(plan_entries, key=str.encode)]

    schema_registry_path = docs / "registries/schema-reference-registry.v1.json"
    schema_registry = _read(schema_registry_path)
    references = {row["logical_name"]: row for row in schema_registry["references"]}
    references["DescendantRepositoryQualificationReceipt"] = {
        "logical_name": "DescendantRepositoryQualificationReceipt",
        "plan_source_path": "pack/docs/schemas/descendant-repository-qualification-receipt.schema.json",
        "materialized_runtime_path": "runtime/vendor/hybrid-discovery-v6.3.6/docs/schemas/descendant-repository-qualification-receipt.schema.json",
        "json_pointer": "#/$defs/DescendantRepositoryQualificationReceipt",
        "creation_owner": "V636-MIG0-T08",
        "required_stage": "MATERIALIZED",
    }
    references["FullVerifierController"] = {
        "logical_name": "FullVerifierController",
        "plan_source_path": "pack/docs/schemas/full-verifier-controller.schema.json",
        "materialized_runtime_path": "runtime/vendor/hybrid-discovery-v6.3.6/docs/schemas/full-verifier-controller.schema.json",
        "json_pointer": "#/$defs/FullVerifierController",
        "creation_owner": "V636-P00-T03",
        "required_stage": "DECLARED",
    }
    schema_registry["references"] = [references[key] for key in sorted(references, key=str.encode)]

    schema_changes: list[tuple[Path, dict[str, object]]] = []
    schema_specs = {
        "self-review-record.schema.json": {"SelfReviewRecord": "runtime-self-review/v2"},
        "external-seal-attestation.schema.json": {"ExternalSealAttestation": "external-seal-attestation/v7"},
        "review-launch-authorization.schema.json": {"ReviewLaunchAuthorization": "review-launch-authorization/v2"},
        "review-execution-receipt.schema.json": {"ReviewExecutionReceipt": "review-execution-receipt/v2"},
        "review-result.schema.json": {
            "ImplementationReviewResult": "independent-review-result/v2",
            "CybersecurityReviewResult": "independent-review-result/v2",
            "AggregateReviewResult": "review-aggregate-result/v2",
        },
    }
    for filename, branches in schema_specs.items():
        path = docs / "schemas" / filename
        schema = _read(path)
        for logical_name, version in branches.items():
            _add_identity_branch(schema, logical_name, version)
        if filename == "external-seal-attestation.schema.json":
            current_seal = schema["$defs"]["DescendantExternalSealAttestation"]
            current_seal["properties"]["artifact_type"] = {"const": "RUNTIME_PACK"}
            if "candidate_receipt_sha256" not in current_seal["required"]:
                current_seal["required"].append("candidate_receipt_sha256")
        schema_changes.append((path, schema))

    contract_path = docs / "contracts/07-command-and-config-lifecycle.md"
    contract = contract_path.read_text(encoding="utf-8")
    marker = "\n## Current descendant qualification path\n"
    if marker not in contract:
        contract += (
            marker
            + "\nThe current v6.3.6 path uses `full-verifier-controller/v2`, proves descent from "
            + f"audited commit `{AUDITED_ANCESTOR}`, and retains P03/P04 plus supplemental "
            "environment evidence under the configured evidence root. P08 is descendant "
            "preflight, exclusive receipt issuance, then check-only validation. Historical "
            "zero-parent commands and v1 schemas remain valid only for their immutable legacy "
            "artifacts; no current command exports, creates, replays, or relabels a baseline. "
            "P09 and both review roles consume one neutral `DESCENDANT` repository identity.\n"
        )

    outputs: list[tuple[Path, object]] = [
        (delivery_path, delivery),
        (docs / "configs/full-verifier-controller.v2.json", config_v2),
        (docs / "configs/review-a.v2.json", review_a),
        (docs / "configs/review-b.v2.json", review_b),
        (docs / "configs/review-aggregation.v2.json", review_aggregation),
        (manifest_path, manifest),
        (registry_path, registry),
        (review_registry_path, review_registry),
        (proof_path, proof),
        (ownership_path, ownership),
        (io_path, command_io),
        (normative_path, normative),
        (schema_registry_path, schema_registry),
        (docs / "schemas/descendant-repository-qualification-receipt.schema.json", _descendant_receipt_schema()),
        (docs / "schemas/full-verifier-controller.schema.json", _controller_schema()),
        *schema_changes,
    ]
    changed = sum(_dump(path, value) for path, value in outputs)
    changed += int(_write_text(contract_path, contract))
    return {"result": "PASS", "changed": changed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(apply_descendant_qualification_followup(args.pack), sort_keys=True))


if __name__ == "__main__":
    main()
