"""Generate the narrow post-baseline controller ownership and P07 DAG amendment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PREFIX = "/home/thenam176/betting-helper"
AUTHORING = f"{PREFIX}/authoring-controller-config-worktree"
RUNTIME = f"{PREFIX}/discovery-runtime-v6.3.6"
EVIDENCE = f"{PREFIX}/authoring-evidence/hybrid-discovery-v6.3.6-controller"


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("E_CONTROLLER_AMENDMENT")
    return value


def _dump(path: Path, value: object) -> bool:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if path.read_bytes() == encoded:
        return False
    path.write_bytes(encoded)
    return True


def _artifact(path: str, owner: str, *, source: str | None = None, consumers: list[str] | None = None) -> dict[str, object]:
    return {
        "path": path,
        "classification": "GENERATED_OUTPUT" if source else "EVIDENCE_OUTPUT",
        "creation_owner": owner,
        "modifying_tasks": ["V636-P05-T09"] if source else [],
        "materialization_required": False,
        "source": {"path": source} if source else None,
        "qualification_owner": "V636-P05-T09" if source else None,
        "consumers": consumers or [],
    }


def apply_full_verifier_followup(pack: Path) -> dict[str, object]:
    docs = pack / "docs"
    manifest_path = docs / "tasks/task-manifest.v6.3.6.json"
    ownership_path = docs / "registries/artifact-ownership.v1.json"
    command_io_path = docs / "registries/command-io.v1.json"
    registry_path = docs / "registries/task-command-registry.v1.json"
    manifest = _read(manifest_path)
    ownership = _read(ownership_path)
    command_io = _read(command_io_path)
    registry = _read(registry_path)
    tasks = {item["task_id"]: item for item in manifest["tasks"]}  # type: ignore[index]

    authoring_receipt = f"{EVIDENCE}/bootstrap/authoring-repository-receipt.json"
    evidence = {
        "V636-P07-T01": f"{EVIDENCE}/V636-P07-T01.json",
        "V636-P07-T02": f"{EVIDENCE}/V636-P07-T02.json",
        "V636-P07-T03": f"{EVIDENCE}/V636-P07-T03.json",
    }
    candidate = f"{EVIDENCE}/CANDIDATE_QUALIFICATION.json"
    mig = tasks["V636-MIG0-T08"]
    for field in ("outputs", "exact_files"):
        mig[field] = sorted(set(mig[field]) | {  # type: ignore[index]
            "authoring-tools/apply_full_verifier_followup.py",
            "authoring-tools/issue_current_authoring_repository_receipt.py",
            "authoring-tests/test_current_authoring_receipt.py",
            "authoring-tests/test_full_verifier_followup_amendment.py",
            "authoring-tests/test_full_verifier_controller_config.py",
            "pack/docs/configs/full-verifier-controller.v1.json",
            authoring_receipt,
        })
    mig["exact_command_ids"] = sorted(set(mig["exact_command_ids"]) | {"ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT"})  # type: ignore[index]
    tasks["V636-P07-T01"]["exact_command_ids"] = sorted(
        set(tasks["V636-P07-T01"]["exact_command_ids"])  # type: ignore[index]
        | {"VERIFY_EXTERNAL_AUTHORING_SOURCES"}
    )
    for task_id, output in evidence.items():
        task = tasks[task_id]
        task["outputs"] = [output]
        task["evidence_artifacts"] = [output]
    tasks["V636-P07-T03"]["outputs"] = [evidence["V636-P07-T03"], candidate]
    tasks["V636-P07-T03"]["evidence_artifacts"] = [evidence["V636-P07-T03"]]

    commands = {item["command_id"]: item for item in registry["commands"]}  # type: ignore[index]
    controller = _read(docs / "configs/full-verifier-controller.v1.json")
    external = controller["external_authoring_command"]
    commands["VERIFY_EXTERNAL_AUTHORING_SOURCES"] = {
        "command_id": "VERIFY_EXTERNAL_AUTHORING_SOURCES",
        "cwd": external["cwd"],
        "argv": external["argv"],
        "purpose": "Execute the closed exported authoring suite against the governed pack",
        "expected_exit": 0,
        "available_at": "MATERIALIZED",
        "network": "DENY",
        "authenticated_operator_access": "DENY",
        "provider_access": "DENY",
        "kind": "operation",
    }
    commands["ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT"] = {
        "command_id": "ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT",
        "cwd": AUTHORING,
        "argv": [
            "python3", "authoring-tools/issue_current_authoring_repository_receipt.py",
            "--root", AUTHORING, "--output", authoring_receipt,
            "--accepted-ancestor", "5249e84b57b7bc4d30abc24f41ead64174ab7549",
        ],
        "purpose": "Issue a receipt for the existing clean descendant authoring repository",
        "expected_exit": 0,
        "available_at": "MATERIALIZED",
        "network": "DENY",
        "authenticated_operator_access": "DENY",
        "provider_access": "DENY",
        "kind": "operation",
    }
    commands["VERIFY_V636_P07_T01"]["argv"] = [
        "uv", "run", "--frozen", "--offline", "python", "tools/run_command_registry.py",
        "--mode", "candidate-qualification", "--registry", "task-command-registry.json",
        "--config", f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json",
        "--output", evidence["V636-P07-T01"],
    ]
    commands["VERIFY_V636_P07_T01"]["cwd"] = RUNTIME
    commands["VERIFY_V636_P07_T02"]["argv"] = [
        "uv", "run", "--frozen", "--offline", "python", "tools/verify_proof_coverage.py",
        "--matrix", "../pack/docs/registries/proof-coverage-matrix.v1.json",
        "--evidence-root", EVIDENCE, "--stage", "CANDIDATE",
        "--config", f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json",
        "--output", evidence["V636-P07-T02"],
    ]
    commands["VERIFY_V636_P07_T02"]["cwd"] = RUNTIME
    commands["VERIFY_V636_P07_T03"]["argv"] = [
        "uv", "run", "--frozen", "--offline", "python", "tools/build_candidate_qualification_receipt.py",
        "--config", f"{RUNTIME}/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json",
        "--source", RUNTIME, "--command-evidence", evidence["V636-P07-T01"], "--output", candidate,
    ]
    commands["VERIFY_V636_P07_T03"]["cwd"] = RUNTIME
    registry["commands"] = list(commands.values())

    owned = {item["path"]: item for item in ownership["entries"]}  # type: ignore[index]
    generated = {
        "runtime/extension/dist/contracts/clock-coherence.js": "runtime/extension/src/contracts/clock-coherence.ts",
        "runtime/extension/.test-build/src/contracts/clock-coherence.js": "runtime/extension/src/contracts/clock-coherence.ts",
        "runtime/extension/.test-build/test-harness/repair-probe.js": "runtime/extension/test-harness/repair-probe.ts",
        "runtime/extension/.test-build/test/repairs/clock-raw-input.test.js": "runtime/extension/test/repairs/clock-raw-input.test.ts",
        "runtime/extension/.test-build/test/repairs/spool-persistence.test.js": "runtime/extension/test/repairs/spool-persistence.test.ts",
    }
    for path, source in generated.items():
        owned[path] = _artifact(path, "V636-MIG0-T07", source=source)
    for path, owner, consumers in (
        (authoring_receipt, "V636-MIG0-T08", ["V636-P07-T01"]),
        (evidence["V636-P07-T01"], "V636-P07-T01", ["V636-P07-T02", "V636-P07-T03"]),
        (evidence["V636-P07-T02"], "V636-P07-T02", ["V636-P07-T03"]),
        (evidence["V636-P07-T03"], "V636-P07-T03", []),
        (candidate, "V636-P07-T03", ["V636-P08-T01"]),
    ):
        owned[path] = _artifact(path, owner, consumers=consumers)
    for path in (
        "authoring-tools/apply_full_verifier_followup.py",
        "authoring-tools/issue_current_authoring_repository_receipt.py",
        "authoring-tests/test_current_authoring_receipt.py",
        "authoring-tests/test_full_verifier_followup_amendment.py",
        "authoring-tests/test_full_verifier_controller_config.py",
        "pack/docs/configs/full-verifier-controller.v1.json",
    ):
        owned[path] = {
            "path": path, "classification": "TASK_OUTPUT", "creation_owner": "V636-MIG0-T08",
            "modifying_tasks": [], "materialization_required": True, "source": None,
            "qualification_owner": "V636-MIG0-T08", "consumers": ["V636-MIG0-T08"],
        }
    ownership["entries"] = sorted(owned.values(), key=lambda item: item["path"])

    io = {item["command_id"]: item for item in command_io["commands"]}  # type: ignore[index]
    io["ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT"] = {
        "command_id": "ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT", "consumers": ["V636-MIG0-T08"],
        "inputs": ["authoring-tools/issue_current_authoring_repository_receipt.py"], "outputs": [authoring_receipt], "input_directories": [],
    }
    io["VERIFY_EXTERNAL_AUTHORING_SOURCES"] = {
        "command_id": "VERIFY_EXTERNAL_AUTHORING_SOURCES",
        "consumers": ["V636-P07-T01"],
        "inputs": [
            "pack/docs/configs/full-verifier-controller.v1.json",
            "pack/docs/registries/delivery-map.v1.json",
        ],
        "outputs": [],
        "input_directories": [
            f"{AUTHORING}/authoring-tests",
            f"{AUTHORING}/authoring-tools",
        ],
    }
    io["VERIFY_V636_P07_T01"]["outputs"] = [evidence["V636-P07-T01"]]
    io["VERIFY_V636_P07_T01"]["inputs"] = sorted(
        set(io["VERIFY_V636_P07_T01"]["inputs"])
        | {"pack/docs/configs/full-verifier-controller.v1.json"}
    )
    io["VERIFY_V636_P07_T02"]["outputs"] = [evidence["V636-P07-T02"]]
    io["VERIFY_V636_P07_T02"]["inputs"] = sorted(
        set(io["VERIFY_V636_P07_T02"]["inputs"])
        | {
            "pack/docs/configs/full-verifier-controller.v1.json",
            evidence["V636-P07-T01"],
        }
    )
    io["VERIFY_V636_P07_T03"]["inputs"] = ["runtime/tools/build_candidate_qualification_receipt.py", evidence["V636-P07-T01"], evidence["V636-P07-T02"]]
    io["VERIFY_V636_P07_T03"]["outputs"] = [evidence["V636-P07-T03"], candidate]
    command_io["commands"] = list(io.values())

    delivery_path = docs / "registries/delivery-map.v1.json"
    delivery = _read(delivery_path)
    exports = {item["source"]: item for item in delivery["authoring_source_exports"]}  # type: ignore[index]
    for path in (
        "authoring-tools/apply_full_verifier_followup.py",
        "authoring-tools/issue_current_authoring_repository_receipt.py",
        "authoring-tests/test_current_authoring_receipt.py",
        "authoring-tests/test_full_verifier_followup_amendment.py",
        "authoring-tests/test_full_verifier_controller_config.py",
    ):
        exports[path] = {
            "source": path,
            "destination": f"pack/authoring-source/{path}",
            "owner": "V636-P09-T01",
        }
    delivery["authoring_source_exports"] = [exports[key] for key in sorted(exports, key=str.encode)]

    changed = sum(
        _dump(path, value)
        for path, value in ((manifest_path, manifest), (ownership_path, ownership), (command_io_path, command_io), (registry_path, registry), (delivery_path, delivery))
    )
    return {"result": "PASS", "changed": changed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(apply_full_verifier_followup(args.pack), sort_keys=True))


if __name__ == "__main__":
    main()
