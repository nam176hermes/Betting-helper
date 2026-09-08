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
from typing import Any, NoReturn

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from tools.full_verifier_config import FullVerifierConfig, load_controller_config  # noqa: E402
from tools.retained_artifact_io import (  # noqa: E402
    RetainedArtifactIO,
    _canonical_relative,
    canonical_recorded_locator,
)

FORBIDDEN_OUTPUTS = {
    "GOVERNED_CONTENT_ROOT.json",
    "SELF_REVIEW_REPORT.md",
    "SELF_REVIEW_REPORT.json",
    "MANIFEST_SHA256.json",
}
EVIDENCE_ROOT = Path("/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6")

TASK_MANIFEST = "docs/tasks/task-manifest.v6.3.6.json"
OWNERSHIP = "docs/registries/artifact-ownership.v1.json"
DELIVERY = "docs/registries/delivery-map.v1.json"
COMMAND_IO = "docs/registries/command-io.v1.json"
CONFIG_COPY = "docs/configs/full-verifier-controller.v2.json"
UNION_MANIFEST = "evidence/retained-artifact-manifest.json"
UNION_ROOT = "evidence/retained"
ASSEMBLY_TASK = "V636-P09-T01"


def _fail() -> NoReturn:
    raise ValueError("E_REVIEW_PACK_ASSEMBLY")


def _regular_bytes(path: Path) -> bytes:
    if str(path) != canonical_recorded_locator(str(path)) or path != path.resolve(strict=True):
        _fail()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail()
    return path.read_bytes()


def _read_bytes(path: Path, artifacts: RetainedArtifactIO | None = None) -> bytes:
    if artifacts is None:
        return _regular_bytes(path)
    return artifacts.read_bytes(str(path), recorded_boundary=artifacts.recorded_boundary(str(path)))


def _document(path: Path, artifacts: RetainedArtifactIO | None = None) -> dict[str, Any]:
    value = json.loads(_read_bytes(path, artifacts))
    if not isinstance(value, dict):
        _fail()
    return value


def _bound_source_document(
    config: FullVerifierConfig,
    relative: str,
    artifacts: RetainedArtifactIO | None,
) -> dict[str, Any]:
    """Source declarations must match the independently qualified LIVE vendor."""
    raw = _read_bytes(config.governed_source_pack / relative, artifacts)
    vendor = config.current_checkout_root / "vendor/hybrid-discovery-v6.3.6"
    if raw != _regular_bytes(vendor / relative):
        _fail()
    value = json.loads(raw)
    if not isinstance(value, dict):
        _fail()
    return value


def _contract(
    config: FullVerifierConfig,
    artifacts: RetainedArtifactIO | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    tasks = _bound_source_document(config, TASK_MANIFEST, artifacts)["tasks"]
    ownership_rows = _bound_source_document(config, OWNERSHIP, artifacts)["entries"]
    owned = {row["path"]: row for row in ownership_rows}
    if len(owned) != len(ownership_rows):
        _fail()
    task = next(row for row in tasks if row["task_id"] == ASSEMBLY_TASK)
    command = next(
        row
        for row in _bound_source_document(config, COMMAND_IO, artifacts)["commands"]
        if row["command_id"] == "VERIFY_V636_P09_T01"
    )
    if not set(task["inputs"]).issubset(command["inputs"]) or set(task["outputs"]) != set(
        command["outputs"]
    ):
        _fail()
    for relative in (UNION_MANIFEST, UNION_ROOT):
        token = "pack/" + relative
        if token not in task["outputs"] or owned[token]["creation_owner"] != ASSEMBLY_TASK:
            _fail()
    delivery = _bound_source_document(config, DELIVERY, artifacts)
    if delivery.get("schema_version") != "delivery-map/v1":
        _fail()
    return task, owned, delivery


def _exports(config: FullVerifierConfig, delivery: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in delivery["authoring_source_exports"]:
        if set(entry) != {"source", "destination", "owner"} or entry["owner"] != ASSEMBLY_TASK:
            _fail()
        relative = _relative(entry["source"])
        target = _relative(entry["destination"])
        if (
            target.parts[:2] != ("pack", "authoring-source")
            or relative.as_posix() != entry["source"]
            or target.as_posix() != entry["destination"]
            or target.relative_to("pack").as_posix() in result
        ):
            _fail()
        result[target.relative_to("pack").as_posix()] = str(
            config.governed_source_pack.parent / relative
        )
    return result


def _source_locators(
    config: FullVerifierConfig,
    artifacts: RetainedArtifactIO | None,
) -> list[str]:
    """Derive complete source membership independently of any supplied union."""
    task, owned, delivery = _contract(config, artifacts)
    separate = {token for token in task["outputs"] if token.startswith("pack/")} | {
        "pack/" + relative for relative in _exports(config, delivery)
    }
    required = {
        token
        for token, row in owned.items()
        if token.startswith("pack/")
        and row["materialization_required"] is True
        and token not in separate
    } | {token for token in task["inputs"] if token.startswith("pack/")}
    normative = _bound_source_document(
        config,
        "docs/registries/normative-source-map.v1.json",
        artifacts,
    )
    required.update(
        "pack/" + entry["plan_source"]
        for entry in [*normative["inherited_entries"], *normative["plan_entries"]]
    )
    if required & separate:
        _fail()
    locators = []
    for token in sorted(required):
        relative = _relative(token).relative_to("pack")
        if token not in owned or relative.name in FORBIDDEN_OUTPUTS:
            _fail()
        locators.append(str(config.governed_source_pack / relative))
    return locators


def _named_deliveries(
    config: FullVerifierConfig,
    source_locators: list[str],
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, str]:
    task, owned, delivery = _contract(config, artifacts)
    source = config.governed_source_pack
    named = {Path(locator).relative_to(source).as_posix(): locator for locator in source_locators}

    def add(relative: str, locator: str, *, exported: bool = False) -> None:
        if _relative(relative).as_posix() != relative:
            _fail()
        token = "pack/" + relative
        if not exported and (
            token not in task["outputs"] or owned[token]["creation_owner"] != ASSEMBLY_TASK
        ):
            _fail()
        if relative in named and named[relative] != locator:
            _fail()
        named[relative] = locator

    for relative, locator in _exports(config, delivery).items():
        add(relative, locator, exported=True)
    for row in _bound_source_document(
        config, "docs/registries/proof-coverage-matrix.v1.json", artifacts
    )["entries"]:
        if row["stage"] == "CANDIDATE":
            locator = canonical_recorded_locator(row["evidence_artifact"])
            if Path(locator).parent != config.evidence_root:
                _fail()
            add(row["sealed_evidence_path"], locator)
    for path in (
        config.candidate_command_evidence,
        config.proof_coverage_evidence,
        config.candidate_issuance_evidence,
        config.candidate_qualification_receipt,
    ):
        add("evidence/" + path.name, str(path))
    assert config.descendant_repository_receipt is not None
    add(
        "docs/receipts/descendant-repository-qualification-receipt.json",
        str(config.descendant_repository_receipt),
    )
    return named


def _retained_inputs(
    config: FullVerifierConfig,
    source_locators: list[str],
    artifacts: RetainedArtifactIO | None = None,
    *,
    snapshots: dict[Path, tuple[bytes, int]] | None = None,
) -> tuple[dict[str, tuple[Path, str, bytes]], dict[str, str]]:
    """Merge finite authenticated owner rows, never discover an evidence directory."""
    task, owned, delivery = _contract(config, artifacts)
    source = config.governed_source_pack
    if len(source_locators) != len(set(source_locators)) or set(source_locators) != set(
        _source_locators(config, artifacts)
    ):
        _fail()
    entries: dict[str, tuple[Path, str, bytes]] = {}

    def add(locator: str, boundary: str, context: RetainedArtifactIO | None = artifacts) -> None:
        locator, boundary = (
            canonical_recorded_locator(locator),
            canonical_recorded_locator(boundary),
        )
        if not Path(locator).is_relative_to(boundary) or locator == boundary:
            _fail()
        if context is None:
            physical, raw = Path(locator), _regular_bytes(Path(locator))
        else:
            physical = context.physical_path(locator, recorded_boundary=boundary)
            raw = context.read_bytes(locator, recorded_boundary=boundary)
        if snapshots is not None:
            snapshots[physical] = raw, stat.S_IMODE(physical.lstat().st_mode)
        prior = entries.get(locator)
        if prior is not None and (prior[1], prior[2]) != (boundary, raw):
            _fail()
        if prior is None:
            entries[locator] = physical, boundary, raw

    qualification = config.qualification_evidence
    assert qualification is not None
    for inventory in (
        qualification.full_repair_inventory,
        qualification.environment_qualification_inventory,
    ):
        manifest = _document(inventory, artifacts)
        # The union changes physical names, not the original owner's manifest
        # grammar. Validate that metadata even when its files use union paths.
        if (
            set(manifest) != {"schema_version", "recorded_boundaries", "files"}
            or manifest["schema_version"] != "retained-artifact-manifest/v1"
            or not isinstance(manifest["recorded_boundaries"], list)
            or not isinstance(manifest["files"], list)
        ):
            _fail()
        boundaries = [canonical_recorded_locator(item) for item in manifest["recorded_boundaries"]]
        if not boundaries or len(boundaries) != len(set(boundaries)):
            _fail()
        locators: set[str] = set()
        relatives: set[str] = set()
        for row in manifest["files"]:
            if not isinstance(row, dict) or set(row) != {
                "recorded_locator",
                "recorded_boundary",
                "copied_relative_path",
                "size_bytes",
                "sha256",
            }:
                _fail()
            locator = canonical_recorded_locator(row["recorded_locator"])
            relative = _canonical_relative(row["copied_relative_path"])
            if (
                locator in locators
                or relative in relatives
                or row["recorded_boundary"] not in boundaries
                or type(row["size_bytes"]) is not int
            ):
                _fail()
            locators.add(locator)
            relatives.add(relative)
        context = artifacts or RetainedArtifactIO.from_manifest(
            manifest, inventory.parent / "retained"
        )
        for row in manifest["files"]:
            add(row["recorded_locator"], row["recorded_boundary"], context)
            if (
                len(entries[row["recorded_locator"]][2]) != row["size_bytes"]
                or hashlib.sha256(entries[row["recorded_locator"]][2]).hexdigest() != row["sha256"]
            ):
                _fail()
        add(str(inventory), str(inventory.parent))
    for locator in source_locators:
        relative = Path(locator).relative_to(source).as_posix()
        if "pack/" + relative not in owned:
            _fail()
        add(locator, str(source))
    add(str(config.source_path), str(config.source_path.parent))
    for locator in _exports(config, delivery).values():
        add(locator, str(source.parent))
    named = _named_deliveries(config, source_locators, artifacts)
    required = {
        str(config.descendant_repository_receipt),
        *named.values(),
        *qualification.binding().values(),
        *(value for value in task["inputs"] if value.startswith("/")),
    }
    for locator in sorted(required):
        if locator in entries:
            if artifacts is None:
                # Required raw aggregates/config/evidence remain independent
                # inputs even when an owner also retained the same locator.
                add(locator, entries[locator][1], None)
            continue
        path = Path(locator)
        boundary = str(source) if path.is_relative_to(source) else str(path.parent)
        add(locator, boundary)
    if artifacts is not None and set(entries) != set(artifacts.recorded_locators()):
        _fail()
    from tools.qualify_descendant_repository import _validate_issuance

    _validate_issuance(config, artifacts)
    return entries, named


def _normative_descendant(
    config: FullVerifierConfig,
    receipt: dict[str, object],
    artifacts: RetainedArtifactIO | None,
) -> None:
    from tools.qualify_zero_parent_baseline import _normative_source_set

    source_map, source_root, count = _normative_source_set(
        config.governed_source_pack, artifacts=artifacts
    )
    if (
        receipt.get("normative_source_map_sha256"),
        receipt.get("normative_source_set_root"),
        receipt.get("normative_source_set_count"),
    ) != (source_map, source_root, int(count)):
        _fail()


def load_sealed_assembly_context(
    pack: Path,
    config_path: Path,
    recorded_config_locator: str,
    retained_manifest: Path,
    retained_root: Path,
) -> tuple[FullVerifierConfig, RetainedArtifactIO]:
    """Load the recorded config, authenticating the named source-owned deliveries."""
    try:
        if (
            pack != pack.resolve(strict=True)
            or config_path != pack / CONFIG_COPY
            or retained_manifest != pack / UNION_MANIFEST
            or retained_root != pack / UNION_ROOT
        ):
            _fail()
        artifacts = RetainedArtifactIO.from_manifest(
            json.loads(_regular_bytes(retained_manifest)), retained_root
        )
        recorded = canonical_recorded_locator(recorded_config_locator)
        physical = artifacts.physical_path(
            recorded, recorded_boundary=artifacts.recorded_boundary(recorded)
        )
        config = load_controller_config(
            physical, mode="SEALED", artifacts=artifacts, recorded_locator=recorded
        )
        if config.schema_version != "full-verifier-controller/v2" or _regular_bytes(
            config_path
        ) != _read_bytes(config.source_path, artifacts):
            _fail()
        from tools.build_candidate_qualification_receipt import (
            validate_candidate_qualification_receipt,
        )

        validate_candidate_qualification_receipt(
            config.current_checkout_root,
            config.candidate_command_evidence,
            _document(config.candidate_qualification_receipt, artifacts),
            config,
            artifacts=artifacts,
        )
        sources = _source_locators(config, artifacts)
        _entries, named = _retained_inputs(config, sources, artifacts)
        for relative, locator in named.items():
            if _regular_bytes(pack / relative) != _read_bytes(Path(locator), artifacts):
                _fail()
        return config, artifacts
    except (OSError, ValueError, KeyError, TypeError, StopIteration, AssertionError) as error:
        raise ValueError("E_REVIEW_PACK_ASSEMBLY") from error


def _current_assembly(
    source: Path,
    destination: Path,
    config: FullVerifierConfig,
    retained_manifest: Path,
    retained_root: Path,
) -> dict[str, object]:
    from tools.qualify_descendant_repository import verify_descendant_qualification_receipt
    from tools.run_environment_qualification import verify_environment_qualification_evidence
    from tools.run_full_repair_qualification import write_closed_inventory
    from tools.verify_full_repair_qualification import verify_full_repair_qualification

    owned_identity: tuple[int, int] | None = None
    try:
        if (
            config.schema_version != "full-verifier-controller/v2"
            or source != config.governed_source_pack
            or config.descendant_repository_receipt is None
            or config.qualification_evidence is None
            or not destination.is_absolute()
            or destination != destination.resolve()
            or retained_manifest != destination / UNION_MANIFEST
            or retained_root != destination / UNION_ROOT
        ):
            _fail()
        # The independent full/candidate/descendant chain precedes any output write.
        receipt = verify_descendant_qualification_receipt(
            config.current_checkout_root,
            config.descendant_repository_receipt,
            pack=source,
            config=config,
        )
        _normative_descendant(config, receipt, None)
        files = _walk(source, strict_directories=True)
        snapshots: dict[Path, tuple[bytes, int]] = {}
        entries, named = _retained_inputs(
            config, [str(path) for path in files], snapshots=snapshots
        )
        protected = {
            config.current_checkout_root,
            source.parent,
            config.evidence_root,
            config.external_authoring_tests.parent,
            config.uv_cache,
            config.pnpm_store,
            config.chrome_path.parent,
            *(Path(boundary) for _, boundary, _ in entries.values()),
            *(physical.parent for physical, _, _ in entries.values()),
            *(physical.parent for physical in snapshots),
        }
        if any(
            destination.is_relative_to(root.resolve()) or root.resolve().is_relative_to(destination)
            for root in protected
        ):
            _fail()
        try:
            destination.lstat()
        except FileNotFoundError:
            pass
        else:
            _fail()
        # Parents may preexist; require canonical existing ancestry before mkdir.
        if destination.parent != destination.parent.resolve(strict=True):
            _fail()
        destination.mkdir()
        info = destination.lstat()
        owned_identity = info.st_dev, info.st_ino

        def check_owned() -> None:
            current = destination.lstat()
            if (
                not stat.S_ISDIR(current.st_mode)
                or (current.st_dev, current.st_ino) != owned_identity
            ):
                _fail()

        for relative, locator in sorted(named.items()):
            check_owned()
            _copy(entries[locator][0], destination / _relative(relative))
        (destination / "evidence").mkdir(exist_ok=True)
        check_owned()
        write_closed_inventory(
            [
                (physical, locator, boundary)
                for locator, (physical, boundary, _raw) in sorted(entries.items())
            ],
            retained_manifest,
        )
        check_owned()
        copied_config, artifacts = load_sealed_assembly_context(
            destination,
            destination / CONFIG_COPY,
            str(config.source_path),
            retained_manifest,
            retained_root,
        )
        if copied_config != config:
            _fail()
        qualification = config.qualification_evidence

        def mapped(path: Path) -> Path:
            return artifacts.physical_path(
                str(path), recorded_boundary=artifacts.recorded_boundary(str(path))
            )

        full = verify_full_repair_qualification(
            mapped(qualification.full_repair_aggregate),
            mapped(qualification.full_repair_inventory),
            config,
            artifacts=artifacts,
        )
        environment = verify_environment_qualification_evidence(
            qualification.environment_qualification_aggregate,
            qualification.environment_qualification_inventory,
            config,
            artifacts=artifacts,
        )
        after = verify_descendant_qualification_receipt(
            config.current_checkout_root,
            config.descendant_repository_receipt,
            pack=source,
            config=config,
            artifacts=artifacts,
        )
        if after != receipt:
            _fail()
        _normative_descendant(config, after, artifacts)
        if files != _walk(source, strict_directories=True):
            _fail()
        for physical, snapshot in snapshots.items():
            if (_regular_bytes(physical), stat.S_IMODE(physical.lstat().st_mode)) != snapshot:
                _fail()
        load_sealed_assembly_context(
            destination,
            destination / CONFIG_COPY,
            str(config.source_path),
            retained_manifest,
            retained_root,
        )
        check_owned()
        return {
            "result": "PASS",
            "production_authority": "NONE",
            "file_count": len(named),
            "files": sorted(named),
            "retained_file_count": len(entries),
            "full_repair": full,
            "environment_qualification": environment,
        }
    except Exception as error:
        if owned_identity is not None:
            try:
                info = destination.lstat()
                if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == owned_identity:
                    shutil.rmtree(destination)
            except OSError:
                pass
        raise ValueError("E_REVIEW_PACK_ASSEMBLY") from error


def _walk(root: Path, *, strict_directories: bool = False) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("E_REVIEW_PACK_ASSEMBLY")
    files: list[Path] = []
    for directory, directory_names, names in os.walk(root, followlinks=False):
        base = Path(directory)
        if base.is_symlink():
            raise ValueError("E_REVIEW_PACK_ASSEMBLY")
        if strict_directories and any((base / name).is_symlink() for name in directory_names):
            _fail()
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


def assemble_review_pack(
    source: Path,
    destination: Path,
    config: FullVerifierConfig | None = None,
    *,
    retained_manifest: Path | None = None,
    retained_root: Path | None = None,
) -> dict[str, object]:
    if config is not None or retained_manifest is not None or retained_root is not None:
        if (
            not isinstance(config, FullVerifierConfig)
            or retained_manifest is None
            or retained_root is None
        ):
            _fail()
        return _current_assembly(source, destination, config, retained_manifest, retained_root)
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
    parser.add_argument("--config", type=Path)
    parser.add_argument("--retained-manifest", type=Path)
    parser.add_argument("--retained-root", type=Path)
    args = parser.parse_args()
    try:
        config = load_controller_config(args.config) if args.config is not None else None
        print(
            assemble_review_pack(
                args.source,
                args.destination,
                config,
                retained_manifest=args.retained_manifest,
                retained_root=args.retained_root,
            )
        )
    except (OSError, ValueError) as error:
        raise ValueError("E_REVIEW_PACK_ASSEMBLY") from error


if __name__ == "__main__":
    main()
