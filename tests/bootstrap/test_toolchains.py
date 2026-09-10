import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tools.verify_toolchains import (
    T07_LOCK_COMMAND_IDS,
    dependency_lock_hashes,
    native_lock_semantic_hashes,
    verify_config_materialization,
    verify_dependency_policy,
    verify_native_lock_binding,
    verify_toolchains,
)

ROOT = Path(__file__).parents[2]


def test_accepts_exact_toolchain_version_tuple() -> None:
    assert (
        verify_toolchains(
            {
                "node": "v22.23.0",
                "pnpm": "10.33.2",
                "python": "Python 3.12.3",
                "uv": "uv 0.11.7 (x86_64-unknown-linux-gnu)",
            }
        )
        == []
    )


def test_rejects_node_version_mutation_to_v22_23_1() -> None:
    versions = {
        "node": "v22.23.1",
        "pnpm": "10.33.2",
        "python": "Python 3.12.3",
        "uv": "uv 0.11.7 (x86_64-unknown-linux-gnu)",
    }
    assert verify_toolchains(versions) == ["E_TOOLCHAIN:node"]


@pytest.mark.parametrize(
    "versions",
    [
        {},
        {"node": "v22.23.0"},
        {
            "node": "v22.23.0",
            "pnpm": "10.33.2",
            "python": "Python 3.12.3",
            "uv": "uv 0.11.7 (x86_64-unknown-linux-gnu)",
            "extra": "value",
        },
    ],
)
def test_rejects_missing_or_extra_toolchain_observations(
    versions: dict[str, str],
) -> None:
    assert verify_toolchains(versions) == ["E_TOOLCHAIN:observations"]


def _dependency_fixture(tmp_path: Path) -> Path:
    (tmp_path / "extension").mkdir(parents=True)
    for relative in (
        "package.json",
        "extension/package.json",
        "pyproject.toml",
        "pnpm-lock.yaml",
        "uv.lock",
        ".node-version",
        ".python-version",
        ".npmrc",
        "pnpm-workspace.yaml",
        "extension/tsconfig.json",
        "extension/tsconfig.test.json",
        "extension/tsconfig.harness.json",
        "extension/tsconfig.build.json",
    ):
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return tmp_path


def _sealed_plan_fixture(tmp_path: Path) -> Path:
    if not (ROOT.parent / "plan-input/MANIFEST_SHA256.json").is_file():
        pytest.skip("sealed authoring plan is not part of the delivered runtime")
    plan = tmp_path / "plan-input"
    for relative in (
        "MANIFEST_SHA256.json",
        "docs/registries/config-materialization.v1.json",
        "docs/configs/runtime-pyproject.toml",
        "docs/configs/tsconfig.test.json",
        "docs/configs/tsconfig.harness.json",
        "docs/configs/tsconfig.build.json",
    ):
        source = ROOT.parent / "plan-input" / relative
        destination = plan / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return plan


def _t07_receipt(root: Path, registry_path: Path) -> dict[str, object]:
    commands = json.loads(registry_path.read_text())["commands"]
    rows = []
    for command_id in T07_LOCK_COMMAND_IDS:
        command = next(item for item in commands if item["command_id"] == command_id)
        rows.append(
            {
                "command_id": command_id,
                "cwd": command["cwd"],
                "argv": command["argv"],
                "exit_code": 0,
            }
        )
    return {
        "task_id": "V636-MIG0-T07",
        "result": "PASS",
        "authority": "PLAN_AUTHORING",
        "authorized_production_phases": "NONE",
        "native_lock_hashes": {
            "runtime/uv.lock": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
            "runtime/pnpm-lock.yaml": hashlib.sha256(
                (root / "pnpm-lock.yaml").read_bytes()
            ).hexdigest(),
        },
        "native_lock_semantic_hashes": native_lock_semantic_hashes(root),
        "command_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "lock_command_results": rows,
    }


def test_exact_dependency_policy_and_lock_bindings_pass() -> None:
    assert verify_dependency_policy(ROOT) == []
    assert dependency_lock_hashes(ROOT) == {
        "pnpm_lock_sha256": hashlib.sha256((ROOT / "pnpm-lock.yaml").read_bytes()).hexdigest(),
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
    }


def test_config_materialization_requires_exact_plan_bytes(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path / "runtime")
    _sealed_plan_fixture(tmp_path)
    assert verify_config_materialization(root) == []
    (root / "extension/tsconfig.test.json").write_text("{}\n")
    assert verify_config_materialization(root) == ["E_CONFIG_MATERIALIZATION:BYTES"]


def test_config_materialization_accepts_delivered_runtime_vendor(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path / "runtime")
    (tmp_path / "plan-input").mkdir()
    vendor = root / "vendor/hybrid-discovery-v6.3.6"
    for relative in (
        "docs/registries/config-materialization.v1.json",
        "docs/configs/runtime-pyproject.toml",
        "docs/configs/tsconfig.test.json",
        "docs/configs/tsconfig.harness.json",
        "docs/configs/tsconfig.build.json",
    ):
        destination = vendor / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "vendor/hybrid-discovery-v6.3.6" / relative, destination)
    assert verify_config_materialization(root) == []


@pytest.mark.parametrize("replacement", ["websockets>=17.1", "websockets==17.2"])
def test_current_websocket_dependency_pin_is_exact(tmp_path: Path, replacement: str) -> None:
    root = _dependency_fixture(tmp_path)
    project = root / "pyproject.toml"
    project.write_text(project.read_text().replace("websockets==17.1", replacement))
    assert "E_DEPENDENCY_POLICY:PYPROJECT" in verify_dependency_policy(root)


def test_config_materialization_ignores_mutable_pack(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path / "runtime")
    _sealed_plan_fixture(tmp_path)
    mutable_registry = tmp_path / "pack/docs/registries/config-materialization.v1.json"
    mutable_registry.parent.mkdir(parents=True)
    mutable_registry.write_text("{}\n")

    assert verify_config_materialization(root) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda registry: registry["entries"].pop(),
        lambda registry: registry["entries"].append(registry["entries"][0]),
        lambda registry: registry["entries"][0].update({"extra": True}),
        lambda registry: registry["entries"][0].update({"owner": "V636-P99-T01"}),
        lambda registry: registry["entries"][0].update(
            {"plan_source": "../runtime/pyproject.toml"}
        ),
        lambda registry: registry["entries"].__setitem__(
            0, {**registry["entries"][0], "destination": "/unowned-target.json"}
        ),
        lambda registry: registry["entries"].reverse(),
    ],
)
def test_config_materialization_rejects_noncanonical_registry(
    tmp_path: Path, mutation: object
) -> None:
    root = _dependency_fixture(tmp_path / "runtime")
    plan = _sealed_plan_fixture(tmp_path)
    registry_path = plan / "docs/registries/config-materialization.v1.json"
    registry = json.loads(registry_path.read_text())
    assert callable(mutation)
    mutation(registry)
    registry_path.write_text(json.dumps(registry))

    assert verify_config_materialization(root) == ["E_CONFIG_MATERIALIZATION:REGISTRY"]


def test_config_materialization_rejects_manifest_source_and_symlink_drift(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path / "runtime")
    plan = _sealed_plan_fixture(tmp_path)
    source = plan / "docs/configs/tsconfig.test.json"
    source.write_text(source.read_text() + "\n")
    assert verify_config_materialization(root) == ["E_CONFIG_MATERIALIZATION:REGISTRY"]

    _sealed_plan_fixture(tmp_path)
    source.unlink()
    source.symlink_to(root / "extension/tsconfig.test.json")
    assert verify_config_materialization(root) == ["E_CONFIG_MATERIALIZATION:REGISTRY"]


def test_config_materialization_rejects_destination_symlink(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path / "runtime")
    _sealed_plan_fixture(tmp_path)
    destination = root / "extension/tsconfig.test.json"
    replacement = tmp_path / "same-bytes.json"
    shutil.copyfile(destination, replacement)
    destination.unlink()
    destination.symlink_to(replacement)

    assert verify_config_materialization(root) == ["E_CONFIG_MATERIALIZATION:BYTES"]


def test_native_lock_binding_requires_exact_t07_receipt_and_command_rows(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path / "runtime")
    registry = ROOT / "task-command-registry.json"
    receipt_path = tmp_path / "V636-MIG0-T07.json"
    receipt_path.write_text(json.dumps(_t07_receipt(root, registry)))
    assert verify_native_lock_binding(root, receipt_path, registry) == []

    receipt = json.loads(receipt_path.read_text())
    receipt["lock_command_results"][0]["argv"] = ["uv", "lock"]
    receipt_path.write_text(json.dumps(receipt))
    assert verify_native_lock_binding(root, receipt_path, registry) == [
        "E_NATIVE_LOCK_BINDING:RECEIPT"
    ]


@pytest.mark.parametrize(
    ("path", "section", "mutation"),
    [
        ("extension/package.json", "dependencies", ("ajv", "^8.20.0")),
        ("extension/package.json", "dependencies", ("left-pad", "1.3.0")),
        ("extension/package.json", "devDependencies", ("typescript", ">=6.0.2")),
        ("package.json", "dependencies", ("left-pad", "1.3.0")),
    ],
)
def test_package_dependency_ranges_and_extras_are_rejected(
    tmp_path: Path,
    path: str,
    section: str,
    mutation: tuple[str, str],
) -> None:
    root = _dependency_fixture(tmp_path)
    manifest_path = root / path
    manifest = json.loads(manifest_path.read_text())
    manifest.setdefault(section, {})[mutation[0]] = mutation[1]
    manifest_path.write_text(json.dumps(manifest))

    assert "E_DEPENDENCY_POLICY:MANIFEST" in verify_dependency_policy(root)


def test_package_lifecycle_script_is_rejected(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path)
    manifest_path = root / "package.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["scripts"]["postinstall"] = "node install.js"
    manifest_path.write_text(json.dumps(manifest))

    assert "E_DEPENDENCY_POLICY:MANIFEST" in verify_dependency_policy(root)


@pytest.mark.parametrize(
    ("relative", "replacement"),
    [
        (".node-version", b"22.23.1\n"),
        (".python-version", b"3.12.4\n"),
        (".npmrc", b"ignore-scripts=false\nsave-exact=true\n"),
        ("pnpm-workspace.yaml", b"packages:\n  - extension-extra\n"),
    ],
)
def test_exact_bootstrap_config_bytes_are_required(
    tmp_path: Path, relative: str, replacement: bytes
) -> None:
    root = _dependency_fixture(tmp_path)
    (root / relative).write_bytes(replacement)

    assert "E_DEPENDENCY_POLICY:BOOTSTRAP_CONFIG" in verify_dependency_policy(root)


def test_pyproject_dependency_ranges_extras_and_uv_pin_are_rejected(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text()
        .replace("cryptography==50.0.1", "cryptography>=50.0.1")
        .replace('required-version = "==0.11.7"', 'required-version = ">=0.11.7"')
    )

    errors = verify_dependency_policy(root)
    assert "E_DEPENDENCY_POLICY:PYPROJECT" in errors
    assert "E_DEPENDENCY_POLICY:UV_VERSION" in errors


def test_successor_test_config_drift_is_rejected(tmp_path: Path) -> None:
    root = _dependency_fixture(tmp_path)
    config_path = root / "extension/tsconfig.harness.json"
    config = json.loads(config_path.read_text())
    config["include"].remove("test/security/**/*.ts")
    config_path.write_text(json.dumps(config))

    assert "E_DEPENDENCY_POLICY:TSCONFIG" in verify_dependency_policy(root)


@pytest.mark.parametrize("lock_name", ["pnpm-lock.yaml", "uv.lock"])
def test_direct_dependency_lock_drift_is_rejected(tmp_path: Path, lock_name: str) -> None:
    root = _dependency_fixture(tmp_path)
    lock = root / lock_name
    if lock_name == "pnpm-lock.yaml":
        lock.write_text(lock.read_text().replace("specifier: 8.20.0", "specifier: ^8.20.0", 1))
    else:
        lock.write_text(
            lock.read_text().replace(
                '{ name = "cryptography", specifier = "==50.0.1" }',
                '{ name = "cryptography", specifier = ">=50.0.1" }',
                1,
            )
        )

    assert "E_DEPENDENCY_POLICY:LOCK" in verify_dependency_policy(root)


@pytest.mark.parametrize("lock_name", ["pnpm-lock.yaml", "uv.lock"])
def test_resolved_direct_dependency_version_drift_is_rejected(
    tmp_path: Path, lock_name: str
) -> None:
    root = _dependency_fixture(tmp_path)
    lock = root / lock_name
    if lock_name == "pnpm-lock.yaml":
        lock.write_text(lock.read_text().replace("version: 8.20.0", "version: 8.20.1", 1))
    else:
        lock.write_text(
            lock.read_text().replace(
                'name = "cryptography"\nversion = "50.0.1"',
                'name = "cryptography"\nversion = "50.0.2"',
                1,
            )
        )

    assert "E_DEPENDENCY_POLICY:LOCK" in verify_dependency_policy(root)


@pytest.mark.parametrize(
    ("lock_name", "before", "after"),
    [
        ("uv.lock", 'name = "attrs"\nversion = "26.1.0"', 'name = "attrs"\nversion = "26.1.1"'),
        ("pnpm-lock.yaml", "ajv@6.15.0:", "ajv@6.15.1:"),
    ],
)
def test_transitive_lock_identity_drift_is_rejected(
    tmp_path: Path, lock_name: str, before: str, after: str
) -> None:
    root = _dependency_fixture(tmp_path)
    lock = root / lock_name
    lock.write_text(lock.read_text().replace(before, after, 1))

    assert "E_DEPENDENCY_POLICY:LOCK" in verify_dependency_policy(root)
