import hashlib
import json
from pathlib import Path

from tools.build_self_review import build_runtime_self_review


def test_self_review_does_not_bind_future_manifest_zip_or_sidecar(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    (pack / "docs/tasks").mkdir(parents=True)
    (pack / "docs/tasks/task-manifest.v6.3.6.json").write_text("{}\n")
    root = pack / "GOVERNED_CONTENT_ROOT.json"
    root.write_text(json.dumps({
        "schema_version": "governed-content-root/v1",
        "algorithm": "HD636-GOVERNED-ROOT-SHA256-v1",
        "root_sha256": "a" * 64,
    }))
    receipt = tmp_path / "repo0.json"
    receipt.write_text(json.dumps({
        "schema_version": "repo0-baseline-receipt/v2",
        "production_authority": "NONE",
        "baseline_commit": "b" * 40,
        "baseline_tree": "c" * 40,
        "baseline_file_root_sha256": "d" * 64,
        "candidate_qualification_sha256": "e" * 64,
        "candidate_command_evidence_sha256": "f" * 64,
        "command_result_root": "0" * 64,
        "baseline_registry_sha256": "1" * 64,
        "toolchain_versions": {"node": "v22.23.0"},
        "lockfile_hashes": {"uv_lock_sha256": "2" * 64},
        "vendor_root_sha256": "3" * 64,
        "normative_source_map_sha256": "4" * 64,
        "normative_source_set_root": "5" * 64,
        "normative_source_set_count": "106",
    }))

    record = build_runtime_self_review(root, receipt, pack)

    assert set(record) == {
        "schema_version", "governed_content_root", "repo0_receipt_sha256",
        "candidate_qualification_sha256", "task_manifest_sha256", "command_result_root",
        "checks", "authority_granted",
    }
    assert record["repo0_receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert "MANIFEST_SHA256.json" not in (pack / "SELF_REVIEW_REPORT.json").read_text()
