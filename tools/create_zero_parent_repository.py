"""Create the one-commit, no-remote delivery repository."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def _git(root: Path, *arguments: str) -> str:
    environment = {
        "GIT_AUTHOR_EMAIL": "hybrid-discovery@localhost",
        "GIT_AUTHOR_NAME": "Hybrid Discovery",
        "GIT_COMMITTER_EMAIL": "hybrid-discovery@localhost",
        "GIT_COMMITTER_NAME": "Hybrid Discovery",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(root),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
    }
    result = subprocess.run(  # noqa: S603 - fixed Git executable and argv
        ["/usr/bin/git", "-C", str(root), *arguments],
        capture_output=True,
        env=environment,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError("E_ZERO_PARENT_REPOSITORY")
    return result.stdout.strip()


def create_zero_parent_repository(root: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir() or (root / ".git").exists():
        raise ValueError("E_ZERO_PARENT_REPOSITORY")
    source_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    if not source_paths or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("E_ZERO_PARENT_REPOSITORY")
    _git(root, "init", "--initial-branch=main")
    _git(root, "add", "--force", "--", *source_paths)
    if _git(root, "ls-files").splitlines() != source_paths:
        raise ValueError("E_ZERO_PARENT_REPOSITORY")
    if not _git(root, "status", "--porcelain"):
        raise ValueError("E_ZERO_PARENT_REPOSITORY")
    _git(root, "commit", "--no-gpg-sign", "-m", "Hybrid Discovery v6.3.6 baseline")
    head = _git(root, "rev-parse", "HEAD")
    roots = _git(root, "rev-list", "--max-parents=0", "HEAD").splitlines()
    commits = _git(root, "rev-list", "--count", "HEAD")
    if (
        roots != [head]
        or commits != "1"
        or _git(root, "remote")
        or _git(root, "status", "--porcelain")
    ):
        raise ValueError("E_ZERO_PARENT_REPOSITORY")
    return {"result": "PASS", "commit": head}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(create_zero_parent_repository(args.root), sort_keys=True))


if __name__ == "__main__":
    main()
