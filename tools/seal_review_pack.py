"""Create the deterministic v6.3.6 review archive and external attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from zipfile import ZIP_STORED, ZipFile, ZipInfo

if TYPE_CHECKING:
    from tools.full_verifier_config import FullVerifierConfig
    from tools.retained_artifact_io import RetainedArtifactIO

EXCLUSIONS = {
    "GOVERNED_CONTENT_ROOT.json",
    "SELF_REVIEW_REPORT.md",
    "SELF_REVIEW_REPORT.json",
    "MANIFEST_SHA256.json",
}
MANIFEST = "MANIFEST_SHA256.json"
HEX = set("0123456789abcdef")
DESCENDANT_RECEIPT = "docs/receipts/descendant-repository-qualification-receipt.json"


def _self_review_bytes(record: dict[str, object]) -> tuple[bytes, bytes]:
    return (
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        (
            "# Runtime self-review\n\n"
            f"Governed content root: `{record['governed_content_root']}`.\n\n"
            "Authority granted: NONE.\n"
        ).encode(),
    )


def _descendant_self_review(
    pack: Path,
    repository_receipt: Path,
    config: FullVerifierConfig,
    artifacts: RetainedArtifactIO,
) -> dict[str, object]:
    from tools.assemble_review_pack import load_sealed_assembly_context
    from tools.qualify_descendant_repository import verify_descendant_qualification_receipt

    if repository_receipt != pack / DESCENDANT_RECEIPT:
        raise ValueError("E_SEAL_PACK")
    checked, copied = load_sealed_assembly_context(
        pack,
        pack / "docs/configs/full-verifier-controller.v2.json",
        str(config.source_path),
        pack / "evidence/retained-artifact-manifest.json",
        pack / "evidence/retained",
    )
    if checked != config or copied != artifacts or config.descendant_repository_receipt is None:
        raise ValueError("E_SEAL_PACK")
    receipt = verify_descendant_qualification_receipt(
        config.current_checkout_root,
        config.descendant_repository_receipt,
        pack=config.governed_source_pack,
        config=config,
        artifacts=artifacts,
    )
    governed = _verified_governed_root(pack)
    return {
        "schema_version": "runtime-self-review/v2",
        "governed_content_root": governed["root_sha256"],
        "repository_qualification_receipt_sha256": _sha256(repository_receipt),
        "candidate_qualification_sha256": receipt["candidate_qualification_sha256"],
        "task_manifest_sha256": _sha256(pack / "docs/tasks/task-manifest.v6.3.6.json"),
        "command_result_root": receipt["command_result_root"],
        "repository_identity_kind": receipt["repository_identity_kind"],
        "repository_commit_oid": receipt["repository_commit"],
        "repository_tree_oid": receipt["repository_tree"],
        "repository_file_tree_root_sha256": receipt["repository_file_root_sha256"],
        "checks": [{"check_id": "NO_FUTURE_SEAL_IDENTITY", "result": "PASS"}],
        "authority_granted": "NONE",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_files(
    pack: Path,
    *,
    include_manifest: bool,
    strict_directories: bool = False,
) -> list[tuple[str, Path]]:
    if pack.is_symlink() or not pack.is_dir():
        raise ValueError("E_SEAL_PACK")
    files: list[tuple[str, Path]] = []
    if strict_directories and pack.absolute() != pack.resolve(strict=True):
        raise ValueError("E_SEAL_PACK")
    for directory, directory_names, names in os.walk(pack, followlinks=False):
        base = Path(directory)
        if base.is_symlink():
            raise ValueError("E_SEAL_PACK")
        if strict_directories and any((base / name).is_symlink() for name in directory_names):
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


def _verified_governed_root(pack: Path) -> dict[str, object]:
    """Reuse the owned-temp writer; never normalize away unsafe original files."""
    from tools.compute_governed_content_root import compute_governed_content_root

    _safe_files(pack, include_manifest=True, strict_directories=True)
    with TemporaryDirectory() as temporary:
        rebuilt = Path(temporary) / pack.name
        shutil.copytree(pack, rebuilt)
        record = compute_governed_content_root(
            rebuilt,
            rebuilt / "docs/registries/seal-exclusions.v1.json",
        )
        if (pack / "GOVERNED_CONTENT_ROOT.json").read_bytes() != (
            rebuilt / "GOVERNED_CONTENT_ROOT.json"
        ).read_bytes():
            raise ValueError("E_SEAL_PACK")
        return record


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


def _validate_inputs(
    pack: Path,
    config: FullVerifierConfig | None = None,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, Any]:
    if config is not None or artifacts is not None:
        if config is None or artifacts is None:
            raise ValueError("E_SEAL_PACK")
        record = _descendant_self_review(pack, pack / DESCENDANT_RECEIPT, config, artifacts)
        expected_json, expected_markdown = _self_review_bytes(record)
        if (pack / "SELF_REVIEW_REPORT.json").read_bytes() != expected_json or (
            pack / "SELF_REVIEW_REPORT.md"
        ).read_bytes() != expected_markdown:
            raise ValueError("E_SEAL_PACK")
        return record
    if (pack / DESCENDANT_RECEIPT).exists():
        raise ValueError("E_SEAL_PACK")
    governed = _read_object(pack / "GOVERNED_CONTENT_ROOT.json")
    review = _read_object(pack / "SELF_REVIEW_REPORT.json")
    receipt = _read_object(pack / "docs/receipts/repo0-baseline-receipt.json")
    if (
        governed.get("schema_version") != "governed-content-root/v1"
        or governed.get("algorithm") != "HD636-GOVERNED-ROOT-SHA256-v1"
        or review.get("authority_granted") != "NONE"
        or review.get("schema_version") != "runtime-self-review/v1"
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
    current = receipt["schema_version"] == "runtime-self-review/v2"
    record = {
        "schema_version": "external-seal-attestation/v7"
        if current
        else "external-seal-attestation/v6",
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
        "candidate_receipt_sha256": receipt["candidate_qualification_sha256"],
    }
    if current:
        record.update(
            {
                key: receipt[key]
                for key in (
                    "repository_qualification_receipt_sha256",
                    "repository_identity_kind",
                    "repository_commit_oid",
                    "repository_tree_oid",
                    "repository_file_tree_root_sha256",
                )
            }
        )
    else:
        record.update(
            repo0_receipt_sha256=_sha256(pack / "docs/receipts/repo0-baseline-receipt.json"),
            baseline_file_root_sha256=receipt["baseline_file_root_sha256"],
            baseline_commit=receipt["baseline_commit"],
            baseline_tree=receipt["baseline_tree"],
        )
    return record


def _current_external_paths(pack: Path, paths: tuple[Path, Path, Path]) -> None:
    if len(set(paths)) != 3:
        raise ValueError("E_SEAL_PACK")
    for path in paths:
        if path != path.resolve() or path.is_relative_to(pack):
            raise ValueError("E_SEAL_PACK")
        if path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("E_SEAL_PACK")


def seal_review_pack(
    pack: Path,
    zip_path: Path,
    sidecar: Path,
    attestation: Path,
    *,
    config: FullVerifierConfig | None = None,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, object]:
    try:
        if len({zip_path.resolve(), sidecar.resolve(), attestation.resolve()}) != 3:
            raise ValueError("E_SEAL_PACK")
        if config is not None or artifacts is not None:
            _current_external_paths(pack, (zip_path, sidecar, attestation))
        receipt = _validate_inputs(pack, config, artifacts)
        manifest = _write_manifest(pack)
        _write_zip(pack, zip_path)
        digest = _sha256(zip_path)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(f"{digest}  {zip_path.name}\n")
        record = _attestation(pack, zip_path, manifest, receipt)
        attestation.parent.mkdir(parents=True, exist_ok=True)
        attestation.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("E_SEAL_PACK") from error


def verify_sealed_review_pack(
    pack: Path,
    zip_path: Path,
    sidecar_path: Path,
    attestation_path: Path,
    *,
    config_path: Path | None = None,
    recorded_config_locator: str | None = None,
    retained_manifest: Path | None = None,
    retained_root: Path | None = None,
    context_out: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Independently reconstruct in owned temporary storage, without input writes."""
    from tools.compute_governed_content_root import compute_governed_content_root

    try:
        # copytree dereferences links by default, so inspect the ORIGINAL first.
        _safe_files(pack, include_manifest=True, strict_directories=True)
        attestation = _read_object(attestation_path)
        current = attestation.get("schema_version") == "external-seal-attestation/v7"
        context = (config_path, recorded_config_locator, retained_manifest, retained_root)
        config, artifacts = None, None
        if current:
            if (
                config_path is None
                or recorded_config_locator is None
                or retained_manifest is None
                or retained_root is None
            ):
                raise ValueError("E_SEAL_PACK")
            from tools.assemble_review_pack import load_sealed_assembly_context

            config, artifacts = load_sealed_assembly_context(
                pack,
                config_path,
                recorded_config_locator,
                retained_manifest,
                retained_root,
            )
            _current_external_paths(pack, (zip_path, sidecar_path, attestation_path))
            receipt = _validate_inputs(pack, config, artifacts)
        elif any(value is not None for value in context):
            raise ValueError("E_SEAL_PACK")
        digest = _sha256(zip_path)
        if (
            attestation.get("schema_version")
            not in {"external-seal-attestation/v6", "external-seal-attestation/v7"}
            or attestation.get("artifact_type") != "RUNTIME_PACK"
            or attestation.get("authorized_production_phases") != "NONE"
            or attestation.get("zip_sha256") != digest
            or sidecar_path.read_text() != f"{digest}  {zip_path.name}\n"
        ):
            raise ValueError("E_SEAL_PACK")
        if current:
            from moj_discovery.schema_formats import _is_rfc3339_date_time

            if not isinstance(attestation["created_at"], str) or not _is_rfc3339_date_time(
                attestation["created_at"]
            ):
                raise ValueError("E_SEAL_PACK")
        else:
            datetime.fromisoformat(str(attestation["created_at"]).replace("Z", "+00:00"))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            rebuilt = root / pack.name
            shutil.copytree(pack, rebuilt)
            compute_governed_content_root(
                rebuilt,
                rebuilt / "docs/registries/seal-exclusions.v1.json",
            )
            if current:
                # The original descendant chain was fully verified above. Rebuild
                # its deterministic envelope from that measured record, without
                # recursively verifying the same chain again in each writer.
                expected_json, expected_markdown = _self_review_bytes(receipt)
                (rebuilt / "SELF_REVIEW_REPORT.json").write_bytes(expected_json)
                (rebuilt / "SELF_REVIEW_REPORT.md").write_bytes(expected_markdown)
                manifest = _write_manifest(rebuilt)
                _write_zip(rebuilt, root / zip_path.name)
                (root / sidecar_path.name).write_text(
                    f"{_sha256(root / zip_path.name)}  {zip_path.name}\n"
                )
                expected = _attestation(rebuilt, root / zip_path.name, manifest, receipt)
            else:
                expected = seal_review_pack(
                    rebuilt,
                    root / zip_path.name,
                    root / sidecar_path.name,
                    root / attestation_path.name,
                )
            expected["created_at"] = attestation["created_at"]
            if (
                expected != attestation
                or (root / zip_path.name).read_bytes() != zip_path.read_bytes()
            ):
                raise ValueError("E_SEAL_PACK")
            if current and (
                any(
                    (rebuilt / name).read_bytes() != (pack / name).read_bytes()
                    for name in EXCLUSIONS
                )
                or (root / sidecar_path.name).read_bytes() != sidecar_path.read_bytes()
            ):
                raise ValueError("E_SEAL_PACK")
        if context_out is not None:
            context_out.clear()
            context_out.update(controller=config, artifacts=artifacts)
        return attestation
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("E_SEAL_PACK") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--attestation", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--recorded-config")
    parser.add_argument("--retained-manifest", type=Path)
    parser.add_argument("--retained-root", type=Path)
    args = parser.parse_args()
    context = (args.config, args.recorded_config, args.retained_manifest, args.retained_root)
    config, artifacts = None, None
    if any(value is not None for value in context):
        if not all(value is not None for value in context):
            raise ValueError("E_SEAL_PACK")
        # Direct governed CLI execution must work outside an installed package.
        import sys

        runtime_root = Path(__file__).resolve().parents[1]
        sys.path[:0] = [str(runtime_root), str(runtime_root / "src")]
        from tools.assemble_review_pack import load_sealed_assembly_context

        config, artifacts = load_sealed_assembly_context(args.pack, *context)
    result = seal_review_pack(
        args.pack,
        args.zip,
        args.sidecar,
        args.attestation,
        config=config,
        artifacts=artifacts,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
