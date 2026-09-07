"""Validate that every promised control has a mechanical proof binding."""

# ruff: noqa: I001
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.retained_artifact_io import RetainedArtifactIO

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from tools.full_verifier_config import FullVerifierConfig, load_controller_config  # noqa: E402


_REQUIRED = {
    "requirement_id",
    "implementation_symbol",
    "test_file",
    "vector_ids",
    "command_id",
    "evidence_artifact",
    "release_gate",
    "stage",
    "evidence_owner",
    "verification_kind",
}


def _mapped(path: Path, artifacts: RetainedArtifactIO | None) -> Path:
    if artifacts is None:
        return path
    recorded = str(path)
    return artifacts.physical_path(
        recorded, recorded_boundary=artifacts.recorded_boundary(recorded)
    )


def _verify_full_repair_proof(
    command_id: object,
    evidence: dict[str, object],
    config: FullVerifierConfig,
    artifacts: RetainedArtifactIO | None,
) -> None:
    if command_id not in {"TEST_V636_P03_T07", "TEST_V636_P04_T04"}:
        return
    if config.qualification_evidence is None:
        raise ValueError("E_PROOF_COVERAGE")
    from tools.verify_full_repair_qualification import verify_full_repair_qualification

    qualification = config.qualification_evidence
    expected = verify_full_repair_qualification(
        _mapped(qualification.full_repair_aggregate, artifacts),
        _mapped(qualification.full_repair_inventory, artifacts),
        config,
        artifacts=artifacts,
    )
    if command_id == "TEST_V636_P04_T04":
        if evidence != expected:
            raise ValueError("E_PROOF_COVERAGE")
        return
    p03 = {
        **expected,
        "schema_version": "full-repair-qualification/v1",
        "clock_proof_pending": True,
    }
    if evidence != p03:
        raise ValueError("E_PROOF_COVERAGE")


def verify_proof_coverage_matrix(
    matrix: dict[str, object],
    evidence_root: Path | None = None,
    stage: str | None = None,
    config: FullVerifierConfig | None = None,
    *,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, object]:
    structural = evidence_root is None and stage is None and config is None and artifacts is None
    if not structural and (
        evidence_root is None
        or stage not in {"CANDIDATE", "SEALED"}
        or config is None
        or config.schema_version != "full-verifier-controller/v2"
        or (stage == "SEALED" and artifacts is None)
    ):
        raise ValueError("E_PROOF_COVERAGE")
    entries = matrix.get("entries")
    if not isinstance(entries, list) or len(entries) != 18:
        raise ValueError("E_PROOF_COVERAGE")
    identifiers: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not set(entry) >= _REQUIRED:
            raise ValueError("E_PROOF_COVERAGE")
        requirement = entry["requirement_id"]
        if (
            not isinstance(requirement, str)
            or not requirement
            or requirement in identifiers
            or not isinstance(entry["implementation_symbol"], str)
            or "::" not in entry["implementation_symbol"]
            or not isinstance(entry["test_file"], str)
            or not entry["test_file"]
            or not isinstance(entry["vector_ids"], list)
            or not entry["vector_ids"]
            or any(not isinstance(vector, str) or not vector for vector in entry["vector_ids"])
            or any(
                not isinstance(entry[key], str) or not entry[key]
                for key in _REQUIRED
                - {"vector_ids", "requirement_id", "implementation_symbol", "test_file"}
            )
        ):
            raise ValueError("E_PROOF_COVERAGE")
        identifiers.add(requirement)
    if evidence_root is not None:
        if stage not in {"CANDIDATE", "SEALED"}:
            raise ValueError("E_PROOF_COVERAGE")
        verified: list[dict[str, str]] = []
        for entry in entries:
            if entry["stage"] != "CANDIDATE" or (stage == "CANDIDATE" and entry["stage"] != stage):
                continue
            if stage == "CANDIDATE":
                prefix = (
                    "/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/"
                )
                artifact = entry["evidence_artifact"]
                if not isinstance(artifact, str):
                    raise ValueError("E_PROOF_COVERAGE")
                if artifacts is not None:
                    path = Path(artifact)
                elif artifact.startswith(prefix):
                    path = evidence_root / artifact.removeprefix(prefix)
                elif config is not None and Path(artifact).is_relative_to(config.evidence_root):
                    path = Path(artifact)
                else:
                    raise ValueError("E_PROOF_COVERAGE")
            else:
                sealed = entry.get("sealed_evidence_path")
                if not isinstance(sealed, str) or not sealed.startswith("evidence/"):
                    raise ValueError("E_PROOF_COVERAGE")
                path = evidence_root.parent / sealed
            try:
                raw = (
                    artifacts.read_bytes(
                        str(path),
                        recorded_boundary=artifacts.recorded_boundary(str(path)),
                    )
                    if artifacts is not None
                    else path.read_bytes()
                )
                evidence = json.loads(raw)
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("E_PROOF_COVERAGE") from error
            if (
                not isinstance(evidence, dict)
                or evidence.get("result") != "PASS"
                or (config is not None and evidence.get("controller_binding") != config.binding())
            ):
                raise ValueError("E_PROOF_COVERAGE")
            if config is not None:
                _verify_full_repair_proof(entry["command_id"], evidence, config, artifacts)
            verified.append(
                {
                    "requirement_id": str(entry["requirement_id"]),
                    "path": str(path),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    result: dict[str, object] = {"result": "PASS", "control_count": len(entries)}
    if config is not None:
        result.update(
            schema_version="proof-coverage-result/v2",
            production_authority="NONE",
            controller_binding=config.binding(),
            evidence=verified,
        )
    return result


def _verify_sealed_inputs(
    matrix: Path, attestation_path: Path, zip_path: Path, sidecar: Path
) -> None:
    from tools.compute_governed_content_root import compute_governed_content_root
    from tools.seal_review_pack import seal_review_pack

    pack = matrix.parents[2]
    try:
        attestation = json.loads(attestation_path.read_text())
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        if (
            not isinstance(attestation, dict)
            or attestation.get("schema_version") != "external-seal-attestation/v6"
            or attestation.get("artifact_type") != "RUNTIME_PACK"
            or attestation.get("authorized_production_phases") != "NONE"
            or attestation.get("zip_sha256") != digest
            or sidecar.read_text() != f"{digest}  {zip_path.name}\n"
        ):
            raise ValueError("E_PROOF_COVERAGE")
        datetime.fromisoformat(str(attestation["created_at"]).replace("Z", "+00:00"))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            rebuilt_pack = root / pack.name
            shutil.copytree(pack, rebuilt_pack)
            compute_governed_content_root(
                rebuilt_pack, rebuilt_pack / "docs/registries/seal-exclusions.v1.json"
            )
            rebuilt_zip = root / zip_path.name
            rebuilt_attestation = root / attestation_path.name
            expected = seal_review_pack(
                rebuilt_pack,
                rebuilt_zip,
                root / sidecar.name,
                rebuilt_attestation,
            )
            expected["created_at"] = attestation["created_at"]
            if expected != attestation or rebuilt_zip.read_bytes() != zip_path.read_bytes():
                raise ValueError("E_PROOF_COVERAGE")
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("E_PROOF_COVERAGE") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--stage")
    parser.add_argument("--attestation", type=Path)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_controller_config(args.config) if args.config else None
    if args.stage == "CANDIDATE" and (config is None or args.output is None):
        raise ValueError("E_PROOF_COVERAGE")
    result = verify_proof_coverage_matrix(
        json.loads(args.matrix.read_text()), args.evidence_root, args.stage, config
    )
    seal_inputs = (args.attestation, args.zip_path, args.sidecar)
    if args.stage == "SEALED":
        if not all(value is not None for value in seal_inputs):
            raise ValueError("E_PROOF_COVERAGE")
        _verify_sealed_inputs(args.matrix, args.attestation, args.zip_path, args.sidecar)
    elif any(value is not None for value in seal_inputs):
        raise ValueError("E_PROOF_COVERAGE")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
