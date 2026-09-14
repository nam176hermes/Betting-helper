"""Issue a receipt for an existing clean descendant authoring repository.

This tool is deliberately read-only with respect to Git.  It never initializes,
checks out, resets, commits, or updates refs; its only write is a new external
receipt created with exclusive-create semantics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("E_AUTHORING_RECEIPT")
    result = subprocess.run(
        [executable, "-C", str(root), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise ValueError("E_AUTHORING_RECEIPT")
    return result.stdout.strip()


def issue_current_authoring_repository_receipt(
    root: Path, output: Path, accepted_ancestor: str
) -> dict[str, str]:
    try:
        canonical = root.resolve(strict=True)
    except OSError as error:
        raise ValueError("E_AUTHORING_RECEIPT") from error
    canonical_output = output.resolve(strict=False)
    if (
        root.is_symlink()
        or not canonical.is_dir()
        or canonical_output != output
        or canonical_output == canonical
        or canonical_output.is_relative_to(canonical)
        or canonical.is_relative_to(canonical_output)
        or re.fullmatch(r"[0-9a-f]{40}", accepted_ancestor) is None
    ):
        raise ValueError("E_AUTHORING_RECEIPT")
    if _git(canonical, "rev-parse", "--show-toplevel") != str(canonical):
        raise ValueError("E_AUTHORING_RECEIPT")
    status = _git(canonical, "status", "--porcelain", "--untracked-files=all")
    head = _git(canonical, "rev-parse", "HEAD")
    tree = _git(canonical, "rev-parse", "HEAD^{tree}")
    _git(canonical, "merge-base", "--is-ancestor", accepted_ancestor, head)
    if status or re.fullmatch(r"[0-9a-f]{40}", head) is None or re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise ValueError("E_AUTHORING_RECEIPT")
    receipt = {
        "schema_version": "current-authoring-repository-receipt/v1",
        "accepted_authoring_ancestor": accepted_ancestor,
        "root": str(canonical),
        "head": head,
        "tree": tree,
        "status": "",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    owned_identity: tuple[int, int] | None = None
    try:
        with output.open("x", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            owned_identity = (info.st_dev, info.st_ino)
            stream.write(encoded.decode())
            stream.flush()
            os.fsync(stream.fileno())
            if (
                _git(canonical, "rev-parse", "HEAD") != head
                or _git(canonical, "rev-parse", "HEAD^{tree}") != tree
                or _git(canonical, "status", "--porcelain", "--untracked-files=all")
            ):
                raise ValueError("E_AUTHORING_RECEIPT")
            for check in range(2):
                info = output.lstat()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != owned_identity
                    or check == 0 and output.read_bytes() != encoded
                ):
                    raise ValueError("E_AUTHORING_RECEIPT")
    except (OSError, ValueError) as error:
        if owned_identity is not None:
            try:
                info = output.lstat()
                if (
                    stat.S_ISREG(info.st_mode)
                    and info.st_nlink == 1
                    and (info.st_dev, info.st_ino) == owned_identity
                ):
                    output.unlink()
            except OSError:
                pass
        raise ValueError("E_AUTHORING_RECEIPT") from error
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--accepted-ancestor", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            issue_current_authoring_repository_receipt(
                args.root, args.output, args.accepted_ancestor
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
