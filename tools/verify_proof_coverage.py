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

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]


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


def verify_proof_coverage_matrix(
    matrix: dict[str, object], evidence_root: Path | None = None, stage: str | None = None
) -> dict[str, object]:
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
        for entry in entries:
            if entry["stage"] != "CANDIDATE" or (stage == "CANDIDATE" and entry["stage"] != stage):
                continue
            if stage == "CANDIDATE":
                prefix = (
                    "/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/"
                )
                artifact = entry["evidence_artifact"]
                if not isinstance(artifact, str) or not artifact.startswith(prefix):
                    raise ValueError("E_PROOF_COVERAGE")
                path = evidence_root / artifact.removeprefix(prefix)
            else:
                sealed = entry.get("sealed_evidence_path")
                if not isinstance(sealed, str) or not sealed.startswith("evidence/"):
                    raise ValueError("E_PROOF_COVERAGE")
                path = evidence_root.parent / sealed
            try:
                evidence = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("E_PROOF_COVERAGE") from error
            if not isinstance(evidence, dict) or evidence.get("result") != "PASS":
                raise ValueError("E_PROOF_COVERAGE")
    return {"result": "PASS", "control_count": len(entries)}


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
    args = parser.parse_args()
    result = verify_proof_coverage_matrix(
        json.loads(args.matrix.read_text()), args.evidence_root, args.stage
    )
    seal_inputs = (args.attestation, args.zip_path, args.sidecar)
    if args.stage == "SEALED":
        if not all(value is not None for value in seal_inputs):
            raise ValueError("E_PROOF_COVERAGE")
        _verify_sealed_inputs(args.matrix, args.attestation, args.zip_path, args.sidecar)
    elif any(value is not None for value in seal_inputs):
        raise ValueError("E_PROOF_COVERAGE")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
