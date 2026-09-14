"""Copy and read-only verify the closed normative source map."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from tempfile import TemporaryDirectory


MANIFEST = "SCHEMA_SHA256.json"


def _relative(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("E_NORMATIVE_PATH")
    return Path(*path.parts)


def _tree(root: Path) -> dict[str, tuple[bytes, int]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("E_NORMATIVE_DRIFT")
    files: dict[str, tuple[bytes, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("E_NORMATIVE_DRIFT")
        if path.is_dir():
            continue
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError("E_NORMATIVE_DRIFT")
        files[path.relative_to(root).as_posix()] = path.read_bytes(), path.stat().st_mode & 0o777
    return files


def _verify_existing(destination: Path, lock_path: Path, expected: Path, expected_lock: Path) -> None:
    if _tree(destination) != _tree(expected):
        raise ValueError("E_NORMATIVE_DRIFT")
    if not lock_path.is_file() or lock_path.is_symlink() or lock_path.stat().st_nlink != 1 or lock_path.read_bytes() != expected_lock.read_bytes():
        raise ValueError("E_NORMATIVE_LOCK")


def synchronize_normative_bundle(
    source: Path, mapping_path: Path, destination: Path, lock_path: Path, *, check: bool = False
) -> dict[str, object]:
    if check:
        with TemporaryDirectory() as temporary:
            expected_root = Path(temporary)
            expected_destination = expected_root / "vendor"
            expected_lock = expected_root / "schema-lock.json"
            result = synchronize_normative_bundle(source, mapping_path, expected_destination, expected_lock)
            _verify_existing(destination, lock_path, expected_destination, expected_lock)
            return result
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    entries = [*mapping["inherited_entries"], *mapping["plan_entries"]]
    copied: list[dict[str, object]] = []
    destinations: set[str] = set()
    for entry in entries:
        source_name = entry["plan_source"]
        if not source_name.startswith("docs/"):
            raise ValueError("E_NORMATIVE_SOURCE")
        target_name = _relative(entry["vendor_relative"])
        target_key = target_name.as_posix()
        if target_key == MANIFEST or target_key in destinations:
            raise ValueError("E_NORMATIVE_DESTINATION")
        destinations.add(target_key)
        origin = source / _relative(source_name.removeprefix("docs/"))
        if not origin.is_file() or origin.is_symlink():
            raise ValueError(f"E_NORMATIVE_MISSING:{source_name}")
        content = origin.read_bytes()
        expected = entry.get("plan_sha256", entry.get("source_sha256"))
        if expected is not None and hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"E_NORMATIVE_HASH:{source_name}")
        target = destination / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        target.chmod(origin.stat().st_mode & 0o777)
        copied.append({"path": target_key, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    copied.sort(key=lambda row: row["path"].encode())
    payload = "".join(f"{row['path']}\0{row['size_bytes']}\0{row['sha256']}\n" for row in copied).encode()
    manifest = {
        "schema_version": "schema-sha256/v1",
        "algorithm": "SHA-256",
        "self_excluded_path": MANIFEST,
        "tree_sha256": hashlib.sha256(payload).hexdigest(),
        "files": copied,
        "production_authority": "NONE",
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    lock = {
        "schema_version": "schema-lock/v1",
        "vendor_path": "vendor/hybrid-discovery-v6.3.6",
        "vendor_tree_sha256": manifest["tree_sha256"],
        "files": copied,
        "production_authority": "NONE",
    }
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return {"result": "PASS", "file_count": len(copied), "tree_sha256": manifest["tree_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(synchronize_normative_bundle(args.source, args.mapping, args.destination, args.lock, check=args.check), sort_keys=True))


if __name__ == "__main__":
    main()
