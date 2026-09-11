"""Verify one immutable full111/105 aggregate through its closed artifact map."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any, cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from tools.full_verifier_config import FullVerifierConfig, load_controller_config
from tools.retained_artifact_io import RetainedArtifactIO


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("E_FULL_REPAIR_QUALIFICATION") from error
    if not isinstance(value, dict):
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    return cast(dict[str, Any], value)


def _load_inventory(path: Path) -> dict[str, object]:
    try:
        info = path.lstat()
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError("E_FULL_REPAIR_QUALIFICATION") from error
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    return cast(dict[str, object], _object(raw))


def _semantic_validation(aggregate: dict[str, Any], artifacts: RetainedArtifactIO) -> None:
    from moj_discovery.durability_release import validate_full_durability_release
    from tools.run_indexeddb_crash_matrix import validate_full_mutation_reports
    from tools.verify_repair_evidence import (
        _clock_validation_scope,
        aggregate_repair_evidence,
        full_required_ids,
    )

    required = full_required_ids()
    records = aggregate.get("records")
    owners = aggregate.get("owner_reports")
    clock = aggregate.get("clock_report")
    if not isinstance(records, list) or not isinstance(owners, dict) or not isinstance(clock, dict):
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    with _clock_validation_scope():
        replay = aggregate_repair_evidence(required, records, artifacts=artifacts)
        mutations = validate_full_mutation_reports(
            Path(__file__).resolve().parents[1] / "vendor/hybrid-discovery-v6.3.6",
            owners,
            clock,
            artifacts=artifacts,
        )
        release = validate_full_durability_release(
            required,
            required,
            mutation_survivors=0,
            evidence=records,
            mutation_summary=mutations,
            mutation_evidence={"owner_reports": owners, "clock_report": clock},
            artifacts=artifacts,
        )
        if (
            replay.get("result") != "PASS"
            or replay.get("status_counts") != {"PASS": 111}
            or mutations != {"required": 105, "verified": 105, "survivors": 0, "complete": True}
            or release.get("result") != "PASS"
            or aggregate.get("result") != "PASS"
            or aggregate.get("release_gate") != release
        ):
            raise ValueError("E_FULL_REPAIR_QUALIFICATION")


def verify_full_repair_qualification(
    aggregate_path: Path,
    inventory_path: Path,
    config: FullVerifierConfig,
    *,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, object]:
    manifest = _load_inventory(inventory_path)
    closure = inventory_path.parent / "retained"
    qualification = config.qualification_evidence
    recorded = (
        str(qualification.full_repair_aggregate)
        if qualification
        else ""
    )
    if not recorded:
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    try:
        active_artifacts = (
            RetainedArtifactIO.from_manifest(manifest, closure) if artifacts is None else artifacts
        )
        if artifacts is not None:
            assert qualification is not None
            recorded_inventory = str(qualification.full_repair_inventory)
            inventory_raw = artifacts.read_bytes(
                recorded_inventory,
                recorded_boundary=artifacts.recorded_boundary(recorded_inventory),
            )
            if _object(inventory_raw) != manifest:
                raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        boundary = active_artifacts.recorded_boundary(recorded)
        mapped = active_artifacts.physical_path(recorded, recorded_boundary=boundary)
        if aggregate_path == Path(recorded):
            if aggregate_path.read_bytes() != mapped.read_bytes():
                raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        elif aggregate_path.resolve(strict=True) != mapped.resolve(strict=True):
            raise ValueError("E_FULL_REPAIR_QUALIFICATION")
        raw = active_artifacts.read_bytes(recorded, recorded_boundary=boundary)
        aggregate = _object(raw)
        from tools.run_full_repair_qualification import validate_inventory_closure

        validate_inventory_closure(
            manifest,
            aggregate,
            aggregate_locator=recorded,
            aggregate_raw=raw,
            live_roots=(Path(__file__).resolve().parents[1],),
        )
        _semantic_validation(aggregate, active_artifacts)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError("E_FULL_REPAIR_QUALIFICATION") from error
    manifest_sha = hashlib.sha256(_canonical(manifest)).hexdigest()
    return {
        "schema_version": "full-repair-clock-proof/v1",
        "result": "PASS",
        "production_authority": "NONE",
        "controller_binding": config.binding(),
        "aggregate_sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_root_sha256": manifest_sha,
        "control_count": 111,
        "clock_control_count": 65,
        "mutation_count": 105,
        "mutation_survivors": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--aggregate", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = load_controller_config(args.config)
    if (
        config.qualification_evidence is None
        or args.aggregate != config.qualification_evidence.full_repair_aggregate
        or args.inventory != config.qualification_evidence.full_repair_inventory
        or args.output != config.qualification_evidence.p04_proof
        or args.output.exists()
    ):
        raise ValueError("E_FULL_REPAIR_QUALIFICATION")
    result = verify_full_repair_qualification(args.aggregate, args.inventory, config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
