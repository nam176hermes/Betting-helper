import argparse
import hashlib
import io
import os
import re
import stat
import subprocess
import tempfile
import unicodedata
import uuid
import zlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

import rfc8785

from .canonical import parse_strict_json
from .errors import ContractNotImplementedError

FILE_TREE_DOMAIN = b"HYBRID-DISCOVERY/v6.2/Repo0IndependentFileTree/v1\0"
COMMAND_RESULT_DOMAIN = b"HYBRID-DISCOVERY/v6.2/Repo0CommandResultSet/v1\0"
RECEIPT_DOMAIN = b"HYBRID-DISCOVERY/v6.2/Repo0BaselineReceipt/v1\0"
RUNTIME_ROOT = Path("/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/runtime")
PACK_ROOT = Path("/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/pack")
COMMAND_RESULT_PATH = PACK_ROOT / "docs/receipts/repo0-command-results.json"
BASELINE_RECEIPT_PATH = PACK_ROOT / "docs/receipts/repo0-baseline-receipt.json"


def _valid_repo_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        value != ""
        and "\ufeff" not in value
        and "\\" not in value
        and "\0" not in value
        and unicodedata.normalize("NFC", value) == value
        and not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _json_equal_exact(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _json_equal_exact(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal_exact(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _validate_independent_file_tree(tree: object) -> dict[str, object]:
    if not isinstance(tree, dict) or set(tree) != {"entries", "schema_version"}:
        raise ValueError("E_REPO0_FILE_TREE_ENTRY")
    if tree["schema_version"] != "repo0-independent-file-tree/v1":
        raise ValueError("E_REPO0_FILE_TREE_ENTRY")
    entries = tree["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("E_REPO0_FILE_TREE_ENTRY")
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "entry_kind",
            "file_sha256",
            "git_mode",
            "gitlink",
            "hardlink",
            "path",
            "size_bytes",
            "symlink",
        }:
            raise ValueError("E_REPO0_FILE_TREE_ENTRY")
        path = entry["path"]
        size = entry["size_bytes"]
        digest = entry["file_sha256"]
        if (
            entry["entry_kind"] != "REGULAR_FILE"
            or entry["git_mode"] not in {"100644", "100755"}
            or entry["gitlink"] is not False
            or entry["hardlink"] is not False
            or entry["symlink"] is not False
            or not isinstance(path, str)
            or path == ".gitmodules"
            or not _valid_repo_path(path)
            or not isinstance(size, str)
            or not size.isdecimal()
            or (len(size) > 1 and size.startswith("0"))
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise ValueError("E_REPO0_FILE_TREE_ENTRY")
        paths.append(path)
    if paths != sorted(paths, key=lambda value: value.encode()) or len(paths) != len(set(paths)):
        raise ValueError("E_REPO0_FILE_TREE_ORDER")
    return cast(dict[str, object], tree)


def compute_independent_file_tree_root(tree: object) -> str:
    validated = _validate_independent_file_tree(tree)
    return hashlib.sha256(FILE_TREE_DOMAIN + rfc8785.dumps(cast(Any, validated))).hexdigest()


def compute_command_result_root(result_set: object) -> str:
    if not isinstance(result_set, dict):
        raise ValueError("E_REPO0_COMMAND_ROOT_INELIGIBLE")
    return hashlib.sha256(
        COMMAND_RESULT_DOMAIN + rfc8785.dumps(cast(Any, result_set))
    ).hexdigest()


def verify_imports(*, bootstrap_only: bool = False) -> bool:
    if not bootstrap_only:
        raise ContractNotImplementedError("R0-T01")
    return True


def validate_finding_coverage(*, bootstrap_only: bool = False) -> bool:
    if not bootstrap_only:
        raise ContractNotImplementedError("R0-T02")
    return True


def validate_spec_coverage(*, bootstrap_only: bool = False) -> bool:
    if not bootstrap_only:
        raise ContractNotImplementedError("R0-T06")
    return True


def _git_environment(root: Path) -> dict[str, str]:
    return {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(root),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
    }


def _git_output(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(  # noqa: S603 - fixed absolute Git executable
        ["/usr/bin/git", "-C", str(root), *arguments],
        capture_output=True,
        env=_git_environment(root),
    )
    if result.returncode != 0:
        raise ValueError("E_REPO0_GIT_STATE")
    return result.stdout


def _head_file_tree(root: Path) -> dict[str, object]:
    raw = _git_output(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    entries: list[dict[str, object]] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            metadata, raw_path = item.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("E_REPO0_FILE_TREE_ENTRY") from error
        if object_type != b"blob" or mode not in {b"100644", b"100755"}:
            raise ValueError("E_REPO0_FILE_TREE_ENTRY")
        if not _valid_repo_path(path) or path == ".gitmodules":
            raise ValueError("E_REPO0_FILE_TREE_ENTRY")
        content = _git_output(root, "cat-file", "blob", object_id.decode("ascii"))
        entries.append(
            {
                "entry_kind": "REGULAR_FILE",
                "file_sha256": hashlib.sha256(content).hexdigest(),
                "git_mode": mode.decode("ascii"),
                "gitlink": False,
                "hardlink": False,
                "path": path,
                "size_bytes": str(len(content)),
                "symlink": False,
            }
        )
    entries.sort(key=lambda entry: cast(str, entry["path"]).encode())
    tree: dict[str, object] = {
        "entries": entries,
        "schema_version": "repo0-independent-file-tree/v1",
    }
    _validate_independent_file_tree(tree)
    return tree


def compute_vendor_tree_root(vendor: Path) -> str:
    root = vendor.absolute()
    root_stat = root.lstat()
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("E_REPO0_VENDOR_TREE")
    files: list[tuple[str, int, str]] = []

    def visit(directory: Path) -> None:
        for entry in sorted(os.scandir(directory), key=lambda value: os.fsencode(value.name)):
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if not _valid_repo_path(relative):
                raise ValueError("E_REPO0_VENDOR_TREE")
            entry_stat = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(entry_stat.st_mode):
                raise ValueError("E_REPO0_VENDOR_TREE")
            if stat.S_ISDIR(entry_stat.st_mode):
                visit(path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode) or entry_stat.st_nlink != 1:
                raise ValueError("E_REPO0_VENDOR_TREE")
            if relative == "SCHEMA_SHA256.json":
                continue
            content = path.read_bytes()
            if len(content) != entry_stat.st_size:
                raise ValueError("E_REPO0_VENDOR_TREE")
            files.append((relative, len(content), hashlib.sha256(content).hexdigest()))

    visit(root)
    framed = b"".join(
        path.encode() + b"\0" + str(size).encode() + b"\0" + digest.encode() + b"\n"
        for path, size, digest in sorted(files, key=lambda value: value[0].encode())
    )
    return hashlib.sha256(framed).hexdigest()


def _read_jcs_record(path: Path, error: str) -> tuple[dict[str, object], bytes]:
    try:
        raw = path.read_bytes()
        parsed = parse_strict_json(raw)
    except (OSError, ValueError) as cause:
        raise ValueError(error) from cause
    if not isinstance(parsed, dict) or raw != rfc8785.dumps(cast(Any, parsed)) + b"\n":
        raise ValueError(error)
    return cast(dict[str, object], parsed), raw


def _verify_command_result_set(
    root: Path,
    result_set: dict[str, object],
    result_bytes: bytes,
) -> tuple[dict[str, object], str]:
    from tools.run_command_registry import (
        EXPECTED_EXECUTION_ENVIRONMENT,
        expand_invocations,
        validate_registry,
    )

    registry_path = root / "task-command-registry.json"
    registry = cast(dict[str, Any], validate_registry(registry_path))
    contract = cast(dict[str, Any], registry["baseline_result_contract"])
    required = {
        "additional_argv_invocation_count",
        "algorithm_id",
        "candidate_exclusion_policy_id",
        "completion_state",
        "domain",
        "execution_environment",
        "expanded_invocation_count",
        "inherit_parent_environment",
        "production_authority",
        "qualified_file_tree",
        "qualified_file_tree_root_sha256",
        "record_type",
        "registry_path",
        "registry_sha256",
        "results",
        "root_eligible",
        "schema_version",
        "task_invocation_count",
        "verification_invocation_count",
        "working_directory",
    }
    if set(result_set) != required:
        raise ValueError("E_REPO0_COMMAND_ROOT_INELIGIBLE")
    if (
        result_set["record_type"] != "Repo0CommandResultSet"
        or result_set["schema_version"] != "repo0-command-result-set/v1"
        or result_set["algorithm_id"] != "HD-REPO0-COMMAND-RESULTS-SHA256-v1"
        or result_set["domain"] != COMMAND_RESULT_DOMAIN.decode()
        or result_set["completion_state"] != "COMPLETE_ACCEPTED"
        or result_set["root_eligible"] is not True
        or result_set["production_authority"] != "NONE"
        or result_set["inherit_parent_environment"] is not False
        or result_set["execution_environment"] != EXPECTED_EXECUTION_ENVIRONMENT
        or result_set["working_directory"] != contract["working_directory"]
        or result_set["registry_path"] != "task-command-registry.json"
        or result_set["registry_sha256"]
        != hashlib.sha256(registry_path.read_bytes()).hexdigest()
        or result_set["candidate_exclusion_policy_id"] != "REPO0-CANDIDATE-EXCLUSIONS-v1"
        or result_set["verification_invocation_count"] != "41"
        or result_set["task_invocation_count"] != "60"
        or result_set["additional_argv_invocation_count"] != "9"
        or result_set["expanded_invocation_count"] != "101"
    ):
        raise ValueError("E_REPO0_COMMAND_CONTEXT")
    qualified_tree = _validate_independent_file_tree(result_set["qualified_file_tree"])
    qualified_root = compute_independent_file_tree_root(qualified_tree)
    if result_set["qualified_file_tree_root_sha256"] != qualified_root:
        raise ValueError("E_REPO0_QUALIFIED_TREE")
    results = result_set["results"]
    expanded = expand_invocations(registry, "baseline")
    if not isinstance(results, list) or len(results) != 101 or len(expanded) != 101:
        raise ValueError("E_REPO0_COMMAND_EXPANSION")
    for expected, actual in zip(expanded, results, strict=True):
        if not isinstance(actual, dict):
            raise ValueError("E_REPO0_COMMAND_EXPANSION")
        expected_keys = {
            "argv",
            "argv_ordinal",
            "contract_error_tokens",
            "disposition",
            "execution_state",
            "expectation",
            "expectation_matched",
            "exit_code",
            "invocation_id",
            "invocation_index",
            "owner_id",
            "owner_kind",
            "stderr_sha256",
            "stderr_size_bytes",
            "stdout_sha256",
            "stdout_size_bytes",
            "working_directory",
        }
        if set(actual) != expected_keys or any(
            not _json_equal_exact(actual.get(key), expected[key])
            for key in (
                "argv",
                "argv_ordinal",
                "expectation",
                "invocation_id",
                "invocation_index",
                "owner_id",
                "owner_kind",
            )
        ):
            raise ValueError("E_REPO0_COMMAND_EXPANSION")
        expectation = cast(dict[str, object], expected["expectation"])
        intentional = expectation["kind"] == "INTENTIONAL_RED"
        expected_tokens = [expectation["expected_contract_error"]] if intentional else []
        if (
            actual["execution_state"] != "COMPLETED"
            or actual["expectation_matched"] is not True
            or isinstance(actual["exit_code"], bool)
            or not isinstance(actual["exit_code"], int)
            or actual["exit_code"] != expectation["expected_exit_code"]
            or actual["working_directory"] != contract["working_directory"]
            or actual["contract_error_tokens"] != expected_tokens
            or actual["disposition"]
            != ("EXPECTED_CONTRACT_RED" if intentional else "PASS")
            or any(
                not isinstance(actual[field], str) or _SHA256.fullmatch(actual[field]) is None
                for field in ("stdout_sha256", "stderr_sha256")
            )
            or any(
                not isinstance(actual[field], str)
                or _UNSIGNED_INTEGER.fullmatch(actual[field]) is None
                for field in ("stdout_size_bytes", "stderr_size_bytes")
            )
        ):
            raise ValueError(
                "E_REPO0_CONTRACT_RED" if intentional else "E_REPO0_COMMAND_ROOT_INELIGIBLE"
            )
    if result_bytes != rfc8785.dumps(cast(Any, result_set)) + b"\n":
        raise ValueError("E_REPO0_COMMAND_ROOT_INELIGIBLE")
    return qualified_tree, compute_command_result_root(result_set)


def _repository_state(root: Path) -> dict[str, object]:
    top_level = _git_output(root, "rev-parse", "--show-toplevel").decode().rstrip("\n")
    if top_level != str(root):
        raise ValueError("E_REPO0_AMBIENT_GIT")
    if _git_output(root, "rev-parse", "--show-object-format").strip() != b"sha1":
        raise ValueError("E_REPO0_GIT_STATE")
    commit = _git_output(root, "rev-parse", "HEAD").decode().strip()
    tree_oid = _git_output(root, "rev-parse", "HEAD^{tree}").decode().strip()
    parents = _git_output(root, "rev-list", "--parents", "-n", "1", "HEAD").split()
    commit_count = int(_git_output(root, "rev-list", "--count", "HEAD").strip())
    remote_count = len(_git_output(root, "remote").splitlines())
    dirty = bool(_git_output(root, "status", "--porcelain=v1", "--untracked-files=all"))
    return {
        "commit": commit,
        "tree_oid": tree_oid,
        "parents": len(parents) - 1,
        "commit_count": commit_count,
        "remote_count": remote_count,
        "dirty": dirty,
        "head_tree": _head_file_tree(root),
    }


def _verify_repository_and_result(
    root: Path,
    command_result_path: Path,
    command_result: dict[str, object] | None,
) -> tuple[dict[str, object], bytes, dict[str, object], str, dict[str, object]]:
    if command_result_path.absolute().is_relative_to(root):
        raise ValueError("E_REPO0_RECEIPT_CYCLE")
    if command_result is None:
        result_set, result_bytes = _read_jcs_record(
            command_result_path, "E_REPO0_COMMAND_ROOT_INELIGIBLE"
        )
    else:
        result_set = command_result
        result_bytes = rfc8785.dumps(cast(Any, result_set)) + b"\n"
    qualified_tree, command_root = _verify_command_result_set(root, result_set, result_bytes)
    state = _repository_state(root)
    head_tree = cast(dict[str, object], state["head_tree"])
    if qualified_tree != head_tree:
        raise ValueError("E_REPO0_QUALIFIED_TREE")
    if (
        compute_independent_file_tree_root(head_tree)
        != result_set["qualified_file_tree_root_sha256"]
    ):
        raise ValueError("E_REPO0_QUALIFIED_TREE")
    from tools.run_command_registry import (
        collect_candidate_file_tree,
    )

    working_tree = collect_candidate_file_tree(root, allow_local_git=True)
    if working_tree != head_tree:
        raise ValueError("E_REPO0_QUALIFIED_TREE")
    if (
        state["commit_count"] != 1
        or state["parents"] != 0
        or state["remote_count"] != 0
        or state["dirty"] is not False
    ):
        raise ValueError("E_REPO0_GIT_STATE")
    return result_set, result_bytes, qualified_tree, command_root, state


def _receipt_content_hash(receipt: dict[str, object]) -> str:
    projected = dict(receipt)
    if "content_hash" not in projected:
        raise ValueError("E_REPO0_RECEIPT")
    del projected["content_hash"]
    return hashlib.sha256(RECEIPT_DOMAIN + rfc8785.dumps(cast(Any, projected))).hexdigest()


def _verify_receipt(
    root: Path,
    receipt: dict[str, object],
    receipt_bytes: bytes,
    result_bytes: bytes,
    qualified_tree: dict[str, object],
    command_root: str,
    state: dict[str, object],
) -> None:
    from tools.verify_toolchains import verify_toolchains

    required = {
        "record_type",
        "schema_version",
        "receipt_id",
        "receipt_id_allocation",
        "receipt_path",
        "git_object_format",
        "actual_git_commit_oid",
        "actual_git_tree_oid",
        "independent_file_tree_algorithm",
        "independent_file_tree_entry_count",
        "independent_file_tree_root_sha256",
        "toolchain_versions",
        "lockfile_hash_algorithm",
        "lockfile_hashes",
        "vendor_root_algorithm",
        "vendor_root_sha256",
        "command_result_algorithm",
        "command_result_manifest_path",
        "command_result_manifest_committed_in_baseline",
        "command_result_manifest_file_sha256",
        "command_registry_file_sha256",
        "command_result_invocation_count",
        "command_result_root_sha256",
        "baseline_commit_count",
        "parent_commit_count",
        "worktree_clean",
        "no_remote",
        "remote_count",
        "zero_parent_commit",
        "receipt_committed_in_baseline",
        "verified_at",
        "content_hash",
        "production_authority",
    }
    try:
        receipt_uuid = uuid.UUID(cast(str, receipt.get("receipt_id")))
    except (ValueError, AttributeError) as error:
        raise ValueError("E_REPO0_RECEIPT") from error
    timestamp = receipt.get("verified_at")
    valid_timestamp = False
    if isinstance(timestamp, str):
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            valid_timestamp = (
                parsed_timestamp.utcoffset() == UTC.utcoffset(parsed_timestamp)
                and parsed_timestamp.microsecond == 0
                and parsed_timestamp.isoformat().replace("+00:00", "Z") == timestamp
            )
        except ValueError:
            pass
    expected_toolchains = [
        {"toolchain": "Node", "version": "22.23.0"},
        {"toolchain": "pnpm", "version": "10.33.2"},
        {"toolchain": "Python", "version": "3.12.3"},
        {"toolchain": "uv", "version": "0.11.7"},
    ]
    lock_hashes = [
        {
            "path": "pnpm-lock.yaml",
            "sha256": hashlib.sha256((root / "pnpm-lock.yaml").read_bytes()).hexdigest(),
        },
        {
            "path": "uv.lock",
            "sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        },
    ]
    entries = cast(list[object], qualified_tree["entries"])
    if (
        set(receipt) != required
        or receipt["record_type"] != "Repo0BaselineReceipt"
        or receipt["schema_version"] != "repo0-baseline-receipt/v1"
        or receipt_uuid.version != 4
        or str(receipt_uuid) != receipt["receipt_id"]
        or receipt["receipt_id_allocation"] != "UUID_V4_INDEPENDENT_OF_CONTENT_HASH"
        or receipt["receipt_path"] != "docs/receipts/repo0-baseline-receipt.json"
        or receipt["git_object_format"] != "sha1"
        or receipt["actual_git_commit_oid"] != state["commit"]
        or receipt["actual_git_tree_oid"] != state["tree_oid"]
        or receipt["independent_file_tree_algorithm"] != "HD-REPO0-FILE-TREE-SHA256-v1"
        or receipt["independent_file_tree_entry_count"] != str(len(entries))
        or receipt["independent_file_tree_root_sha256"]
        != compute_independent_file_tree_root(qualified_tree)
        or receipt["toolchain_versions"] != expected_toolchains
        or verify_toolchains()
        or receipt["lockfile_hash_algorithm"] != "SHA-256-RAW-BYTES"
        or receipt["lockfile_hashes"] != lock_hashes
        or receipt["vendor_root_algorithm"] != "HD-VENDOR-TREE-SHA256-v1"
        or receipt["vendor_root_sha256"]
        != compute_vendor_tree_root(root / "vendor/hybrid-discovery-v6.3.6")
        or receipt["command_result_algorithm"] != "HD-REPO0-COMMAND-RESULTS-SHA256-v1"
        or receipt["command_result_manifest_path"] != "docs/receipts/repo0-command-results.json"
        or receipt["command_result_manifest_committed_in_baseline"] is not False
        or receipt["command_result_manifest_file_sha256"]
        != hashlib.sha256(result_bytes).hexdigest()
        or receipt["command_registry_file_sha256"]
        != hashlib.sha256((root / "task-command-registry.json").read_bytes()).hexdigest()
        or receipt["command_result_invocation_count"] != "101"
        or receipt["command_result_root_sha256"] != command_root
        or isinstance(receipt["baseline_commit_count"], bool)
        or not isinstance(receipt["baseline_commit_count"], int)
        or receipt["baseline_commit_count"] != 1
        or isinstance(receipt["parent_commit_count"], bool)
        or not isinstance(receipt["parent_commit_count"], int)
        or receipt["parent_commit_count"] != 0
        or receipt["worktree_clean"] is not True
        or receipt["no_remote"] is not True
        or isinstance(receipt["remote_count"], bool)
        or not isinstance(receipt["remote_count"], int)
        or receipt["remote_count"] != 0
        or receipt["zero_parent_commit"] is not True
        or receipt["receipt_committed_in_baseline"] is not False
        or not valid_timestamp
        or receipt["production_authority"] != "NONE"
        or receipt["content_hash"] != _receipt_content_hash(receipt)
        or receipt_bytes != rfc8785.dumps(cast(Any, receipt)) + b"\n"
    ):
        raise ValueError("E_REPO0_RECEIPT")


def _verify_inherited_repository_baseline(
    root: Path,
    receipt: dict[str, object] | None = None,
    *,
    receipt_path: Path = BASELINE_RECEIPT_PATH,
    command_result: dict[str, object] | None = None,
    command_result_path: Path = COMMAND_RESULT_PATH,
) -> list[str]:
    root = root.absolute()
    try:
        root_stat = root.lstat()
    except OSError:
        return ["E_BASELINE:NO_GIT"]
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        return ["E_REPO0_AMBIENT_GIT"]
    local_git = root / ".git"
    try:
        git_stat = local_git.lstat()
    except OSError:
        ambient = subprocess.run(  # noqa: S603 - fixed absolute Git executable
            ["/usr/bin/git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            env=_git_environment(root),
        )
        return ["E_REPO0_AMBIENT_GIT" if ambient.returncode == 0 else "E_BASELINE:NO_GIT"]
    if stat.S_ISLNK(git_stat.st_mode) or not stat.S_ISDIR(git_stat.st_mode):
        return ["E_REPO0_AMBIENT_GIT"]
    result_present = command_result is not None or command_result_path.exists()
    receipt_present = receipt is not None or receipt_path.exists()
    if not result_present or (receipt_present and not result_present):
        return ["E_REPO0_PRESENCE_STATE"]
    try:
        result_set, result_bytes, qualified_tree, command_root, state = (
            _verify_repository_and_result(root, command_result_path, command_result)
        )
        del result_set
        if not receipt_present:
            return []
        if receipt_path.absolute().is_relative_to(root):
            raise ValueError("E_REPO0_RECEIPT_CYCLE")
        if receipt is None:
            receipt_record, receipt_bytes = _read_jcs_record(receipt_path, "E_REPO0_RECEIPT")
        else:
            receipt_record = receipt
            receipt_bytes = rfc8785.dumps(cast(Any, receipt)) + b"\n"
        _verify_receipt(
            root,
            receipt_record,
            receipt_bytes,
            result_bytes,
            qualified_tree,
            command_root,
            state,
        )
    except (OSError, UnicodeError, ValueError) as error:
        return [str(error)]
    return []


def _build_repo0_baseline_receipt(
    root: Path,
    accepted_result_set: Path,
) -> dict[str, object]:
    receipt_path = accepted_result_set.with_name("repo0-baseline-receipt.json")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("E_REPO0_RECEIPT_EXISTS")
    errors = _verify_inherited_repository_baseline(
        root,
        receipt_path=receipt_path,
        command_result_path=accepted_result_set,
    )
    if errors:
        raise ValueError(errors[0])
    result_set, result_bytes = _read_jcs_record(
        accepted_result_set, "E_REPO0_COMMAND_ROOT_INELIGIBLE"
    )
    qualified_tree, command_root = _verify_command_result_set(root, result_set, result_bytes)
    state = _repository_state(root)
    entries = cast(list[object], qualified_tree["entries"])
    receipt: dict[str, object] = {
        "record_type": "Repo0BaselineReceipt",
        "schema_version": "repo0-baseline-receipt/v1",
        "receipt_id": str(uuid.uuid4()),
        "receipt_id_allocation": "UUID_V4_INDEPENDENT_OF_CONTENT_HASH",
        "receipt_path": "docs/receipts/repo0-baseline-receipt.json",
        "git_object_format": "sha1",
        "actual_git_commit_oid": state["commit"],
        "actual_git_tree_oid": state["tree_oid"],
        "independent_file_tree_algorithm": "HD-REPO0-FILE-TREE-SHA256-v1",
        "independent_file_tree_entry_count": str(len(entries)),
        "independent_file_tree_root_sha256": compute_independent_file_tree_root(qualified_tree),
        "toolchain_versions": [
            {"toolchain": "Node", "version": "22.23.0"},
            {"toolchain": "pnpm", "version": "10.33.2"},
            {"toolchain": "Python", "version": "3.12.3"},
            {"toolchain": "uv", "version": "0.11.7"},
        ],
        "lockfile_hash_algorithm": "SHA-256-RAW-BYTES",
        "lockfile_hashes": [
            {
                "path": "pnpm-lock.yaml",
                "sha256": hashlib.sha256((root / "pnpm-lock.yaml").read_bytes()).hexdigest(),
            },
            {
                "path": "uv.lock",
                "sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
            },
        ],
        "vendor_root_algorithm": "HD-VENDOR-TREE-SHA256-v1",
        "vendor_root_sha256": compute_vendor_tree_root(
            root / "vendor/hybrid-discovery-v6.3.6"
        ),
        "command_result_algorithm": "HD-REPO0-COMMAND-RESULTS-SHA256-v1",
        "command_result_manifest_path": "docs/receipts/repo0-command-results.json",
        "command_result_manifest_committed_in_baseline": False,
        "command_result_manifest_file_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "command_registry_file_sha256": hashlib.sha256(
            (root / "task-command-registry.json").read_bytes()
        ).hexdigest(),
        "command_result_invocation_count": "101",
        "command_result_root_sha256": command_root,
        "baseline_commit_count": 1,
        "parent_commit_count": 0,
        "worktree_clean": True,
        "no_remote": True,
        "remote_count": 0,
        "zero_parent_commit": True,
        "receipt_committed_in_baseline": False,
        "verified_at": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "content_hash": "",
        "production_authority": "NONE",
    }
    receipt["content_hash"] = _receipt_content_hash(receipt)
    return receipt


def build_repo0_baseline_receipt(
    root: Path,
    accepted_result_set: Path,
) -> dict[str, object]:
    if root.absolute() != RUNTIME_ROOT or accepted_result_set.absolute() != COMMAND_RESULT_PATH:
        raise ValueError("E_REPO0_RECEIPT_PATH")
    return _build_repo0_baseline_receipt(root.absolute(), accepted_result_set.absolute())


def _write_repo0_baseline_receipt(path: Path, receipt: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("E_REPO0_RECEIPT_EXISTS")
    content = rfc8785.dumps(cast(Any, receipt)) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    replaced = False
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary_stat = temporary.lstat()
        if not stat.S_ISREG(temporary_stat.st_mode) or temporary_stat.st_nlink != 1:
            raise ValueError("E_REPO0_RECEIPT_WRITE")
        os.replace(temporary, path)
        replaced = True
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if path.read_bytes() != content:
            raise ValueError("E_REPO0_RECEIPT_WRITE")
    except Exception:
        if replaced:
            path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def write_repo0_baseline_receipt(path: Path, receipt: dict[str, object]) -> None:
    if path.absolute() != BASELINE_RECEIPT_PATH:
        raise ValueError("E_REPO0_RECEIPT_PATH")
    _write_repo0_baseline_receipt(path.absolute(), receipt)


def verify_repository_baseline(
    root: Path,
    receipt: dict[str, object] | None = None,
    *,
    receipt_path: Path = BASELINE_RECEIPT_PATH,
    command_result: dict[str, object] | None = None,
    command_result_path: Path = COMMAND_RESULT_PATH,
) -> list[str]:
    """Verify only the current v6.3.6 external receipt contract.

    The historical command-result API above remains for immutable archive fixtures;
    it cannot grant qualification to a successor runtime.
    """
    del command_result_path
    root = root.absolute()
    try:
        root_stat = root.lstat()
    except OSError:
        return ["E_BASELINE:NO_GIT"]
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        return ["E_REPO0_AMBIENT_GIT"]
    local_git = root / ".git"
    if not local_git.is_dir() or local_git.is_symlink():
        ambient = subprocess.run(  # noqa: S603 - fixed absolute Git executable
            ["/usr/bin/git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            env=_git_environment(root),
        )
        return ["E_REPO0_AMBIENT_GIT" if ambient.returncode == 0 else "E_BASELINE:NO_GIT"]
    if command_result is not None or receipt is not None:
        return ["E_REPO0_LEGACY_RESULT"]
    if not receipt_path.exists() or receipt_path.is_symlink():
        return ["E_REPO0_PRESENCE_STATE"]
    if receipt_path.absolute().is_relative_to(root):
        return ["E_REPO0_RECEIPT_CYCLE"]
    try:
        from tools.qualify_zero_parent_baseline import verify_zero_parent_baseline

        verify_zero_parent_baseline(root, receipt_path.absolute())
    except (OSError, ValueError) as error:
        return [str(error)]
    return []


PACK_DIRECTORY_NAME = "hybrid-discovery-v6.2"
ARCHIVE_BASENAME = f"{PACK_DIRECTORY_NAME}.zip"
MANIFEST_PATH = "MANIFEST_SHA256.json"
SIDECAR_SUFFIX = ".sha256"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_EXTERNAL_ATTR = (stat.S_IFREG | 0o644) << 16
MAX_MANIFEST_SIZE_BYTES = 9_007_199_254_740_991
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UNSIGNED_INTEGER = re.compile(r"(?:0|[1-9][0-9]{0,39})")
_PORTABLE_PATH = re.compile(r"[A-Za-z0-9._/-]+")


def _source_files(pack: Path) -> dict[str, bytes]:
    try:
        root_stat = pack.lstat()
    except OSError as error:
        raise ValueError("E_PACK:SOURCE_TYPE") from error
    if pack.name != PACK_DIRECTORY_NAME or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("E_PACK:SOURCE_TYPE")

    files: dict[str, bytes] = {}

    def visit(directory: Path, prefix: PurePosixPath | None = None) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            raise ValueError("E_PACK:SOURCE_TYPE") from error
        for entry in sorted(entries, key=lambda value: os.fsencode(value.name)):
            relative_text = (
                entry.name if prefix is None else f"{prefix.as_posix()}/{entry.name}"
            )
            relative = _safe_relative_path(relative_text)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ValueError("E_PACK:SOURCE_TYPE") from error
            if stat.S_ISLNK(entry_stat.st_mode):
                raise ValueError("E_PACK:SOURCE_TYPE")
            if stat.S_ISDIR(entry_stat.st_mode):
                visit(Path(entry.path), relative)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise ValueError("E_PACK:SOURCE_TYPE")
            if entry_stat.st_nlink != 1:
                raise ValueError("E_PACK:SOURCE_HARDLINK")
            try:
                content = Path(entry.path).read_bytes()
            except OSError as error:
                raise ValueError("E_PACK:SOURCE_TYPE") from error
            if len(content) != entry_stat.st_size:
                raise ValueError("E_PACK:SOURCE_CHANGED")
            files[relative.as_posix()] = content

    visit(pack)
    return files


def _verify_pack(pack: Path) -> dict[str, bytes]:
    source_files = _source_files(pack)
    manifest_bytes = source_files.get(MANIFEST_PATH)
    if manifest_bytes is None:
        raise ValueError("E_PACK:MANIFEST")
    try:
        manifest = parse_strict_json(manifest_bytes)
    except ValueError as error:
        raise ValueError("E_PACK:MANIFEST") from error
    required = {
        "schema_version",
        "pack_version",
        "pack_hash",
        "implementation_baseline_hash",
        "files",
        "self_excluded_path",
        "production_authority",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError("E_PACK:MANIFEST")
    if (
        manifest["schema_version"] != "pack-manifest/v1"
        or manifest["pack_version"] != "6.2"
        or manifest["self_excluded_path"] != MANIFEST_PATH
        or manifest["production_authority"] != "NONE"
        or not isinstance(manifest["pack_hash"], str)
        or _SHA256.fullmatch(manifest["pack_hash"]) is None
        or not isinstance(manifest["implementation_baseline_hash"], str)
        or _SHA256.fullmatch(manifest["implementation_baseline_hash"]) is None
        or not isinstance(manifest["files"], list)
        or not manifest["files"]
        or len(manifest["files"]) > 4096
    ):
        raise ValueError("E_PACK:MANIFEST")
    declared: dict[str, tuple[int, str]] = {}
    declared_order: list[str] = []
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
            raise ValueError("E_PACK:MANIFEST")
        path_value = item["path"]
        size = item["size_bytes"]
        digest = item["sha256"]
        if (
            not isinstance(path_value, str)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or size > MAX_MANIFEST_SIZE_BYTES
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise ValueError("E_PACK:MANIFEST")
        relative = _safe_relative_path(path_value).as_posix()
        if relative == MANIFEST_PATH:
            raise ValueError("E_PACK:MANIFEST_SELF_REFERENCE")
        if relative in declared:
            raise ValueError("E_PACK:MANIFEST_DUPLICATE")
        declared[relative] = (size, digest)
        declared_order.append(relative)
    if manifest_bytes != rfc8785.dumps(manifest) + b"\n":
        raise ValueError("E_PACK:MANIFEST_SERIALIZATION")
    if declared_order != sorted(declared_order, key=lambda value: value.encode("utf-8")):
        raise ValueError("E_PACK:MANIFEST_ORDER")

    actual_paths = set(source_files) - {MANIFEST_PATH}
    if set(declared) != actual_paths:
        raise ValueError("E_PACK:MANIFEST_FILE_SET")
    for relative, (size, digest) in declared.items():
        content = source_files[relative]
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"E_PACK:FILE:{relative}")

    tree_preimage = b"".join(
        relative.encode("utf-8")
        + b"\0"
        + str(declared[relative][0]).encode("ascii")
        + b"\0"
        + declared[relative][1].encode("ascii")
        + b"\n"
        for relative in declared_order
    )
    if hashlib.sha256(tree_preimage).hexdigest() != manifest["pack_hash"]:
        raise ValueError("E_PACK:MANIFEST_HASH")
    return source_files


def write_pack_manifest(pack: Path, baseline_receipt: Path) -> str:
    if pack.name != PACK_DIRECTORY_NAME or baseline_receipt != (
        pack / "docs/receipts/repo0-baseline-receipt.json"
    ):
        raise ValueError("E_PACK:MANIFEST_PATH")
    manifest_path = pack / MANIFEST_PATH
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("E_PACK:MANIFEST_EXISTS")
    receipt = parse_strict_json(baseline_receipt.read_bytes())
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != "repo0-baseline-receipt/v1"
        or not isinstance(receipt.get("independent_file_tree_root_sha256"), str)
        or _SHA256.fullmatch(receipt["independent_file_tree_root_sha256"]) is None
        or receipt.get("production_authority") != "NONE"
    ):
        raise ValueError("E_PACK:BASELINE_RECEIPT")
    source_files = _source_files(pack)
    files: list[dict[str, object]] = []
    tree_items: list[bytes] = []
    for relative in sorted(source_files, key=lambda value: value.encode("utf-8")):
        content = source_files[relative]
        digest = hashlib.sha256(content).hexdigest()
        files.append({"path": relative, "sha256": digest, "size_bytes": len(content)})
        tree_items.append(
            relative.encode("utf-8")
            + b"\0"
            + str(len(content)).encode("ascii")
            + b"\0"
            + digest.encode("ascii")
            + b"\n"
        )
    manifest = {
        "files": files,
        "implementation_baseline_hash": receipt["independent_file_tree_root_sha256"],
        "pack_hash": hashlib.sha256(b"".join(tree_items)).hexdigest(),
        "pack_version": "6.2",
        "production_authority": "NONE",
        "schema_version": "pack-manifest/v1",
        "self_excluded_path": MANIFEST_PATH,
    }
    _atomic_write(manifest_path, rfc8785.dumps(cast(Any, manifest)) + b"\n")
    _verify_pack(pack)
    return cast(str, manifest["pack_hash"])


def _safe_relative_path(value: str) -> PurePosixPath:
    if (
        "\\" in value
        or "\0" in value
        or unicodedata.normalize("NFC", value) != value
        or _PORTABLE_PATH.fullmatch(value) is None
    ):
        raise ValueError("E_PACK:ARCHIVE_PATH")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("E_PACK:ARCHIVE_PATH")
    return path


def _archive_bytes(pack: Path, expected: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED, allowZip64=False) as zipped:
        for relative in sorted(expected, key=lambda value: value.encode("utf-8")):
            info = ZipInfo(f"{pack.name}/{relative}", ZIP_TIMESTAMP)
            info.compress_type = ZIP_STORED
            info.create_system = 3
            info.create_version = 20
            info.extract_version = 20
            info.flag_bits = 0
            info.internal_attr = 0
            info.external_attr = ZIP_EXTERNAL_ATTR
            info.volume = 0
            info.extra = b""
            info.comment = b""
            zipped.writestr(info, expected[relative])
    return output.getvalue()


def build_pack_archive(pack: Path, archive: Path) -> str:
    if archive.name != ARCHIVE_BASENAME:
        raise ValueError("E_PACK:ARCHIVE_NAME")
    resolved_pack = pack.resolve()
    resolved_archive = archive.resolve()
    if resolved_archive == resolved_pack or resolved_pack in resolved_archive.parents:
        raise ValueError("E_PACK:ARCHIVE_PATH")
    expected = _verify_pack(pack)
    content = _archive_bytes(pack, expected)
    digest = hashlib.sha256(content).hexdigest()
    _atomic_write(archive, content)
    _atomic_write(
        archive.with_name(archive.name + SIDECAR_SUFFIX),
        f"{digest}  {archive.name}\n".encode("ascii"),
    )
    verify_pack_archive(pack, archive)
    return digest


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_pack_archive(pack: Path, archive: Path) -> None:
    if archive.name != ARCHIVE_BASENAME:
        raise ValueError("E_PACK:ARCHIVE_NAME")
    expected = _verify_pack(pack)
    try:
        archive_stat = archive.lstat()
    except OSError as error:
        raise ValueError("E_PACK:ARCHIVE_FORMAT") from error
    if not stat.S_ISREG(archive_stat.st_mode) or archive_stat.st_nlink != 1:
        raise ValueError("E_PACK:ARCHIVE_FORMAT")
    try:
        archive_bytes = archive.read_bytes()
    except OSError as error:
        raise ValueError("E_PACK:ARCHIVE_FORMAT") from error
    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    sidecar = archive.with_name(archive.name + SIDECAR_SUFFIX)
    expected_sidecar = f"{archive_digest}  {archive.name}\n".encode("ascii")
    try:
        sidecar_stat = sidecar.lstat()
        sidecar_bytes = sidecar.read_bytes()
    except OSError as error:
        raise ValueError("E_PACK:SIDECAR") from error
    if (
        not stat.S_ISREG(sidecar_stat.st_mode)
        or sidecar_stat.st_nlink != 1
        or sidecar_bytes != expected_sidecar
    ):
        raise ValueError("E_PACK:SIDECAR")

    archived: dict[str, bytes] = {}
    try:
        with ZipFile(io.BytesIO(archive_bytes)) as zipped:
            if zipped.comment:
                raise ValueError("E_PACK:ARCHIVE_METADATA")
            seen_names: set[str] = set()
            expected_names = [
                f"{PACK_DIRECTORY_NAME}/{relative}"
                for relative in sorted(expected, key=lambda value: value.encode("utf-8"))
            ]
            relative_names: dict[str, str] = {}
            for info in zipped.infolist():
                if info.filename in seen_names:
                    raise ValueError("E_PACK:ARCHIVE_DUPLICATE")
                seen_names.add(info.filename)
                if info.is_dir():
                    raise ValueError("E_PACK:ARCHIVE_FILE_SET")
                archive_path = _safe_relative_path(info.filename)
                if not archive_path.parts or archive_path.parts[0] != PACK_DIRECTORY_NAME:
                    raise ValueError("E_PACK:ARCHIVE_PATH")
                relative = PurePosixPath(*archive_path.parts[1:])
                if not relative.parts:
                    raise ValueError("E_PACK:ARCHIVE_PATH")
                relative_names[info.filename] = relative.as_posix()
            if [info.filename for info in zipped.infolist()] != expected_names:
                raise ValueError("E_PACK:ARCHIVE_FILE_SET")

            for info in zipped.infolist():
                relative_name = relative_names[info.filename]
                if (
                    info.date_time != ZIP_TIMESTAMP
                    or info.compress_type != ZIP_STORED
                    or info.create_system != 3
                    or info.create_version != 20
                    or info.extract_version != 20
                    or info.flag_bits != 0
                    or info.internal_attr != 0
                    or info.external_attr != ZIP_EXTERNAL_ATTR
                    or info.volume != 0
                    or info.extra
                    or info.comment
                ):
                    raise ValueError("E_PACK:ARCHIVE_METADATA")
                expected_content = expected.get(relative_name)
                if expected_content is None:
                    raise ValueError("E_PACK:ARCHIVE_FILE_SET")
                expected_crc = zlib.crc32(expected_content) & 0xFFFFFFFF
                if (
                    info.file_size != len(expected_content)
                    or info.compress_size != len(expected_content)
                    or expected_crc != info.CRC
                ):
                    raise ValueError("E_PACK:ARCHIVE_INTEGRITY")
                archived[relative_name] = zipped.read(info)
    except (BadZipFile, RuntimeError, zlib.error) as error:
        raise ValueError("E_PACK:ARCHIVE_FORMAT") from error
    if set(archived) != set(expected):
        raise ValueError("E_PACK:ARCHIVE_FILE_SET")
    if any(archived[name] != content for name, content in expected.items()):
        raise ValueError("E_PACK:ARCHIVE_BYTES")
    if archive_bytes != _archive_bytes(pack, expected):
        raise ValueError("E_PACK:ARCHIVE_REBUILD")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--pack", type=Path, required=True)
    build.add_argument("--archive", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--pack", type=Path, required=True)
    verify.add_argument("--archive", type=Path)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--pack", type=Path, required=True)
    manifest.add_argument("--baseline-receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build_pack_archive(args.pack, args.archive)
    elif args.command == "manifest":
        write_pack_manifest(args.pack, args.baseline_receipt)
    elif args.archive is None:
        _verify_pack(args.pack)
    else:
        verify_pack_archive(args.pack, args.archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
