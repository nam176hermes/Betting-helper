import hashlib
import stat
from pathlib import Path

from .canonical import parse_strict_json

VENDOR_DIRECTORY = "vendor/hybrid-discovery-v6.3.6"


def plan_root(runtime: Path) -> Path:
    candidate = runtime.parent / "plan-input"
    manifest = candidate / "docs/tasks/task-manifest.v6.3.6.json"
    return (
        candidate
        if manifest.is_file() and not manifest.is_symlink()
        else runtime / VENDOR_DIRECTORY
    )


def pack_root(runtime: Path) -> Path:
    candidate = runtime.parent / "pack"
    manifest = candidate / "docs/tasks/task-manifest.v6.3.6.json"
    return (
        candidate
        if manifest.is_file() and not manifest.is_symlink()
        else runtime / VENDOR_DIRECTORY
    )


def verify_vendored_assets(root: Path | None = None) -> bool:
    root = root or Path.cwd()
    vendor = root / "vendor/hybrid-discovery-v6.3.6"
    manifest_path = vendor / "SCHEMA_SHA256.json"
    lock_path = root / "schema-lock.json"
    if not manifest_path.is_file() or not lock_path.is_file():
        raise ValueError("E_VENDOR:PACK_REQUIRED")
    if any(path.lstat().st_nlink != 1 for path in (manifest_path, lock_path)):
        raise ValueError("E_VENDOR:HARDLINK")
    manifest = parse_strict_json(manifest_path.read_bytes())
    lock = parse_strict_json(lock_path.read_bytes())
    assert isinstance(manifest, dict) and isinstance(lock, dict)
    files = manifest["files"]
    assert isinstance(files, list)
    if not all(isinstance(item, dict) for item in files):
        raise ValueError("E_VENDOR:MANIFEST")
    recorded_paths = {item.get("path") for item in files}
    if len(recorded_paths) != len(files) or not all(
        isinstance(path, str) and path and not path.startswith("/") and ".." not in path.split("/")
        for path in recorded_paths
    ):
        raise ValueError("E_VENDOR:MANIFEST")
    actual_paths = {
        path.relative_to(vendor).as_posix()
        for path in vendor.rglob("*")
        if path.is_file() and path != manifest_path and not path.is_symlink()
    }
    if recorded_paths != actual_paths:
        raise ValueError("E_VENDOR:FILE_SET")
    for item in files:
        assert isinstance(item, dict)
        path = vendor / str(item["path"])
        path_stat = path.lstat()
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_nlink != 1
            or stat.S_IMODE(path_stat.st_mode) not in {0o644, 0o755}
            or path_stat.st_size != item["size_bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError(f"E_VENDOR:BYTES:{item['path']}")
    payload = "".join(
        f"{item['path']}\0{item['size_bytes']}\0{item['sha256']}\n" for item in files
    ).encode()
    tree_hash = hashlib.sha256(payload).hexdigest()
    if (
        manifest["tree_sha256"] != tree_hash
        or lock["vendor_tree_sha256"] != tree_hash
        or lock["files"] != files
    ):
        raise ValueError("E_VENDOR:MANIFEST")
    registry = vendor / "docs/registries/task-command-registry.v1.json"
    if registry.read_bytes() != (root / "task-command-registry.json").read_bytes():
        raise ValueError("E_VENDOR:TASK_REGISTRY")
    return True
