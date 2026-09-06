"""Compute the acyclic HD636 governed content root."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import unicodedata
from pathlib import Path
from typing import Any, cast

FILE_DOMAIN = b"HYBRID-DISCOVERY/v6.3.6/GOVERNED-FILE/v1\0"
ROOT_DOMAIN = b"HYBRID-DISCOVERY/v6.3.6/GOVERNED-ROOT/v1\0"
EXPECTED_EXCLUSIONS = [
    "GOVERNED_CONTENT_ROOT.json",
    "SELF_REVIEW_REPORT.md",
    "SELF_REVIEW_REPORT.json",
    "MANIFEST_SHA256.json",
]


def _files(pack: Path, exclusions: set[str]) -> list[tuple[str, bytes]]:
    if pack.is_symlink() or not pack.is_dir():
        raise ValueError("E_GOVERNED_ROOT")
    result: list[tuple[str, bytes]] = []
    for directory, _names, names in os.walk(pack, followlinks=False):
        base = Path(directory)
        if base.is_symlink():
            raise ValueError("E_GOVERNED_ROOT")
        for name in names:
            path = base / name
            relative = path.relative_to(pack).as_posix()
            metadata = path.lstat()
            if (
                path.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or unicodedata.normalize("NFC", relative) != relative
                or relative.startswith("/")
                or ".." in Path(relative).parts
            ):
                raise ValueError("E_GOVERNED_ROOT")
            if relative not in exclusions:
                result.append((relative, path.read_bytes()))
    return sorted(result, key=lambda item: item[0].encode())


def compute_governed_content_root(pack: Path, registry: Path) -> dict[str, object]:
    data = json.loads(registry.read_text())
    if not isinstance(data, dict):
        raise ValueError("E_GOVERNED_ROOT")
    exclusions = data.get("governed_root_exclusions")
    if (
        data.get("schema_version") != "seal-exclusions/v2"
        or exclusions != EXPECTED_EXCLUSIONS
        or data.get("external_outputs_must_be_outside_root") is not True
    ):
        raise ValueError("E_GOVERNED_ROOT")
    leaves: list[tuple[str, bytes]] = []
    for relative, content in _files(pack, set(cast(list[str], exclusions))):
        encoded = relative.encode()
        leaf = hashlib.sha256(
            FILE_DOMAIN + encoded + b"\0" + hashlib.sha256(content).digest()
        ).digest()
        leaves.append((relative, leaf))
    framed = b"".join(
        len(path.encode()).to_bytes(4, "big") + path.encode() + leaf for path, leaf in leaves
    )
    root = hashlib.sha256(ROOT_DOMAIN + framed).hexdigest()
    record = {
        "schema_version": "governed-content-root/v1",
        "algorithm": "HD636-GOVERNED-ROOT-SHA256-v1",
        "root_sha256": root,
        "file_count": len(leaves),
        "exclusion_registry": "docs/registries/seal-exclusions.v1.json",
    }
    target = pack / "GOVERNED_CONTENT_ROOT.json"
    target.write_text(json.dumps(cast(Any, record), sort_keys=True, separators=(",", ":")) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compute_governed_content_root(args.pack, args.registry), sort_keys=True))


if __name__ == "__main__":
    main()
