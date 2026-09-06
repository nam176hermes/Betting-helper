import hashlib
import json
from pathlib import Path

from tools.build_self_review import build_runtime_self_review
from tools.compute_governed_content_root import compute_governed_content_root
from tools.seal_review_pack import seal_review_pack
from tools.verify_proof_coverage import _verify_sealed_inputs


def test_independent_rebuild_is_byte_identical_and_external_attestation_matches(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    (pack / "docs/registries").mkdir(parents=True)
    (pack / "docs/receipts").mkdir(parents=True)
    (pack / "docs/tasks").mkdir(parents=True)
    (pack / "docs/tasks/task-manifest.v6.3.6.json").write_text("{}\n")
    registry = pack / "docs/registries/seal-exclusions.v1.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "seal-exclusions/v2",
                "governed_root_exclusions": [
                    "GOVERNED_CONTENT_ROOT.json",
                    "SELF_REVIEW_REPORT.md",
                    "SELF_REVIEW_REPORT.json",
                    "MANIFEST_SHA256.json",
                ],
                "external_outputs_must_be_outside_root": True,
            }
        )
    )
    matrix = pack / "docs/registries/proof-coverage-matrix.v1.json"
    matrix.write_text("{}\n")
    receipt = pack / "docs/receipts/repo0-baseline-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "repo0-baseline-receipt/v2",
                "production_authority": "NONE",
                "baseline_commit": "a" * 40,
                "baseline_tree": "b" * 40,
                "baseline_file_root_sha256": "c" * 64,
                "candidate_qualification_sha256": "d" * 64,
                "command_result_root": "e" * 64,
                "candidate_command_evidence_sha256": "f" * 64,
                "baseline_registry_sha256": "0" * 64,
                "toolchain_versions": {"node": "v22.23.0"},
                "lockfile_hashes": {"uv_lock_sha256": "1" * 64},
                "vendor_root_sha256": "2" * 64,
                "normative_source_map_sha256": "3" * 64,
                "normative_source_set_root": "4" * 64,
                "normative_source_set_count": "106",
            }
        )
    )
    root = compute_governed_content_root(pack, registry)
    assert root["file_count"] == 4
    build_runtime_self_review(pack / "GOVERNED_CONTENT_ROOT.json", receipt, pack)

    first = seal_review_pack(
        pack, tmp_path / "one.zip", tmp_path / "one.sha256", tmp_path / "one.json"
    )
    second = seal_review_pack(
        pack, tmp_path / "two.zip", tmp_path / "two.sha256", tmp_path / "two.json"
    )

    assert (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()
    assert first["zip_sha256"] == hashlib.sha256((tmp_path / "one.zip").read_bytes()).hexdigest()
    assert second["manifest_sha256"] == first["manifest_sha256"]
    _verify_sealed_inputs(
        matrix, tmp_path / "one.json", tmp_path / "one.zip", tmp_path / "one.sha256"
    )
