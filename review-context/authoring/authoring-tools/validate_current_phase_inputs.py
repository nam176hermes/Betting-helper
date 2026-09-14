"""Validate current declarations and adopted descendant source, read-only.

Historical MIG0 receipts retain their original meaning. Source adoption is not
historical acceptance, candidate qualification, or live authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from issue_declaration_gate import validate_declaration
from validate_task_manifest import AUTHORING_ROOT
from verify_successor_migration import _entry_index, _scan_legacy


def regular(path):
    if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("E_CURRENT_PATH")
    return path.read_bytes()


def resolve(authoring, runtime, logical):
    if (not isinstance(logical, str) or "\\" in logical or
        any(p in {"", ".", ".."} for p in logical.split("/")) or
        PurePosixPath(logical).as_posix() != logical or
        not authoring.is_absolute() or not runtime.is_absolute() or
        authoring.resolve() != authoring or runtime.resolve() != runtime or
        runtime == authoring or runtime.is_relative_to(authoring) or authoring.is_relative_to(runtime)):
        raise ValueError("E_CURRENT_PATH")
    if logical.startswith("runtime/"):
        target = runtime / logical.removeprefix("runtime/")
    elif logical.startswith("pack/"):
        target = authoring / logical
    else:
        raise ValueError("E_CURRENT_PATH")
    if target.resolve() != target:
        raise ValueError("E_CURRENT_PATH")
    return target


def sha(path):
    return hashlib.sha256(regular(path)).hexdigest()


def declaration(authoring):
    docs = authoring / "pack/docs"
    paths = ["tasks/task-manifest.v6.3.6.json", "registries/artifact-ownership.v1.json",
             "schemas/artifact-ownership.schema.json", *["registries/" + name for name in (
                 "task-command-registry.v1.json", "review-command-registry.v1.json",
                 "cybersecurity-command-registry.v1.json", "baseline-replay-command-registry.v1.json")]]
    hashes = {name: sha(docs / name) for name in paths}
    # BOOT0 logical references retain their original namespace; this parameter
    # only normalizes declared names and never reads that historical checkout.
    result = validate_declaration(docs / paths[0], docs / paths[1], docs / paths[3], authoring_root=Path(AUTHORING_ROOT))
    if hashes != {name: sha(docs / name) for name in paths}:
        raise ValueError("E_CURRENT_INPUT_DRIFT")
    return {"schema_version": "current-declaration/v1", "gate": "CURRENT_DECLARATION_VALID",
            "result": "PASS", "input_hashes": hashes, "task_count": result["task_count"],
            "command_count": result["command_count"], "artifact_count": result["artifact_count"],
            "production_authority": "NONE"}


def validate_changed_paths(changed, approved, ownership, generated):
    for name in changed:
        logical = "runtime/" + name
        if logical in generated and logical not in approved:
            row = ownership.get(logical, {})
            if row.get("classification") != "GENERATED_OUTPUT" or not row.get("source"):
                raise ValueError("E_CURRENT_GENERATED_OWNER:" + logical)
            continue
        if logical not in approved:
            raise ValueError("E_CURRENT_UNDECLARED:" + logical)
        row = ownership.get(logical, {})
        if approved[logical] not in {row.get("creation_owner"), *row.get("modifying_tasks", [])}:
            raise ValueError("E_CURRENT_OWNER:" + logical)


def migration(authoring, runtime, contract):
    # Reuse the runtime's clean-source and closed normative checks without
    # importing its future qualification receipt (which would create a cycle).
    sys.path[:0] = [str(runtime), str(runtime / "src")]
    from tools.run_command_registry import _git_source_identity, _declared_compiler_outputs
    from tools.qualify_descendant_repository import _git
    from tools.sync_pack_assets import sync_pack_assets, _files
    from tools.verify_toolchains import dependency_lock_hashes

    before = _git_source_identity(runtime)
    adopted = contract["adopted_source"]
    if _git(runtime, "rev-parse", adopted["commit"] + "^{tree}") != adopted["tree"]:
        raise ValueError("E_CURRENT_PREDECESSOR")
    _git(runtime, "merge-base", "--is-ancestor", adopted["commit"], "HEAD")
    historical = resolve(authoring, runtime, contract["historical_migration"])
    if sha(historical) != contract["historical_migration_sha256"]:
        raise ValueError("E_CURRENT_HISTORICAL_RECEIPT")
    docs = authoring / "pack/docs"
    ownership = _entry_index(docs / "registries/artifact-ownership.v1.json")
    mapping = json.loads(regular(docs / "registries/normative-source-map.v1.json"))
    generated = {"runtime/" + p for p in _declared_compiler_outputs(runtime)}
    generated.update({"runtime/schema-lock.json", "runtime/task-command-registry.json", "runtime/vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json"})
    for origin, relative in _files(authoring / "pack"):
        logical = mapping["vendor_prefix"] + relative.as_posix()
        destination = resolve(authoring, runtime, logical)
        row = ownership.get(logical, {})
        if row.get("source") != {"path": str(origin.relative_to(authoring))} or regular(origin) != regular(destination):
            raise ValueError("E_CURRENT_NORMATIVE")
        generated.add(logical)
    for name in ("review-a.v2.json", "review-b.v2.json", "review-aggregation.v2.json", "review-authority.v1.json", "review-a.v3.json", "review-b.v3.json"):
        logical = "runtime/review-config/" + name
        if regular(resolve(authoring, runtime, logical)) != regular(docs / "configs" / name):
            raise ValueError("E_CURRENT_CONFIG")
        generated.add(logical)
    if regular(runtime / "task-command-registry.json") != regular(docs / "registries/task-command-registry.v1.json"):
        raise ValueError("E_CURRENT_REGISTRY")
    sync_pack_assets(authoring / "pack", runtime, check=True)
    changed = _git(runtime, "diff", "--name-only", "--no-renames", adopted["commit"], "HEAD").splitlines()
    validate_changed_paths(changed, contract["approved_files"], ownership, generated)
    if _git(runtime, "diff", "--diff-filter=D", "--name-only", adopted["commit"], "HEAD"):
        raise ValueError("E_CURRENT_DELETION")
    registry = json.loads(regular(docs / "registries/version-rebinding.v1.json"))
    policy = registry["final_legacy_policy"]
    # Feed the unchanged historical scanner a narrow regular-file copy; no
    # symlinked runtime layout and no weakening of its finite allowlist.
    with TemporaryDirectory() as temporary:
        staging = Path(temporary)
        for logical in {row["path"] for field in ("source_entries", "immutable_fixture_files") for row in policy.get(field, [])}:
            raw = regular(resolve(authoring, runtime, logical))
            target = staging / logical
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        _scan_legacy(staging, policy)
    hashes = {name: sha(runtime / name) for name in changed}
    after = _git_source_identity(runtime)
    if before != after or sha(historical) != contract["historical_migration_sha256"]:
        raise ValueError("E_CURRENT_INPUT_DRIFT")
    return {"schema_version": "current-descendant-migration/v1", "gate": "CURRENT_DESCENDANT_SOURCE_VALID",
            "result": "PASS", "source_identity": before, "adopted_source": adopted,
            "historical_receipt_sha256": sha(historical), "changed_outputs": hashes,
            "dependency_locks": dependency_lock_hashes(runtime), "legacy_scan": "PASS",
            "historical_acceptance": "NOT_INFERRED", "production_authority": "NONE"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("declaration", "migration"), required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    authoring = TOOLS.parent
    path = authoring / args.contract
    if path != authoring / "pack/docs/contracts/part-b-one-ready.v1.json":
        raise ValueError("E_CURRENT_CONTRACT")
    raw = regular(path)
    contract = json.loads(raw)
    if contract["schema_version"] != "part-b-one-ready/v1" or contract["production_authority"] != "NONE":
        raise ValueError("E_CURRENT_CONTRACT")
    sys.path[:0] = [str(args.runtime), str(args.runtime / "src")]
    from tools.run_command_registry import _git_source_identity
    before = _git_source_identity(args.runtime)
    inputs = declaration(authoring)
    result = inputs if args.mode == "declaration" else migration(authoring, args.runtime, contract)
    if args.mode == "migration":
        run = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", *contract["historical_checks"], "-c", "/dev/null", "--confcutdir", str(authoring)], cwd=authoring, capture_output=True, timeout=120)
        if run.returncode != 0:
            raise ValueError("E_CURRENT_HISTORICAL_REGRESSION")
        result["historical_regressions"] = {"exit_code": run.returncode, "stdout": run.stdout.decode(), "stderr": run.stderr.decode()}
    if regular(path) != raw or before != _git_source_identity(args.runtime) or inputs["input_hashes"] != declaration(authoring)["input_hashes"]:
        raise ValueError("E_CURRENT_INPUT_DRIFT")
    result["source_identity"] = before
    result["input_hashes"] = inputs["input_hashes"]
    result["contract_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
