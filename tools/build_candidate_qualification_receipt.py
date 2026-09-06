"""Bind passed candidate replay evidence to the exact source inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import unicodedata
from pathlib import Path
from typing import cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_ROOT))

from tools import run_command_registry  # noqa: E402

EVIDENCE_ROOT = Path("/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6")
EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
EXCLUDED_FILES = {".coverage"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _inventory(root: Path) -> list[dict[str, str]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("E_CANDIDATE_RECEIPT")
    entries: list[dict[str, str]] = []
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        relative_base = base.relative_to(root)
        names[:] = [name for name in names if name not in EXCLUDED_DIRECTORIES]
        for name in sorted(files, key=lambda item: item.encode()):
            path = base / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if name in EXCLUDED_FILES:
                continue
            if (
                path.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or not relative
                or relative.startswith("/")
                or unicodedata.normalize("NFC", relative) != relative
                or any(part in {"", ".", ".."} for part in relative_base.parts)
            ):
                raise ValueError("E_CANDIDATE_RECEIPT")
            contents = path.read_bytes()
            entries.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(contents).hexdigest(),
                    "size": str(len(contents)),
                    "mode": "100755" if info.st_mode & 0o111 else "100644",
                }
            )
    return sorted(entries, key=lambda item: item["path"].encode())


def _read_evidence(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_CANDIDATE_RECEIPT") from error
    if not isinstance(value, dict):
        raise ValueError("E_CANDIDATE_RECEIPT")
    return cast(dict[str, object], value)


def validate_candidate_qualification_receipt(
    source: Path, command_evidence: Path, receipt: dict[str, object]
) -> None:
    evidence = _read_evidence(command_evidence)
    registry = run_command_registry.validate_registry(source / "task-command-registry.json")
    try:
        expected_evidence = run_command_registry.build_candidate_command_results(
            registry, evidence.get("results")
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
    }
    if (
        set(receipt) != required
        or receipt.get("schema_version") != "candidate-qualification-receipt/v1"
        or receipt.get("production_authority") != "NONE"
        or receipt.get("command_result_root")
        != hashlib.sha256(
            b"HD636/CANDIDATE-COMMAND-RESULTS/v1\0" + _canonical(evidence)
        ).hexdigest()
        or receipt.get("command_evidence_sha256")
        != hashlib.sha256(command_evidence.read_bytes()).hexdigest()
        or receipt.get("command_ids")
        != [entry["command_id"] for entry in cast(list[dict[str, object]], evidence["results"])]
        or receipt.get("inventory") != inventory
    ):
        raise ValueError("E_CANDIDATE_RECEIPT")


def build_candidate_qualification_receipt(
    source: Path, command_evidence: Path, output: Path
) -> dict[str, object]:
    evidence = _read_evidence(command_evidence)
    registry = run_command_registry.validate_registry(source / "task-command-registry.json")
    try:
        expected = run_command_registry.build_candidate_command_results(
            registry, evidence.get("results")
        )
    except ValueError as error:
        raise ValueError("E_CANDIDATE_RECEIPT") from error
    if evidence != expected:
        raise ValueError("E_CANDIDATE_RECEIPT")
    results = cast(list[dict[str, object]], evidence["results"])
    record: dict[str, object] = {
        "schema_version": "candidate-qualification-receipt/v1",
        "production_authority": "NONE",
        "command_result_root": hashlib.sha256(
            b"HD636/CANDIDATE-COMMAND-RESULTS/v1\0" + _canonical(evidence)
        ).hexdigest(),
        "command_evidence_sha256": hashlib.sha256(command_evidence.read_bytes()).hexdigest(),
        "command_ids": [item["command_id"] for item in results],
        "inventory": _inventory(source),
    }
    validate_candidate_qualification_receipt(source, command_evidence, record)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evidence = EVIDENCE_ROOT / "V636-P07-T01.json"
    result = build_candidate_qualification_receipt(RUNTIME_ROOT, evidence, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
