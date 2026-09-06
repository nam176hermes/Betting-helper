"""Copy a governed review pack into one fresh, independently sealable directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

FORBIDDEN_OUTPUTS = {
    "GOVERNED_CONTENT_ROOT.json",
    "SELF_REVIEW_REPORT.md",
    "SELF_REVIEW_REPORT.json",
    "MANIFEST_SHA256.json",
}
EVIDENCE_ROOT = Path("/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6")


def _walk(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    files: list[Path] = []
    for directory, _names, names in os.walk(root, followlinks=False):
        base = Path(directory)
        if base.is_symlink():
            raise ValueError("E_REVIEW_PACK_ASSEMBLY")
        for name in names:
            source = base / name
            relative = source.relative_to(root)
            info = source.lstat()
            if (
                source.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise ValueError("E_REVIEW_PACK_ASSEMBLY")
            if relative.name in FORBIDDEN_OUTPUTS:
                raise ValueError("E_REVIEW_PACK_ASSEMBLY")
            files.append(source)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix().encode())


def _relative(value: object) -> Path:
    if not isinstance(value, str):
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    return path


def _copy(source: Path, target: Path) -> None:
    info = source.lstat()
    if source.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    shutil.copyfile(source, target, follow_symlinks=False)
    target.chmod(stat.S_IMODE(info.st_mode))
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")


def _copy_authoring_exports(source: Path, destination: Path) -> list[str]:
    mapping_path = source / "docs/registries/delivery-map.v1.json"
    if not mapping_path.exists():
        return []
    try:
        mapping = json.loads(mapping_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_REVIEW_PACK_ASSEMBLY") from error
    exports = mapping.get("authoring_source_exports") if isinstance(mapping, dict) else None
    if mapping.get("schema_version") != "delivery-map/v1" or not isinstance(exports, list):
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    copied: list[str] = []
    for entry in exports:
        if not isinstance(entry, dict) or set(entry) != {"source", "destination", "owner"}:
            raise ValueError("E_REVIEW_PACK_ASSEMBLY")
        source_relative = _relative(entry["source"])
        destination_relative = _relative(entry["destination"])
        if entry["owner"] != "V636-P09-T01" or destination_relative.parts[:2] != (
            "pack",
            "authoring-source",
        ):
            raise ValueError("E_REVIEW_PACK_ASSEMBLY")
        target_relative = Path(*destination_relative.parts[1:])
        _copy(source.parent / source_relative, destination / target_relative)
        copied.append(target_relative.as_posix())
    if len(copied) != len(set(copied)):
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    return copied


def _copy_candidate_evidence(source: Path, destination: Path) -> list[str]:
    matrix_path = source / "docs/registries/proof-coverage-matrix.v1.json"
    if not matrix_path.exists():
        return []
    matrix = json.loads(matrix_path.read_text())
    entries = matrix.get("entries") if isinstance(matrix, dict) else None
    if not isinstance(entries, list):
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    copied: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("stage") != "CANDIDATE":
            continue
        source_path = Path(str(entry.get("evidence_artifact")))
        target_relative = _relative(entry.get("sealed_evidence_path"))
        if source_path.parent != EVIDENCE_ROOT or target_relative.parts[:1] != ("evidence",):
            raise ValueError("E_REVIEW_PACK_ASSEMBLY")
        if target_relative.as_posix() in copied:
            continue
        _copy(source_path, destination / target_relative)
        copied.append(target_relative.as_posix())
    return copied


def _copy_sealed_review_sources(source: Path, destination: Path) -> list[str]:
    manifest_path = source / "docs/tasks/task-manifest.v6.3.6.json"
    if not manifest_path.exists():
        return []
    copied: list[str] = []
    authoring_root = source.resolve().parent
    bootstrap = authoring_root / "plan-input/bootstrap"
    for source_path in _walk(bootstrap):
        target_relative = Path("authoring-source/bootstrap") / source_path.relative_to(bootstrap)
        _copy(source_path, destination / target_relative)
        copied.append(target_relative.as_posix())
    manifest = json.loads(manifest_path.read_text())
    tasks = manifest.get("tasks") if isinstance(manifest, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    roots = (
        (EVIDENCE_ROOT.resolve(), Path("evidence")),
        (authoring_root, Path("authoring-source/workspace")),
        (authoring_root.parent / "plan-input", Path("authoring-source/plan-input")),
    )
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("E_REVIEW_PACK_ASSEMBLY")
        for value in task.get("exact_files", []):
            path = Path(str(value))
            if not path.is_absolute() or not path.is_file():
                continue
            match = next(
                ((root, target) for root, target in roots if path.is_relative_to(root)), None
            )
            if match is None:
                continue
            root, target = match
            target_relative = target / path.relative_to(root)
            target_path = destination / target_relative
            if target_path.exists():
                if (
                    hashlib.sha256(path.read_bytes()).digest()
                    != hashlib.sha256(target_path.read_bytes()).digest()
                ):
                    raise ValueError("E_REVIEW_PACK_ASSEMBLY")
                continue
            _copy(path, target_path)
            copied.append(target_relative.as_posix())
    return copied


def _prove_normative_source_set(pack: Path) -> None:
    from tools.qualify_zero_parent_baseline import _normative_source_set

    receipt_path = pack / "docs/receipts/repo0-baseline-receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_REVIEW_PACK_ASSEMBLY") from error
    if not isinstance(receipt, dict):
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    source_map, source_set, count = _normative_source_set(pack)
    if (
        receipt.get("schema_version") != "repo0-baseline-receipt/v2"
        or receipt.get("normative_source_map_sha256") != source_map
        or receipt.get("normative_source_set_root") != source_set
        or receipt.get("normative_source_set_count") != count
    ):
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")


def assemble_review_pack(source: Path, destination: Path) -> dict[str, object]:
    _prove_normative_source_set(source)
    files = _walk(source)
    if destination.exists() or destination.is_symlink():
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    destination.mkdir(parents=True)
    copied: list[str] = []
    try:
        for source_path in files:
            relative = source_path.relative_to(source)
            target = destination / relative
            _copy(source_path, target)
            copied.append(relative.as_posix())
        copied.extend(_copy_authoring_exports(source, destination))
        copied.extend(_copy_candidate_evidence(source, destination))
        copied.extend(_copy_sealed_review_sources(source, destination))
        _prove_normative_source_set(destination)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {"result": "PASS", "file_count": len(copied), "files": copied}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(assemble_review_pack(args.source, args.destination))


if __name__ == "__main__":
    main()
