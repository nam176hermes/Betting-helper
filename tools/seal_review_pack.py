"""Create the deterministic v6.3.6 review archive and external attestation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZIP_STORED, ZipFile, ZipInfo

EXCLUSIONS = {
    "GOVERNED_CONTENT_ROOT.json",
    "SELF_REVIEW_REPORT.md",
    "SELF_REVIEW_REPORT.json",
    "MANIFEST_SHA256.json",
}
MANIFEST = "MANIFEST_SHA256.json"
HEX = set("0123456789abcdef")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_files(pack: Path, *, include_manifest: bool) -> list[tuple[str, Path]]:
    if pack.is_symlink() or not pack.is_dir():
        raise ValueError("E_SEAL_PACK")
    files: list[tuple[str, Path]] = []
    for directory, _names, names in os.walk(pack, followlinks=False):
        base = Path(directory)
        if base.is_symlink():
            raise ValueError("E_SEAL_PACK")
        for name in names:
            path = base / name
            relative = path.relative_to(pack).as_posix()
            info = path.lstat()
            if (
                path.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or unicodedata.normalize("NFC", relative) != relative
                or not relative
                or relative.startswith("/")
                or any(part in {"", ".", ".."} for part in Path(relative).parts)
            ):
                raise ValueError("E_SEAL_PACK")
            if relative == MANIFEST and not include_manifest:
                continue
            files.append((relative, path))
    paths = [relative for relative, _path in files]
    if len(paths) != len(set(paths)):
        raise ValueError("E_SEAL_PACK")
    return sorted(files, key=lambda item: item[0].encode())


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_SEAL_PACK") from error
    if not isinstance(value, dict):
        raise ValueError("E_SEAL_PACK")
    return value


def _hex(value: object, length: int = 64) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in HEX for character in value)
    ):
        raise ValueError("E_SEAL_PACK")
    return value


def _validate_inputs(pack: Path) -> dict[str, Any]:
    governed = _read_object(pack / "GOVERNED_CONTENT_ROOT.json")
    review = _read_object(pack / "SELF_REVIEW_REPORT.json")
    receipt = _read_object(pack / "docs/receipts/repo0-baseline-receipt.json")
    if (
        governed.get("schema_version") != "governed-content-root/v1"
        or governed.get("algorithm") != "HD636-GOVERNED-ROOT-SHA256-v1"
        or review.get("authority_granted") != "NONE"
        or any(key in review for key in ("manifest_sha256", "zip_sha256", "sidecar_sha256"))
        or receipt.get("schema_version") != "repo0-baseline-receipt/v2"
        or receipt.get("production_authority") != "NONE"
    ):
        raise ValueError("E_SEAL_PACK")
    for key in ("root_sha256",):
        _hex(governed.get(key))
    for key in (
        "baseline_file_root_sha256",
        "candidate_qualification_sha256",
        "candidate_command_evidence_sha256",
        "command_result_root",
        "baseline_registry_sha256",
        "vendor_root_sha256",
        "normative_source_map_sha256",
        "normative_source_set_root",
    ):
        _hex(receipt.get(key))
    _hex(receipt.get("baseline_commit"), 40)
    _hex(receipt.get("baseline_tree"), 40)
    return receipt


def _write_manifest(pack: Path) -> Path:
    entries = [
        {"path": relative, "size": str(path.stat().st_size), "sha256": _sha256(path)}
        for relative, path in _safe_files(pack, include_manifest=False)
    ]
    manifest = {"schema_version": "manifest-sha256/v1", "entries": entries}
    target = pack / MANIFEST
    target.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    return target


def _write_zip(pack: Path, target: Path) -> None:
    if target.is_relative_to(pack):
        raise ValueError("E_SEAL_PACK")
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_STORED, strict_timestamps=True) as archive:
        archive.comment = b""
        for relative, path in _safe_files(pack, include_manifest=True):
            info = ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.extra = b""
            info.comment = b""
            archive.writestr(info, path.read_bytes())


def _attestation(
    pack: Path, zip_path: Path, manifest: Path, receipt: dict[str, Any]
) -> dict[str, object]:
    return {
        "schema_version": "external-seal-attestation/v6",
        "artifact_type": "RUNTIME_PACK",
        "artifact": pack.name,
        "authorized_production_phases": "NONE",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "zip_sha256": _sha256(zip_path),
        "manifest_sha256": _sha256(manifest),
        "governed_content_root": _read_object(pack / "GOVERNED_CONTENT_ROOT.json")["root_sha256"],
        "self_review_markdown_sha256": _sha256(pack / "SELF_REVIEW_REPORT.md"),
        "self_review_json_sha256": _sha256(pack / "SELF_REVIEW_REPORT.json"),
        "task_manifest_sha256": _sha256(pack / "docs/tasks/task-manifest.v6.3.6.json"),
        "repo0_receipt_sha256": _sha256(pack / "docs/receipts/repo0-baseline-receipt.json"),
        "baseline_file_root_sha256": receipt["baseline_file_root_sha256"],
        "candidate_receipt_sha256": receipt["candidate_qualification_sha256"],
        "baseline_commit": receipt["baseline_commit"],
        "baseline_tree": receipt["baseline_tree"],
    }


def seal_review_pack(
    pack: Path, zip_path: Path, sidecar: Path, attestation: Path
) -> dict[str, object]:
    if len({zip_path.resolve(), sidecar.resolve(), attestation.resolve()}) != 3:
        raise ValueError("E_SEAL_PACK")
    receipt = _validate_inputs(pack)
    manifest = _write_manifest(pack)
    _write_zip(pack, zip_path)
    digest = _sha256(zip_path)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(f"{digest}  {zip_path.name}\n")
    record = _attestation(pack, zip_path, manifest, receipt)
    attestation.parent.mkdir(parents=True, exist_ok=True)
    attestation.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--attestation", required=True, type=Path)
    args = parser.parse_args()
    result = seal_review_pack(args.pack, args.zip, args.sidecar, args.attestation)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
