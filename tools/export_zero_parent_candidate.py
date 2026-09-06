"""Copy exactly the inventory bound by the candidate qualification receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
from pathlib import Path, PurePosixPath


def _relative(value: object) -> Path:
    if not isinstance(value, str):
        raise ValueError("E_ZERO_PARENT_EXPORT")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("E_ZERO_PARENT_EXPORT")
    return Path(*path.parts)


def _receipt(path: Path) -> list[dict[str, str]]:
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_ZERO_PARENT_EXPORT") from error
    inventory = record.get("inventory") if isinstance(record, dict) else None
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != "candidate-qualification-receipt/v1"
        or record.get("production_authority") != "NONE"
        or not isinstance(inventory, list)
        or not inventory
    ):
        raise ValueError("E_ZERO_PARENT_EXPORT")
    result: list[dict[str, str]] = []
    for entry in inventory:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "sha256", "size", "mode"}
            or entry.get("mode") not in {"100644", "100755"}
            or not isinstance(entry.get("sha256"), str)
            or len(entry["sha256"]) != 64
            or not isinstance(entry.get("size"), str)
            or not entry["size"].isdecimal()
        ):
            raise ValueError("E_ZERO_PARENT_EXPORT")
        _relative(entry.get("path"))
        result.append(entry)
    if [entry["path"] for entry in result] != sorted(entry["path"] for entry in result):
        raise ValueError("E_ZERO_PARENT_EXPORT")
    return result


def _ownership_allows(ownership: Path, inventory: list[dict[str, str]]) -> None:
    try:
        record = json.loads(ownership.read_text())
        entries = record.get("entries") if isinstance(record, dict) else None
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_ZERO_PARENT_EXPORT") from error
    if not isinstance(entries, list):
        raise ValueError("E_ZERO_PARENT_EXPORT")
    paths = {entry.get("path") for entry in entries if isinstance(entry, dict)}
    if any(f"runtime/{entry['path']}" not in paths for entry in inventory):
        raise ValueError("E_ZERO_PARENT_EXPORT")


def export_zero_parent_candidate(
    source: Path, destination: Path, candidate_receipt: Path, ownership: Path
) -> dict[str, object]:
    inventory = _receipt(candidate_receipt)
    _ownership_allows(ownership, inventory)
    if (
        source.is_symlink()
        or not source.is_dir()
        or destination.exists()
        or destination.is_symlink()
    ):
        raise ValueError("E_ZERO_PARENT_EXPORT")
    destination.mkdir(parents=True)
    try:
        for entry in inventory:
            relative = _relative(entry["path"])
            original = source / relative
            info = original.lstat()
            if (
                original.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or str(info.st_size) != entry["size"]
                or hashlib.sha256(original.read_bytes()).hexdigest() != entry["sha256"]
                or ("100755" if info.st_mode & 0o111 else "100644") != entry["mode"]
            ):
                raise ValueError("E_ZERO_PARENT_EXPORT")
            copied = destination / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, copied, follow_symlinks=False)
            copied.chmod(0o755 if entry["mode"] == "100755" else 0o644)
            if hashlib.sha256(copied.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("E_ZERO_PARENT_EXPORT")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {"result": "PASS", "file_count": len(inventory)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--candidate-receipt", required=True, type=Path)
    parser.add_argument("--ownership", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export_zero_parent_candidate(
        args.source, args.destination, args.candidate_receipt, args.ownership
    ), sort_keys=True))


if __name__ == "__main__":
    main()
