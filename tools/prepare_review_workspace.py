"""Prepare a one-use, read-only Bubblewrap review workspace."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from moj_discovery.review_authorization import verify_review_launch_authorization
from tools.issue_review_launch_authorization import (
    measure_review_context,
    recheck_review_context,
    review_config_for_role,
    review_public_key,
)
from tools.run_review_a_checks import run_review_a_checks
from tools.run_review_b_checks import run_review_b_checks

PREPARATION_DOMAIN = b"HD636/REVIEW-PREPARATION/v1\0"
HOST_PNPM_STORE = Path("/home/thenam176/.local/share/pnpm/store/v10")
HOST_UV_CACHE = Path("/home/thenam176/.cache/uv")
NAMESPACE_SOCKET = Path(os.sep) / "tmp/namespace.sock"
Run = Callable[..., subprocess.CompletedProcess[bytes]]


def _regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or stat.S_ISLNK(path.lstat().st_mode):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")


def _directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir() or stat.S_ISLNK(path.lstat().st_mode):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")


def _sha256(path: Path) -> str:
    _regular(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_review_workspace(config: dict[str, object]) -> dict[str, object]:
    if config.get("schema_version") == "review-config/v2":
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    return _prepare_review_directories(config)


def _prepare_review_directories(config: dict[str, object]) -> dict[str, object]:
    if config.get("network") != "DENY":
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    excluded_roots = config.get("excluded_roots")
    excluded = set(excluded_roots) if isinstance(excluded_roots, list) else set()
    mounts = config.get("input_mounts")
    if not excluded or not isinstance(mounts, list):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    for mount in mounts:
        if (
            not isinstance(mount, dict)
            or mount.get("mode") != "READ_ONLY"
            or mount.get("source_root") in excluded
            or mount.get("workspace_mount") in excluded
        ):
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    workspace = Path(cast(str, config["workspace_root"]))
    output = Path(cast(str, config["output_root"]))
    if workspace.is_symlink() or output.is_symlink():
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    workspace.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    return {"result": "PASS", "workspace_root": str(workspace), "output_root": str(output)}


def _config_for_role(role: str, version: int = 1) -> dict[str, object]:
    return review_config_for_role(role, version, runtime_root=RUNTIME_ROOT)


def _public_key(authority_config: dict[str, object]) -> tuple[Ed25519PublicKey, int]:
    try:
        return review_public_key(authority_config)
    except (OSError, ValueError) as error:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION") from error


def _authority_state(
    authorization: dict[str, object], authority: dict[str, object], *, consume: bool
) -> None:
    state = Path(cast(str, authority["private_key_path"])).parent / "state.sqlite"
    _regular(state)
    connection = sqlite3.connect(state)
    try:
        connection.execute("BEGIN IMMEDIATE")
        key = cast(str, authorization["issuer_key_id"])
        serial = cast(str, authorization["one_use_serial"])
        epoch = connection.execute(
            "SELECT trust_epoch FROM authority_state WHERE key_id = ?", (key,)
        ).fetchone()
        revoked = connection.execute(
            "SELECT 1 FROM revocations WHERE authorization_id = ?",
            (authorization["authorization_id"],),
        ).fetchone()
        consumed = connection.execute(
            "SELECT 1 FROM consumed_serials WHERE authority_key_id = ? AND one_use_serial = ?",
            (key, serial),
        ).fetchone()
        if epoch != (authorization["trust_epoch"],) or revoked is not None:
            raise ValueError("E_REVIEW_LAUNCH_CONSUMED")
        if consume:
            if consumed is not None:
                raise ValueError("E_REVIEW_LAUNCH_CONSUMED")
            connection.execute("INSERT INTO consumed_serials VALUES (?, ?)", (key, serial))
        elif consumed is None:
            raise ValueError("E_REVIEW_LAUNCH_CONSUMED")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _preparation_commands(config: dict[str, object]) -> list[dict[str, object]]:
    leaf_registry = Path(cast(str, config["command_registry_path"]))
    registry_path = leaf_registry.with_name("review-command-registry.v1.json")
    _regular(registry_path)
    registry = json.loads(registry_path.read_text())
    rows = registry.get("commands") if isinstance(registry, dict) else None
    ids = config.get("preparation_command_ids")
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != "review-command-registry/v1"
        or not isinstance(rows, list)
        or not isinstance(ids, list)
    ):
        raise ValueError("E_REVIEW_PREPARATION")
    mapped: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("command_id"), str):
            raise ValueError("E_REVIEW_PREPARATION")
        command_id = cast(str, row["command_id"])
        if command_id in mapped:
            raise ValueError("E_REVIEW_PREPARATION")
        mapped[command_id] = row
    if len(ids) != 2 or not all(isinstance(item, str) for item in ids):
        raise ValueError("E_REVIEW_PREPARATION")
    commands = [mapped.get(cast(str, item)) for item in ids]
    if any(item is None for item in commands):
        raise ValueError("E_REVIEW_PREPARATION")
    result = cast(list[dict[str, object]], commands)
    for command in result:
        argv = command.get("argv")
        if (
            command.get("kind") != "review-operation"
            or command.get("expected_exit") != 0
            or any(
                command.get(key) != "DENY"
                for key in ("network", "authenticated_operator_access", "provider_access")
            )
            or not isinstance(command.get("cwd"), str)
            or not isinstance(argv, list)
            or not argv
            or not all(isinstance(token, str) and token for token in argv)
        ):
            raise ValueError("E_REVIEW_PREPARATION")
    return result


def _copy_node_inputs(config: dict[str, object]) -> None:
    node = config.get("node_environment")
    scratch = Path(cast(str, config["scratch_root"]))
    if not isinstance(node, dict) or scratch.exists() or scratch.is_symlink():
        raise ValueError("E_REVIEW_PREPARATION")
    project = Path(cast(str, node.get("project_root")))
    if project.parent != scratch or project.is_symlink():
        raise ValueError("E_REVIEW_PREPARATION")
    inputs = node.get("project_inputs")
    if not isinstance(inputs, list) or len(inputs) != 4:
        raise ValueError("E_REVIEW_PREPARATION")
    project.mkdir(parents=True)
    for item in inputs:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("source"), str)
            or not isinstance(item.get("destination"), str)
        ):
            raise ValueError("E_REVIEW_PREPARATION")
        source = Path(cast(str, item["source"]))
        destination = PurePosixPath(cast(str, item["destination"]))
        if destination.is_absolute() or any(part in {"", ".", ".."} for part in destination.parts):
            raise ValueError("E_REVIEW_PREPARATION")
        _regular(source)
        target = project.joinpath(*destination.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
        if _sha256(source) != _sha256(target):
            raise ValueError("E_REVIEW_PREPARATION")


def _environment(config: dict[str, object]) -> dict[str, str]:
    supplied = config.get("environment")
    scratch = Path(cast(str, config["scratch_root"]))
    if not isinstance(supplied, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in supplied.items()
    ):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    home = scratch / "home"
    home.mkdir(parents=True, exist_ok=True)
    tool_paths = filter(None, (shutil.which(command) for command in ("uv", "pnpm")))
    path_entries = {str(Path(path).parent) for path in tool_paths}
    path_entries.update({"/usr/bin", "/bin"})
    return {
        "HOME": str(home),
        "PATH": os.pathsep.join(sorted(path_entries)),
        **cast(dict[str, str], supplied),
    }


def _preparation_environment(
    command: dict[str, object], environment: dict[str, str]
) -> dict[str, str]:
    argv = cast(list[str], command["argv"])
    if argv[0] == "uv":
        _directory(HOST_UV_CACHE)
        return {**environment, "UV_CACHE_DIR": str(HOST_UV_CACHE)}
    if argv[0] != "pnpm":
        return environment
    _directory(HOST_PNPM_STORE)
    node = _node_binary()
    return {
        **environment,
        "PATH": str(node.parent) + os.pathsep + environment["PATH"],
        "npm_config_store_dir": str(HOST_PNPM_STORE),
    }


def _run_preparation(
    config: dict[str, object], commands: list[dict[str, object]], *, execute: Run = subprocess.run
) -> list[dict[str, object]]:
    _copy_node_inputs(config)
    environment = _environment(config)
    records: list[dict[str, object]] = []
    for command in commands:
        command_environment = _preparation_environment(command, environment)
        cwd = Path(cast(str, command["cwd"]))
        _directory(cwd)
        snapshots = {
            path: _sha256(cwd / path)
            for path in ("pyproject.toml", "uv.lock")
            if (cwd / path).exists()
        }
        completed = execute(
            cast(list[str], command["argv"]),
            cwd=cwd,
            env=command_environment,
            capture_output=True,
        )
        after = {path: _sha256(cwd / path) for path in snapshots}
        if completed.returncode != command["expected_exit"] or snapshots != after:
            raise ValueError("E_REVIEW_PREPARATION")
        records.append(
            {
                "command_id": command["command_id"],
                "argv": command["argv"],
                "cwd": str(cwd),
                "environment": command_environment,
                "exit_code": completed.returncode,
                "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
            }
        )
    return records


def _preparation_root(records: list[dict[str, object]]) -> str:
    return hashlib.sha256(PREPARATION_DOMAIN + rfc8785.dumps(cast(Any, records))).hexdigest()


def _parent_dirs(paths: list[Path]) -> list[str]:
    result: set[Path] = set()
    for path in paths:
        current = path.parent
        while current != Path("/"):
            result.add(current)
            current = current.parent
    return [str(path) for path in sorted(result, key=lambda item: (len(item.parts), str(item)))]


def _prepared_python_environment(config: dict[str, object]) -> Path:
    environment = config.get("environment")
    scratch = Path(cast(str, config["scratch_root"]))
    path = (
        Path(cast(str, environment["UV_PROJECT_ENVIRONMENT"]))
        if (
            isinstance(environment, dict)
            and isinstance(environment.get("UV_PROJECT_ENVIRONMENT"), str)
        )
        else None
    )
    if path is None or path.parent != scratch:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    _directory(path)
    if not (path / "bin/python").exists():
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    return path


def _registered_leaf_commands(
    config: dict[str, object], authorization: dict[str, object]
) -> list[dict[str, object]]:
    registry_path = Path(cast(str, config["command_registry_path"]))
    raw = registry_path.read_bytes()
    if registry_path.is_symlink() or hashlib.sha256(raw).hexdigest() != authorization.get(
        "command_registry_sha256"
    ):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    registry = json.loads(raw)
    rows = registry.get("commands") if isinstance(registry, dict) else None
    configured = config.get("mechanical_command_ids")
    if not isinstance(rows, list) or not isinstance(configured, list):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    found: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("command_id"), str):
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        command_id = cast(str, row["command_id"])
        if command_id in found:
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        found[command_id] = row
    if not configured or not all(isinstance(item, str) for item in configured):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    commands = [found.get(cast(str, item)) for item in configured]
    if any(command is None for command in commands):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    result = cast(list[dict[str, object]], commands)
    for command in result:
        argv, cwd = command.get("argv"), command.get("cwd")
        if (
            command.get("kind") != "review-leaf"
            or command.get("network") != "DENY"
            or command.get("authenticated_operator_access") != "DENY"
            or command.get("provider_access") != "DENY"
            or command.get("expected_exit") != 0
            or not isinstance(cwd, str)
            or not isinstance(argv, list)
            or not argv
            or not all(isinstance(token, str) and token for token in argv)
        ):
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    return result


def _node_binary() -> Path:
    mise = shutil.which("mise")
    if mise is None:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    completed = subprocess.run(  # noqa: S603 - fixed locally resolved tool, output is validated below
        [mise, "which", "node"], check=False, capture_output=True, text=True
    )
    source = Path(completed.stdout.strip()) if completed.returncode == 0 else Path()
    if not source.is_file() or source.is_symlink():
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    return source


def _tool_mounts(
    commands: list[dict[str, object]],
) -> tuple[list[tuple[Path, Path]], list[tuple[str, str]]]:
    names = {cast(list[str], command["argv"])[0] for command in commands}
    if any(
        command.get("command_id") in {"A_CHECK_BASELINE", "A_CHECK_DESCENDANT"}
        for command in commands
    ):
        names.update({"node", "pnpm"})
    mounts: list[tuple[Path, Path]] = []
    links: list[tuple[str, str]] = []
    for name in sorted(names):
        if name == "node":
            source = _node_binary()
        else:
            resolved = shutil.which(name)
            source = Path(resolved).resolve() if resolved else Path()
        if not source.is_file() or source.is_symlink():
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        if name == "pnpm":
            package = source.parents[1]
            _directory(package)
            mounts.append((package, Path("/review-tools/pnpm")))
            links.append(("/review-tools/pnpm/bin/pnpm.cjs", "/review-bin/pnpm"))
        else:
            mounts.append((source, Path(f"/review-bin/{name}")))
    if "pnpm" in names and "node" not in names:
        mounts.append((_node_binary(), Path("/review-bin/node")))
    return mounts, links


def _dependency_projection(root: Path, boundary: Path, *, python: bool) -> dict[str, str]:
    """Compare all imported package bytes; installation wrappers have local shebangs."""
    _directory(root)
    result: dict[str, str] = {}
    for directory, names, files in os.walk(root, followlinks=True):
        parent = Path(directory)
        names[:] = [name for name in names if name not in {"__pycache__", ".bin"}]
        for name in list(names):
            entry = parent / name
            resolved = entry.resolve(strict=True)
            if not python and entry.is_symlink() and resolved == boundary / "extension":
                # pnpm's declared local workspace resolves to the mounted governed source.
                result[entry.relative_to(root).as_posix()] = "workspace:extension"
                names.remove(name)
                continue
            if not resolved.is_relative_to(boundary) or any(
                ancestor.resolve() == resolved for ancestor in (parent, *parent.parents)
            ):
                raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        for name in files:
            path = parent / name
            if name.endswith((".pyc", ".pyo")) or name in {
                ".modules.yaml", ".pnpm-workspace-state-v1.json",
            }:
                continue
            if not path.resolve(strict=True).is_relative_to(boundary) or not path.is_file():
                raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
            content = path.read_bytes()
            if python and name == "RECORD" and parent.name.endswith(".dist-info"):
                rows = list(csv.reader(content.decode().splitlines()))
                if any(len(row) != 3 for row in rows):
                    raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
                # Console wrappers are not imported; frozen uv checks them as installed scripts.
                content = json.dumps([row for row in rows if not row[0].startswith(
                    "../../../bin/"
                )], sort_keys=True).encode()
            result[path.relative_to(root).as_posix()] = hashlib.sha256(content).hexdigest()
    if not result:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    return result


def _producer_projection(
    config: dict[str, object], commands: list[dict[str, object]],
) -> tuple[list[tuple[Path, Path]], list[tuple[str, str]], dict[str, str]]:
    """Validate source-owned exact live identities before creating read-only projections."""
    if not any(row.get("command_id") == "A_CHECK_DESCENDANT" for row in commands):
        return [], [], {}
    from tools.run_environment_qualification import NATIVE
    from tools.run_indexeddb_crash_matrix import CHROME
    from tools.run_native_ingestor_qualification import DEPENDENCIES, dependency_binding
    from tools.verify_repair_evidence import _resolved_node_executable

    if config.get("schema_version") != "review-config/v2" or config != _config_for_role(
        cast(str, config["role"]), 2
    ):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    declaration = config.get("producer_environment")
    if not isinstance(declaration, dict) or set(declaration) != {
        "schema_version", "mode", "python_environment", "python_executable",
        "python_executable_sha256", "node_lookup", "node_executable", "node_executable_sha256",
        "native_dependency_root", "live_files",
        "path_translation_executable", "path_translation_sha256",
        "wsl_distro", "runtime_unc",
    } or declaration.get("schema_version") != "review-producer-environment/v1" or declaration.get(
        "mode"
    ) != "VERIFIED_READ_ONLY_PROJECTION":
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    qualified = Path(cast(str, declaration["python_environment"]))
    python = Path(cast(str, declaration["python_executable"]))
    node = Path(cast(str, declaration["node_executable"]))
    lookup = Path(cast(str, declaration["node_lookup"]))
    prepared = _prepared_python_environment(config)
    translation = Path(cast(str, declaration["path_translation_executable"]))
    python_configs = []
    for path in (qualified, prepared):
        _directory(path / "bin")
        _regular(path / "pyvenv.cfg")
        lines = (path / "pyvenv.cfg").read_text().splitlines()
        settings = dict(line.split(" = ", 1) for line in lines)
        if len(settings) != len(lines):
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        settings["home"] = str(Path(settings["home"]).resolve(strict=True))
        python_configs.append(settings)
    if (
        qualified != RUNTIME_ROOT / ".venv" or python != qualified / "bin/python3"
        or shutil.which("node") != str(lookup) or _resolved_node_executable() != node
        or _sha256(node) != declaration["node_executable_sha256"]
        or _sha256(python.resolve(strict=True)) != declaration["python_executable_sha256"]
        or (prepared / "bin/python3").resolve(strict=True) != python.resolve(strict=True)
        or any(
            not (environment / "bin" / alias).is_symlink()
            or (environment / "bin" / alias).resolve(strict=True) != python.resolve(strict=True)
            for environment in (qualified, prepared)
            for alias in ("python", "python3", "python3.12")
        )
        or python_configs[0] != python_configs[1]
        or translation != Path("/init")
        or Path("/usr/bin/wslpath").resolve(strict=True) != translation
        or _sha256(translation) != declaration["path_translation_sha256"]
    ):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    distro = declaration["wsl_distro"]
    runtime_unc = declaration["runtime_unc"]
    if (
        distro != "Ubuntu"
        or runtime_unc != "\\\\wsl.localhost\\Ubuntu" + str(RUNTIME_ROOT).replace("/", "\\")
    ):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    for option, operand, expected in (
        ("-w", str(RUNTIME_ROOT), runtime_unc), ("-u", runtime_unc, str(RUNTIME_ROOT)),
    ):
        translated = subprocess.run(  # noqa: S603 -- fixed source-owned path translation only.
            ["/usr/bin/wslpath", option, operand], env={"PATH": "/usr/bin"},
            capture_output=True, text=True, check=False, timeout=10,
        )
        if translated.returncode or translated.stdout.strip() != expected:
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    for environment_root in (qualified, prepared):
        checked = subprocess.run(  # noqa: S603 -- pinned offline read-only lock/environment check.
            [uv, "sync", "--check", "--frozen", "--offline"], cwd=RUNTIME_ROOT,
            env={**_environment(config), "UV_PROJECT_ENVIRONMENT": str(environment_root)},
            capture_output=True, check=False, timeout=60,
        )
        if checked.returncode:
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    if _dependency_projection(qualified / "lib", qualified, python=True) != _dependency_projection(
        prepared / "lib", prepared, python=True
    ):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    node_environment = cast(dict[str, object], config["node_environment"])
    project = Path(cast(str, node_environment["project_root"]))
    for item in cast(list[dict[str, str]], node_environment["project_inputs"]):
        if (project / item["destination"]).read_bytes() != Path(item["source"]).read_bytes():
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    if _dependency_projection(RUNTIME_ROOT / "node_modules", RUNTIME_ROOT, python=False) != (
        _dependency_projection(project / "node_modules", project, python=False)
    ) or _dependency_projection(
        RUNTIME_ROOT / "extension/node_modules", RUNTIME_ROOT, python=False
    ) != _dependency_projection(project / "extension/node_modules", project, python=False):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    dependency = dependency_binding()  # Includes independent wheel, lock and rfc8785 provenance.
    preparation = json.loads((DEPENDENCIES / "preparation.json").read_text())
    expected_files = {
        CHROME, Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"), NATIVE,
        NATIVE.parent / "python312.dll", NATIVE.parent / "DLLs/_sqlite3.pyd",
        NATIVE.parent / "DLLs/sqlite3.dll", NATIVE.parent.parent / "node/bin/node.exe",
        *(Path(row["path"]) for row in dependency["wheels"]),
        *(Path(row["independent_source"]) for row in preparation["rfc8785"]["files"]),
    }
    live_files = declaration["live_files"]
    if (
        declaration["native_dependency_root"] != str(DEPENDENCIES)
        or not isinstance(live_files, list)
        or len(live_files) != len(expected_files)
        or set(live_files) != {str(path) for path in expected_files}
    ):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    for path in expected_files:
        _regular(path)
    _directory(DEPENDENCIES)
    mounts = [
        (node, node), (translation, translation), (DEPENDENCIES, DEPENDENCIES),
        (prepared, qualified),
    ]
    mounts.extend((path, path) for path in sorted(expected_files))
    return mounts, [(str(node), str(lookup))], {
        "PATH": f"{lookup.parent}:/review-bin:/usr/bin",
        "UV_PROJECT_ENVIRONMENT": str(qualified),
        "WSL_DISTRO_NAME": distro,
    }


def build_bubblewrap_argv(
    config: dict[str, object],
    command: dict[str, object],
    *,
    leaf_commands: list[dict[str, object]] | None = None,
) -> list[str]:
    if shutil.which("bwrap") != "/usr/bin/bwrap":
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    argv = command.get("argv")
    cwd = command.get("cwd")
    mounts = config.get("input_mounts")
    node = config.get("node_environment")
    if (
        not isinstance(argv, list)
        or not argv
        or not isinstance(cwd, str)
        or not isinstance(mounts, list)
        or not isinstance(node, dict)
    ):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    scratch = Path(cast(str, config["scratch_root"]))
    output = Path(cast(str, config["output_root"]))
    writable = [scratch / "control", scratch / "home", scratch / "tmp", output]
    readonly: list[tuple[Path, Path]] = []
    for mount in mounts:
        if not isinstance(mount, dict) or mount.get("mode") != "READ_ONLY":
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        source = Path(cast(str, mount.get("source_root")))
        target = Path(cast(str, mount.get("workspace_mount")))
        if source != target or str(source) in cast(list[str], config["excluded_roots"]):
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        if source.is_dir():
            _directory(source)
        else:
            _regular(source)
        readonly.append((source, target))
    dependencies = node.get("dependency_mounts")
    if not isinstance(dependencies, list) or len(dependencies) != 2:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    for mount in dependencies:
        if not isinstance(mount, dict) or mount.get("mode") != "READ_ONLY":
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        source = Path(cast(str, mount.get("source_root")))
        target = Path(cast(str, mount.get("workspace_mount")))
        if scratch not in source.parents or source.is_symlink() or not source.is_dir():
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        readonly.append((source, target))
    prepared_python = _prepared_python_environment(config) if leaf_commands is not None else None
    if prepared_python is not None:
        readonly.append((prepared_python, prepared_python))
    executable = shutil.which(cast(str, argv[0]), path=os.environ.get("PATH"))
    if executable is None:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    executable_path = Path(executable).resolve(strict=True)
    _regular(executable_path)
    tools, links = _tool_mounts(leaf_commands or [command])
    projected, projected_links, projected_environment = _producer_projection(
        config, leaf_commands or [command]
    )
    readonly.extend(projected)
    links.extend(projected_links)
    if leaf_commands is None and not any(target.name == argv[0] for _, target in tools):
        tools.append((executable_path, Path(f"/review-bin/{argv[0]}")))
    temporary_target = Path(os.sep) / "tmp"
    destinations = (
        [target for _, target in readonly]
        + writable
        + [
            temporary_target,
            Path("/review-bin"),
            Path("/review-tools"),
        ]
        + [Path(target) for _source, target in links]
        + [target for _source, target in tools]
    )
    result = [
        "/usr/bin/bwrap",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--ro-bind",
        "/usr",
        "/usr",
    ]
    for system_path in ("/bin", "/lib", "/lib64"):
        path = Path(system_path)
        if projected and path.is_symlink():
            if not path.resolve(strict=True).is_relative_to("/usr"):
                raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
            result.extend(["--symlink", os.readlink(path), system_path])
        else:
            result.extend(["--ro-bind", system_path, system_path])
    for directory in _parent_dirs(destinations):
        result.extend(["--dir", directory])
    result.extend(
        ["--dir", "/review-bin", "--dir", "/review-tools", "--proc", "/proc", "--dev", "/dev"]
    )
    for source, target in readonly:
        result.extend(["--ro-bind", str(source), str(target)])
    for path in writable:
        _directory(path)
        bind_target = temporary_target if path == scratch / "tmp" else path
        result.extend(["--bind", str(path), str(bind_target)])
    for source, target in tools:
        result.extend(["--ro-bind", str(source), str(target)])
    for link_source, link_target in links:
        result.extend(["--symlink", link_source, link_target])
    environment = _environment(config)
    environment["PATH"] = "/review-bin:/usr/bin"
    environment.update(projected_environment)
    for key, value in sorted(environment.items()):
        result.extend(["--setenv", key, value])
    result.extend(["--chdir", cwd, "--", *cast(list[str], argv)])
    return result


def _namespace_state_path(config: dict[str, object]) -> Path:
    return Path(cast(str, config["scratch_root"])) / "control/namespace-state.json"


def _namespace_facts(pid: int) -> dict[str, object]:
    stat_path = Path(f"/proc/{pid}/stat")
    if not stat_path.exists():
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    fields = stat_path.read_text().rsplit(") ", 1)
    if len(fields) != 2 or len(fields[1].split()) < 20:
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    namespaces = {
        name: os.stat(f"/proc/{pid}/ns/{name}").st_ino for name in ("user", "pid", "mnt", "net")
    }
    return {"pid": pid, "start_ticks": fields[1].split()[19], "namespaces": namespaces}


def _write_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _start_namespace(
    config: dict[str, object], authorization: dict[str, object]
) -> dict[str, object]:
    version = 2 if authorization.get("schema_version") == "review-launch-authorization/v2" else 1
    if version == 2 and _config_for_role(cast(str, config["role"]), version) != config:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    commands = _registered_leaf_commands(config, authorization)
    scratch = Path(cast(str, config["scratch_root"]))
    control, home, temporary = scratch / "control", scratch / "home", scratch / "tmp"
    _directory(home)
    for path in (control, temporary):
        path.mkdir(parents=True, exist_ok=False)
        _directory(path)
    python = _prepared_python_environment(config) / "bin/python"
    socket_path = temporary / "namespace.sock"
    label = "a" if config["role"] == "IMPLEMENTATION_READINESS_REVIEWER" else "b"
    config_name = f"review-{label}.v{version}.json"
    broker: dict[str, object] = {
        "argv": [
            str(python),
            str(Path(__file__).resolve()),
            "--namespace-broker",
            "--config",
            str(RUNTIME_ROOT / "review-config" / config_name),
            "--authorization-id",
            str(authorization["authorization_id"]),
            "--registry-sha256",
            str(authorization["command_registry_sha256"]),
            "--socket",
            str(NAMESPACE_SOCKET),
            "--expires-at",
            str(authorization["expires_at"]),
        ],
        "cwd": str(RUNTIME_ROOT),
    }
    process = subprocess.Popen(  # noqa: S603 - closed Bubblewrap argv and registry-derived tools
        build_bubblewrap_argv(config, broker, leaf_commands=commands),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if socket_path.exists() and process.poll() is None:
            state = {
                "schema_version": "review-namespace/v1",
                "authorization_id": authorization["authorization_id"],
                "command_registry_sha256": authorization["command_registry_sha256"],
                "expires_at": authorization["expires_at"],
                "socket_path": str(socket_path),
                **_namespace_facts(process.pid),
            }
            _write_json(_namespace_state_path(config), state)
            return state
        time.sleep(0.02)
    process.terminate()
    process.wait(timeout=5)
    raise ValueError("E_REVIEW_NAMESPACE_START")


def _active_namespace(
    config: dict[str, object], authorization: dict[str, object]
) -> dict[str, object]:
    state_path = _namespace_state_path(config)
    _regular(state_path)
    state = json.loads(state_path.read_text())
    if not isinstance(state, dict):
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    expected = {
        "schema_version": "review-namespace/v1",
        "authorization_id": authorization["authorization_id"],
        "command_registry_sha256": authorization["command_registry_sha256"],
        "expires_at": authorization["expires_at"],
        "socket_path": str(Path(cast(str, config["scratch_root"])) / "tmp/namespace.sock"),
    }
    if any(state.get(key) != value for key, value in expected.items()) or not isinstance(
        state.get("pid"), int
    ):
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    facts = _namespace_facts(cast(int, state["pid"]))
    if (
        state.get("start_ticks") != facts["start_ticks"]
        or state.get("namespaces") != facts["namespaces"]
    ):
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    if not Path(cast(str, state["socket_path"])).exists():
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    return state


def _namespace_request(
    socket_path: Path, payload: dict[str, object]
) -> subprocess.CompletedProcess[bytes]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if len(encoded) > 4096:
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    directory = os.open(socket_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        endpoint = f"/proc/self/fd/{directory}/{socket_path.name}"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(60)
            connection.connect(endpoint)
            connection.sendall(encoded)
            response = connection.recv(1 << 20)
    finally:
        os.close(directory)
    try:
        decoded = json.loads(response)
        stdout = base64.b64decode(decoded["stdout"], validate=True)
        stderr = base64.b64decode(decoded["stderr"], validate=True)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL") from error
    if set(decoded) != {"exit_code", "stdout", "stderr"} or not isinstance(
        decoded["exit_code"], int
    ):
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    return subprocess.CompletedProcess([], decoded["exit_code"], stdout, stderr)


def _execute_in_namespace(config: dict[str, object], authorization: dict[str, object]) -> Run:
    commands = _registered_leaf_commands(config, authorization)
    mapped = {
        (
            tuple(cast(list[str], command["argv"])),
            cast(str, command["cwd"]),
        ): cast(str, command["command_id"])
        for command in commands
    }
    sequence = 0
    state = _active_namespace(config, authorization)

    def execute(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal sequence
        cwd = kwargs.get("cwd")
        if not isinstance(cwd, str):
            raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
        command_id = mapped.get((tuple(argv), cwd))
        if command_id is None:
            raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
        result = _namespace_request(
            Path(cast(str, state["socket_path"])),
            {
                "authorization_id": authorization["authorization_id"],
                "sequence": sequence,
                "command_id": command_id,
            },
        )
        sequence += 1
        return result

    return execute


def _broker_commands(
    config: dict[str, object], expected_sha256: str
) -> dict[str, dict[str, object]]:
    registry = Path(cast(str, config["command_registry_path"]))
    raw = registry.read_bytes()
    if registry.is_symlink() or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    decoded = json.loads(raw)
    rows = decoded.get("commands") if isinstance(decoded, dict) else None
    wanted = config.get("mechanical_command_ids")
    if not isinstance(rows, list) or not isinstance(wanted, list):
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("command_id"), str):
            result[cast(str, row["command_id"])] = row
    if not all(isinstance(item, str) and item in result for item in wanted):
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    selected = {item: result[item] for item in cast(list[str], wanted)}
    if any(command.get("kind") != "review-leaf" for command in selected.values()):
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    return selected


def _run_namespace_broker(args: argparse.Namespace) -> None:
    config = json.loads(Path(args.config).read_text())
    if not isinstance(config, dict) or config.get("network") != "DENY":
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    commands = _broker_commands(config, args.registry_sha256)
    expected = list(cast(list[str], config["mechanical_command_ids"]))
    environment = _environment(config)
    environment["PATH"] = "/review-bin:/usr/bin"
    endpoint = Path(args.socket)
    if endpoint != NAMESPACE_SOCKET or endpoint.exists():
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(endpoint))
        os.chmod(endpoint, 0o600)
        server.listen(1)
        for sequence, command_id in enumerate(expected):
            connection, _ = server.accept()
            with connection:
                raw = connection.recv(4096)
                try:
                    request = json.loads(raw)
                except json.JSONDecodeError as error:
                    raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL") from error
                if (
                    not isinstance(request, dict)
                    or set(request) != {"authorization_id", "sequence", "command_id"}
                    or request.get("authorization_id") != args.authorization_id
                    or request.get("sequence") != sequence
                    or request.get("command_id") != command_id
                ):
                    raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
                if datetime.now(UTC) >= datetime.fromisoformat(args.expires_at).astimezone(UTC):
                    raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
                command = commands[command_id]
                completed = subprocess.run(  # noqa: S603 - closed signed registry command
                    cast(list[str], command["argv"]),
                    cwd=cast(str, command["cwd"]),
                    env=environment,
                    check=False,
                    capture_output=True,
                )
                reply = {
                    "exit_code": completed.returncode,
                    "stdout": base64.b64encode(completed.stdout).decode(),
                    "stderr": base64.b64encode(completed.stderr).decode(),
                }
                connection.sendall(
                    json.dumps(reply, sort_keys=True, separators=(",", ":")).encode()
                )


def _consume(
    config: dict[str, object], authorization: dict[str, object], *, execute: bool
) -> dict[str, object]:
    authority = json.loads(Path(cast(str, config["authority_config"])).read_text())
    if not isinstance(authority, dict):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    public_key, trust_epoch = _public_key(cast(dict[str, object], authority))
    verify_review_launch_authorization(
        authorization,
        public_key,
        cast(str, config["role"]),
        cast(str, config["workspace_root"]),
        cast(str, authorization["pack_zip_sha256"]),
        expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        expected_trust_epoch=trust_epoch,
    )
    context = None
    if (
        authorization.get("schema_version") == "review-launch-authorization/v2"
        or config.get("schema_version") == "review-config/v2"
    ):
        context = measure_review_context(config, authorization)
        recheck_review_context(context)
    _authority_state(authorization, cast(dict[str, object], authority), consume=not execute)
    output = Path(cast(str, config["output_root"]))
    attestation_path = output / "workspace-attestation.json"
    if execute:
        _regular(attestation_path)
        prior = json.loads(attestation_path.read_text())
        registry = json.loads(Path(cast(str, config["command_registry_path"])).read_text())
        runner = (
            run_review_a_checks
            if config["role"] == "IMPLEMENTATION_READINESS_REVIEWER"
            else run_review_b_checks
        )
        execution = runner(config, registry, execute=_execute_in_namespace(config, authorization))
        prior.update(
            {
                "commands_executed_root": execution["commands_executed_root"],
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        attestation_path.write_text(json.dumps(prior, sort_keys=True, separators=(",", ":")) + "\n")
        return execution
    _authority_state(authorization, cast(dict[str, object], authority), consume=False)
    prepared = (
        _prepare_review_directories(config)
        if context is not None
        else prepare_review_workspace(config)
    )
    commands = _preparation_commands(config)
    records = _run_preparation(config, commands)
    namespace = _start_namespace(config, authorization)
    now = datetime.now(UTC).isoformat()
    attestation = {
        "authorization_consumed_at": now,
        "started_at": now,
        "workspace_root": prepared["workspace_root"],
        "allowed_changed_paths": [
            "result.json",
            "execution-receipt.json",
            "workspace-attestation.json",
        ],
        "unexpected_changed_paths": [],
        "fresh_session_attestation": None,
        "preparation_commands": records,
        "preparation_commands_root": _preparation_root(records),
        "commands_executed_root": "0" * 64,
        "namespace": namespace,
    }
    attestation_path.write_text(
        json.dumps(attestation, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return prepared


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--namespace-broker", action="store_true")
    parser.add_argument("--authorization-id")
    parser.add_argument("--registry-sha256")
    parser.add_argument("--socket")
    parser.add_argument("--expires-at")
    args = parser.parse_args()
    if args.namespace_broker:
        if not all(
            (args.config, args.authorization_id, args.registry_sha256, args.socket, args.expires_at)
        ):
            parser.error("namespace broker requires complete fixed arguments")
            return
        _run_namespace_broker(args)
        return
    elif args.config is not None and args.authorization is None and not args.execute:
        result = prepare_review_workspace(json.loads(args.config.read_text()))
    elif args.authorization is not None and args.config is None:
        authorization = json.loads(args.authorization.read_text())
        result = _consume(
            _config_for_role(
                cast(str, authorization["review_role"]),
                2 if authorization.get("schema_version") == "review-launch-authorization/v2" else 1,
            ),
            authorization,
            execute=args.execute,
        )
    else:
        parser.error("provide exactly --config or --authorization")
        return
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
