import hashlib
import json
import stat
import subprocess
import tomllib
from functools import partial
from pathlib import Path
from typing import Any

EXPECTED = {
    "node": "v22.23.0",
    "pnpm": "10.33.2",
    "python": "Python 3.12.3",
    "uv": "uv 0.11.7 (x86_64-unknown-linux-gnu)",
}
COMMANDS = {
    "node": ["node", "--version"],
    "pnpm": ["pnpm", "--version"],
    "python": ["python3.12", "--version"],
    "uv": ["uv", "--version"],
}
ROOT_DEPENDENCIES: dict[str, str] = {}
EXTENSION_DEPENDENCIES = {
    "ajv": "8.20.0",
    "ajv-formats": "3.0.1",
    "canonicalize": "4.0.0",
}
EXTENSION_DEV_DEPENDENCIES = {
    "@eslint/js": "10.0.1",
    "@types/chrome": "0.2.8",
    "@types/node": "26.4.1",
    "eslint": "10.9.1",
    "typescript": "6.0.2",
    "typescript-eslint": "8.69.0",
}
PYTHON_DEPENDENCIES = {
    "cryptography": "50.0.1",
    "jsonschema": "4.26.0",
    "rfc8785": "0.1.4",
    "websockets": "17.1",
}
PYTHON_DEV_DEPENDENCIES = {
    "mypy": "2.3.1",
    "pytest": "9.1.1",
    "ruff": "0.16.6",
}
DEPENDENCY_KEYS = {
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
    "bundledDependencies",
    "bundleDependencies",
}
ROOT_MANIFEST = {
    "name": "hybrid-discovery-repo0",
    "private": True,
    "version": "6.2.0",
    "packageManager": "pnpm@10.33.2",
    "engines": {"node": "22.23.0", "pnpm": "10.33.2"},
    "scripts": {
        "build": "pnpm --dir extension exec tsc -p tsconfig.build.json",
        "lint": "pnpm --dir extension exec eslint src test test-red tools",
        "test:compile": "pnpm --dir extension exec tsc -p tsconfig.test.json",
        "typecheck": "pnpm --dir extension exec tsc -p tsconfig.json --noEmit",
    },
}
EXTENSION_MANIFEST = {
    "name": "@hybrid-discovery/extension-repo0",
    "private": True,
    "version": "6.2.0",
    "type": "module",
    "engines": {"node": "22.23.0", "pnpm": "10.33.2"},
    "dependencies": EXTENSION_DEPENDENCIES,
    "devDependencies": EXTENSION_DEV_DEPENDENCIES,
}
BOOTSTRAP_CONFIG_BYTES = {
    ".node-version": b"22.23.0\n",
    ".python-version": b"3.12.3\n",
    ".npmrc": b"ignore-scripts=true\nsave-exact=true\n",
    "pnpm-workspace.yaml": b"packages:\n  - extension\n",
}
PNPM_RESOLVED_DEPENDENCIES = {
    "dependencies": {
        "ajv": "8.20.0",
        "ajv-formats": "3.0.1(ajv@8.20.0)",
        "canonicalize": "4.0.0",
    },
    "devDependencies": {
        "@eslint/js": "10.0.1(eslint@10.9.1)",
        "@types/chrome": "0.2.8",
        "@types/node": "26.4.1",
        "eslint": "10.9.1",
        "typescript": "6.0.2",
        "typescript-eslint": "8.69.0(eslint@10.9.1)(typescript@6.0.2)",
    },
}
EXPECTED_PYPROJECT = {
    "project": {
        "name": "moj-discovery-repo0",
        "version": "6.2.0",
        "description": "Authoring-only REPO0 governance and typed discovery contract stubs",
        "requires-python": "==3.12.3",
        "dependencies": [
            "cryptography==50.0.1",
            "jsonschema==4.26.0",
            "rfc8785==0.1.4",
            "websockets==17.1",
        ],
    },
    "dependency-groups": {
        "dev": ["mypy==2.3.1", "pytest==9.1.1", "ruff==0.16.6"],
    },
    "tool": {
        "uv": {"package": False, "required-version": "==0.11.7"},
        "pytest": {
            "ini_options": {
                "addopts": "--strict-config --strict-markers",
                "pythonpath": [".", "src"],
                "testpaths": ["tests", "../authoring-tests"],
                "cache_dir": "/home/thenam176/betting-helper/authoring-evidence/"
                "hybrid-discovery-v6.3.6/pytest-cache",
            }
        },
        "ruff": {
            "target-version": "py312",
            "line-length": 100,
            "lint": {"select": ["E", "F", "I", "UP", "B", "SIM", "S"], "ignore": ["S101"]},
        },
        "mypy": {
            "python_version": "3.12",
            "strict": True,
            "mypy_path": "src",
            "files": ["src", "tests", "tools"],
            "exclude": ["tests-red"],
        },
    },
}
EXPECTED_TSCONFIG = {
    "compilerOptions": {
        "allowJs": False,
        "exactOptionalPropertyTypes": True,
        "forceConsistentCasingInFileNames": True,
        "lib": ["ES2024", "DOM"],
        "module": "NodeNext",
        "moduleResolution": "NodeNext",
        "noEmit": True,
        "noFallthroughCasesInSwitch": True,
        "noImplicitOverride": True,
        "noImplicitReturns": True,
        "noUncheckedIndexedAccess": True,
        "resolveJsonModule": True,
        "rootDir": ".",
        "skipLibCheck": False,
        "strict": True,
        "target": "ES2024",
        "types": ["node", "chrome"],
        "verbatimModuleSyntax": True,
    },
    "include": [
        "src/**/*.ts",
        "test/**/*.ts",
        "test-red/**/*.ts",
        "tools/**/*.ts",
        "test-harness/**/*.ts",
    ],
}
EXPECTED_TSCONFIG_TEST = {
    "extends": "./tsconfig.json",
    "compilerOptions": {
        "noEmit": False,
        "outDir": ".test-build",
        "rootDir": ".",
        "sourceMap": False,
    },
    "include": EXPECTED_TSCONFIG["include"],
    "exclude": [],
}
EXPECTED_TSCONFIG_HARNESS = {
    "extends": "./tsconfig.test.json",
    "include": [
        "src/**/*.ts",
        "test-harness/**/*.ts",
        "test/durability/**/*.ts",
        "test/security/**/*.ts",
    ],
    "exclude": [],
}
EXPECTED_TSCONFIG_BUILD = {
    "extends": "./tsconfig.json",
    "compilerOptions": {"noEmit": False, "outDir": "dist", "rootDir": "src", "sourceMap": False},
    "include": ["src/**/*.ts"],
    "exclude": ["test", "test-red", "test-harness", "tools"],
}
EXPECTED_NATIVE_LOCK_SEMANTIC_HASHES = {
    "runtime/uv.lock": "34d75031a20b7045a94b9fa1f9e70ffd3c9a7a1e76c262bd5ffb0a7516cc6a3c",
    "runtime/pnpm-lock.yaml": "9f0bdb0ff473263eaea4c4bc063831198b0c92446fd7d0c8e02b0ab1489bc888",
}
T07_LOCK_COMMAND_IDS = (
    "MIG0_UV_LOCK",
    "MIG0_PNPM_LOCK",
    "MIG0_UV_SYNC_REFRESH",
    "MIG0_PNPM_INSTALL_REFRESH",
)
SEALED_PLAN_MANIFEST_SHA256 = "35b6526801f6e017f55305817ad57507376aef2536e5f2f15ffc75bbdff020f0"
CONFIG_MATERIALIZATION_ENTRIES = (
    ("docs/configs/runtime-pyproject.toml", "runtime/pyproject.toml"),
    ("docs/configs/tsconfig.test.json", "runtime/extension/tsconfig.test.json"),
    ("docs/configs/tsconfig.harness.json", "runtime/extension/tsconfig.harness.json"),
    ("docs/configs/tsconfig.build.json", "runtime/extension/tsconfig.build.json"),
)
CONFIG_MATERIALIZATION_REGISTRY = {
    "schema_version": "config-materialization/v1",
    "entries": [
        {"plan_source": source, "destination": destination, "owner": "V636-P01-T01"}
        for source, destination in CONFIG_MATERIALIZATION_ENTRIES
    ],
    "byte_policy": "COPY_EXACT_PLAN_BYTES",
}


def verify_toolchains(versions: dict[str, str] | None = None) -> list[str]:
    if versions is not None and set(versions) != set(EXPECTED):
        return ["E_TOOLCHAIN:observations"]
    observed = (
        versions
        if versions is not None
        else {
            name: subprocess.run(  # noqa: S603 - fixed local toolchain commands
                argv, check=True, capture_output=True, text=True
            ).stdout.strip()
            for name, argv in COMMANDS.items()
        }
    )
    return [
        f"E_TOOLCHAIN:{name}"
        for name, expected in EXPECTED.items()
        if observed.get(name) != expected
    ]


def dependency_lock_hashes(root: Path) -> dict[str, str]:
    return {
        "pnpm_lock_sha256": hashlib.sha256((root / "pnpm-lock.yaml").read_bytes()).hexdigest(),
        "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
    }


def _semantic_sha256(identities: list[str]) -> str:
    if not identities or len(identities) != len(set(identities)):
        raise ValueError("E_LOCK_SEMANTICS:IDENTITIES")
    return hashlib.sha256(
        json.dumps(sorted(identities), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _uv_lock_semantic_hash(path: Path) -> str:
    parsed = tomllib.loads(path.read_text())
    packages = parsed.get("package")
    if not isinstance(packages, list):
        raise ValueError("E_LOCK_SEMANTICS:UV")
    identities = [
        f"{item['name']}@{item['version']}"
        for item in packages
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("version"), str)
    ]
    if len(identities) != len(packages):
        raise ValueError("E_LOCK_SEMANTICS:UV")
    return _semantic_sha256(identities)


def _pnpm_lock_semantic_hash(path: Path) -> str:
    lines = path.read_text().splitlines()
    try:
        start = lines.index("packages:") + 1
        end = lines.index("snapshots:")
    except ValueError as error:
        raise ValueError("E_LOCK_SEMANTICS:PNPM") from error
    identities = [
        line.strip()[:-1].strip("'\"")
        for line in lines[start:end]
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":")
    ]
    return _semantic_sha256(identities)


def native_lock_semantic_hashes(root: Path) -> dict[str, str]:
    return {
        "runtime/uv.lock": _uv_lock_semantic_hash(root / "uv.lock"),
        "runtime/pnpm-lock.yaml": _pnpm_lock_semantic_hash(root / "pnpm-lock.yaml"),
    }


def _safe_regular_bytes(base: Path, relative: str) -> bytes:
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path")
    base_stat = base.lstat()
    if base.is_symlink() or not stat.S_ISDIR(base_stat.st_mode):
        raise ValueError("base")
    candidate = base
    for index, part in enumerate(path.parts):
        candidate = candidate / part
        candidate_stat = candidate.lstat()
        if candidate.is_symlink():
            raise ValueError("symlink")
        if index == len(path.parts) - 1:
            if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_nlink != 1:
                raise ValueError("file")
        elif not stat.S_ISDIR(candidate_stat.st_mode):
            raise ValueError("directory")
    return candidate.read_bytes()


def _manifest_entry_bytes(plan: Path, manifest: dict[str, Any], relative: str) -> bytes:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("entries")
    matches = [
        entry for entry in entries if isinstance(entry, dict) and entry.get("path") == relative
    ]
    if len(matches) != 1 or set(matches[0]) != {"path", "size", "sha256"}:
        raise ValueError("entry")
    expected = matches[0]
    if (
        not isinstance(expected["size"], int)
        or isinstance(expected["size"], bool)
        or not isinstance(expected["sha256"], str)
    ):
        raise ValueError("entry")
    content = _safe_regular_bytes(plan, relative)
    if len(content) != expected["size"] or (
        hashlib.sha256(content).hexdigest() != expected["sha256"]
    ):
        raise ValueError("bytes")
    return content


def verify_config_materialization(root: Path) -> list[str]:
    plan = root.parent / "plan-input"
    try:
        plan_manifest = plan / "MANIFEST_SHA256.json"
        if plan_manifest.exists() or plan_manifest.is_symlink():
            manifest_bytes = _safe_regular_bytes(plan, "MANIFEST_SHA256.json")
            if hashlib.sha256(manifest_bytes).hexdigest() != SEALED_PLAN_MANIFEST_SHA256:
                raise ValueError("manifest")
            manifest = json.loads(manifest_bytes)
            if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "entries"}:
                raise ValueError("manifest")
            if manifest.get("schema_version") != "manifest-sha256/v1":
                raise ValueError("registry")
            read_source = partial(_manifest_entry_bytes, plan, manifest)
        else:
            plan = root / "vendor/hybrid-discovery-v6.3.6"
            read_source = partial(_safe_regular_bytes, plan)
        registry = json.loads(read_source("docs/registries/config-materialization.v1.json"))
        if registry != CONFIG_MATERIALIZATION_REGISTRY:
            raise ValueError("registry")
        source_bytes = {source: read_source(source) for source, _ in CONFIG_MATERIALIZATION_ENTRIES}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return ["E_CONFIG_MATERIALIZATION:REGISTRY"]
    for source, destination in CONFIG_MATERIALIZATION_ENTRIES:
        try:
            destination_bytes = _safe_regular_bytes(root, destination.removeprefix("runtime/"))
        except (OSError, ValueError):
            return ["E_CONFIG_MATERIALIZATION:BYTES"]
        if source_bytes[source] != destination_bytes:
            return ["E_CONFIG_MATERIALIZATION:BYTES"]
    return []


def verify_native_lock_binding(
    root: Path, receipt_path: Path, command_registry_path: Path | None = None
) -> list[str]:
    registry_path = command_registry_path or root.parent / "runtime/task-command-registry.json"
    try:
        receipt = _json_object(receipt_path)
        registry = _json_object(registry_path)
        commands = registry.get("commands")
        if not isinstance(commands, list):
            raise ValueError("commands")
        expected_commands = []
        for command_id in T07_LOCK_COMMAND_IDS:
            matches = [
                item
                for item in commands
                if isinstance(item, dict) and item.get("command_id") == command_id
            ]
            if len(matches) != 1:
                raise ValueError(command_id)
            command = matches[0]
            expected_commands.append(
                {
                    "command_id": command_id,
                    "cwd": command.get("cwd"),
                    "argv": command.get("argv"),
                    "exit_code": 0,
                }
            )
        raw_hashes = {
            "runtime/uv.lock": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
            "runtime/pnpm-lock.yaml": hashlib.sha256(
                (root / "pnpm-lock.yaml").read_bytes()
            ).hexdigest(),
        }
        expected = {
            "task_id": "V636-MIG0-T07",
            "result": "PASS",
            "authority": "PLAN_AUTHORING",
            "authorized_production_phases": "NONE",
            "native_lock_hashes": raw_hashes,
            "native_lock_semantic_hashes": native_lock_semantic_hashes(root),
            "command_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            "lock_command_results": expected_commands,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return ["E_NATIVE_LOCK_BINDING:INPUT"]
    if all(receipt.get(key) == value for key, value in expected.items()):
        return []
    return ["E_NATIVE_LOCK_BINDING:RECEIPT"]


def _json_object(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text())
    if not isinstance(parsed, dict):
        raise ValueError(path)
    return parsed


def _manifest_dependencies_exact(
    manifest: dict[str, Any],
    expected_dependencies: dict[str, str],
    expected_dev_dependencies: dict[str, str],
) -> bool:
    expected_sections = {
        "dependencies": expected_dependencies,
        "devDependencies": expected_dev_dependencies,
    }
    for key in DEPENDENCY_KEYS:
        actual = manifest.get(key, {})
        if not isinstance(actual, dict) or actual != expected_sections.get(key, {}):
            return False
    return True


def _parse_requirement(requirement: object) -> tuple[str, str] | None:
    if not isinstance(requirement, str) or "==" not in requirement:
        return None
    name, version = requirement.split("==", 1)
    if not name or not version or any(marker in version for marker in "<>=!~*^"):
        return None
    return name, version


def _requirements_exact(value: object, expected: dict[str, str]) -> bool:
    if not isinstance(value, list):
        return False
    parsed: dict[str, str] = {}
    for item in value:
        requirement = _parse_requirement(item)
        if requirement is None or requirement[0] in parsed:
            return False
        parsed[requirement[0]] = requirement[1]
    return parsed == expected and len(parsed) == len(expected)


def _pnpm_extension_bindings(
    text: str,
) -> dict[str, dict[str, dict[str, str]]] | None:
    lines = text.splitlines()
    try:
        start = lines.index("  extension:") + 1
    except ValueError:
        return None
    result: dict[str, dict[str, dict[str, str]]] = {}
    section: str | None = None
    package: str | None = None
    for line in lines[start:]:
        if line and len(line) - len(line.lstrip()) <= 2:
            break
        if line.startswith("    ") and not line.startswith("      ") and line.endswith(":"):
            section = line.strip()[:-1]
            package = None
            result[section] = {}
        elif section is not None and line.startswith("      ") and not line.startswith("        "):
            package = line.strip()[:-1].strip("'") if line.strip().endswith(":") else None
            if package is not None:
                result[section][package] = {}
        elif section is not None and package is not None and line.startswith("        "):
            key, separator, value = line.strip().partition(": ")
            if separator and key in {"specifier", "version"}:
                result[section][package][key] = value.strip("'\"")
    return result


def _pnpm_lock_exact(path: Path) -> bool:
    text = path.read_text()
    bindings = _pnpm_extension_bindings(text)
    expected_bindings = {
        section: {
            name: {"specifier": version, "version": PNPM_RESOLVED_DEPENDENCIES[section][name]}
            for name, version in dependencies.items()
        }
        for section, dependencies in {
            "dependencies": EXTENSION_DEPENDENCIES,
            "devDependencies": EXTENSION_DEV_DEPENDENCIES,
        }.items()
    }
    return (
        text.startswith("lockfileVersion: '9.0'\n")
        and "\n  .: {}\n" in text
        and bindings == expected_bindings
    )


def _named_specifiers(values: object) -> dict[str, str] | None:
    if not isinstance(values, list):
        return None
    result: dict[str, str] = {}
    for value in values:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("name"), str)
            or not isinstance(value.get("specifier"), str)
            or set(value) != {"name", "specifier"}
        ):
            return None
        result[value["name"]] = value["specifier"]
    return result if len(result) == len(values) else None


def _named_dependencies(values: object) -> set[str] | None:
    if not isinstance(values, list):
        return None
    names: list[str] = []
    for value in values:
        if (
            not isinstance(value, dict)
            or set(value) != {"name"}
            or not isinstance(value["name"], str)
        ):
            return None
        names.append(value["name"])
    return set(names) if len(names) == len(set(names)) else None


def _uv_lock_exact(path: Path) -> bool:
    text = path.read_text()
    parsed = tomllib.loads(text)
    packages = parsed.get("package")
    if not isinstance(packages, list):
        return False
    project = [
        item
        for item in packages
        if isinstance(item, dict) and item.get("name") == "moj-discovery-repo0"
    ]
    if len(project) != 1:
        return False
    item = project[0]
    metadata = item.get("metadata")
    dev_dependencies = item.get("dev-dependencies")
    if not isinstance(metadata, dict) or not isinstance(dev_dependencies, dict):
        return False
    requires_dev = metadata.get("requires-dev")
    if not isinstance(requires_dev, dict):
        return False
    expected_python = {name: f"=={version}" for name, version in PYTHON_DEPENDENCIES.items()}
    expected_dev = {name: f"=={version}" for name, version in PYTHON_DEV_DEPENDENCIES.items()}
    exact_direct_versions = {
        **PYTHON_DEPENDENCIES,
        **PYTHON_DEV_DEPENDENCIES,
    }
    resolved_direct_versions = {
        name: [
            candidate.get("version")
            for candidate in packages
            if isinstance(candidate, dict) and candidate.get("name") == name
        ]
        for name in exact_direct_versions
    }
    return (
        parsed.get("requires-python") == "==3.12.3"
        and _named_dependencies(item.get("dependencies")) == set(PYTHON_DEPENDENCIES)
        and _named_dependencies(dev_dependencies.get("dev")) == set(PYTHON_DEV_DEPENDENCIES)
        and _named_specifiers(metadata.get("requires-dist")) == expected_python
        and _named_specifiers(requires_dev.get("dev")) == expected_dev
        and resolved_direct_versions
        == {name: [version] for name, version in exact_direct_versions.items()}
    )


def verify_dependency_policy(root: Path | None = None) -> list[str]:
    absolute_root = (root or Path.cwd()).resolve()
    errors: list[str] = []
    try:
        root_manifest = _json_object(absolute_root / "package.json")
        extension_manifest = _json_object(absolute_root / "extension/package.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return ["E_DEPENDENCY_POLICY:MANIFEST"]
    manifests_valid = root_manifest == ROOT_MANIFEST and extension_manifest == EXTENSION_MANIFEST
    if not manifests_valid:
        errors.append("E_DEPENDENCY_POLICY:MANIFEST")

    try:
        pyproject = tomllib.loads((absolute_root / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        pyproject = {}
    if pyproject != EXPECTED_PYPROJECT:
        errors.append("E_DEPENDENCY_POLICY:PYPROJECT")
    tool_config = pyproject.get("tool", {})
    uv_config = tool_config.get("uv", {}) if isinstance(tool_config, dict) else {}
    if not isinstance(uv_config, dict) or uv_config.get("required-version") != "==0.11.7":
        errors.append("E_DEPENDENCY_POLICY:UV_VERSION")

    try:
        config_valid = all(
            (absolute_root / relative).read_bytes() == expected
            for relative, expected in BOOTSTRAP_CONFIG_BYTES.items()
        )
    except OSError:
        config_valid = False
    if not config_valid:
        errors.append("E_DEPENDENCY_POLICY:BOOTSTRAP_CONFIG")

    if verify_config_materialization(absolute_root):
        errors.append("E_DEPENDENCY_POLICY:CONFIG_MATERIALIZATION")

    try:
        tsconfig_valid = (
            _json_object(absolute_root / "extension/tsconfig.json") == EXPECTED_TSCONFIG
            and _json_object(absolute_root / "extension/tsconfig.test.json")
            == EXPECTED_TSCONFIG_TEST
            and _json_object(absolute_root / "extension/tsconfig.harness.json")
            == EXPECTED_TSCONFIG_HARNESS
            and _json_object(absolute_root / "extension/tsconfig.build.json")
            == EXPECTED_TSCONFIG_BUILD
        )
    except (OSError, ValueError, json.JSONDecodeError):
        tsconfig_valid = False
    if not tsconfig_valid:
        errors.append("E_DEPENDENCY_POLICY:TSCONFIG")

    try:
        locks_valid = (
            _pnpm_lock_exact(absolute_root / "pnpm-lock.yaml")
            and _uv_lock_exact(absolute_root / "uv.lock")
            and native_lock_semantic_hashes(absolute_root) == EXPECTED_NATIVE_LOCK_SEMANTIC_HASHES
        )
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        locks_valid = False
    if not locks_valid:
        errors.append("E_DEPENDENCY_POLICY:LOCK")
    return errors


if __name__ == "__main__":
    raise SystemExit(bool(verify_toolchains() + verify_dependency_policy()))
