"""Run the full durability campaign once and retain its closed evidence closure."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from tools.full_verifier_config import FullVerifierConfig, load_controller_config
from tools.retained_artifact_io import canonical_recorded_locator

_BROWSER_MODULES = {
    "indexeddb-crash-child.js",
    "repair-probe.js",
    "src/canonical.js",
    "src/canonicalize.js",
    "src/errors.js",
    "src/spool.js",
    "src/storage/durable_idb.js",
    "src/offline/validators.js",
}
_GRAPH_OWNER_SCOPES = {
    "BROWSER_LOOPBACK_ACK",
    "INDEXEDDB_SPOOL_ONLY",
    "DISPOSABLE_DESTRUCTION",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_closed_inventory(
    aggregate_path: Path,
    campaign: Path,
    inventory_path: Path,
    config: FullVerifierConfig,
) -> dict[str, object]:
    if config.qualification_evidence is None:
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    recorded_aggregate = config.qualification_evidence.full_repair_aggregate
    aggregate = json.loads(aggregate_path.read_text())
    sources = [
        (aggregate_path, str(recorded_aggregate), str(recorded_aggregate.parent)),
        *collect_retained_sources(
            aggregate,
            retained_boundaries=(campaign,),
            live_roots=(Path(__file__).resolve().parents[1],),
        ),
    ]
    return write_closed_inventory(sources, inventory_path)


def _artifact_references(value: object) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []

    def visit(item: object) -> None:
        if isinstance(item, dict):
            scope = item.get("qualification_scope")
            # run_indexeddb_crash_matrix shares its scope with its case records.
            campaign = (
                scope in {"BROWSER_LOOPBACK_ACK", "INDEXEDDB_SPOOL_ONLY"}
                and set(item) == {
                    "result", "executed_vector_ids", "records", "mutation_results",
                    "killed_child_count", "qualification_scope", "legacy_full_qualification",
                }
                and isinstance(item["records"], list)
                and isinstance(item["mutation_results"], list)
            )
            if scope in _GRAPH_OWNER_SCOPES and not campaign:
                execution_binding = item.get("typescript_execution_binding")
                modules = item.get("module_hashes")
                case_directory = item.get("case_directory")
                if (
                    not isinstance(case_directory, str)
                    or not isinstance(modules, dict)
                    or set(modules) != _BROWSER_MODULES
                    or any(not isinstance(value, str) for value in modules.values())
                    or execution_binding != {"before": modules, "after": modules}
                ):
                    raise ValueError("E_FULL_REPAIR_QUALIFICATION")
                extension = canonical_recorded_locator(case_directory) + "/test-extension"
                references.extend(
                    (extension + "/" + name, digest)
                    for name, digest in sorted(modules.items())
                )
            path = item.get("path")
            digest = item.get("sha256")
            if isinstance(path, str) and isinstance(digest, str):
                references.append((path, digest))
            elif isinstance(path, str) and isinstance(item.get("binary_sha256"), str):
                references.append((path, item["binary_sha256"]))
            for key, candidate in item.items():
                if key.endswith("_path") and isinstance(candidate, str):
                    paired = item.get(key.removesuffix("_path") + "_sha256")
                    if isinstance(paired, str):
                        references.append((candidate, paired))
                visit(candidate)
        elif isinstance(item, list):
            for candidate in item:
                visit(candidate)

    visit(value)
    return references


def collect_retained_sources(
    value: object,
    *,
    retained_boundaries: tuple[Path, ...],
    live_roots: tuple[Path, ...],
) -> list[tuple[Path, str, str]]:
    """Select only recursively referenced artifacts and verify live exclusions."""
    declarations = retained_artifact_declarations(
        value, retained_boundaries=retained_boundaries, live_roots=live_roots
    )
    selected: list[tuple[Path, str, str]] = []
    for locator, boundary, digest in declarations:
        source = Path(locator)
        try:
            info = source.lstat()
            data = source.read_bytes()
        except OSError as error:
            raise ValueError("E_FULL_REPAIR_QUALIFICATION") from error
        if (
            source.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or hashlib.sha256(data).hexdigest() != digest
        ):
            raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        selected.append((source, locator, boundary))
    return selected


def retained_artifact_declarations(
    value: object,
    *,
    retained_boundaries: tuple[Path | str, ...],
    live_roots: tuple[Path, ...],
) -> list[tuple[str, str, str]]:
    """Derive the exact retained locator/boundary/hash set without opening it."""
    retained = [
        canonical_recorded_locator(str(path.resolve()) if isinstance(path, Path) else path)
        for path in retained_boundaries
    ]
    live = [canonical_recorded_locator(str(path.resolve())) for path in live_roots]
    selected: dict[str, tuple[str, str, str]] = {}
    for raw_locator, digest in _artifact_references(value):
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        locator = canonical_recorded_locator(raw_locator)
        matching_retained = [root for root in retained if Path(locator).is_relative_to(root)]
        matching_live = [root for root in live if Path(locator).is_relative_to(root)]
        source = Path(locator)
        if matching_retained:
            boundary = max(matching_retained, key=len)
        elif matching_live:
            try:
                if (
                    not source.resolve(strict=True).is_file()
                    or hashlib.sha256(source.read_bytes()).hexdigest() != digest
                ):
                    raise ValueError("E_FULL_REPAIR_QUALIFICATION")
            except OSError as error:
                raise ValueError("E_FULL_REPAIR_QUALIFICATION") from error
            continue
        else:
            raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        prior = selected.get(locator)
        current = (locator, boundary, digest)
        if prior is not None and prior != current:
            raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        selected[locator] = current
    return [row for _, row in sorted(selected.items())]


def validate_inventory_closure(
    manifest: object,
    value: object,
    *,
    aggregate_locator: str,
    aggregate_raw: bytes,
    live_roots: tuple[Path, ...],
) -> None:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    boundaries = manifest.get("recorded_boundaries")
    if not isinstance(boundaries, list):
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    declarations = retained_artifact_declarations(
        value,
        retained_boundaries=tuple(str(item) for item in boundaries),
        live_roots=live_roots,
    )
    expected = {
        canonical_recorded_locator(aggregate_locator): hashlib.sha256(aggregate_raw).hexdigest(),
        **{locator: digest for locator, _boundary, digest in declarations},
    }
    rows = manifest["files"]
    actual = {
        canonical_recorded_locator(row["recorded_locator"]): row["sha256"]
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("recorded_locator"), str)
        and isinstance(row.get("sha256"), str)
    }
    if len(actual) != len(rows) or actual != expected:
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")


def write_closed_inventory(
    sources: list[tuple[Path, str, str]], inventory_path: Path
) -> dict[str, object]:
    closure = inventory_path.parent / "retained"
    closure.mkdir(parents=False, exist_ok=False)
    rows: list[dict[str, object]] = []
    seen: dict[str, tuple[str, bytes, Path]] = {}
    for source, recorded, boundary in sources:
        canonical_recorded = canonical_recorded_locator(recorded)
        canonical_boundary = canonical_recorded_locator(boundary)
        try:
            info = source.lstat()
        except OSError as error:
            raise ValueError("E_FULL_REPAIR_QUALIFICATION") from error
        if source.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        data = source.read_bytes()
        prior = seen.get(canonical_recorded)
        identity = (canonical_boundary, data, source.resolve())
        if prior is not None:
            if prior != identity:
                raise ValueError("E_FULL_REPAIR_QUALIFICATION")
            continue
        seen[canonical_recorded] = identity
        relative = f"files/{_sha(canonical_recorded.encode())}.bin"
        target = closure / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows.append(
            {
                "recorded_locator": canonical_recorded,
                "recorded_boundary": canonical_boundary,
                "copied_relative_path": relative,
                "size_bytes": len(data),
                "sha256": _sha(data),
            }
        )
    manifest: dict[str, object] = {
        "schema_version": "retained-artifact-manifest/v1",
        "recorded_boundaries": sorted({str(row["recorded_boundary"]) for row in rows}),
        "files": sorted(rows, key=lambda row: str(row["recorded_locator"]).encode()),
    }
    with inventory_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    return manifest


def run_full_repair_qualification(
    config: FullVerifierConfig,
    aggregate_path: Path,
    inventory_path: Path,
    proof_path: Path,
) -> dict[str, object]:
    from tools.run_indexeddb_crash_matrix import run_full_repair_evidence
    from tools.verify_full_repair_qualification import verify_full_repair_qualification

    if (
        config.schema_version != "full-verifier-controller/v2"
        or config.qualification_evidence is None
        or aggregate_path != config.qualification_evidence.full_repair_aggregate
        or inventory_path != config.qualification_evidence.full_repair_inventory
        or proof_path != config.qualification_evidence.p03_proof
        or any(path.exists() for path in (aggregate_path, inventory_path, proof_path))
    ):
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    campaign = aggregate_path.parent / "campaign"
    if campaign.exists() or (inventory_path.parent / "retained").exists():
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    aggregate = run_full_repair_evidence(
        Path(__file__).resolve().parents[1] / "vendor/hybrid-discovery-v6.3.6",
        Path(__file__).resolve().parents[1],
        campaign,
        browser_binary=config.chrome_path,
    )
    if aggregate.get("result") != "PASS":
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    aggregate_path.write_text(
        json.dumps(aggregate, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    _write_closed_inventory(aggregate_path, campaign, inventory_path, config)
    retained_aggregate = (
        inventory_path.parent / "retained/files" / (_sha(str(aggregate_path).encode()) + ".bin")
    )
    proof = verify_full_repair_qualification(retained_aggregate, inventory_path, config)
    record = {
        **proof,
        "schema_version": "full-repair-qualification/v1",
        "clock_proof_pending": True,
    }
    with proof_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--aggregate", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--proof", required=True, type=Path)
    args = parser.parse_args()
    config = load_controller_config(args.config)
    result = run_full_repair_qualification(config, args.aggregate, args.inventory, args.proof)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
