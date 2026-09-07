"""Run the full durability campaign once and retain its closed evidence closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path

from tools.full_verifier_config import FullVerifierConfig, load_controller_config


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
    sources = [
        (aggregate_path, str(recorded_aggregate), str(recorded_aggregate.parent)),
        *[
            (path, str(path.resolve()), str(campaign.resolve()))
            for path in sorted(path for path in campaign.rglob("*") if path.is_file())
        ],
    ]
    return write_closed_inventory(sources, inventory_path)


def write_closed_inventory(
    sources: list[tuple[Path, str, str]], inventory_path: Path
) -> dict[str, object]:
    closure = inventory_path.parent / "retained"
    closure.mkdir(parents=False, exist_ok=False)
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for source, recorded, boundary in sources:
        try:
            info = source.lstat()
        except OSError as error:
            raise ValueError("E_FULL_REPAIR_QUALIFICATION") from error
        if source.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        if recorded in seen:
            continue
        seen.add(recorded)
        data = source.read_bytes()
        relative = f"files/{_sha(recorded.encode())}.bin"
        target = closure / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows.append(
            {
                "recorded_locator": recorded,
                "recorded_boundary": boundary,
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
