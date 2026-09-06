"""Replay or verify the zero-parent v6.3.6 baseline without live authority."""

# ruff: noqa: S108
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

EVIDENCE_ROOT = Path("/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6")
AUTHORING_PACK = "/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/pack"
FINAL_PACK = "/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6"
CANDIDATE_RECEIPT = EVIDENCE_ROOT / "CANDIDATE_QUALIFICATION.json"
CANDIDATE_COMMAND_EVIDENCE = EVIDENCE_ROOT / "V636-P07-T01.json"
HEX = re.compile(r"[0-9a-f]{64}")
ENVIRONMENT = {
    "FORCE_COLOR": "0",
    "HOME": "/home/thenam176",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NPM_CONFIG_IGNORE_SCRIPTS": "true",
    "NPM_CONFIG_USERCONFIG": "/dev/null",
    "NO_COLOR": "1",
    "PATH": (
        "/home/thenam176/.npm-global/bin:/home/thenam176/.local/share/mise/shims:"
        "/home/thenam176/.local/bin:/usr/local/bin:/usr/bin:/bin"
    ),
    "PYTHONHASHSEED": "0",
    "TMPDIR": "/tmp",
    "TZ": "UTC",
    "UV_NO_CONFIG": "1",
    "UV_NO_PROGRESS": "1",
    "UV_PYTHON_DOWNLOADS": "never",
}


def _activate_baseline_environment(root: Path) -> None:
    if importlib.util.find_spec("rfc8785") and importlib.util.find_spec("jsonschema"):
        return
    lib = root / ".venv/lib"
    try:
        candidates = [
            path / "site-packages"
            for path in lib.iterdir()
            if path.name.startswith("python") and (path / "site-packages").is_dir()
        ]
    except OSError as error:
        raise ValueError("E_ZERO_PARENT_BASELINE") from error
    if len(candidates) != 1 or candidates[0].is_symlink():
        raise ValueError("E_ZERO_PARENT_BASELINE")
    sys.path.insert(0, str(candidates[0]))


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _regular(path: Path) -> bytes:
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError("E_ZERO_PARENT_BASELINE") from error
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("E_ZERO_PARENT_BASELINE")
    return path.read_bytes()


def _relative(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    return value


def _object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(_regular(path))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_ZERO_PARENT_BASELINE") from error
    if not isinstance(value, dict):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    return cast(dict[str, object], value)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed Git executable and argv
        ["/usr/bin/git", "-C", str(root), *arguments], capture_output=True, env=ENVIRONMENT
    )
    if completed.returncode != 0:
        raise ValueError("E_ZERO_PARENT_BASELINE")
    return completed.stdout.decode().strip()


def _repository_identity(root: Path) -> tuple[str, str, str]:
    if root.is_symlink() or not (root / ".git").is_dir() or (root / ".git").is_symlink():
        raise ValueError("E_ZERO_PARENT_BASELINE")
    if (
        _git(root, "rev-parse", "--show-toplevel") != str(root)
        or _git(root, "rev-parse", "--show-object-format") != "sha1"
        or _git(root, "remote")
        or _git(root, "status", "--porcelain", "--untracked-files=all")
        or _git(root, "rev-list", "--count", "HEAD") != "1"
        or len(_git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()) != 1
    ):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    from tools.run_command_registry import collect_candidate_file_tree

    tree = collect_candidate_file_tree(root, allow_local_git=True)
    file_root = hashlib.sha256(b"HD636/BASELINE-FILE-ROOT/v1\0" + _canonical(tree)).hexdigest()
    return _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}"), file_root


def _registry(path: Path, root: Path) -> list[dict[str, object]]:
    record = _object(path)
    commands = record.get("commands")
    if (
        set(record) != {"schema_version", "commands", "runtime_root", "source_registry", "rule"}
        or record.get("schema_version") != "baseline-replay-command-registry/v1"
        or record.get("runtime_root") != str(root)
        or record.get("source_registry") != "pack/docs/registries/task-command-registry.v1.json"
        or not isinstance(record.get("rule"), str)
        or not isinstance(commands, list)
    ):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    _activate_baseline_environment(root)
    from tools.run_command_registry import candidate_commands, validate_registry

    source = candidate_commands(validate_registry(root / "task-command-registry.json"))
    if len(source) != 45 or len(commands) != len(source):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    result: list[dict[str, object]] = []
    required = {
        "command_id",
        "cwd",
        "argv",
        "purpose",
        "expected_exit",
        "available_at",
        "network",
        "authenticated_operator_access",
        "provider_access",
        "kind",
    }
    for original, baseline in zip(source, commands, strict=True):
        if not isinstance(baseline, dict) or set(baseline) != required:
            raise ValueError("E_ZERO_PARENT_BASELINE")
        original_cwd = original.get("cwd")
        if not isinstance(original_cwd, str):
            raise ValueError("E_ZERO_PARENT_BASELINE")
        expected_argv = [
            value.replace(original_cwd, str(root)).replace(
                AUTHORING_PACK, FINAL_PACK
            )
            for value in cast(list[str], original["argv"])
        ]
        if (
            baseline.get("command_id") != f"BASELINE__{original['command_id']}"
            or baseline.get("cwd") != str(root)
            or baseline.get("argv") != expected_argv
            or baseline.get("purpose") != f"Post-commit runtime replay of {original['command_id']}"
            or baseline.get("expected_exit") != original.get("expected_exit")
            or baseline.get("available_at") != original.get("available_at")
            or baseline.get("network") != "DENY"
            or baseline.get("authenticated_operator_access") != "DENY"
            or baseline.get("provider_access") != "DENY"
            or baseline.get("kind") != "baseline-verification"
        ):
            raise ValueError("E_ZERO_PARENT_BASELINE")
        result.append(cast(dict[str, object], baseline))
    return result


def _normative_source_set(pack: Path) -> tuple[str, str, str]:
    source_map_path = pack / "docs/registries/normative-source-map.v1.json"
    source_map_bytes = _regular(source_map_path)
    source_map = _object(source_map_path)
    inherited = source_map.get("inherited_entries")
    plan = source_map.get("plan_entries")
    if (
        source_map.get("schema_version") != "normative-source-map/v1"
        or source_map.get("owner_phase") != "MIG0"
        or not isinstance(inherited, list)
        or not isinstance(plan, list)
    ):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    entries: list[dict[str, str]] = []
    for entry in [*inherited, *plan]:
        if not isinstance(entry, dict):
            raise ValueError("E_ZERO_PARENT_BASELINE")
        source = _relative(entry.get("plan_source"))
        _relative(entry.get("vendor_relative"))
        contents = _regular(pack / source)
        digest = hashlib.sha256(contents).hexdigest()
        declared = entry.get("plan_sha256", entry.get("source_sha256"))
        if declared is not None and declared != digest:
            raise ValueError("E_ZERO_PARENT_BASELINE")
        entries.append({"path": source, "sha256": digest, "size": str(len(contents))})
    if len(entries) != len({entry["path"] for entry in entries}):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    entries.sort(key=lambda entry: entry["path"].encode())
    return (
        hashlib.sha256(source_map_bytes).hexdigest(),
        hashlib.sha256(b"HD636/NORMATIVE-SOURCE-SET/v1\0" + _canonical(entries)).hexdigest(),
        str(len(entries)),
    )


def _receipt(
    root: Path,
    candidate: Path,
    candidate_evidence: Path,
    registry: Path,
    results: list[dict[str, object]],
) -> dict[str, object]:
    from moj_discovery.pack_verifier import compute_vendor_tree_root
    from tools.build_candidate_qualification_receipt import validate_candidate_qualification_receipt
    from tools.verify_toolchains import EXPECTED, dependency_lock_hashes, verify_toolchains

    candidate_record = _object(candidate)
    validate_candidate_qualification_receipt(root, candidate_evidence, candidate_record)
    if verify_toolchains():
        raise ValueError("E_ZERO_PARENT_BASELINE")
    commit, tree, file_root = _repository_identity(root)
    map_hash, source_set_root, source_set_count = _normative_source_set(registry.parents[2])
    return {
        "schema_version": "repo0-baseline-receipt/v2",
        "production_authority": "NONE",
        "baseline_commit": commit,
        "baseline_tree": tree,
        "baseline_file_root_sha256": file_root,
        "candidate_qualification_sha256": hashlib.sha256(_regular(candidate)).hexdigest(),
        "candidate_command_evidence_sha256": hashlib.sha256(
            _regular(candidate_evidence)
        ).hexdigest(),
        "command_result_root": hashlib.sha256(
            b"HD636/BASELINE/RESULTS/v1\0" + _canonical(results)
        ).hexdigest(),
        "baseline_registry_sha256": hashlib.sha256(_regular(registry)).hexdigest(),
        "toolchain_versions": EXPECTED,
        "lockfile_hashes": dependency_lock_hashes(root),
        "vendor_root_sha256": compute_vendor_tree_root(root / "vendor/hybrid-discovery-v6.3.6"),
        "normative_source_map_sha256": map_hash,
        "normative_source_set_root": source_set_root,
        "normative_source_set_count": source_set_count,
    }


def verify_zero_parent_baseline(
    root: Path, receipt_path: Path, *, pack: Path | None = None
) -> dict[str, object]:
    from moj_discovery.pack_verifier import compute_vendor_tree_root
    from tools.verify_toolchains import EXPECTED, dependency_lock_hashes, verify_toolchains

    receipt = _object(receipt_path)
    pack_root = pack or receipt_path.parents[2]
    commit, tree, file_root = _repository_identity(root)
    map_hash, source_set_root, source_set_count = _normative_source_set(pack_root)
    required = {
        "schema_version",
        "production_authority",
        "baseline_commit",
        "baseline_tree",
        "baseline_file_root_sha256",
        "candidate_qualification_sha256",
        "candidate_command_evidence_sha256",
        "command_result_root",
        "baseline_registry_sha256",
        "toolchain_versions",
        "lockfile_hashes",
        "vendor_root_sha256",
        "normative_source_map_sha256",
        "normative_source_set_root",
        "normative_source_set_count",
    }
    hashes = (
        "baseline_file_root_sha256",
        "candidate_qualification_sha256",
        "candidate_command_evidence_sha256",
        "command_result_root",
        "baseline_registry_sha256",
        "vendor_root_sha256",
        "normative_source_map_sha256",
        "normative_source_set_root",
    )
    if (
        set(receipt) != required
        or receipt.get("schema_version") != "repo0-baseline-receipt/v2"
        or receipt.get("production_authority") != "NONE"
        or receipt.get("baseline_commit") != commit
        or receipt.get("baseline_tree") != tree
        or receipt.get("baseline_file_root_sha256") != file_root
        or receipt.get("toolchain_versions") != EXPECTED
        or receipt.get("lockfile_hashes") != dependency_lock_hashes(root)
        or receipt.get("vendor_root_sha256")
        != compute_vendor_tree_root(root / "vendor/hybrid-discovery-v6.3.6")
        or receipt.get("normative_source_map_sha256") != map_hash
        or receipt.get("normative_source_set_root") != source_set_root
        or receipt.get("normative_source_set_count") != source_set_count
        or any(
            not isinstance(receipt.get(field), str)
            or HEX.fullmatch(cast(str, receipt[field])) is None
            for field in hashes
        )
        or not isinstance(receipt.get("normative_source_set_count"), str)
        or not cast(str, receipt["normative_source_set_count"]).isdecimal()
    ):
        raise ValueError("E_ZERO_PARENT_BASELINE")
    if verify_toolchains():
        raise ValueError("E_ZERO_PARENT_BASELINE")
    return receipt


def qualify_zero_parent_baseline(
    root: Path,
    receipt: Path,
    registry: Path,
    *,
    candidate: Path = CANDIDATE_RECEIPT,
    candidate_evidence: Path = CANDIDATE_COMMAND_EVIDENCE,
) -> dict[str, object]:
    if receipt.exists() or receipt.is_symlink():
        raise ValueError("E_ZERO_PARENT_BASELINE")
    commands = _registry(registry, root)
    results: list[dict[str, object]] = []
    for command in commands:
        completed = subprocess.run(  # noqa: S603 - frozen validated argv
            cast(list[str], command["argv"]), capture_output=True, cwd=root, env=ENVIRONMENT
        )
        row: dict[str, object] = {
            "command_id": command["command_id"],
            "argv": command["argv"],
            "cwd": command["cwd"],
            "expected_exit": command["expected_exit"],
            "exit_code": completed.returncode,
            "passed": completed.returncode == command["expected_exit"],
            "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
            "stdout_size_bytes": str(len(completed.stdout)),
            "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
            "stderr_size_bytes": str(len(completed.stderr)),
        }
        if row["passed"] is not True:
            raise ValueError("E_ZERO_PARENT_BASELINE")
        results.append(row)
    record = _receipt(root, candidate, candidate_evidence, registry, results)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return verify_zero_parent_baseline(root, receipt, pack=registry.parents[2])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.check_only:
        if args.registry is not None:
            parser.error("--check-only does not accept --registry")
        result = verify_zero_parent_baseline(args.root, args.receipt)
    elif args.registry is None:
        parser.error("--registry is required when replaying the baseline")
    else:
        result = qualify_zero_parent_baseline(args.root, args.receipt, args.registry)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
