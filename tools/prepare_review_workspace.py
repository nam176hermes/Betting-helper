"""Prepare a one-use, read-only Bubblewrap review workspace."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import select
import selectors
import shutil
import signal
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from moj_discovery.canonical import parse_strict_json
from moj_discovery.review_authorization import verify_review_launch_authorization
from tools.issue_review_launch_authorization import (
    measure_review_context,
    recheck_review_context,
    resolve_review_run,
    review_config_for_authorization,
    review_config_for_role,
    review_execution_root,
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
    if config.get("schema_version") in {"review-config/v2", "review-config/v3"}:
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
    if workspace != workspace.resolve() or output != output.resolve():
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    reuse_legacy = config.get("schema_version") != "review-config/v3"
    workspace.mkdir(parents=True, exist_ok=reuse_legacy)
    output.mkdir(parents=True, exist_ok=reuse_legacy)
    return {"result": "PASS", "workspace_root": str(workspace), "output_root": str(output)}


def _config_for_role(role: str, version: int = 1) -> dict[str, object]:
    return review_config_for_role(role, version, runtime_root=RUNTIME_ROOT)


def _config_template(config: dict[str, object]) -> dict[str, object]:
    version = 3 if config.get("schema_version") == "review-config/v3" else 2
    template = _config_for_role(cast(str, config["role"]), version)
    expected = (
        resolve_review_run(template, cast(str, config["review_run_id"]))
        if version == 3
        else template
    )
    if config != expected:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    return template


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
    if config.get("schema_version") == "review-config/v3":
        template = _config_template(config)
        before = cast(dict[str, object], template["node_environment"])["project_root"]
        after = cast(dict[str, object], config["node_environment"])["project_root"]
        result = [{**row, "cwd": after} if row["cwd"] == before else row for row in result]
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
    runtime = _python_runtime_projection(config)
    if runtime is not None:
        environment["UV_PYTHON"] = str(runtime[0] / "bin/python3.12")
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


def _reject_unvalidated_python_bytecode(environment: Path) -> None:
    """A projected prepared environment must not expose excluded executable caches."""
    _directory(environment)

    def failed_walk(_error: OSError) -> None:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")

    try:
        for directory, names, files in os.walk(
            environment, followlinks=True, onerror=failed_walk
        ):
            parent = Path(directory)
            for name in (*names, *files):
                entry = parent / name
                if name == "__pycache__" or name.lower().endswith((".pyc", ".pyo")):
                    raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
                if entry.is_symlink():
                    resolved = entry.resolve(strict=True)
                    if ("__pycache__" in resolved.parts
                            or resolved.suffix.lower() in {".pyc", ".pyo"}):
                        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
            for name in names:
                resolved = (parent / name).resolve(strict=True)
                if not resolved.is_relative_to(environment) or any(
                    ancestor.resolve() == resolved for ancestor in (parent, *parent.parents)
                ):
                    raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    except (OSError, RuntimeError) as error:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION") from error


def _dependency_projection(root: Path, boundary: Path, *, python: bool) -> dict[str, str]:
    """Compare package source bytes; only a cache-free prepared tree is projectable."""
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


def _python_runtime_projection(config: dict[str, object]) -> tuple[Path, str] | None:
    """Verify the finite source-declared standalone Python tree before mounting it."""
    declared = config.get("python_runtime")
    if declared is None:
        return None
    if not isinstance(declared, dict) or set(declared) != {"root", "sha256"}:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    root = Path(str(declared["root"]))
    if not root.is_absolute() or root != root.resolve(strict=True):
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    _reject_unvalidated_python_bytecode(root)
    projection = _dependency_projection(root, root, python=True)
    digest = hashlib.sha256(rfc8785.dumps(cast(Any, projection))).hexdigest()
    if digest != declared["sha256"]:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    return root, digest


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

    if config.get("schema_version") not in {"review-config/v2", "review-config/v3"}:
        raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
    _config_template(config)
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
    _reject_unvalidated_python_bytecode(prepared)
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
    python_runtime = _python_runtime_projection(config)
    if python_runtime is not None:
        readonly.append((python_runtime[0], python_runtime[0]))
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
    if type(pid) is not int or pid <= 1:
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)
        if len(fields) != 2 or len(fields[1].split()) < 20 or fields[1].split()[0] == "Z":
            raise ValueError("E_REVIEW_NAMESPACE_STALE")
        namespaces = {
            name: os.stat(f"/proc/{pid}/ns/{name}").st_ino for name in ("user", "pid", "mnt", "net")
        }
    except OSError as error:
        raise ValueError("E_REVIEW_NAMESPACE_STALE") from error
    return {"pid": pid, "start_ticks": fields[1].split()[19], "namespaces": namespaces}


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("E_REVIEW_NAMESPACE_EXPIRED")
    return remaining


def _lease_deadline(expires_at: object) -> float:
    expires = datetime.fromisoformat(str(expires_at))
    if expires.tzinfo is None:
        raise ValueError("E_REVIEW_NAMESPACE_EXPIRED")
    remaining = (expires.astimezone(UTC) - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise ValueError("E_REVIEW_NAMESPACE_EXPIRED")
    return time.monotonic() + min(28800, remaining)


def _read_frame(connection: socket.socket, limit: int, deadline: float) -> dict[str, Any]:
    raw = bytearray()
    while b"\n" not in raw:
        connection.settimeout(_remaining(deadline))
        chunk = connection.recv(min(65536, limit + 1 - len(raw)))
        if not chunk:
            raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
        raw.extend(chunk)
        if len(raw) > limit:
            raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    value = parse_strict_json(bytes(raw))
    if not isinstance(value, dict):
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    return cast(dict[str, Any], value)


def _namespace_exchange(
    socket_path: Path,
    payload: dict[str, object],
    deadline: float,
    expected_peer: dict[str, object] | None = None,
) -> tuple[dict[str, Any], int]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if len(encoded) > 4096:
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    directory = os.open(socket_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(_remaining(deadline))
            connection.connect(f"/proc/self/fd/{directory}/{socket_path.name}")
            pid, uid, _gid = struct.unpack(
                "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if uid != os.getuid():
                raise ValueError("E_REVIEW_NAMESPACE_STALE")
            if expected_peer is not None:
                facts = _namespace_facts(pid)
                if any(expected_peer.get(name) != value for name, value in facts.items()):
                    raise ValueError("E_REVIEW_NAMESPACE_STALE")
            connection.sendall(encoded)
            response = _read_frame(connection, 1 << 20, deadline)
            _remaining(deadline)
            return response, pid
    finally:
        os.close(directory)


def _namespace_status(
    socket_path: Path,
    authorization: dict[str, object],
    deadline: float,
    expected_peer: dict[str, object] | None = None,
) -> dict[str, object]:
    response, pid = _namespace_exchange(
        socket_path,
        {"authorization_id": authorization["authorization_id"], "kind": "STATUS"},
        deadline,
        expected_peer,
    )
    expected = {
        name: authorization[name]
        for name in ("authorization_id", "command_registry_sha256", "expires_at")
    }
    if (
        set(response) != {*expected, "sequence"}
        or any(response.get(key) != value for key, value in expected.items())
        or type(response["sequence"]) is not int
        or response["sequence"] != 0
    ):
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    facts = _namespace_facts(pid)
    if any(
        inode == os.stat(f"/proc/self/ns/{name}").st_ino
        for name, inode in cast(dict[str, int], facts["namespaces"]).items()
    ):
        raise ValueError("E_REVIEW_NAMESPACE_STALE")
    return facts


def _write_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _start_namespace(
    config: dict[str, object], authorization: dict[str, object]
) -> dict[str, object]:
    version = (
        3
        if config.get("schema_version") == "review-config/v3"
        else (2 if authorization.get("schema_version") == "review-launch-authorization/v2" else 1)
    )
    if version >= 2:
        _config_template(config)
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
            *(["--review-run-id", str(authorization["review_run_id"])] if version == 3 else []),
        ],
        "cwd": str(RUNTIME_ROOT),
    }
    lease_deadline = _lease_deadline(authorization["expires_at"])
    reader, writer = os.pipe()
    process = None
    sandbox: dict[str, object] | None = None
    sandbox_fd = -1
    try:
        argv = build_bubblewrap_argv(config, broker, leaf_commands=commands)
        argv[1:1] = ["--info-fd", str(writer)]
        deadline = min(time.monotonic() + 5, lease_deadline)
        _remaining(deadline)
        with (control / "broker.stderr").open("xb") as error:
            os.fchmod(error.fileno(), 0o600)
            process = subprocess.Popen(  # noqa: S603 - fixed bwrap and signed registry
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=error,
                start_new_session=True,
                pass_fds=(writer,),
            )
        os.close(writer)
        writer = -1
        info = bytearray()
        while True:
            ready, _, _ = select.select([reader], [], [], _remaining(deadline))
            if not ready:
                raise ValueError("E_REVIEW_NAMESPACE_START")
            chunk = os.read(reader, 4097 - len(info))
            if not chunk:
                break
            info.extend(chunk)
            if len(info) > 4096:
                raise ValueError("E_REVIEW_NAMESPACE_START")
        decoded = parse_strict_json(bytes(info))
        if not isinstance(decoded, dict) or type(decoded.get("child-pid")) is not int:
            raise ValueError("E_REVIEW_NAMESPACE_START")
        sandbox = _namespace_facts(decoded["child-pid"])
        sandbox_fd = os.pidfd_open(decoded["child-pid"])
        while _remaining(deadline):
            if process.poll() is not None:
                raise ValueError("E_REVIEW_NAMESPACE_START")
            if socket_path.exists():
                peer = _namespace_status(socket_path, authorization, deadline)
                # bwrap can enter its final user namespace after writing --info-fd.
                ready_sandbox = _namespace_facts(cast(int, sandbox["pid"]))
                if (
                    ready_sandbox["start_ticks"] != sandbox["start_ticks"]
                    or peer["namespaces"] != ready_sandbox["namespaces"]
                ):
                    raise ValueError("E_REVIEW_NAMESPACE_START")
                state = {
                    "schema_version": "review-namespace/v2",
                    "authorization_id": authorization["authorization_id"],
                    "command_registry_sha256": authorization["command_registry_sha256"],
                    "expires_at": authorization["expires_at"],
                    "socket_path": str(socket_path),
                    "host_boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    **peer,
                }
                _write_json(_namespace_state_path(config), state)
                return state
            time.sleep(min(0.02, _remaining(deadline)))
    except (OSError, ValueError) as error:
        if sandbox_fd != -1:
            with suppress(OSError):
                signal.pidfd_send_signal(sandbox_fd, signal.SIGTERM)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        raise ValueError("E_REVIEW_NAMESPACE_START") from error
    finally:
        os.close(reader)
        if writer != -1:
            os.close(writer)
        if sandbox_fd != -1:
            os.close(sandbox_fd)
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
        "schema_version": "review-namespace/v2",
        "authorization_id": authorization["authorization_id"],
        "command_registry_sha256": authorization["command_registry_sha256"],
        "expires_at": authorization["expires_at"],
        "socket_path": str(Path(cast(str, config["scratch_root"])) / "tmp/namespace.sock"),
        "host_boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
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
    _namespace_status(
        Path(cast(str, state["socket_path"])),
        authorization,
        min(time.monotonic() + 5, _lease_deadline(authorization["expires_at"])),
        state,
    )
    return state


def _namespace_request(
    socket_path: Path,
    payload: dict[str, object],
    *,
    deadline: float | None = None,
    expected_peer: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    decoded, _pid = _namespace_exchange(
        socket_path,
        payload,
        deadline if deadline is not None else time.monotonic() + 60,
        expected_peer,
    )
    try:
        stdout = base64.b64decode(decoded["stdout"], validate=True)
        stderr = base64.b64decode(decoded["stderr"], validate=True)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL") from error
    if set(decoded) != {"exit_code", "stdout", "stderr"} or type(decoded["exit_code"]) is not int:
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    return subprocess.CompletedProcess([], decoded["exit_code"], stdout, stderr)


def _execute_in_namespace(
    config: dict[str, object],
    authorization: dict[str, object],
    context: dict[str, object] | None = None,
    log_root: Path | None = None,
) -> Run:
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
    deadline = _lease_deadline(authorization["expires_at"])

    def execute(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal sequence
        cwd = kwargs.get("cwd")
        if not isinstance(cwd, str):
            raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
        command_id = mapped.get((tuple(argv), cwd))
        if command_id is None:
            raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
        authority = json.loads(Path(cast(str, config["authority_config"])).read_bytes())
        public, epoch = _public_key(authority)
        verify_review_launch_authorization(
            authorization,
            public,
            cast(str, config["role"]),
            cast(str, config["workspace_root"]),
            cast(str, authorization["pack_zip_sha256"]),
            expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            expected_trust_epoch=epoch,
        )
        _authority_state(authorization, authority, consume=False)
        if context is not None:
            recheck_review_context(context)
        result = _namespace_request(
            Path(cast(str, state["socket_path"])),
            {
                "authorization_id": authorization["authorization_id"],
                "sequence": sequence,
                "command_id": command_id,
            },
            deadline=min(deadline, _lease_deadline(authorization["expires_at"])),
            expected_peer=state,
        )
        if log_root is not None:
            for stream, data in (("stdout", result.stdout), ("stderr", result.stderr)):
                with (log_root / f"{sequence:02d}.{stream}").open("xb") as output:
                    output.write(data)
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


def _run_broker_command(
    command: dict[str, object],
    environment: dict[str, str],
    deadline: float,
    expires_at: datetime,
) -> dict[str, object]:
    def remaining() -> float:
        if expires_at.tzinfo is None or datetime.now(UTC) >= expires_at:
            raise ValueError("E_REVIEW_NAMESPACE_TIMEOUT")
        return _remaining(deadline)

    remaining()
    child = subprocess.Popen(  # noqa: S603 - exact signed registry argv, never client argv
        cast(list[str], command["argv"]),
        cwd=cast(str, command["cwd"]),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert child.stdout is not None and child.stderr is not None
    output = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        with child.stdout, child.stderr, selectors.DefaultSelector() as selector:
            for stream, name in ((child.stdout, "stdout"), (child.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() or child.returncode is None:
                # Keep the leader unreaped until its group is stopped: no PID reuse.
                if (
                    child.returncode is None
                    and os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                    is not None
                ):
                    with suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=1)
                for ready, _ in selector.select(min(0.05, remaining())):
                    chunk = os.read(ready.fd, 65536)
                    if not chunk:
                        selector.unregister(ready.fileobj)
                    else:
                        output[ready.data].extend(chunk)
                        if sum(map(len, output.values())) > 750000:
                            raise ValueError("E_REVIEW_NAMESPACE_OUTPUT_LIMIT")
            remaining()
            return {
                "exit_code": child.returncode,
                **{name: base64.b64encode(value).decode() for name, value in output.items()},
            }
    finally:
        if child.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=1)


def _broker_environment(
    config: dict[str, object], commands: dict[str, dict[str, object]],
) -> dict[str, str]:
    environment = _environment(config)
    environment["PATH"] = "/review-bin:/usr/bin"
    if "A_CHECK_DESCENDANT" in commands:
        declaration = cast(dict[str, str], config["producer_environment"])
        projected = {
            "PATH": str(Path(declaration["node_lookup"]).parent) + ":/review-bin:/usr/bin",
            "UV_PROJECT_ENVIRONMENT": declaration["python_environment"],
            "WSL_DISTRO_NAME": declaration["wsl_distro"],
        }
        # The host validated and bwrap installed exactly these three values.
        # No other ambient variable enters a leaf subprocess.
        if any(os.environ.get(name) != value for name, value in projected.items()):
            raise ValueError("E_REVIEW_WORKSPACE_ISOLATION")
        environment.update(projected)
    return environment


def _run_namespace_broker(args: argparse.Namespace) -> None:
    config = json.loads(Path(args.config).read_text())
    if not isinstance(config, dict) or config.get("network") != "DENY":
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    if config.get("schema_version") == "review-config/v3":
        config = resolve_review_run(config, args.review_run_id)
    elif args.review_run_id is not None:
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    commands = _broker_commands(config, args.registry_sha256)
    expected = list(cast(list[str], config["mechanical_command_ids"]))
    environment = _broker_environment(config, commands)
    endpoint = Path(args.socket)
    if endpoint != NAMESPACE_SOCKET or endpoint.exists():
        raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
    deadline = _lease_deadline(args.expires_at)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(endpoint))
        os.chmod(endpoint, 0o600)
        server.listen(1)
        sequence = 0
        while sequence < len(expected):
            server.settimeout(_remaining(deadline))
            connection, _ = server.accept()
            with connection:
                request = _read_frame(connection, 4096, min(deadline, time.monotonic() + 5))
                if request == {"authorization_id": args.authorization_id, "kind": "STATUS"}:
                    reply = {
                        "authorization_id": args.authorization_id,
                        "command_registry_sha256": args.registry_sha256,
                        "expires_at": args.expires_at,
                        "sequence": sequence,
                    }
                    connection.settimeout(_remaining(deadline))
                    connection.sendall(json.dumps(reply, sort_keys=True).encode() + b"\n")
                    continue
                command_id = expected[sequence]
                if (
                    not isinstance(request, dict)
                    or set(request) != {"authorization_id", "sequence", "command_id"}
                    or request.get("authorization_id") != args.authorization_id
                    or type(request.get("sequence")) is not int
                    or request.get("sequence") != sequence
                    or request.get("command_id") != command_id
                ):
                    raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
                if datetime.now(UTC) >= datetime.fromisoformat(args.expires_at).astimezone(UTC):
                    raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
                if _broker_commands(config, args.registry_sha256) != commands:
                    raise ValueError("E_REVIEW_NAMESPACE_PROTOCOL")
                reply = _run_broker_command(
                    commands[command_id],
                    environment,
                    min(deadline, _lease_deadline(args.expires_at)),
                    datetime.fromisoformat(args.expires_at),
                )
                connection.settimeout(_remaining(min(deadline, _lease_deadline(args.expires_at))))
                connection.sendall(
                    json.dumps(reply, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                )
                sequence += 1


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
    if authorization.get("schema_version") == "review-launch-authorization/v2" or config.get(
        "schema_version"
    ) in {"review-config/v2", "review-config/v3"}:
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
        host_root = review_execution_root(authorization, authority)
        host_root.mkdir(parents=True, exist_ok=False, mode=0o700)
        execution = runner(
            config,
            registry,
            execute=_execute_in_namespace(
                config,
                authorization,
                context,
                host_root,
            ),
        )
        if context is not None:
            recheck_review_context(context)
        _authority_state(authorization, authority, consume=False)
        with (host_root / "execution.json").open("x") as stream:
            json.dump(
                {"authorization_id": authorization["authorization_id"], **execution},
                stream,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
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
    parser.add_argument("--review-run-id")
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
            review_config_for_authorization(authorization, runtime_root=RUNTIME_ROOT),
            authorization,
            execute=args.execute,
        )
    else:
        parser.error("provide exactly --config or --authorization")
        return
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
