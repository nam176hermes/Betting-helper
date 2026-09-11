"""Build a reviewable extension/launcher ZIP; never install or grant live access."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def inventory(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != root:
        raise ValueError("E_DELIVERY_PATH")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.resolve() != path:
            raise ValueError("E_DELIVERY_PATH")
        if path.is_dir():
            continue
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError("E_DELIVERY_PATH")
        name = path.relative_to(root).as_posix()
        if name != "DELIVERY_MANIFEST.json":
            raw = path.read_bytes()
            result[name] = {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return result


def validate_delivery(root: Path) -> dict[str, Any]:
    try:
        path = root / "DELIVERY_MANIFEST.json"
        if path.resolve() != path or path.stat().st_nlink != 1 or path.stat().st_size > 1024 * 1024:
            raise ValueError()
        value = json.loads(path.read_bytes())
        files = value["files"]
        if (
            value["schema_version"] != "part-b-delivery/v1"
            or re.fullmatch("[0-9a-f]{40}", value["source_commit"]) is None
            or value["model_enabled"] is not False
            or value["money_ready"] is not False
        ):
            raise ValueError()
        if len({name.casefold() for name in files}) != len(files):
            raise ValueError()
        for name in files:
            if (
                not name
                or "\\" in name
                or PurePosixPath(name).is_absolute()
                or PurePosixPath(name).as_posix() != name
                or any(part in {"", ".", ".."} for part in name.split("/"))
            ):
                raise ValueError()
        if files != inventory(root):
            raise ValueError()
        return cast(dict[str, Any], value)
    except (OSError, KeyError, TypeError, ValueError):
        raise ValueError("E_DELIVERY_INTEGRITY") from None


def package(output: Path) -> dict[str, Any]:
    from moj_discovery.live_intent import source_tree_hash
    from moj_discovery.windows_credential_store import NATIVE_PYTHON
    from tools.qualify_live_platform import build_live_extension
    from tools.run_command_registry import _git_source_identity

    if output.resolve() != output or output.is_relative_to(ROOT) or output.exists():
        raise ValueError("E_DELIVERY_OUTPUT")
    before = _git_source_identity(ROOT)
    source_hash = source_tree_hash(ROOT)
    extension, origin = build_live_extension(output / "build")
    manifest = json.loads((extension / "manifest.json").read_bytes())
    if (
        set(manifest["permissions"]) != {"storage", "sidePanel", "scripting", "activeTab"}
        or manifest["optional_host_permissions"] != ["https://miseojeuplus.espacejeux.com/*"]
        or manifest.get("host_permissions", []) != []
        or manifest["manifest_version"] != 3
    ):
        raise ValueError("E_DELIVERY_PERMISSIONS")
    payload = output / "BettingHelper"
    payload.mkdir()
    shutil.copytree(extension, payload / "extension")
    for name in ("launch_part_b.py", "package_part_b.py"):
        shutil.copyfile(ROOT / "tools" / name, payload / name)
    for name in ("INSTALL_PART_B_VI.md", "RUN_ONE_MATCH_VI.md"):
        shutil.copyfile(ROOT / "docs/runbooks" / name, payload / name)
    native = (
        r"C:\Users\thenam\.cache\codex-runtimes\codex-primary-runtime"
        r"\dependencies\python\python.exe"
    )
    (payload / "Install.cmd").write_bytes(
        (f'@echo off\r\n"{native}" -I -B "%~dp0launch_part_b.py" --install\r\npause\r\n').encode()
    )
    (payload / "Betting Helper.cmd").write_bytes(
        (f'@echo off\r\n"{native}" -I -B "%~dp0launch_part_b.py"\r\npause\r\n').encode()
    )
    (payload / "create-shortcut.vbs").write_text(
        'Set shell = CreateObject("WScript.Shell")\n'
        "Set link = shell.CreateShortcut(WScript.Arguments(0))\n"
        "link.TargetPath = WScript.Arguments(1)\n"
        'link.Arguments = "-I -B " & Chr(34) & WScript.Arguments(2) & Chr(34)\n'
        "link.WorkingDirectory = WScript.Arguments(3)\n"
        'link.Description = "Betting Helper - read only"\n'
        "link.Save\n",
        encoding="ascii",
    )
    credential_files = (
        "tools/windows_credential_helper.py",
        "tools/launch_part_b.py",
        "src/moj_discovery/windows_credential_store.py",
        "src/moj_discovery/secrets_local.py",
    )
    record = {
        "schema_version": "part-b-delivery/v1",
        "source_commit": before["head"],
        "source_tree": before["tree"],
        "source_tree_sha256": source_hash,
        "platform": "WINDOWS_CHROME_WSL2",
        "extension_origin": origin,
        "release_state": "CANDIDATE_WAITING_REVIEW",
        "model_enabled": False,
        "money_ready": False,
        "native_python_sha256": hashlib.sha256(NATIVE_PYTHON.read_bytes()).hexdigest(),
        "backend_credential_files": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in credential_files
        },
        "files": inventory(payload),
    }
    (payload / "DELIVERY_MANIFEST.json").write_text(json.dumps(record, indent=2) + "\n")
    validate_delivery(payload)
    if before != _git_source_identity(ROOT) or source_tree_hash(ROOT) != source_hash:
        raise ValueError("E_DELIVERY_SOURCE_CHANGED")
    archive = output / "betting-helper-part-b.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                entry = zipfile.ZipInfo(
                    "BettingHelper/" + path.relative_to(payload).as_posix(),
                    date_time=(2020, 1, 1, 0, 0, 0),
                )
                entry.external_attr = 0o100644 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                stream.writestr(entry, path.read_bytes(), compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n")
    return {
        "zip": str(archive),
        "sha256": digest,
        "source_commit": before["head"],
        "release_state": "CANDIDATE_WAITING_REVIEW",
        "authority": "NONE",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(package(parser.parse_args().output), indent=2))
