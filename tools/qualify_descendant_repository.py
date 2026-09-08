"""Issue or verify the clean descendant repository qualification receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import NoReturn, cast

from moj_discovery.pack_verifier import compute_vendor_tree_root
from tools.build_candidate_qualification_receipt import (
    _inventory,
    _read_bytes,
    _read_evidence,
    validate_candidate_qualification_receipt,
)
from tools.full_verifier_config import FullVerifierConfig, load_controller_config
from tools.qualify_zero_parent_baseline import _normative_source_set
from tools.retained_artifact_io import RetainedArtifactIO
from tools.verify_toolchains import EXPECTED, dependency_lock_hashes, verify_toolchains


def _fail() -> NoReturn:
    raise ValueError("E_DESCENDANT_REPOSITORY")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _git(root: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        _fail()
    completed = subprocess.run(  # noqa: S603 - resolved Git, fixed read-only operations.
        [git, "-C", str(root), *args], capture_output=True, check=False, timeout=30
    )
    if completed.returncode != 0:
        _fail()
    return completed.stdout.decode().strip()


def descendant_repository_identity(root: Path, audited_ancestor: str) -> dict[str, str]:
    if (
        not root.is_absolute()
        or root != root.resolve()
        or root.is_symlink()
        or not root.is_dir()
        or re.fullmatch(r"[0-9a-f]{40}", audited_ancestor) is None
        or _git(root, "rev-parse", "--show-toplevel") != str(root.resolve())
        or _git(root, "rev-parse", "--show-object-format") != "sha1"
    ):
        _fail()
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if head == audited_ancestor:
        _fail()
    git = shutil.which("git")
    assert git is not None
    ancestor = subprocess.run(  # noqa: S603 - resolved Git, fixed read-only operation.
        [git, "-C", str(root), "merge-base", "--is-ancestor", audited_ancestor, head],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if ancestor.returncode != 0:
        _fail()
    try:
        inventory = _inventory(root)
    except ValueError as error:
        raise ValueError("E_DESCENDANT_REPOSITORY") from error
    return {
        "repository_commit": head,
        "repository_tree": tree,
        "repository_file_root_sha256": hashlib.sha256(
            b"HD636/DESCENDANT-FILE-ROOT/v1\0" + _canonical(inventory)
        ).hexdigest(),
    }


def _regular_hash(path: Path, artifacts: RetainedArtifactIO | None = None) -> str:
    return hashlib.sha256(_read_bytes(path, artifacts)).hexdigest()


def _validate_issuance(config: FullVerifierConfig, artifacts: RetainedArtifactIO | None) -> None:
    """The controller's P07 T03 record binds the actual declared invocation."""
    record = _read_evidence(config.candidate_issuance_evidence, artifacts)
    registry = _read_evidence(config.current_checkout_root / "task-command-registry.json")
    rows = registry.get("commands")
    if not isinstance(rows, list):
        _fail()
    declared = next(
        (
            row
            for row in rows
            if isinstance(row, dict) and row.get("command_id") == "VERIFY_V636_P07_T03"
        ),
        None,
    )
    if declared is None:
        _fail()
    command = record.get("command")
    if (
        set(record)
        != {
            "schema_version",
            "result",
            "production_authority",
            "controller_binding",
            "command",
            "proof_coverage_sha256",
        }
        or record.get("schema_version") != "candidate-issuance-result/v1"
        or record.get("result") != "PASS"
        or record.get("production_authority") != "NONE"
        or record.get("controller_binding") != config.binding()
        or record.get("proof_coverage_sha256")
        != hashlib.sha256(_read_bytes(config.proof_coverage_evidence, artifacts)).hexdigest()
        or not isinstance(command, dict)
        or set(command)
        != {
            "command_id",
            "argv",
            "cwd",
            "expected_exit",
            "exit_code",
            "passed",
            "stdout_sha256",
            "stderr_sha256",
            "stdout_size_bytes",
            "stderr_size_bytes",
        }
        or any(
            command[key] != declared[key] for key in ("command_id", "argv", "cwd", "expected_exit")
        )
        or command["cwd"] != str(config.current_checkout_root)
        or type(command["exit_code"]) is not int
        or command["exit_code"] != 0
        or type(command["expected_exit"]) is not int
        or command["expected_exit"] != 0
        or command["passed"] is not True
    ):
        _fail()
    for stream in ("stdout", "stderr"):
        if (
            not isinstance(command[stream + "_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", command[stream + "_sha256"]) is None
            or not isinstance(command[stream + "_size_bytes"], str)
            or re.fullmatch(r"0|[1-9][0-9]*", command[stream + "_size_bytes"]) is None
        ):
            _fail()


def _validated_context(
    root: Path, config: FullVerifierConfig, artifacts: RetainedArtifactIO | None = None
) -> None:
    try:
        if (
            not isinstance(config, FullVerifierConfig)
            or config.schema_version != "full-verifier-controller/v2"
            or config.audited_runtime_ancestor is None
            or config.qualification_evidence is None
            or config.descendant_repository_receipt is None
            or root != root.resolve()
            or root != config.current_checkout_root
        ):
            _fail()
        if artifacts is None:
            reloaded = load_controller_config(config.source_path)
        else:
            recorded = str(config.source_path)
            physical = artifacts.physical_path(
                recorded, recorded_boundary=artifacts.recorded_boundary(recorded)
            )
            reloaded = load_controller_config(
                physical, mode="SEALED", artifacts=artifacts, recorded_locator=recorded
            )
        if reloaded != config:
            _fail()
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError("E_DESCENDANT_REPOSITORY") from error


def _receipt_record(
    root: Path,
    config: FullVerifierConfig,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, object]:
    try:
        _validated_context(root, config, artifacts)
        return _capture_receipt_record(root, config, artifacts)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        raise ValueError("E_DESCENDANT_REPOSITORY") from error


def _capture_receipt_record(
    root: Path, config: FullVerifierConfig, artifacts: RetainedArtifactIO | None
) -> dict[str, object]:
    if (
        config.schema_version != "full-verifier-controller/v2"
        or config.audited_runtime_ancestor is None
        or config.qualification_evidence is None
    ):
        _fail()
    _validate_issuance(config, artifacts)
    identity = descendant_repository_identity(root, config.audited_runtime_ancestor)
    candidate = _read_evidence(config.candidate_qualification_receipt, artifacts)
    validate_candidate_qualification_receipt(
        root,
        config.candidate_command_evidence,
        candidate,
        config,
        artifacts=artifacts,
    )
    if verify_toolchains():
        _fail()
    source_map, source_root, source_count = _normative_source_set(
        config.governed_source_pack, artifacts=artifacts
    )
    from tools.run_environment_qualification import verify_environment_qualification_evidence
    from tools.verify_full_repair_qualification import verify_full_repair_qualification

    qualification = config.qualification_evidence
    assert qualification is not None

    def mapped(path: Path) -> Path:
        if artifacts is None:
            return path
        recorded = str(path)
        return artifacts.physical_path(
            recorded, recorded_boundary=artifacts.recorded_boundary(recorded)
        )

    full_proof = verify_full_repair_qualification(
        mapped(qualification.full_repair_aggregate),
        mapped(qualification.full_repair_inventory),
        config,
        artifacts=artifacts,
    )
    p03 = _read_evidence(config.qualification_evidence.p03_proof, artifacts)
    p04 = _read_evidence(config.qualification_evidence.p04_proof, artifacts)
    environment = verify_environment_qualification_evidence(
        qualification.environment_qualification_aggregate,
        qualification.environment_qualification_inventory,
        config,
        artifacts=artifacts,
    )
    if (
        p03
        != {
            **full_proof,
            "schema_version": "full-repair-qualification/v1",
            "clock_proof_pending": True,
        }
        or p04 != full_proof
    ):
        _fail()
    candidate_inventory = candidate.get("inventory")
    if not isinstance(candidate_inventory, dict):
        _fail()
    return {
        "schema_version": "descendant-repository-qualification-receipt/v1",
        "repository_identity_kind": "DESCENDANT",
        "production_authority": "NONE",
        "audited_ancestor_commit": config.audited_runtime_ancestor,
        **identity,
        "candidate_qualification_sha256": _regular_hash(
            config.candidate_qualification_receipt, artifacts
        ),
        "candidate_command_evidence_sha256": _regular_hash(
            config.candidate_command_evidence, artifacts
        ),
        "proof_coverage_sha256": _regular_hash(config.proof_coverage_evidence, artifacts),
        "controller_config_sha256": config.source_sha256,
        "command_result_root": candidate["command_result_root"],
        "candidate_inventory_sha256": hashlib.sha256(
            b"HD636/CANDIDATE-INVENTORY/v1\0" + _canonical(candidate_inventory)
        ).hexdigest(),
        "toolchain_versions": EXPECTED,
        "lockfile_hashes": dependency_lock_hashes(root),
        "vendor_root_sha256": compute_vendor_tree_root(root / "vendor/hybrid-discovery-v6.3.6"),
        "normative_source_map_sha256": source_map,
        "normative_source_set_root": source_root,
        "normative_source_set_count": int(source_count),
        "full_repair_aggregate_sha256": _regular_hash(
            config.qualification_evidence.full_repair_aggregate, artifacts
        ),
        "full_repair_evidence_root_sha256": p03["evidence_root_sha256"],
        "environment_qualification_aggregate_sha256": _regular_hash(
            config.qualification_evidence.environment_qualification_aggregate,
            artifacts,
        ),
        "environment_qualification_evidence_root_sha256": environment["evidence_root_sha256"],
    }


def _outside_protected(output: Path, root: Path, config: FullVerifierConfig) -> None:
    if (
        output != config.descendant_repository_receipt
        or not output.is_absolute()
        or output.parent.resolve(strict=True) != output.parent
        or not output.parent.is_dir()
    ):
        _fail()
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    else:
        _fail()
    candidate = output.resolve(strict=False)
    boundaries = (
        root.resolve(),
        config.governed_source_pack.resolve(),
        config.external_authoring_tests.parent.resolve(),
    )
    if any(
        candidate == boundary
        or candidate.is_relative_to(boundary)
        or boundary.is_relative_to(candidate)
        for boundary in boundaries
    ):
        _fail()


def issue_descendant_qualification_receipt(
    root: Path, config: FullVerifierConfig, output: Path
) -> dict[str, object]:
    owned_identity: tuple[int, int] | None = None
    try:
        _validated_context(root, config)
        _outside_protected(output, root, config)
        before = _receipt_record(root, config)
        encoded = _canonical(before) + b"\n"
        with output.open("x", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            owned_identity = (info.st_dev, info.st_ino)
            stream.write(encoded.decode())
            stream.flush()
            os.fsync(stream.fileno())
            after = _receipt_record(root, config)
            if before != after:
                _fail()
            for _ in range(2):
                info = output.lstat()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != owned_identity
                ):
                    _fail()
                if _ == 0 and _read_bytes(output) != encoded:
                    _fail()
        return before
    except Exception as error:
        if owned_identity is not None:
            try:
                info = output.lstat()
                if (
                    stat.S_ISREG(info.st_mode)
                    and info.st_nlink == 1
                    and (info.st_dev, info.st_ino) == owned_identity
                ):
                    output.unlink()
            except OSError:
                pass
        raise ValueError("E_DESCENDANT_REPOSITORY") from error


def verify_descendant_qualification_receipt(
    root: Path,
    receipt_path: Path,
    *,
    pack: Path,
    config: FullVerifierConfig,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, object]:
    try:
        _validated_context(root, config, artifacts)
        if (
            pack != config.governed_source_pack
            or receipt_path != config.descendant_repository_receipt
        ):
            _fail()
        receipt = _read_evidence(receipt_path, artifacts)
        expected = _receipt_record(root, config, artifacts)
        if receipt != expected:
            _fail()
        return receipt
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError("E_DESCENDANT_REPOSITORY") from error


def main() -> None:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--recorded-config")
    parser.add_argument("--retained-manifest", type=Path)
    parser.add_argument("--retained-root", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--issue", action="store_true")
    mode.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    flags = [token.split("=", 1)[0] for token in sys.argv[1:] if token.startswith("--")]
    transport = (args.pack, args.recorded_config, args.retained_manifest, args.retained_root)
    if (
        len(flags) != len(set(flags))
        or (not args.check_only and args.output is None)
        or ((args.issue or args.check_only) and args.receipt is None)
        or (
            any(value is not None for value in transport)
            and (not args.check_only or not all(value is not None for value in transport))
        )
    ):
        parser.error("invalid descendant operation/context")
    artifacts = None
    if args.pack is not None:
        from tools.assemble_review_pack import load_sealed_assembly_context

        config, artifacts = load_sealed_assembly_context(
            args.pack,
            args.config,
            args.recorded_config,
            args.retained_manifest,
            args.retained_root,
        )
        named_receipt = args.pack / "docs/receipts/descendant-repository-qualification-receipt.json"
        if config.descendant_repository_receipt is None:
            _fail()
        if (
            args.root != config.current_checkout_root
            or args.receipt != named_receipt
            or named_receipt.is_symlink()
            or not named_receipt.is_file()
            or named_receipt.read_bytes()
            != _read_bytes(config.descendant_repository_receipt, artifacts)
        ):
            _fail()
    else:
        config = load_controller_config(args.config)
    if args.issue:
        if args.receipt is None:
            _fail()
        result = issue_descendant_qualification_receipt(args.root, config, args.receipt)
    elif args.check_only:
        if args.receipt is None:
            _fail()
        result = verify_descendant_qualification_receipt(
            args.root,
            cast(Path, config.descendant_repository_receipt)
            if artifacts is not None
            else args.receipt,
            pack=config.governed_source_pack,
            config=config,
            artifacts=artifacts,
        )
    else:
        result = {
            "schema_version": "descendant-repository-preflight/v1",
            "result": "PASS",
            "production_authority": "NONE",
            **descendant_repository_identity(args.root, cast(str, config.audited_runtime_ancestor)),
            "controller_binding": config.binding(),
        }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
