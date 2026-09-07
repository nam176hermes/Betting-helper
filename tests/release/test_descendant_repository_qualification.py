"""A descendant receipt preserves ancestry without recreating BOOT0."""

from __future__ import annotations

import shutil
import subprocess
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
