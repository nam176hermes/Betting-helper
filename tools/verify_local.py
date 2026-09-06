"""Run bounded local checks or fail closed before legacy full qualification."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools import run_command_registry  # noqa: E402
from tools.build_candidate_qualification_receipt import (  # noqa: E402
    validate_candidate_qualification_receipt,
)
from tools.sync_pack_assets import sync_pack_assets  # noqa: E402

REPAIR_TESTS = (
    "tests/repairs/test_restart_evidence_boundary.py",
    "tests/repairs/test_clock_raw_input.py",
    "tests/repairs/test_clock_dispatch_completeness.py",
    "tests/repairs/test_clock_qualification_records.py",
)
PYTEST_CACHE = "cache_dir=.local/bh-repair/pytest-cache"


def _display_argv(argv: Sequence[str]) -> list[str]:
    displayed = list(argv)
    executable = Path(displayed[0])
    if executable.is_absolute():
        try:
            displayed[0] = executable.relative_to(REPOSITORY_ROOT).as_posix()
        except ValueError:
            displayed[0] = executable.name
    return displayed


def _portable_commands() -> tuple[tuple[str, list[str]], ...]:
    pytest = [sys.executable, "-m", "pytest"]
    return (
        (
            "compile_all_tests",
            ["pnpm", "--dir", "extension", "exec", "tsc", "-p", "tsconfig.test.json"],
        ),
        (
            "registry_self_check",
            [sys.executable, "tools/run_command_registry.py", "--self-check"],
        ),
        (
            "implemented_repair_tests",
            [*pytest, "-q", *REPAIR_TESTS, "-o", PYTEST_CACHE],
        ),
        (
            "collect_all_repair_tests",
            [*pytest, "--collect-only", "-q", "tests/repairs", "-o", PYTEST_CACHE],
        ),
    )


def _run_portable() -> int:
    environment = os.environ.copy()
    environment.update(
        {
            "NPM_CONFIG_IGNORE_SCRIPTS": "true",
            "UV_NO_PROGRESS": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        }
    )
    results: list[dict[str, object]] = []
    for check_id, argv in _portable_commands():
        try:
            completed = subprocess.run(  # noqa: S603 - fixed repo-owned command list.
                argv,
                cwd=REPOSITORY_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            result: dict[str, object] = {
                "check_id": check_id,
                "argv": _display_argv(argv),
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            result = {
                "check_id": check_id,
                "argv": _display_argv(argv),
                "exit_code": None,
                "stdout": "",
                "stderr": f"{type(error).__name__}: {error}",
            }
        results.append(result)
        if result["exit_code"] != 0:
            break
    passed = len(results) == len(_portable_commands()) and all(
        result["exit_code"] == 0 for result in results
    )
    print(
        json.dumps(
            {
                "schema_version": "local-verification-report/v1",
                "profile": "portable",
                "status": "PASS" if passed else "FAIL",
                "production_authority": "NONE",
                "results": results,
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def _configured_path(identifier: str, path: Path | None, *, directory: bool) -> dict[str, object]:
    record: dict[str, object] = {"prerequisite_id": identifier, "path": None}
    if path is None:
        return {**record, "status": "MISSING_CONFIGURATION"}
    record["path"] = str(path)
    if not path.is_absolute():
        return {**record, "status": "INVALID", "detail": "path must be absolute"}
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        return {**record, "status": "MISSING", "detail": str(error)}
    record["path"] = str(resolved)
    valid = resolved.is_dir() if directory else resolved.is_file()
    return {**record, "status": "PASS" if valid else "INVALID"}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("JSON root is not an object")
    return cast(dict[str, Any], value)


def _git_output(root: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise ValueError("receipt content mismatch")
    completed = subprocess.run(  # noqa: S603 - fixed git executable and read-only args.
        [git, "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError("receipt content mismatch")
    return completed.stdout.strip()


def _validate_bootstrap_receipt(receipt_path: Path, pack: Path) -> None:
    receipt = _load_object(receipt_path)
    authoring_root = pack.resolve(strict=True).parent
    if (
        set(receipt) != {"schema_version", "root", "head", "tree", "status"}
        or receipt.get("schema_version") != "boot0-authoring-repository-receipt/v2"
        or receipt.get("root") != str(authoring_root)
        or receipt.get("head") != _git_output(authoring_root, "rev-parse", "HEAD")
        or receipt.get("tree") != _git_output(authoring_root, "rev-parse", "HEAD^{tree}")
        or receipt.get("status") != ""
        or _git_output(authoring_root, "status", "--porcelain", "--untracked-files=all")
    ):
        raise ValueError("receipt content mismatch")


def _validate_authoring_tests(root: Path) -> None:
    delivery = _load_object(
        REPOSITORY_ROOT
        / "vendor/hybrid-discovery-v6.3.6/docs/registries/delivery-map.v1.json"
    )
    exports = delivery.get("authoring_source_exports")
    if not isinstance(exports, list):
        raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
    expected = {
        Path(cast(str, item["source"])).name
        for item in exports
        if isinstance(item, dict)
        and isinstance(item.get("source"), str)
        and cast(str, item["source"]).startswith("authoring-tests/")
    }
    if not expected:
        raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
    for name in expected:
        path = root / name
        try:
            source = path.read_text()
            tree = ast.parse(source)
        except (OSError, UnicodeError, SyntaxError) as error:
            raise ValueError("E_EXTERNAL_AUTHORING_TESTS") from error
        if path.is_symlink() or not source or not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in ast.walk(tree)
        ):
            raise ValueError("E_EXTERNAL_AUTHORING_TESTS")


def _nonempty_directory(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and next(path.iterdir(), None) is not None


def _validate_cache(root: Path, kind: str) -> None:
    if kind == "uv":
        tag = root / "CACHEDIR.TAG"
        valid = tag.is_file() and bool(tag.read_bytes()) and any(
            child.name.startswith(("archive-v", "wheels-v", "simple-v", "sdists-v"))
            and _nonempty_directory(child)
            for child in root.iterdir()
        )
        code = "E_UV_CACHE"
    elif kind == "pnpm":
        valid = all(_nonempty_directory(root / name) for name in ("files", "index"))
        code = "E_PNPM_STORE"
    else:
        raise ValueError("E_CACHE_KIND")
    if not valid:
        raise ValueError(code)


def _controller_binding(args: argparse.Namespace) -> dict[str, object]:
    commands = run_command_registry.candidate_commands(run_command_registry.validate_registry())
    values = [
        cast(str, value)
        for command in commands
        for value in [command["cwd"], *cast(list[str], command["argv"])]
    ]
    root = str(REPOSITORY_ROOT)
    configured = {
        name: path
        for name, path in {
            "pack": args.pack,
            "evidence_root": args.evidence_root,
            "authoring_tests": args.authoring_tests,
            "uv_cache": args.uv_cache,
            "pnpm_store": args.pnpm_store,
            "chrome": args.chrome,
        }.items()
        if path is not None
    }
    unbound = []
    if {cast(str, command["cwd"]) for command in commands} != {root}:
        unbound.append("checkout_root")
    for name, path in configured.items():
        resolved = str(path.resolve())
        if not any(value == resolved or value.startswith(f"{resolved}/") for value in values):
            unbound.append(name)
    if unbound:
        return {
            "prerequisite_id": "controller_configuration_binding",
            "path": None,
            "status": "HOLD",
            "code": "CONTROLLER_CONFIG_UNBOUND",
            "detail": sorted(unbound),
        }
    return {
        "prerequisite_id": "controller_configuration_binding",
        "path": None,
        "status": "PASS",
    }


def _full_prerequisites(args: argparse.Namespace) -> list[dict[str, object]]:
    pack = _configured_path("governed_source_pack", args.pack, directory=True)
    if pack["status"] == "PASS":
        try:
            sync_pack_assets(Path(cast(str, pack["path"])), REPOSITORY_ROOT, check=True)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            pack.update(status="INVALID", detail=str(error))

    evidence = _configured_path("evidence_root", args.evidence_root, directory=True)
    bootstrap: dict[str, object] = {
        "prerequisite_id": "authoring_repository_receipt",
        "path": None,
        "status": "MISSING_CONFIGURATION",
    }
    candidate: dict[str, object] = {
        "prerequisite_id": "candidate_qualification_receipt",
        "path": None,
        "status": "MISSING_CONFIGURATION",
    }
    if evidence["status"] == "PASS":
        evidence_root = Path(cast(str, evidence["path"]))
        bootstrap_path = evidence_root / "bootstrap/authoring-repository-receipt.json"
        bootstrap = _configured_path(
            "authoring_repository_receipt", bootstrap_path, directory=False
        )
        if bootstrap["status"] == "PASS":
            try:
                if pack["status"] != "PASS":
                    raise ValueError("receipt content mismatch")
                _validate_bootstrap_receipt(
                    bootstrap_path, Path(cast(str, pack["path"]))
                )
            except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
                bootstrap.update(status="INVALID", detail=str(error))

        candidate_path = evidence_root / "CANDIDATE_QUALIFICATION.json"
        candidate = _configured_path(
            "candidate_qualification_receipt", candidate_path, directory=False
        )
        if candidate["status"] == "PASS":
            try:
                validate_candidate_qualification_receipt(
                    REPOSITORY_ROOT,
                    evidence_root / "V636-P07-T01.json",
                    _load_object(candidate_path),
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                candidate.update(status="INVALID", detail=str(error))

    uv_cache = _configured_path("uv_cache", args.uv_cache, directory=True)
    pnpm_store = _configured_path("pnpm_store", args.pnpm_store, directory=True)
    authoring_tests = _configured_path(
        "external_authoring_tests", args.authoring_tests, directory=True
    )
    if authoring_tests["status"] == "PASS":
        try:
            _validate_authoring_tests(Path(cast(str, authoring_tests["path"])))
        except (OSError, ValueError) as error:
            authoring_tests.update(status="INVALID", detail=str(error))
    for record, kind in ((uv_cache, "uv"), (pnpm_store, "pnpm")):
        if record["status"] == "PASS":
            try:
                _validate_cache(Path(cast(str, record["path"])), kind)
            except (OSError, ValueError) as error:
                record.update(status="INVALID", detail=str(error))
    chrome = _configured_path("chrome_binary", args.chrome, directory=False)
    if chrome["status"] == "PASS":
        chrome_path = Path(cast(str, chrome["path"]))
        if args.chrome_sha256 is None:
            chrome.update(status="MISSING_CONFIGURATION", detail="--chrome-sha256 is required")
        else:
            with chrome_path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if not os.access(chrome_path, os.X_OK) or digest != args.chrome_sha256:
                chrome.update(status="INVALID", detail="executable bit or SHA-256 mismatch")

    return [
        pack,
        evidence,
        bootstrap,
        candidate,
        authoring_tests,
        uv_cache,
        pnpm_store,
        chrome,
        _controller_binding(args),
    ]


def _delegate_controller() -> int:
    completed = subprocess.run(  # noqa: S603 - fixed authoritative controller argv.
        [
            sys.executable,
            str(REPOSITORY_ROOT / "tools/run_command_registry.py"),
            "--mode",
            "candidate-qualification",
            "--registry",
            "task-command-registry.json",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    return completed.returncode


def _run_full(args: argparse.Namespace) -> int:
    prerequisites = _full_prerequisites(args)
    ready = all(item["status"] == "PASS" for item in prerequisites)
    hold_codes = sorted(
        cast(str, item["code"]) for item in prerequisites if isinstance(item.get("code"), str)
    )
    print(
        json.dumps(
            {
                "schema_version": "full-verification-prerequisites/v1",
                "profile": "full",
                "status": "READY" if ready else "HOLD",
                "production_authority": "NONE",
                "authoritative_controller": "PENDING" if ready else "NOT_EXECUTED",
                "hold_codes": hold_codes,
                "prerequisites": prerequisites,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if not ready:
        return 2
    return _delegate_controller()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("portable", "full"), required=True)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--authoring-tests", type=Path)
    parser.add_argument("--uv-cache", type=Path)
    parser.add_argument("--pnpm-store", type=Path)
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--chrome-sha256")
    args = parser.parse_args(argv)
    return _run_portable() if args.profile == "portable" else _run_full(args)


if __name__ == "__main__":
    raise SystemExit(main())
