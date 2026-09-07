"""A descendant receipt preserves ancestry without recreating BOOT0."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tools.qualify_descendant_repository import descendant_repository_identity


def _commit(root: Path, name: str, value: str) -> str:
    (root / name).write_text(value)
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "add", name], cwd=root, check=True, capture_output=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [git, "commit", "-m", name], cwd=root, check=True, capture_output=True
    )
    return subprocess.check_output(  # noqa: S603
        [git, "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def test_descendant_identity_accepts_clean_multi_commit_history_and_rejects_drift(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    assert git is not None
    root = tmp_path / "runtime"
    root.mkdir()
    subprocess.run(  # noqa: S603
        [git, "init", "-b", "main"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603
        [git, "config", "user.name", "Descendant Test"], cwd=root, check=True
    )
    subprocess.run(  # noqa: S603
        [git, "config", "user.email", "descendant@example.invalid"],
        cwd=root,
        check=True,
    )
    ancestor = _commit(root, "audited.txt", "audited")
    descendant = _commit(root, "repair.txt", "repair")

    identity = descendant_repository_identity(root, ancestor)
    assert identity["repository_commit"] == descendant
    assert identity["repository_commit"] != ancestor
    assert len(identity["repository_file_root_sha256"]) == 64

    (root / "untracked.txt").write_text("dirty")
    with pytest.raises(ValueError, match="E_DESCENDANT_REPOSITORY"):
        descendant_repository_identity(root, ancestor)
    (root / "untracked.txt").unlink()
    with pytest.raises(ValueError, match="E_DESCENDANT_REPOSITORY"):
        descendant_repository_identity(root, "f" * 40)


def test_receipt_exclusive_create_failure_never_removes_competing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.qualify_descendant_repository as qualifier

    output = tmp_path / "receipt.json"
    competitor = b"competitor\n"

    def record(*_args: object) -> dict[str, object]:
        output.write_bytes(competitor)
        return {"schema_version": "test"}

    monkeypatch.setattr(qualifier, "_outside_protected", lambda *_args: None)
    monkeypatch.setattr(qualifier, "_receipt_record", record)
    with pytest.raises(FileExistsError):
        qualifier.issue_descendant_qualification_receipt(tmp_path, object(), output)  # type: ignore[arg-type]
    assert output.read_bytes() == competitor


def test_receipt_post_write_replacement_is_not_unlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.qualify_descendant_repository as qualifier

    output = tmp_path / "receipt.json"
    competitor = b"replacement\n"
    calls = 0

    def record(*_args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            output.unlink()
            output.write_bytes(competitor)
            raise ValueError("post-write drift")
        return {"schema_version": "test"}

    monkeypatch.setattr(qualifier, "_outside_protected", lambda *_args: None)
    monkeypatch.setattr(qualifier, "_receipt_record", record)
    with pytest.raises(ValueError, match="post-write drift"):
        qualifier.issue_descendant_qualification_receipt(tmp_path, object(), output)  # type: ignore[arg-type]
    assert output.read_bytes() == competitor


def test_receipt_post_write_drift_removes_only_owned_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.qualify_descendant_repository as qualifier

    output = tmp_path / "receipt.json"
    values = iter(({"revision": "before"}, {"revision": "after"}))
    monkeypatch.setattr(qualifier, "_outside_protected", lambda *_args: None)
    monkeypatch.setattr(qualifier, "_receipt_record", lambda *_args: next(values))
    with pytest.raises(ValueError, match="E_DESCENDANT_REPOSITORY"):
        qualifier.issue_descendant_qualification_receipt(tmp_path, object(), output)  # type: ignore[arg-type]
    assert not output.exists()


def test_descendant_record_recursively_validates_full_and_supplemental_proofs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.qualify_descendant_repository as qualifier
    from tools.full_verifier_config import load_controller_config

    source_config = Path(
        "/home/thenam176/betting-helper/authoring-controller-config-worktree/pack/"
        "docs/configs/full-verifier-controller.v2.json"
    )
    original = load_controller_config(source_config)
    assert original.qualification_evidence is not None
    qualification = replace(
        original.qualification_evidence,
        full_repair_aggregate=tmp_path / "full.json",
        full_repair_inventory=tmp_path / "full-inventory.json",
        environment_qualification_aggregate=tmp_path / "environment.json",
        environment_qualification_inventory=tmp_path / "environment-inventory.json",
        p03_proof=tmp_path / "p03.json",
        p04_proof=tmp_path / "p04.json",
    )
    config = replace(original, qualification_evidence=qualification)
    full = {
        "schema_version": "full-repair-clock-proof/v1",
        "result": "PASS",
        "production_authority": "NONE",
        "controller_binding": config.binding(),
        "aggregate_sha256": "1" * 64,
        "evidence_root_sha256": "2" * 64,
        "control_count": 111,
        "clock_control_count": 65,
        "mutation_count": 105,
        "mutation_survivors": 0,
    }
    p03 = {**full, "schema_version": "full-repair-qualification/v1", "clock_proof_pending": True}
    evidence = {
        config.candidate_qualification_receipt: {"inventory": {}, "command_result_root": "x"},
        qualification.p03_proof: p03,
        qualification.p04_proof: full,
    }
    calls: list[str] = []
    monkeypatch.setattr(qualifier, "descendant_repository_identity", lambda *_args: {})
    monkeypatch.setattr(qualifier, "_read_evidence", lambda path, _artifacts=None: evidence[path])
    monkeypatch.setattr(
        qualifier, "validate_candidate_qualification_receipt", lambda *_a, **_k: None
    )
    monkeypatch.setattr(qualifier, "verify_toolchains", lambda: [])
    monkeypatch.setattr(qualifier, "_normative_source_set", lambda *_a, **_k: ("m", "s", "1"))
    monkeypatch.setattr(qualifier, "_regular_hash", lambda *_a, **_k: "3" * 64)
    monkeypatch.setattr(qualifier, "dependency_lock_hashes", lambda *_a: {})
    monkeypatch.setattr(qualifier, "compute_vendor_tree_root", lambda *_a: "4" * 64)
    monkeypatch.setattr(
        "tools.verify_full_repair_qualification.verify_full_repair_qualification",
        lambda *_a, **_k: calls.append("full") or full,
    )
    monkeypatch.setattr(
        "tools.run_environment_qualification.verify_environment_qualification_evidence",
        lambda *_a, **_k: calls.append("environment")
        or {"result": "PARTIAL_HOLD", "evidence_root_sha256": "5" * 64},
    )
    record = qualifier._receipt_record(tmp_path, config)
    assert calls == ["full", "environment"]
    assert record["full_repair_evidence_root_sha256"] == "2" * 64
    evidence[qualification.p04_proof] = {**full, "mutation_count": 104}
    with pytest.raises(ValueError, match="E_DESCENDANT_REPOSITORY"):
        qualifier._receipt_record(tmp_path, config)
