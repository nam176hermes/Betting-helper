"""Run only the explicit v6.3.6 candidate-verification command allowlist."""

# ruff: noqa: S108
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, NoReturn, cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]  # noqa: E402

from moj_discovery.canonical import parse_strict_json  # noqa: E402
from tools.full_verifier_config import FullVerifierConfig, load_controller_config  # noqa: E402

VENDOR_ROOT = RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6"
SCHEMA_PATH = VENDOR_ROOT / "docs/schemas/command-registry.schema.json"
TOPOLOGY_PATH = VENDOR_ROOT / "docs/registries/verification-topology.v1.json"
SHELLS = {"bash", "cmd", "powershell", "pwsh", "sh", "zsh"}
PLACEHOLDER = re.compile(r"(?:\bFIXME\b|\bPLACEHOLDER\b|\bTBD\b|\.\.\.|<[^>]+>|\$\{|\$\(|`)")
GLOBS = re.compile(r"[*?\[]")
EXCLUDED_DIRECTORY_COMPONENTS = {
    ".coverage",
    ".local",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    ".venv",
    "__pycache__",
    "node_modules",
}
EXCLUDED_EXACT_SUBTREES = {"extension/.test-build", "extension/dist"}
EXCLUDED_FILE_SUFFIXES = {".pyc", ".pyd", ".pyo"}
EXACT_GITIGNORE = b""".coverage/
.mypy_cache/
.pytest_cache/
.ruff_cache/
.superpowers/
.venv/
__pycache__/
*.py[cod]
extension/.test-build/
extension/dist/
extension/node_modules/
node_modules/
.local/
"""
EXPECTED_EXECUTION_ENVIRONMENT = {
    "FORCE_COLOR": "0",
    "HOME": str(Path.home()),
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NPM_CONFIG_IGNORE_SCRIPTS": "true",
    "NPM_CONFIG_USERCONFIG": "/dev/null",
    "NO_COLOR": "1",
    "PATH": os.environ.get("PATH", os.defpath),
    "PYTHONHASHSEED": "0",
    "TMPDIR": "/tmp",
    "TZ": "UTC",
    "UV_NO_CONFIG": "1",
    "UV_NO_PROGRESS": "1",
    "UV_PYTHON_DOWNLOADS": "never",
}
LEGACY_AUTHORING_RUNTIME = (
    "/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/runtime"
)
LEGACY_AUTHORING_PACK = "/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/pack"


def _fail(code: str) -> NoReturn:
    raise ValueError(f"E_COMMAND_REGISTRY:{code}")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = parse_strict_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise ValueError("E_COMMAND_REGISTRY:JSON") from error
    if not isinstance(value, dict):
        _fail("SHAPE")
    return cast(dict[str, Any], value)


def _schema_validator() -> Draft202012Validator:
    schema = _read_object(SCHEMA_PATH)
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        _fail("SCHEMA")
    return Draft202012Validator({"$ref": "#/$defs/CommandRegistry", "$defs": definitions})


def _validate_argv(argv: object, *, inline_source: bool) -> None:
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
    ):
        _fail("ARGV")
    values = cast(list[str], argv)
    if values[0] in SHELLS:
        _fail("SHELL")
    if not inline_source and (
        "-k" in values or any(PLACEHOLDER.search(item) or GLOBS.search(item) for item in values)
    ):
        _fail("NON_CONCRETE")


def _require_vendored_bytes(path: Path, raw: bytes) -> None:
    expected = (
        path.parent / "vendor/hybrid-discovery-v6.3.6/docs/registries/task-command-registry.v1.json"
    )
    if path.resolve() == (RUNTIME_ROOT / "task-command-registry.json").resolve():
        expected = VENDOR_ROOT / "docs/registries/task-command-registry.v1.json"
    if expected.exists() and expected.read_bytes() != raw:
        _fail("BYTES")


def validate_registry(
    path: Path = RUNTIME_ROOT / "task-command-registry.json",
) -> dict[str, object]:
    raw = path.read_bytes()
    registry = _read_object(path)
    commands = registry.get("commands")
    if not isinstance(commands, list):
        _fail("SHAPE")
    identifiers: list[str] = []
    for command in commands:
        if not isinstance(command, dict):
            _fail("SHAPE")
        identifier = command.get("command_id")
        if not isinstance(identifier, str):
            _fail("AUTHORITY")
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        _fail("DUPLICATE")
    for command in commands:
        assert isinstance(command, dict)
        identifier = command["command_id"]
        cwd = command.get("cwd")
        expected_exit = command.get("expected_exit")
        if (
            not isinstance(cwd, str)
            or not Path(cwd).is_absolute()
            or not isinstance(expected_exit, int)
            or isinstance(expected_exit, bool)
            or command.get("network") != "DENY"
            or command.get("authenticated_operator_access") != "DENY"
            or command.get("provider_access") != "DENY"
        ):
            _fail("AUTHORITY")
        _validate_argv(command.get("argv"), inline_source=identifier == "BOOT0_EXTRACT_PLAN")
    if next(_schema_validator().iter_errors(registry), None) is not None:
        _fail("SHAPE")
    _require_vendored_bytes(path, raw)
    return cast(dict[str, object], registry)


def candidate_commands(registry: dict[str, object]) -> list[dict[str, object]]:
    topology = _read_object(TOPOLOGY_PATH)
    required = topology.get("candidate_command_ids")
    excluded = topology.get("excluded_kinds")
    if (
        set(topology)
        != {
            "schema_version",
            "candidate_command_ids",
            "excluded_kinds",
            "required_groups",
            "group_sources",
            "harness_compile_command",
            "all_test_compile_command",
            "source_freeze_task",
        }
        or topology.get("schema_version") != "verification-topology/v1"
        or not isinstance(required, list)
        or len(required) != 45
        or len(required) != len(set(required))
        or any(not isinstance(item, str) for item in required)
        or not isinstance(excluded, list)
        or any(not isinstance(item, str) for item in excluded)
    ):
        _fail("TOPOLOGY")
    required_ids = cast(list[str], required)
    excluded_kinds = cast(list[str], excluded)
    commands = registry.get("commands")
    if not isinstance(commands, list):
        _fail("SHAPE")
    by_id = {
        cast(str, item["command_id"]): cast(dict[str, object], item)
        for item in commands
        if isinstance(item, dict)
    }
    if len(by_id) != len(commands) or any(identifier not in by_id for identifier in required_ids):
        _fail("TOPOLOGY")
    selected = [by_id[identifier] for identifier in required_ids]
    if any(command.get("kind") in excluded_kinds for command in selected):
        _fail("TOPOLOGY")
    return selected


def effective_candidate_commands(
    registry: dict[str, object], config: FullVerifierConfig
) -> list[dict[str, object]]:
    if config.current_checkout_root.resolve() != RUNTIME_ROOT.resolve():
        _fail("CONFIG_ROOT")
    effective: list[dict[str, object]] = []
    replacements = (
        (LEGACY_AUTHORING_RUNTIME, str(config.current_checkout_root)),
        (LEGACY_AUTHORING_PACK, str(config.governed_source_pack)),
    )

    def rebind(value: str) -> str:
        for old, new in replacements:
            if value == old:
                return new
            if value.startswith(f"{old}/"):
                return new + value[len(old) :]
        return value

    for source in candidate_commands(registry):
        command = dict(source)
        cwd = cast(str, command["cwd"])
        argv = cast(list[str], command["argv"])
        command["cwd"] = rebind(cwd)
        command["argv"] = [rebind(item) for item in argv]
        effective.append(command)
    if {cast(str, command["cwd"]) for command in effective} != {str(config.current_checkout_root)}:
        _fail("CONFIG_ROOT")
    if any(
        value == old or value.startswith(f"{old}/")
        for command in effective
        for value in [cast(str, command["cwd"]), *cast(list[str], command["argv"])]
        for old, _new in replacements
    ):
        _fail("CONFIG_ROOT")
    return effective


def execution_environment(config: FullVerifierConfig) -> dict[str, str]:
    return {
        **EXPECTED_EXECUTION_ENVIRONMENT,
        "BH_CHROME_BINARY": str(config.chrome_path),
        "UV_CACHE_DIR": str(config.uv_cache),
        "npm_config_store_dir": str(config.pnpm_store),
    }


def expand_invocations(
    registry: dict[str, Any], mode: str = "candidate-qualification"
) -> list[dict[str, object]]:
    if mode != "candidate-qualification":
        _fail("MODE")
    return candidate_commands(cast(dict[str, object], registry))


def build_candidate_command_results(
    registry: dict[str, object], results: object, config: FullVerifierConfig | None = None
) -> dict[str, object]:
    expected = (
        candidate_commands(registry)
        if config is None
        else effective_candidate_commands(registry, config)
    )
    if not isinstance(results, list) or len(results) != len(expected):
        _fail("RESULTS")
    required = {
        "argv",
        "command_id",
        "cwd",
        "expected_exit",
        "exit_code",
        "passed",
        "stderr_sha256",
        "stderr_size_bytes",
        "stdout_sha256",
        "stdout_size_bytes",
    }
    for command, result in zip(expected, results, strict=True):
        if not isinstance(result, dict) or set(result) != required:
            _fail("RESULTS")
        if any(
            result.get(key) != command.get(key)
            for key in ("argv", "command_id", "cwd", "expected_exit")
        ) or (
            result.get("passed") is not True
            or not isinstance(result.get("exit_code"), int)
            or isinstance(result.get("exit_code"), bool)
            or result["exit_code"] != result["expected_exit"]
        ):
            _fail("RESULTS")
        if any(
            not isinstance(result.get(key), str)
            or re.fullmatch(r"[0-9a-f]{64}", result[key]) is None
            for key in ("stdout_sha256", "stderr_sha256")
        ) or any(
            not isinstance(result.get(key), str)
            or re.fullmatch(r"0|[1-9][0-9]*", result[key]) is None
            for key in ("stdout_size_bytes", "stderr_size_bytes")
        ):
            _fail("RESULTS")
    report: dict[str, object] = {
        "schema_version": (
            "candidate-command-results/v1" if config is None else "candidate-command-results/v2"
        ),
        "production_authority": "NONE",
        "results": results,
    }
    if config is not None:
        report["controller_binding"] = config.binding()
    return report


def evaluate_invocation(
    invocation: dict[str, object], *, environment: dict[str, str], working_directory: Path
) -> dict[str, object]:
    argv = cast(list[str], invocation["argv"])
    try:
        completed = subprocess.run(  # noqa: S603 - argv passed from closed registry
            argv, capture_output=True, cwd=working_directory, env=environment
        )
    except OSError as error:
        return {
            "command_id": invocation["command_id"],
            "failure": "E_COMMAND_SPAWN",
            "detail": str(error),
        }
    stdout, stderr = completed.stdout, completed.stderr
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        return {"command_id": invocation["command_id"], "failure": "E_COMMAND_CAPTURE"}
    return {
        "command_id": invocation["command_id"],
        "argv": argv,
        "cwd": str(working_directory),
        "exit_code": completed.returncode,
        "expected_exit": invocation["expected_exit"],
        "passed": completed.returncode == invocation["expected_exit"],
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stdout_size_bytes": str(len(stdout)),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stderr_size_bytes": str(len(stderr)),
    }


def _excluded(relative: Path, *, directory: bool) -> bool:
    text = relative.as_posix()
    components = relative.parts if directory else relative.parts[:-1]
    return (
        any(part in EXCLUDED_DIRECTORY_COMPONENTS for part in components)
        or any(
            (directory and text == subtree) or text.startswith(f"{subtree}/")
            for subtree in EXCLUDED_EXACT_SUBTREES
        )
        or (not directory and relative.suffix in EXCLUDED_FILE_SUFFIXES)
    )


def _candidate_pass(root: Path, *, allow_local_git: bool = False) -> list[dict[str, object]]:
    if root.is_symlink() or not root.is_dir() or (not allow_local_git and (root / ".git").exists()):
        raise ValueError("E_REPO0_FILE_TREE_ENTRY")
    entries: list[dict[str, object]] = []
    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root)
        names[:] = [
            name
            for name in names
            if (allow_local_git and relative_directory == Path(".") and name == ".git")
            or not _excluded(relative_directory / name, directory=True)
        ]
        for name in sorted(files, key=lambda item: item.encode()):
            path = directory_path / name
            relative = path.relative_to(root)
            text = relative.as_posix()
            info = path.lstat()
            if (
                _excluded(relative, directory=False)
                or unicodedata.normalize("NFC", text) != text
                or "\ufeff" in text
                or "\\" in text
                or "\0" in text
                or path.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
            ):
                if _excluded(relative, directory=False):
                    continue
                raise ValueError("E_REPO0_FILE_TREE_ENTRY")
            contents = path.read_bytes()
            entries.append(
                {
                    "entry_kind": "REGULAR_FILE",
                    "file_sha256": hashlib.sha256(contents).hexdigest(),
                    "git_mode": "100755" if info.st_mode & 0o111 else "100644",
                    "gitlink": False,
                    "hardlink": False,
                    "path": text,
                    "size_bytes": str(len(contents)),
                    "symlink": False,
                }
            )
    return sorted(entries, key=lambda item: cast(str, item["path"]).encode())


def collect_candidate_file_tree(root: Path, *, allow_local_git: bool = False) -> dict[str, object]:
    if allow_local_git:
        git = root / ".git"
        if git.is_symlink() or not git.is_dir():
            _fail("LOCAL_GIT")
    first = _candidate_pass(root, allow_local_git=allow_local_git)
    second = _candidate_pass(root, allow_local_git=allow_local_git)
    if first != second:
        _fail("CANDIDATE_TREE_CHANGED")
    return {"entries": first, "schema_version": "repo0-independent-file-tree/v1"}


def _git_source_identity(root: Path) -> dict[str, str]:
    git = shutil.which("git")
    if git is None:
        _fail("LOCAL_GIT")

    def read(*args: str) -> str:
        completed = subprocess.run(  # noqa: S603 - fixed read-only Git operation.
            [git, "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            _fail("LOCAL_GIT")
        return completed.stdout.strip()

    if read("rev-parse", "--show-toplevel") != str(root.resolve()) or read(
        "status", "--porcelain", "--untracked-files=all"
    ):
        _fail("LOCAL_GIT")
    return {
        "head": read("rev-parse", "HEAD"),
        "tree": read("rev-parse", "HEAD^{tree}"),
    }


def run_registry(
    registry_path: Path, config: FullVerifierConfig | None = None
) -> dict[str, object]:
    registry = validate_registry(registry_path)
    initial_hash = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    source_root = registry_path.resolve().parent
    before: dict[str, object] | dict[str, str] = (
        collect_candidate_file_tree(source_root)
        if config is None
        else _git_source_identity(source_root)
    )
    results: list[dict[str, object]] = []
    commands = (
        candidate_commands(registry)
        if config is None
        else effective_candidate_commands(registry, config)
    )
    environment = (
        EXPECTED_EXECUTION_ENVIRONMENT if config is None else execution_environment(config)
    )
    for command in commands:
        result = evaluate_invocation(
            command,
            environment=environment,
            working_directory=Path(cast(str, command["cwd"])),
        )
        results.append(result)
        if result.get("passed") is not True:
            raise RuntimeError(f"E_COMMAND_REGISTRY:{command['command_id']}")
    if (
        hashlib.sha256(registry_path.read_bytes()).hexdigest() != initial_hash
        or (
            collect_candidate_file_tree(source_root)
            if config is None
            else _git_source_identity(source_root)
        )
        != before
    ):
        raise RuntimeError("E_COMMAND_REGISTRY:DRIFT")
    return build_candidate_command_results(registry, results, config)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--mode", choices=("candidate-qualification",))
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_check == bool(args.mode):
        parser.error("provide exactly one of --self-check or --mode candidate-qualification")
    if args.self_check:
        validate_registry(RUNTIME_ROOT / "task-command-registry.json")
    else:
        if args.registry is None or args.registry != Path("task-command-registry.json"):
            parser.error("candidate qualification requires --registry task-command-registry.json")
        if args.config is None or args.output is None:
            parser.error("candidate qualification requires --config and --output")
        config = load_controller_config(args.config)
        report = run_registry(RUNTIME_ROOT / "task-command-registry.json", config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
