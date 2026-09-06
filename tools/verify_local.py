"""Run bounded local checks or fail closed before legacy full qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

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
                receipt = _load_object(bootstrap_path)
                expected_root = (
                    str(Path(cast(str, pack["path"])).parent)
                    if pack["status"] == "PASS"
                    else None
                )
                if (
                    set(receipt) != {"schema_version", "root", "head", "tree", "status"}
                    or receipt.get("schema_version") != "boot0-authoring-repository-receipt/v2"
                    or receipt.get("root") != expected_root
                    or receipt.get("status") != ""
                    or re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("head"))) is None
                    or re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("tree"))) is None
                ):
                    raise ValueError("receipt content mismatch")
            except (OSError, ValueError, json.JSONDecodeError) as error:
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

    return [pack, evidence, bootstrap, candidate, authoring_tests, uv_cache, pnpm_store, chrome]


def _run_full(args: argparse.Namespace) -> int:
    prerequisites = _full_prerequisites(args)
    ready = all(item["status"] == "PASS" for item in prerequisites)
    print(
        json.dumps(
            {
                "schema_version": "full-verification-prerequisites/v1",
                "profile": "full",
                "status": "READY" if ready else "HOLD",
                "production_authority": "NONE",
                "authoritative_controller": "PENDING" if ready else "NOT_EXECUTED",
                "prerequisites": prerequisites,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if not ready:
        return 2
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
