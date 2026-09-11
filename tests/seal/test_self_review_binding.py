import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.seal.test_pack_assembly import current_chain as current_chain
from tools.build_self_review import build_runtime_self_review


@pytest.fixture
def descendant_pack(current_chain: dict[str, Any]) -> dict[str, Any]:
    """TEST_ONLY binding fixture; full/environment semantics are named fixed seams."""
    from tests.seal.test_pack_assembly import _assemble, _load
    from tools.compute_governed_content_root import compute_governed_content_root

    chain = current_chain
    pack = chain["directory"] / "review-pack"
    _assemble(chain, pack)
    config, artifacts = _load(chain, pack)
    root = compute_governed_content_root(pack, pack / "docs/registries/seal-exclusions.v1.json")
    return {
        **chain,
        "pack": pack,
        "copied_config": config,
        "artifacts": artifacts,
        "governed": root,
    }


def test_descendant_builder_binds_real_recorded_receipt(descendant_pack: dict[str, Any]) -> None:
    chain = descendant_pack
    pack = chain["pack"]
    receipt = pack / "docs/receipts/descendant-repository-qualification-receipt.json"
    result = build_runtime_self_review(
        pack / "GOVERNED_CONTENT_ROOT.json",
        receipt,
        pack,
        config=chain["copied_config"],
        artifacts=chain["artifacts"],
    )
    assert result == {
        "schema_version": "runtime-self-review/v2",
        "governed_content_root": chain["governed"]["root_sha256"],
        "repository_qualification_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "candidate_qualification_sha256": chain["receipt"]["candidate_qualification_sha256"],
        "task_manifest_sha256": hashlib.sha256(
            (pack / "docs/tasks/task-manifest.v6.3.6.json").read_bytes()
        ).hexdigest(),
        "command_result_root": chain["receipt"]["command_result_root"],
        "repository_identity_kind": "DESCENDANT",
        "repository_commit_oid": chain["receipt"]["repository_commit"],
        "repository_tree_oid": chain["receipt"]["repository_tree"],
        "repository_file_tree_root_sha256": chain["receipt"]["repository_file_root_sha256"],
        "checks": [{"check_id": "NO_FUTURE_SEAL_IDENTITY", "result": "PASS"}],
        "authority_granted": "NONE",
    }
    assert json.loads((pack / "SELF_REVIEW_REPORT.json").read_bytes()) == result


def test_registered_descendant_self_review_argv_emits_exact_v2(
    descendant_pack: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import build_self_review

    chain, pack = descendant_pack, descendant_pack["pack"]
    registry = json.loads((pack / "docs/registries/task-command-registry.v1.json").read_bytes())
    row = next(row for row in registry["commands"] if row["command_id"] == "VERIFY_V636_P09_T03")
    argv = row["argv"][row["argv"].index("tools/build_self_review.py"):]
    values = {
        "--governed-root": pack / "GOVERNED_CONTENT_ROOT.json",
        "--repository-receipt": pack
        / "docs/receipts/descendant-repository-qualification-receipt.json",
        "--output-dir": pack,
        "--config": pack / "docs/configs/full-verifier-controller.v2.json",
        "--recorded-config": chain["config"].source_path,
        "--retained-manifest": pack / "evidence/retained-artifact-manifest.json",
        "--retained-root": pack / "evidence/retained",
    }
    for flag, value in values.items():
        argv[argv.index(flag) + 1] = str(value)
    monkeypatch.setattr("sys.argv", argv)
    build_self_review.main()
    assert (
        json.loads((pack / "SELF_REVIEW_REPORT.json").read_bytes())["schema_version"]
        == "runtime-self-review/v2"
    )


@pytest.mark.parametrize("field", ["root_sha256", "file_count"])
def test_descendant_builder_recomputes_governed_record_before_writing(
    descendant_pack: dict[str, Any],
    field: str,
) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    path = pack / "GOVERNED_CONTENT_ROOT.json"
    record = json.loads(path.read_bytes())
    record[field] = "a" * 64 if field == "root_sha256" else record[field] + 1
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="E_SELF_REVIEW_BINDING"):
        build_runtime_self_review(
            path,
            pack / "docs/receipts/descendant-repository-qualification-receipt.json",
            pack,
            config=chain["copied_config"],
            artifacts=chain["artifacts"],
        )
    assert not (pack / "SELF_REVIEW_REPORT.json").exists()
    assert not (pack / "SELF_REVIEW_REPORT.md").exists()


def test_self_review_does_not_bind_future_manifest_zip_or_sidecar(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    (pack / "docs/tasks").mkdir(parents=True)
    (pack / "docs/tasks/task-manifest.v6.3.6.json").write_text("{}\n")
    root = pack / "GOVERNED_CONTENT_ROOT.json"
    root.write_text(
        json.dumps(
            {
                "schema_version": "governed-content-root/v1",
                "algorithm": "HD636-GOVERNED-ROOT-SHA256-v1",
                "root_sha256": "a" * 64,
            }
        )
    )
    receipt = tmp_path / "repo0.json"
    receipt.write_text(
        json.dumps(
            {
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
            }
        )
    )

    record = build_runtime_self_review(root, receipt, pack)

    assert set(record) == {
        "schema_version",
        "governed_content_root",
        "repo0_receipt_sha256",
        "candidate_qualification_sha256",
        "task_manifest_sha256",
        "command_result_root",
        "checks",
        "authority_granted",
    }
    assert record["repo0_receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert "MANIFEST_SHA256.json" not in (pack / "SELF_REVIEW_REPORT.json").read_text()


def test_builder_cli_rejects_ambiguous_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.seal.test_deterministic_seal import _legacy_pack
    from tools import build_self_review

    pack, _matrix = _legacy_pack(tmp_path)
    argv = [
        "builder",
        "--governed-root",
        str(pack / "GOVERNED_CONTENT_ROOT.json"),
        "--repo0-receipt",
        str(pack / "docs/receipts/repo0-baseline-receipt.json"),
        "--output-dir",
        str(pack),
    ]
    for suffix in (["--repository-receipt", "other"], ["--input", "plan", "--output", "other"]):
        monkeypatch.setattr("sys.argv", [*argv, *suffix])
        with pytest.raises(SystemExit) as error:
            build_self_review.main()
        assert error.value.code == 2
    monkeypatch.setattr("sys.argv", ["builder"])
    with pytest.raises(SystemExit) as error:
        build_self_review.main()
    assert error.value.code == 2


def test_descendant_builder_rejects_absent_context_and_named_receipt_changes(
    descendant_pack: dict[str, Any],
) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    receipt = pack / "docs/receipts/descendant-repository-qualification-receipt.json"
    original = receipt.read_bytes()
    for damage in ("no-context", "config-only", "artifacts-only", "named-copy", "missing"):
        context = {"config": chain["copied_config"], "artifacts": chain["artifacts"]}
        if damage == "no-context":
            context = {}
        elif damage == "config-only":
            del context["artifacts"]
        elif damage == "artifacts-only":
            del context["config"]
        elif damage == "named-copy":
            receipt.write_bytes(original + b"\n")
        else:
            receipt.unlink()
        try:
            with pytest.raises(ValueError, match="^E_SELF_REVIEW_BINDING$"):
                build_runtime_self_review(
                    pack / "GOVERNED_CONTENT_ROOT.json", receipt, pack, **context
                )
            assert not (pack / "SELF_REVIEW_REPORT.json").exists()
            assert not (pack / "SELF_REVIEW_REPORT.md").exists()
        finally:
            receipt.write_bytes(original)
