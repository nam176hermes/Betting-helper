import subprocess
from pathlib import Path

import pytest

import tools.assemble_review_pack as pack_assembly
from tools.assemble_review_pack import assemble_review_pack
from tools.qualify_zero_parent_baseline import _normative_source_set

RUNTIME = Path(__file__).resolve().parents[2]


def test_pack_inventory_has_no_external_review_or_final_seal_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "docs/prompts").mkdir(parents=True)
    (source / "docs/registries").mkdir(parents=True)
    (source / "docs/receipts").mkdir(parents=True)
    (source / "docs/prompts/review.md").write_text("review")
    (source / "docs/registries/normative-source-map.v1.json").write_text(
        """{"schema_version":"normative-source-map/v1","owner_phase":"MIG0","inherited_entries":[],"""
        """"plan_entries":[{"plan_source":"docs/prompts/review.md","vendor_relative":"docs/prompts/review.md"}]}"""
    )
    source_map, source_set, count = _normative_source_set(source)
    (source / "docs/receipts/repo0-baseline-receipt.json").write_text(
        f'{{"schema_version":"repo0-baseline-receipt/v2","normative_source_map_sha256":"{source_map}",'
        f'"normative_source_set_root":"{source_set}","normative_source_set_count":"{count}"}}'
    )
    result = assemble_review_pack(source, tmp_path / "review-pack")
    assert "docs/prompts/review.md" in result["files"]

    completed = subprocess.run(  # noqa: S603 - fixed local interpreter and argv
        [
            "/usr/bin/python3.12",
            "tools/assemble_review_pack.py",
            "--source",
            str(source),
            "--destination",
            str(tmp_path / "cli-review-pack"),
        ],
        cwd=RUNTIME,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode()

    (source / "MANIFEST_SHA256.json").write_text("forbidden")
    with pytest.raises(ValueError, match="E_REVIEW_PACK_ASSEMBLY"):
        assemble_review_pack(source, tmp_path / "second-pack")


def test_pack_copies_only_mapped_candidate_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    (source / "docs/registries").mkdir(parents=True)
    evidence.mkdir()
    (evidence / "proof.json").write_text('{"result":"PASS"}')
    (source / "docs/registries/proof-coverage-matrix.v1.json").write_text(
        '{"entries":[{"stage":"CANDIDATE","evidence_artifact":"'
        + str(evidence / "proof.json")
        + '","sealed_evidence_path":"evidence/proof.json"}]}'
    )
    monkeypatch.setattr(pack_assembly, "EVIDENCE_ROOT", evidence)

    copied = pack_assembly._copy_candidate_evidence(source, tmp_path / "destination")

    assert copied == ["evidence/proof.json"]
