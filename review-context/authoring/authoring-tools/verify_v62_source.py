"""Verify the pinned v6.2 REPO0 source before successor copying."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["/usr/bin/git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("E_SOURCE_GIT")
    return result.stdout


def _tree_root(root: Path) -> tuple[str, int]:
    entries: list[dict[str, object]] = []
    for item in _git(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ", 2)
        if object_type != b"blob" or mode not in {b"100644", b"100755"}:
            raise ValueError("E_SOURCE_TREE")
        content = _git(root, "cat-file", "blob", object_id.decode("ascii"))
        entries.append({
            "entry_kind": "REGULAR_FILE",
            "file_sha256": hashlib.sha256(content).hexdigest(),
            "git_mode": mode.decode("ascii"),
            "gitlink": False,
            "hardlink": False,
            "path": raw_path.decode("utf-8"),
            "size_bytes": str(len(content)),
            "symlink": False,
        })
    entries.sort(key=lambda row: str(row["path"]).encode())
    tree = {"entries": entries, "schema_version": "repo0-independent-file-tree/v1"}
    canonical = json.dumps(tree, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b"HYBRID-DISCOVERY/v6.2/Repo0IndependentFileTree/v1\0" + canonical).hexdigest(), len(entries)


def verify_v62_source(config_path: Path, source_inventory_path: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    inventory = json.loads(source_inventory_path.read_text(encoding="utf-8"))
    root = Path(config["source_runtime"])
    if Path(inventory["root"]) != root or not (root / ".git").is_dir():
        raise ValueError("E_SOURCE_ROOT")
    if _git(root, "rev-parse", "HEAD").decode().strip() != config["source_commit"]:
        raise ValueError("E_SOURCE_COMMIT")
    if _git(root, "rev-parse", "HEAD^{tree}").decode().strip() != config["source_tree_oid"]:
        raise ValueError("E_SOURCE_TREE")
    if config["required_clean"] and _git(root, "status", "--porcelain"):
        raise ValueError("E_SOURCE_DIRTY")
    if config["required_no_remote"] and _git(root, "remote").strip():
        raise ValueError("E_SOURCE_REMOTE")
    files = inventory["files"]
    for row in files:
        path = root / row["path"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != row["size"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"E_SOURCE_FILE:{row['path']}")
    tree_root, count = _tree_root(root)
    if tree_root != config["source_file_tree_root"] or count != len(files):
        raise ValueError("E_SOURCE_FILE_TREE")
    return {"result": "PASS", "file_count": count, "source_tree_root": tree_root}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--source-inventory", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_v62_source(args.config, args.source_inventory), sort_keys=True))


if __name__ == "__main__":
    main()
