"""Run bounded local checks or fail closed before legacy full qualification."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools import run_command_registry  # noqa: E402
from tools.build_candidate_qualification_receipt import (  # noqa: E402
    validate_candidate_qualification_receipt,
)
from tools.full_verifier_config import FullVerifierConfig, load_controller_config  # noqa: E402
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


def _portable_timeout(check_id: str) -> int:
    return 900 if check_id == "implemented_repair_tests" else 300


def _portable_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTEST_", "PYTHON"))
    }
    environment.update(
        {
            "NPM_CONFIG_IGNORE_SCRIPTS": "true",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "UV_NO_PROGRESS": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        }
    )
    return environment


def _captured_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _run_portable() -> int:
    environment = _portable_environment()
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
                timeout=_portable_timeout(check_id),
            )
            result: dict[str, object] = {
                "check_id": check_id,
                "argv": _display_argv(argv),
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        except subprocess.TimeoutExpired as error:
            partial_stderr = _captured_text(error.stderr)
            result = {
                "check_id": check_id,
                "argv": _display_argv(argv),
                "exit_code": None,
                "stdout": _captured_text(error.stdout),
                "stderr": "\n".join(
                    part
                    for part in (partial_stderr, f"{type(error).__name__}: {error}")
                    if part
                ),
            }
        except OSError as error:
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


def _configured_output_directory(identifier: str, path: Path) -> dict[str, object]:
    record: dict[str, object] = {"prerequisite_id": identifier, "path": str(path)}
    if not path.is_absolute() or path.is_symlink():
        return {**record, "status": "INVALID"}
    if path.exists():
        return {**record, "status": "PASS" if path.is_dir() else "INVALID"}
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as error:
        return {**record, "status": "MISSING", "detail": str(error)}
    return {**record, "status": "PASS" if parent.is_dir() else "INVALID"}


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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


def _validate_bootstrap_receipt(
    receipt_path: Path, pack: Path, accepted_ancestor: str
) -> None:
    receipt = _load_object(receipt_path)
    authoring_root = pack.resolve(strict=True).parent
    if (
        set(receipt)
        != {
            "schema_version",
            "accepted_authoring_ancestor",
            "root",
            "head",
            "tree",
            "status",
        }
        or receipt.get("schema_version") != "current-authoring-repository-receipt/v1"
        or receipt.get("accepted_authoring_ancestor") != accepted_ancestor
        or receipt.get("root") != str(authoring_root)
        or receipt.get("head") != _git_output(authoring_root, "rev-parse", "HEAD")
        or receipt.get("tree") != _git_output(authoring_root, "rev-parse", "HEAD^{tree}")
        or receipt.get("status") != ""
        or _git_output(authoring_root, "status", "--porcelain", "--untracked-files=all")
    ):
        raise ValueError("receipt content mismatch")
    _git_output(
        authoring_root,
        "merge-base",
        "--is-ancestor",
        accepted_ancestor,
        cast(str, receipt["head"]),
    )


def _validate_authoring_tests(root: Path, expected_sha256: str | None = None) -> str:
    delivery = _load_object(
        REPOSITORY_ROOT / "vendor/hybrid-discovery-v6.3.6/docs/registries/delivery-map.v1.json"
    )
    exports = delivery.get("authoring_source_exports")
    if not isinstance(exports, list):
        raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
    expected: set[str] = set()
    destinations: set[str] = set()
    for item in exports:
        if (
            not isinstance(item, dict)
            or set(item) != {"source", "destination", "owner"}
            or item["owner"] != "V636-P09-T01"
        ):
            raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
        for field in ("source", "destination"):
            value = item[field]
            if (
                not isinstance(value, str)
                or not value
                or "\\" in value
                or "\0" in value
                or PurePosixPath(value).is_absolute()
                or PurePosixPath(value).as_posix() != value
                or any(part in {".", ".."} for part in PurePosixPath(value).parts)
            ):
                raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
        name, destination = item["source"], item["destination"]
        if (
            name in expected
            or destination in destinations
            or PurePosixPath(destination).parts[:2] != ("pack", "authoring-source")
            or len(PurePosixPath(destination).parts) < 3
        ):
            raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
        expected.add(name)
        destinations.add(destination)
    python_expected = {
        name for name in expected if name.startswith(("authoring-tests/", "authoring-tools/"))
    }
    if not python_expected:
        raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
    authoring_root = root.parent
    actual_paths = {
        path.relative_to(authoring_root).as_posix()
        for directory in (authoring_root / "authoring-tests", authoring_root / "authoring-tools")
        for path in directory.rglob("*.py")
        if path.is_file()
    }
    if actual_paths != python_expected:
        raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
    rows: list[tuple[str, int, str]] = []
    for name in sorted(expected, key=lambda item: item.encode()):
        path = authoring_root / name
        try:
            info = path.lstat()
            if (
                path.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or path.resolve(strict=True) != path
            ):
                raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
            contents = path.read_bytes()
            source = contents.decode("utf-8") if name in python_expected else ""
        except (OSError, UnicodeError, RuntimeError) as error:
            raise ValueError("E_EXTERNAL_AUTHORING_TESTS") from error
        if not contents:
            raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
        if name.startswith("authoring-tests/"):
            try:
                tree = ast.parse(source)
            except SyntaxError as error:
                raise ValueError("E_EXTERNAL_AUTHORING_TESTS") from error
            if not any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
                for node in ast.walk(tree)
            ):
                raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
        rows.append((name, len(contents), hashlib.sha256(contents).hexdigest()))
    payload = "".join(f"{name}\0{size}\0{digest}\n" for name, size, digest in rows).encode()
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("E_EXTERNAL_AUTHORING_TESTS")
    return digest


def _external_authoring_environment(config: FullVerifierConfig) -> dict[str, str]:
    environment = run_command_registry.execution_environment(config)
    environment.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    return environment


def _execute_external_authoring_suite(config: FullVerifierConfig) -> dict[str, object]:
    completed = subprocess.run(  # noqa: S603 - exact argv is source-owned configuration.
        list(config.external_authoring_argv),
        cwd=config.external_authoring_cwd,
        env=_external_authoring_environment(config),
        capture_output=True,
        check=False,
    )
    stdout = completed.stdout
    stderr = completed.stderr
    record: dict[str, object] = {
        "argv": list(config.external_authoring_argv),
        "cwd": str(config.external_authoring_cwd),
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stdout_size_bytes": str(len(stdout)),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stderr_size_bytes": str(len(stderr)),
    }
    if completed.returncode == 0:
        run_command_registry.validate_external_authoring_result(record, config)
    return record


def _nonempty_directory(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and next(path.iterdir(), None) is not None


def _validate_cache(root: Path, kind: str) -> None:
    if kind == "uv":
        tag = root / "CACHEDIR.TAG"
        valid = (
            tag.is_file()
            and bool(tag.read_bytes())
            and any(
                child.name.startswith(("archive-v", "wheels-v", "simple-v", "sdists-v"))
                and _nonempty_directory(child)
                for child in root.iterdir()
            )
        )
        code = "E_UV_CACHE"
    elif kind == "pnpm":
        valid = all(_nonempty_directory(root / name) for name in ("files", "index"))
        code = "E_PNPM_STORE"
    else:
        raise ValueError("E_CACHE_KIND")
    if not valid:
        raise ValueError(code)


def _controller_binding(config: FullVerifierConfig) -> dict[str, object]:
    try:
        registry = run_command_registry.validate_registry()
        commands = run_command_registry.effective_candidate_commands(registry, config)
        environment = run_command_registry.execution_environment(config)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "prerequisite_id": "controller_configuration_binding",
            "path": str(config.source_path),
            "status": "HOLD",
            "code": "CONTROLLER_CONFIG_UNBOUND",
            "detail": str(error),
        }
    external = next(
        (
            item
            for item in cast(list[dict[str, object]], registry["commands"])
            if item["command_id"] == "VERIFY_EXTERNAL_AUTHORING_SOURCES"
        ),
        None,
    )
    if (
        {Path(cast(str, command["cwd"])) for command in commands} != {config.current_checkout_root}
        or external is None
        or external.get("cwd") != str(config.external_authoring_cwd)
        or external.get("argv") != list(config.external_authoring_argv)
        or environment.get("UV_CACHE_DIR") != str(config.uv_cache)
        or environment.get("npm_config_store_dir") != str(config.pnpm_store)
        or environment.get("BH_CHROME_BINARY") != str(config.chrome_path)
        or environment.get("UV_OFFLINE") != "1"
        or environment.get("npm_config_offline") != "true"
    ):
        return {
            "prerequisite_id": "controller_configuration_binding",
            "path": str(config.source_path),
            "status": "HOLD",
            "code": "CONTROLLER_CONFIG_UNBOUND",
        }
    return {
        "prerequisite_id": "controller_configuration_binding",
        "path": str(config.source_path),
        "status": "PASS",
    }


def _full_prerequisites(config: FullVerifierConfig) -> list[dict[str, object]]:
    source_config = _configured_path(
        "source_owned_controller_config", config.source_path, directory=False
    )
    pack = _configured_path("governed_source_pack", config.governed_source_pack, directory=True)
    if pack["status"] == "PASS":
        try:
            sync_pack_assets(Path(cast(str, pack["path"])), REPOSITORY_ROOT, check=True)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            pack.update(status="INVALID", detail=str(error))

    evidence = _configured_output_directory("evidence_root", config.evidence_root)
    bootstrap: dict[str, object] = {
        "prerequisite_id": "authoring_repository_receipt",
        "path": None,
        "status": "MISSING_CONFIGURATION",
    }
    if evidence["status"] == "PASS":
        bootstrap_path = config.authoring_repository_receipt
        bootstrap = _configured_path(
            "authoring_repository_receipt", bootstrap_path, directory=False
        )
        if bootstrap["status"] == "PASS":
            try:
                if pack["status"] != "PASS":
                    raise ValueError("receipt content mismatch")
                _validate_bootstrap_receipt(
                    bootstrap_path,
                    Path(cast(str, pack["path"])),
                    config.accepted_authoring_ancestor,
                )
            except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
                bootstrap.update(status="INVALID", detail=str(error))

    uv_cache = _configured_path("uv_cache", config.uv_cache, directory=True)
    pnpm_store = _configured_path("pnpm_store", config.pnpm_store, directory=True)
    authoring_tests = _configured_path(
        "external_authoring_tests", config.external_authoring_tests, directory=True
    )
    if authoring_tests["status"] == "PASS":
        try:
            _validate_authoring_tests(
                Path(cast(str, authoring_tests["path"])),
                config.external_authoring_source_sha256,
            )
        except (OSError, ValueError) as error:
            authoring_tests.update(status="INVALID", detail=str(error))
    for record, kind in ((uv_cache, "uv"), (pnpm_store, "pnpm")):
        if record["status"] == "PASS":
            try:
                _validate_cache(Path(cast(str, record["path"])), kind)
            except (OSError, ValueError) as error:
                record.update(status="INVALID", detail=str(error))
    chrome = _configured_path("chrome_binary", config.chrome_path, directory=False)
    if chrome["status"] == "PASS":
        chrome_path = Path(cast(str, chrome["path"]))
        digest = _sha256_file(chrome_path)
        if not os.access(chrome_path, os.X_OK) or digest != config.chrome_sha256:
            chrome.update(status="INVALID", detail="executable bit or SHA-256 mismatch")

    return [
        source_config,
        pack,
        evidence,
        bootstrap,
        authoring_tests,
        uv_cache,
        pnpm_store,
        chrome,
        _controller_binding(config),
    ]


def _delegate_controller(config: FullVerifierConfig) -> int:
    config.evidence_root.mkdir(parents=True, exist_ok=True)
    external_result = _execute_external_authoring_suite(config)
    if external_result["passed"] is not True:
        return 1
    try:
        _validate_bootstrap_receipt(
            config.authoring_repository_receipt,
            config.governed_source_pack,
            config.accepted_authoring_ancestor,
        )
        _validate_authoring_tests(
            config.external_authoring_tests,
            config.external_authoring_source_sha256,
        )
        registry = run_command_registry.validate_registry()
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
        return 1

    def execute(command_id: str) -> dict[str, object]:
        command = next(
            (
                item
                for item in cast(list[dict[str, object]], registry["commands"])
                if item["command_id"] == command_id
            ),
            None,
        )
        if command is None or Path(cast(str, command["cwd"])) != REPOSITORY_ROOT:
            raise ValueError("E_CONTROLLER_DAG")
        result = run_command_registry.evaluate_invocation(
            command,
            environment=run_command_registry.execution_environment(config),
            working_directory=REPOSITORY_ROOT,
        )
        if result.get("passed") is not True:
            raise RuntimeError(f"E_CONTROLLER_DAG:{command_id}")
        return result

    try:
        execute("VERIFY_V636_P07_T01")
        command_evidence = _load_object(config.candidate_command_evidence)
        command_evidence["schema_version"] = "candidate-command-results/v3"
        command_evidence["external_authoring_result"] = external_result
        config.candidate_command_evidence.write_text(
            json.dumps(command_evidence, sort_keys=True, separators=(",", ":")) + "\n"
        )
        execute("VERIFY_V636_P07_T02")
        issuance = execute("VERIFY_V636_P07_T03")
        config.candidate_issuance_evidence.write_text(
            json.dumps(
                {
                    "schema_version": "candidate-issuance-result/v1",
                    "result": "PASS",
                    "production_authority": "NONE",
                    "controller_binding": config.binding(),
                    "command": issuance,
                    "proof_coverage_sha256": _sha256_file(config.proof_coverage_evidence),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return 1
    return 0


def _validate_candidate_postcondition(config: FullVerifierConfig) -> None:
    validate_candidate_qualification_receipt(
        REPOSITORY_ROOT,
        config.candidate_command_evidence,
        _load_object(config.candidate_qualification_receipt),
        config,
    )


def _run_full(config: FullVerifierConfig | None) -> int:
    prerequisites: list[dict[str, object]]
    if config is None:
        prerequisites = [
            {
                "prerequisite_id": "source_owned_controller_config",
                "path": None,
                "status": "MISSING_CONFIGURATION",
                "code": "CONTROLLER_CONFIG_UNBOUND",
            }
        ]
    else:
        prerequisites = _full_prerequisites(config)
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
    assert config is not None
    result = _delegate_controller(config)
    if result != 0:
        return result
    try:
        _validate_candidate_postcondition(config)
    except (OSError, ValueError, json.JSONDecodeError):
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("portable", "full"), required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--authoring-tests", type=Path)
    parser.add_argument("--uv-cache", type=Path)
    parser.add_argument("--pnpm-store", type=Path)
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--chrome-sha256")
    args = parser.parse_args(argv)
    if args.profile == "portable":
        return _run_portable()
    if any(
        value is not None
        for value in (
            args.pack,
            args.evidence_root,
            args.authoring_tests,
            args.uv_cache,
            args.pnpm_store,
            args.chrome,
            args.chrome_sha256,
        )
    ):
        return _run_full(None)
    if args.config is None:
        return _run_full(None)
    try:
        config = load_controller_config(args.config)
    except ValueError:
        return _run_full(None)
    return _run_full(config)


if __name__ == "__main__":
    raise SystemExit(main())
