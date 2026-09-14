from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> object:
    path = ROOT / "authoring-tools/issue_current_authoring_repository_receipt.py"
    spec = importlib.util.spec_from_file_location("current_receipt", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_receipt_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-b", "main"], ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"], ["commit", "--allow-empty", "-m", "fixture"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo, subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("damage", ["replacement", "symlink", "hardlink", "same-inode-bytes"])
@pytest.mark.parametrize("git_drift", [False, True])
def test_receipt_postwrite_identity_and_bytes_preserve_foreign_outputs(
    tmp_path: Path, clean_receipt_repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch,
    damage: str, git_drift: bool,
) -> None:
    tool = _load()
    repo, head = clean_receipt_repo
    output = tmp_path / "receipt.json"
    competitor = tmp_path / "competitor.json"
    competitor.write_bytes(b"competitor\n")
    original_git = tool._git
    calls = 0

    def git(root: Path, *args: str) -> str:
        nonlocal calls
        value = original_git(root, *args)
        if args == ("rev-parse", "HEAD"):
            calls += 1
            if calls == 2:
                if damage == "same-inode-bytes":
                    output.write_bytes(b"changed owned bytes\n")
                elif damage == "hardlink":
                    os.link(output, tmp_path / "owned-alias.json")
                else:
                    output.rename(tmp_path / "held-owned.json")
                    if damage == "symlink":
                        output.symlink_to(competitor)
                    else:
                        output.write_bytes(competitor.read_bytes())
                if git_drift:
                    return "0" * 40
        return value

    monkeypatch.setattr(tool, "_git", git)
    with pytest.raises(ValueError, match="^E_AUTHORING_RECEIPT$"):
        tool.issue_current_authoring_repository_receipt(repo, output, head)
    assert calls == 2
    assert competitor.read_bytes() == b"competitor\n"
    if damage == "same-inode-bytes":
        assert not output.exists()
    elif damage == "hardlink":
        assert output.stat().st_nlink == 2
    else:
        assert output.read_bytes() == competitor.read_bytes()
        assert output.is_symlink() == (damage == "symlink")


@pytest.mark.parametrize("failure", ["write", "fsync", "post-git"])
def test_receipt_failure_removes_only_its_owned_partial_file(
    tmp_path: Path, clean_receipt_repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    tool = _load()
    repo, head = clean_receipt_repo
    output = tmp_path / "receipt.json"
    calls = 0
    original_git = tool._git
    original_open = Path.open

    def fail(*_args: object) -> None:
        raise OSError("injected owned write/sync failure")

    class PartialWriter:
        def __init__(self, stream: object):
            self.stream = stream

        def fileno(self) -> int:
            return self.stream.fileno()

        def write(self, payload: str) -> None:
            self.stream.write(payload[:1])
            fail()

    @contextmanager
    def partial_open(path: Path, *args: object, **kwargs: object):
        with original_open(path, *args, **kwargs) as stream:
            yield PartialWriter(stream) if path == output and args[0] == "x" else stream

    def git(root: Path, *args: str) -> str:
        nonlocal calls
        if args == ("rev-parse", "HEAD"):
            calls += 1
            if calls == 2:
                raise ValueError("E_AUTHORING_RECEIPT")
        return original_git(root, *args)

    if failure == "write":
        monkeypatch.setattr(Path, "open", partial_open)
    elif failure == "fsync":
        monkeypatch.setattr(os, "fsync", fail)
    else:
        monkeypatch.setattr(tool, "_git", git)
    with pytest.raises(ValueError, match="^E_AUTHORING_RECEIPT$"):
        tool.issue_current_authoring_repository_receipt(repo, output, head)
    assert not output.exists()


def test_issues_descendant_receipt_without_initializing_or_mutating_git(tmp_path: Path) -> None:
    tool = _load()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "tracked").write_text("source")
    subprocess.run(["git", "-C", str(repo), "add", "tracked"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "descendant"], check=True, capture_output=True)
    before = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    output = tmp_path / "evidence/authoring.json"
    receipt = tool.issue_current_authoring_repository_receipt(repo, output, before)
    assert receipt["head"] == before
    assert receipt["tree"] == subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], check=True, capture_output=True, text=True).stdout.strip()
    assert json.loads(output.read_text()) == receipt
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip() == before
    with pytest.raises(ValueError, match="E_AUTHORING_RECEIPT"):
        tool.issue_current_authoring_repository_receipt(repo, output, before)


def test_rejects_dirty_or_non_repository_input(tmp_path: Path) -> None:
    tool = _load()
    with pytest.raises(ValueError, match="E_AUTHORING_RECEIPT"):
        tool.issue_current_authoring_repository_receipt(tmp_path, tmp_path / "out", "0" * 40)


def test_rejects_unrelated_repository_and_output_inside_checkout(tmp_path: Path) -> None:
    tool = _load()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "tracked").write_text("source")
    subprocess.run(["git", "-C", str(repo), "add", "tracked"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "unrelated"], check=True, capture_output=True)
    with pytest.raises(ValueError, match="E_AUTHORING_RECEIPT"):
        tool.issue_current_authoring_repository_receipt(repo, tmp_path / "outside.json", "0" * 40)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    with pytest.raises(ValueError, match="E_AUTHORING_RECEIPT"):
        tool.issue_current_authoring_repository_receipt(repo, repo / "receipt.json", head)
