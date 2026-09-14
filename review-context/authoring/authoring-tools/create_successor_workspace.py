"""Copy only the pinned baseline inventory into the BOOT0 runtime root."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil


def _relative(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", "..", ".git"} for part in path.parts):
        raise ValueError("E_SUCCESSOR_PATH")
    return Path(*path.parts)


def create_successor_workspace(config_path: Path, source_inventory_path: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    inventory = json.loads(source_inventory_path.read_text(encoding="utf-8"))
    source = Path(inventory["root"])
    destination = Path(config["runtime_candidate"])
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("E_SUCCESSOR_DESTINATION_EXISTS")
    if not source.is_dir() or not destination.is_absolute():
        raise ValueError("E_SUCCESSOR_ROOT")
    destination.mkdir(parents=True, exist_ok=True)
    for row in inventory["files"]:
        relative = _relative(row["path"])
        origin = source / relative
        target = destination / relative
        if not origin.is_file() or origin.is_symlink() or origin.stat().st_size != row["size"] or hashlib.sha256(origin.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"E_SUCCESSOR_SOURCE:{row['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        os.chmod(target, origin.stat().st_mode & 0o777)
    return {"result": "PASS", "file_count": len(inventory["files"]), "runtime": str(destination)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--source-inventory", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(create_successor_workspace(args.config, args.source_inventory), sort_keys=True))


if __name__ == "__main__":
    main()
