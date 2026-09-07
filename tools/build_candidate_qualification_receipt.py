"""Bind passed candidate replay evidence to the exact source inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_ROOT))

from tools import run_command_registry  # noqa: E402
from tools.full_verifier_config import FullVerifierConfig, load_controller_config  # noqa: E402


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _git(root: Path, *args: str) -> bytes:
    git = shutil.which("git")
    if git is None:
        raise ValueError("E_CANDIDATE_RECEIPT")
    completed = subprocess.run(  # noqa: S603 - fixed read-only Git operation.
        [git, "-C", str(root), *args],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError("E_CANDIDATE_RECEIPT")
    return completed.stdout


def _inventory(root: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("E_CANDIDATE_RECEIPT")
    if _git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root.resolve()):
        raise ValueError("E_CANDIDATE_RECEIPT")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("E_CANDIDATE_RECEIPT")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    tree = _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    if re.fullmatch(r"[0-9a-f]{40}", head) is None or re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise ValueError("E_CANDIDATE_RECEIPT")
    entries: list[dict[str, str]] = []
    raw = _git(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            metadata, encoded_path = item.split(b"\t", 1)
            mode, kind, object_id = metadata.decode().split(" ")
            relative = encoded_path.decode("utf-8")
        except (UnicodeError, ValueError) as error:
            raise ValueError("E_CANDIDATE_RECEIPT") from error
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("E_CANDIDATE_RECEIPT")
        contents = (root / relative).read_bytes()
        if (
            hashlib.sha1(  # noqa: S324 - Git object identity is SHA-1 by protocol.
                f"blob {len(contents)}\0".encode() + contents,
                usedforsecurity=False,
            ).hexdigest()
            != object_id
        ):
            raise ValueError("E_CANDIDATE_RECEIPT")
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(contents).hexdigest(),
                "size": str(len(contents)),
                "mode": mode,
            }
        )
    return {"head": head, "tree": tree, "entries": entries}


def _read_evidence(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_CANDIDATE_RECEIPT") from error
    if not isinstance(value, dict):
        raise ValueError("E_CANDIDATE_RECEIPT")
    return cast(dict[str, object], value)


def validate_candidate_qualification_receipt(
    source: Path,
    command_evidence: Path,
    receipt: dict[str, object],
    config: FullVerifierConfig | None = None,
) -> None:
    evidence = _read_evidence(command_evidence)
    registry = run_command_registry.validate_registry(source / "task-command-registry.json")
    try:
        expected_evidence = run_command_registry.build_candidate_command_results(
            registry, evidence.get("results"), config
        )
    except ValueError as error:
        raise ValueError("E_CANDIDATE_RECEIPT") from error
    if evidence != expected_evidence:
        raise ValueError("E_CANDIDATE_RECEIPT")
    inventory = _inventory(source)
    required = {
        "schema_version",
        "production_authority",
        "command_result_root",
        "command_evidence_sha256",
        "command_ids",
        "inventory",
        "controller_binding",
    }
    if (
        set(receipt) != required
        or receipt.get("schema_version") != "candidate-qualification-receipt/v2"
        or receipt.get("production_authority") != "NONE"
        or receipt.get("command_result_root")
        != hashlib.sha256(
            b"HD636/CANDIDATE-COMMAND-RESULTS/v2\0" + _canonical(evidence)
        ).hexdigest()
        or receipt.get("command_evidence_sha256")
        != hashlib.sha256(command_evidence.read_bytes()).hexdigest()
        or receipt.get("command_ids")
        != [entry["command_id"] for entry in cast(list[dict[str, object]], evidence["results"])]
        or receipt.get("inventory") != inventory
        or config is None
        or receipt.get("controller_binding") != config.binding()
    ):
        raise ValueError("E_CANDIDATE_RECEIPT")


def build_candidate_qualification_receipt(
    source: Path,
    command_evidence: Path,
    output: Path,
    config: FullVerifierConfig,
) -> dict[str, object]:
    evidence = _read_evidence(command_evidence)
    registry = run_command_registry.validate_registry(source / "task-command-registry.json")
    try:
        expected = run_command_registry.build_candidate_command_results(
            registry, evidence.get("results"), config
        )
    except ValueError as error:
        raise ValueError("E_CANDIDATE_RECEIPT") from error
    if evidence != expected:
        raise ValueError("E_CANDIDATE_RECEIPT")
    results = cast(list[dict[str, object]], evidence["results"])
    record: dict[str, object] = {
        "schema_version": "candidate-qualification-receipt/v2",
        "production_authority": "NONE",
        "command_result_root": hashlib.sha256(
            b"HD636/CANDIDATE-COMMAND-RESULTS/v2\0" + _canonical(evidence)
        ).hexdigest(),
        "command_evidence_sha256": hashlib.sha256(command_evidence.read_bytes()).hexdigest(),
        "command_ids": [item["command_id"] for item in results],
        "inventory": _inventory(source),
        "controller_binding": config.binding(),
    }
    validate_candidate_qualification_receipt(source, command_evidence, record, config)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--command-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = load_controller_config(args.config)
    result = build_candidate_qualification_receipt(
        args.source, args.command_evidence, args.output, config
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
