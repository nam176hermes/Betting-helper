import argparse
import hashlib
import json
import os
import shutil
import stat
import unicodedata
from pathlib import Path, PurePosixPath

MANIFEST = "SCHEMA_SHA256.json"


def _validate_relative_path(root: Path, path: Path) -> None:
    relative = path.relative_to(root)
    if any(
        part in {"", ".", ".."} or unicodedata.normalize("NFC", part) != part
        for part in relative.parts
    ):
        raise ValueError(f"E_VENDOR:PATH:{path}")


def _tree_files(root: Path, *, missing_ok: bool = False) -> list[Path]:
    """Return every regular file after a no-follow, fail-closed tree walk."""
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        if missing_ok:
            return []
        raise ValueError(f"E_VENDOR:ENTRY:{root}") from None
    if stat.S_ISLNK(root_stat.st_mode):
        raise ValueError(f"E_VENDOR:SYMLINK:{root}")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError(f"E_VENDOR:ENTRY:{root}")

    files: list[Path] = []

    def walk(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            raise ValueError(f"E_VENDOR:ENTRY:{directory}") from error
        for entry in entries:
            path = Path(entry.path)
            _validate_relative_path(root, path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ValueError(f"E_VENDOR:ENTRY:{path}") from error
            mode = entry_stat.st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(f"E_VENDOR:SYMLINK:{path}")
            if stat.S_ISDIR(mode):
                walk(path)
                continue
            if not stat.S_ISREG(mode):
                raise ValueError(f"E_VENDOR:ENTRY:{path}")
            if entry_stat.st_nlink != 1:
                raise ValueError(f"E_VENDOR:HARDLINK:{path}")
            if stat.S_IMODE(mode) not in {0o644, 0o755}:
                raise ValueError(f"E_VENDOR:MODE:{path}")
            files.append(path)

    walk(root)
    return files


def _relative(value: object, *, prefix: str = "") -> str:
    if not isinstance(value, str) or "\\" in value or not value.startswith(prefix):
        raise ValueError("E_VENDOR:PATH")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(
            part in {"", ".", ".."} or unicodedata.normalize("NFC", part) != part
            for part in path.parts
        )
    ):
        raise ValueError("E_VENDOR:PATH")
    return value


def _files(pack: Path) -> list[tuple[Path, Path]]:
    try:
        mapping = json.loads(
            (pack / "docs/registries/normative-source-map.v1.json").read_text()
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_VENDOR:MAP") from error
    if not isinstance(mapping, dict) or (
        mapping.get("schema_version") != "normative-source-map/v1"
        or mapping.get("owner_phase") != "MIG0"
        or mapping.get("vendor_prefix")
        != "runtime/vendor/hybrid-discovery-v6.3.6/"
        or mapping.get("plan_namespace") != "docs/"
    ):
        raise ValueError("E_VENDOR:MAP")
    inherited = mapping.get("inherited_entries")
    plan_entries = mapping.get("plan_entries")
    overrides = mapping.get("graph_overrides")
    if (
        not isinstance(inherited, list)
        or not isinstance(plan_entries, list)
        or not isinstance(overrides, list)
    ):
        raise ValueError("E_VENDOR:MAP")
    override_paths = {_relative(entry) for entry in overrides}
    source_files = {
        f"docs/{path.relative_to(pack / 'docs').as_posix()}": path
        for path in _tree_files(pack / "docs")
    }
    sources: set[str] = set()
    effective: dict[str, tuple[Path, Path]] = {}
    for entry in [*inherited, *plan_entries]:
        if not isinstance(entry, dict):
            raise ValueError("E_VENDOR:MAP")
        source_name = _relative(entry.get("plan_source"), prefix="docs/")
        destination_name = _relative(entry.get("vendor_relative"))
        if source_name in sources or destination_name == MANIFEST:
            raise ValueError("E_VENDOR:MAP")
        sources.add(source_name)
        source = source_files.get(source_name)
        if source is None:
            raise ValueError("E_VENDOR:SOURCE")
        expected_hash = entry.get("plan_sha256", entry.get("source_sha256"))
        if expected_hash is not None and (
            not isinstance(expected_hash, str)
            or hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash
        ):
            raise ValueError("E_VENDOR:HASH")
        if destination_name in effective and destination_name not in override_paths:
            raise ValueError("E_VENDOR:COLLISION")
        effective[destination_name] = (source, Path(destination_name))
    return [effective[name] for name in sorted(effective, key=lambda item: item.encode())]


def _manifest(vendor: Path) -> dict[str, object]:
    vendor_files = _tree_files(vendor)
    files = [
        {
            "path": path.relative_to(vendor).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in vendor_files
        if path.relative_to(vendor).as_posix() != MANIFEST
    ]
    payload = "".join(
        f"{item['path']}\0{item['size_bytes']}\0{item['sha256']}\n" for item in files
    ).encode()
    return {
        "schema_version": "schema-sha256/v1",
        "algorithm": "SHA-256",
        "self_excluded_path": MANIFEST,
        "tree_sha256": hashlib.sha256(payload).hexdigest(),
        "files": files,
        "production_authority": "NONE",
    }


def _encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def sync_pack_assets(pack: Path, root: Path, *, check: bool = False) -> None:
    vendor = root / "vendor/hybrid-discovery-v6.3.6"
    vendor_files = _tree_files(vendor, missing_ok=True)
    for generated in (root / "schema-lock.json", vendor / MANIFEST):
        if not generated.exists() and not generated.is_symlink():
            continue
        generated_stat = generated.lstat()
        if stat.S_ISLNK(generated_stat.st_mode):
            raise ValueError(f"E_VENDOR:SYMLINK:{generated}")
        if not stat.S_ISREG(generated_stat.st_mode):
            raise ValueError(f"E_VENDOR:ENTRY:{generated}")
        if generated_stat.st_nlink != 1:
            raise ValueError(f"E_VENDOR:HARDLINK:{generated}")
        if stat.S_IMODE(generated_stat.st_mode) != 0o644:
            raise ValueError(f"E_VENDOR:MODE:{generated}")
    expected = _files(pack)
    expected_paths = {relative.as_posix() for _, relative in expected}
    if MANIFEST in expected_paths:
        raise ValueError(f"E_VENDOR:RESERVED:{MANIFEST}")
    actual_paths = {
        path.relative_to(vendor).as_posix()
        for path in vendor_files
        if path.relative_to(vendor).as_posix() != MANIFEST
    }
    if actual_paths - expected_paths:
        raise ValueError("E_VENDOR:FILE_SET")
    if check:
        if actual_paths != expected_paths:
            raise ValueError("E_VENDOR:FILE_SET")
        for source, relative in expected:
            destination = vendor / relative
            if destination.read_bytes() != source.read_bytes():
                raise ValueError(f"E_VENDOR:BYTES:{relative.as_posix()}")
            if stat.S_IMODE(destination.stat().st_mode) != stat.S_IMODE(
                source.stat().st_mode
            ):
                raise ValueError(f"E_VENDOR:MODE:{relative.as_posix()}")
    else:
        for source, relative in expected:
            destination = vendor / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            destination.chmod(stat.S_IMODE(source.stat().st_mode))
    root_registry = root / "task-command-registry.json"
    if check:
        registry = vendor / "docs/registries/task-command-registry.v1.json"
        if (
            not root_registry.is_file()
            or root_registry.is_symlink()
            or root_registry.lstat().st_nlink != 1
            or root_registry.read_bytes() != registry.read_bytes()
        ):
            raise ValueError("E_VENDOR:TASK_REGISTRY")
    manifest = _manifest(vendor)
    lock = {
        "schema_version": "schema-lock/v1",
        "vendor_path": "vendor/hybrid-discovery-v6.3.6",
        "vendor_tree_sha256": manifest["tree_sha256"],
        "files": manifest["files"],
        "production_authority": "NONE",
    }
    artifacts = (
        (vendor / MANIFEST, _encoded(manifest)),
        (root / "schema-lock.json", _encoded(lock)),
    )
    for path, content in artifacts:
        if check and path.read_bytes() != content:
            raise ValueError(f"E_VENDOR:MANIFEST:{path.name}")
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


synchronize_normative_assets = sync_pack_assets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    sync_pack_assets(args.pack, Path.cwd(), check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
