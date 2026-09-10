"""TEST_ONLY namespace projection; never formal A/B or full descendant qualification."""

from __future__ import annotations

import importlib.util
import json
import marshal
import os
import platform
import struct
import subprocess
from copy import deepcopy
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from tools import prepare_review_workspace as workspace
from tools import run_clock_vector_qualification as clock
from tools import verify_repair_evidence as repair
from tools.run_full_repair_qualification import collect_retained_sources, write_closed_inventory

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind", [
    "cache_directory", "legacy_root", "pyo", "optimized", "cache_alias",
    "escaped_directory", "cyclic_directory",
])
def test_python_bytecode_guard_rejects_hidden_or_unsafe_tree(tmp_path: Path, kind: str) -> None:
    environment = tmp_path / "prepared"
    environment.mkdir()
    if kind == "cache_directory":
        (environment / "__pycache__").mkdir()
    elif kind in {"legacy_root", "pyo", "optimized"}:
        name = {"legacy_root": "module.pyc", "pyo": "module.pyo",
                "optimized": "module.cpython-312.opt-1.pyc"}[kind]
        (environment / name).write_bytes(b"TEST_ONLY-unvalidated-bytecode")
    elif kind == "cache_alias":
        target = tmp_path / "external.pyc"
        target.write_bytes(b"TEST_ONLY-unvalidated-bytecode")
        (environment / "ordinary-name").symlink_to(target)
    elif kind == "escaped_directory":
        target = tmp_path / "external-library"
        target.mkdir()
        (environment / "library").symlink_to(target, target_is_directory=True)
    else:
        (environment / "recursive").symlink_to(environment, target_is_directory=True)
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        workspace._reject_unvalidated_python_bytecode(environment)


def test_python_bytecode_guard_accepts_contained_source_alias_without_touching_other_cache(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "prepared"
    library = environment / "lib"
    library.mkdir(parents=True)
    (library / "module.py").write_text("value = 'SOURCE'\n")
    (environment / "lib64").symlink_to(library, target_is_directory=True)
    other_cache = tmp_path / "qualified-cache.pyc"
    other_cache.write_bytes(b"TEST_ONLY-preserved-other-environment")
    workspace._reject_unvalidated_python_bytecode(environment)
    assert other_cache.read_bytes() == b"TEST_ONLY-preserved-other-environment"


def test_python_bytecode_guard_fails_closed_when_walk_cannot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreadable_walk(_path: Path, *, followlinks: bool, onerror: Any) -> Any:
        onerror(PermissionError("TEST_ONLY unreadable directory"))
        return iter(())

    monkeypatch.setattr(os, "walk", unreadable_walk)
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        workspace._reject_unvalidated_python_bytecode(tmp_path)


@pytest.fixture
def cache_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], Path]:
    config = json.loads((ROOT / "review-config/review-a.v2.json").read_text())
    # TEST_ONLY preparation consumes the source registry before a final seal exists.
    config["command_registry_path"] = str(
        ROOT / "vendor/hybrid-discovery-v6.3.6/docs/registries/review-command-registry.v1.json"
    )
    old_scratch = config["scratch_root"]
    scratch = tmp_path / "TEST_ONLY-cache-scratch"
    config = json.loads(json.dumps(config).replace(old_scratch, str(scratch)))
    commands = workspace._preparation_commands(config)
    commands = json.loads(json.dumps(commands).replace(old_scratch, str(scratch)))
    assert all(old_scratch not in json.dumps(command) for command in commands)
    workspace._run_preparation(config, commands)
    prepared = scratch / "python-env"
    initial_caches = [
        str(Path(directory) / name)
        for directory, names, files in os.walk(prepared, followlinks=True)
        for name in (*names, *files)
        if name == "__pycache__" or name.endswith((".pyc", ".pyo"))
    ]
    assert not initial_caches, f"HOLD_FRESH_PREPARATION_HAS_CACHES:{initial_caches}"
    monkeypatch.setattr(workspace, "_config_for_role", lambda *_args: deepcopy(config))
    return config, prepared


@pytest.mark.parametrize("cache_kind", [
    "timestamp", "checked_hash", "unchecked_hash", "legacy_module", "legacy_package",
])
def test_cache_only_prepared_python_cannot_be_projected(
    cache_projection: tuple[dict[str, Any], Path], cache_kind: str,
) -> None:
    config, prepared = cache_projection
    site = prepared / "lib/python3.12/site-packages"
    source_path = site / "rfc8785/_impl.py"
    record = site / "rfc8785-0.1.4.dist-info/RECORD"
    fixed = [
        source_path, record, prepared / "pyvenv.cfg", ROOT / "uv.lock",
        ROOT / "pyproject.toml", prepared.parent / "node-project/pnpm-lock.yaml",
    ]

    def snapshot() -> tuple[dict[Path, bytes], tuple[int, int], dict[str, tuple[str, bytes]]]:
        info = source_path.stat()
        return (
            {path: path.read_bytes() for path in fixed}, (info.st_mtime_ns, info.st_size),
            {alias: (os.readlink(prepared / "bin" / alias),
                     (prepared / "bin" / alias).resolve().read_bytes())
             for alias in ("python", "python3", "python3.12")},
        )

    frozen = snapshot()
    before = workspace._dependency_projection(prepared / "lib", prepared, python=True)
    assert before == workspace._dependency_projection(ROOT / ".venv/lib", ROOT / ".venv",
                                                       python=True)
    source = source_path.read_bytes()
    code_source = source + b"\nCACHE_SENTINEL = 'UNVALIDATED_CACHE'\n"
    module = "rfc8785._impl"
    cache = Path(importlib.util.cache_from_source(str(source_path)))
    header = importlib.util.MAGIC_NUMBER + struct.pack(
        "<III", 0, int(source_path.stat().st_mtime) & 0xffffffff, len(source)
    )
    if cache_kind in {"checked_hash", "unchecked_hash"}:
        flags = 3 if cache_kind == "checked_hash" else 1
        header = (importlib.util.MAGIC_NUMBER + struct.pack("<I", flags)
                  + importlib.util.source_hash(source))
    elif cache_kind in {"legacy_module", "legacy_package"}:
        code_source = b"CACHE_SENTINEL = 'UNVALIDATED_CACHE'\n"
        module = "rfc8785.bytecode_only" if cache_kind == "legacy_module" else "bytecode_only"
        cache = (site / "rfc8785/bytecode_only.pyc" if cache_kind == "legacy_module"
                 else site / "bytecode_only/__init__.pyc")
        assert not cache.with_suffix(".py").exists()
    cache.parent.mkdir(parents=True, exist_ok=True)
    code = compile(code_source, str(source_path), "exec", dont_inherit=True, optimize=0)
    cache.write_bytes(header + marshal.dumps(code))
    probe = (
        "import importlib,sys; "
        f"sys.path.insert(0,{str(site)!r}); "
        f"print(importlib.import_module({module!r}).CACHE_SENTINEL)"
    )
    observed = subprocess.run(  # noqa: S603 -- benign cache in wholly owned TEST_ONLY environment.
        [str(prepared / "bin/python3"), "-I", "-B", "-S", "-c", probe],
        capture_output=True, text=True, check=False, timeout=15,
    )
    assert observed.returncode == 0, observed.stderr
    assert observed.stdout.strip() == "UNVALIDATED_CACHE"
    assert snapshot() == frozen
    assert workspace._dependency_projection(prepared / "lib", prepared, python=True) == before
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        workspace._producer_projection(config, [{"command_id": "A_CHECK_DESCENDANT"}])


def test_projection_rejects_divergent_python_alias_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = json.loads((ROOT / "review-config/review-a.v2.json").read_text())
    runtime = tmp_path / "runtime"
    qualified = runtime / ".venv"
    scratch = tmp_path / "scratch"
    prepared = scratch / "python-env"
    for environment in (qualified, prepared):
        (environment / "bin").mkdir(parents=True)
        (environment / "pyvenv.cfg").write_bytes((ROOT / ".venv/pyvenv.cfg").read_bytes())
        for basename in ("python", "python3", "python3.12"):
            (environment / "bin" / basename).symlink_to("/usr/bin/python3.12")
    (prepared / "bin/python").unlink()
    (prepared / "bin/python").symlink_to("/usr/bin/true")
    config["scratch_root"] = str(scratch)
    config["environment"]["UV_PROJECT_ENVIRONMENT"] = str(prepared)
    config["producer_environment"]["python_environment"] = str(qualified)
    config["producer_environment"]["python_executable"] = str(qualified / "bin/python3")
    config["producer_environment"]["runtime_unc"] = (
        "\\\\wsl.localhost\\Ubuntu" + str(runtime).replace("/", "\\")
    )
    monkeypatch.setattr(workspace, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(workspace, "_config_for_role", lambda *_args: deepcopy(config))
    node = Path(config["producer_environment"]["node_executable"])
    monkeypatch.setattr(repair, "_resolved_node_executable", lambda: node)

    def forbidden_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("divergent Python alias must reject before any subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden_subprocess)
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        workspace._producer_projection(config, [{"command_id": "A_CHECK_DESCENDANT"}])


def test_descendant_leaf_cli_bootstraps_its_local_packages() -> None:
    completed = subprocess.run(  # noqa: S603 -- fixed read-only CLI contract.
        [str(ROOT / ".venv/bin/python3"), "tools/qualify_descendant_repository.py", "--help"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--check-only" in completed.stdout


def test_real_test_only_namespace_preserves_descendant_producer_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory(prefix="test-only-namespace-", dir=ROOT / ".local") as temporary:
        owned = Path(temporary)
        config = json.loads((ROOT / "review-config/review-a.v2.json").read_text())
        config["command_registry_path"] = str(
            ROOT / "vendor/hybrid-discovery-v6.3.6/docs/registries/review-command-registry.v1.json"
        )
        old_scratch = config["scratch_root"]
        scratch = owned / "scratch"
        config = json.loads(json.dumps(config).replace(old_scratch, str(scratch)))
        config["output_root"] = str(owned / "output")
        config["workspace_root"] = str(owned)
        # Only authority context is a test fixture. No actual authority path is opened.
        config["authority_config"] = str(owned / "TEST_ONLY-no-authority.json")
        Path(config["output_root"]).mkdir()
        fixtures = [owned / name for name in ("pack", "seal", "zip", "sidecar")]
        fixtures[0].mkdir()
        for path in fixtures[1:]:
            path.write_text("TEST_ONLY")
        config["input_mounts"] = [
            {"source_root": str(path), "workspace_mount": str(path), "mode": "READ_ONLY"}
            for path in (ROOT, *fixtures)
        ]
        # Use the existing offline preparation path and immutable source inputs.
        commands = workspace._preparation_commands(config)
        commands = json.loads(json.dumps(commands).replace(old_scratch, str(scratch)))
        workspace._run_preparation(config, commands)
        for name in ("control", "home", "tmp"):
            (scratch / name).mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(workspace, "_config_for_role", lambda *_args: deepcopy(config))
        probe = (
            "import json,sys; from shutil import which; "
            "from tools.verify_repair_evidence import capture_binding; "
            "print(json.dumps({'binding':capture_binding(), 'lookup':which('node'),"
            "'argv_python':sys.executable}))"
        )
        leaf: dict[str, Any] = {
            "command_id": "A_CHECK_DESCENDANT", "cwd": str(ROOT),
            "argv": ["uv", "run", "--frozen", "--offline", "python", "-c", probe],
        }
        argv = workspace.build_bubblewrap_argv(config, leaf, leaf_commands=[leaf])
        completed = subprocess.run(  # noqa: S603 -- actual isolated TEST_ONLY local probe.
            argv, capture_output=True, text=True, timeout=90, check=False,
        )
        assert completed.returncode == 0, completed.stderr
        observed = json.loads(completed.stdout)
        host = subprocess.run(  # noqa: S603 -- identical read-only host producer identity probe.
            leaf["argv"], cwd=ROOT, capture_output=True, text=True, timeout=90, check=True,
        )
        expected = json.loads(host.stdout)
        assert observed["binding"]["environment"] == expected["binding"]["environment"]
        assert observed == expected
        assert "--unshare-net" in argv and "--unshare-user" in argv
        for excluded in config["excluded_roots"]:
            assert excluded not in argv
        # No host key/state, host home/config, parent cache or Windows profile mount.
        mounted_sources = {
            argv[index + 1] for index, token in enumerate(argv)
            if token in {"--ro-bind", "--bind"}
        }
        for forbidden in (str(Path.home()), "/mnt/c/Users/thenam", "/home/thenam176/.cache"):
            assert forbidden not in mounted_sources
        readonly_probe = (
            "import json,os; from pathlib import Path; "
            "from tools.run_environment_qualification import "
            "environment_live_roots,winpath,localpath,NATIVE; "
            "from tools.run_native_ingestor_qualification import dependency_binding; "
            "from tools.verify_repair_evidence import capture_binding; "
            "assert len(dependency_binding()['wheels']) == 6; "
            "assert all(p.exists() for p in environment_live_roots()); "
            "assert localpath(winpath(NATIVE)) == NATIVE; "
            f"assert localpath(winpath(Path({str(ROOT)!r}))) == Path({str(ROOT)!r}); "
            "assert not Path('/run/WSL').exists(); "
            "assert 'WSL_INTEROP' not in os.environ; "
            "assert not Path('/proc/sys/fs/binfmt_misc/WSLInterop').exists(); "
            "assert not Path('/home/thenam176/.config').exists(); "
            "print('TEST_ONLY_LIVE_PREREQUISITES_PASS')"
        )
        next_leaf = {**leaf, "argv": [*leaf["argv"][:-1], readonly_probe]}
        checked = subprocess.run(  # noqa: S603 -- same isolated read-only prerequisite probe.
            workspace.build_bubblewrap_argv(config, next_leaf, leaf_commands=[next_leaf]),
            capture_output=True, text=True, timeout=90, check=False,
        )
        assert checked.returncode == 0, checked.stderr
        assert checked.stdout.strip() == "TEST_ONLY_LIVE_PREREQUISITES_PASS"
        original_clock = owned / "original-clock"
        original_clock.mkdir()
        pack = ROOT / "vendor/hybrid-discovery-v6.3.6"
        coverage = json.loads((pack / clock._COVERAGE_PATH).read_text())
        vectors = json.loads((pack / clock._VECTOR_PATH).read_text())
        entry = next(
            row for row in coverage["entries"] if row["vector_id"] == "DRIFT-02-ONE-SECOND"
        )
        case = clock._case(entry, vectors)
        binding = repair.capture_binding()
        context = {
            "evidence_binding": binding, "evidence_directory": str(original_clock),
            "typescript_executable_artifacts": clock._retain_typescript_executable(
                ROOT, original_clock
            ),
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "node": which("node")},
            "code": {"revision": binding["revision"], "sha256": {
                str(ROOT / name): digest for name, digest in binding["source_sha256"].items()
            }},
            "registry_version": coverage["schema_version"],
        }
        row = clock._execute(case, ROOT, original_clock / case["case_id"], context)
        assert row["status"] == "PASS"
        closure = owned / "clock-closure"
        closure.mkdir()
        write_closed_inventory(
            collect_retained_sources(
                row, retained_boundaries=(original_clock,), live_roots=(ROOT,)
            ),
            closure / "inventory.json",
        )
        row_path = owned / "clock-row.json"
        row_path.write_text(json.dumps(row))
        original_clock.rename(owned / "unavailable-original-clock")
        clock_probe = (
            "import json; from pathlib import Path; "
            "from tools.retained_artifact_io import RetainedArtifactIO; "
            "from tools.verify_repair_evidence import aggregate_repair_evidence; "
            f"row=json.loads(Path({str(row_path)!r}).read_text()); "
            f"root=Path({str(closure)!r}); "
            "artifacts=RetainedArtifactIO.from_manifest("
            "json.loads((root/'inventory.json').read_text()),root/'retained'); "
            "checked=aggregate_repair_evidence([row['case_id']],[row],artifacts=artifacts); "
            "assert checked['result']=='PASS',checked; print('TEST_ONLY_COPIED_CLOCK_PASS')"
        )
        clock_leaf = {**leaf, "argv": [*leaf["argv"][:-1], clock_probe]}
        checked = subprocess.run(  # noqa: S603 -- genuine retained clock replay inside namespace.
            workspace.build_bubblewrap_argv(config, clock_leaf, leaf_commands=[clock_leaf]),
            capture_output=True, text=True, timeout=90, check=False,
        )
        assert checked.returncode == 0, checked.stderr
        assert checked.stdout.strip() == "TEST_ONLY_COPIED_CLOCK_PASS"
        # A transported config-only source copy, never actual authority/evidence inputs.
        controller = json.loads(
            (pack / "docs/configs/full-verifier-controller.v2.json").read_text()
        )
        controller = json.loads(json.dumps(controller).replace(
            controller["evidence_root"], "/TEST_ONLY-absent-evidence"
        ))
        controller["governed_source_pack"] = str(fixtures[0])
        controller_path = fixtures[0] / "docs/configs/full-verifier-controller.v2.json"
        controller_path.parent.mkdir(parents=True)
        controller_path.write_text(json.dumps(controller))
        descendant = {**leaf, "argv": [
            "uv", "run", "--frozen", "--offline", "python",
            "tools/qualify_descendant_repository.py", "--root", str(ROOT),
            "--config", str(controller_path), "--check-only", "--receipt",
            controller["receipts"]["descendant_repository"],
        ]}
        rejected = subprocess.run(  # noqa: S603 -- actual check-only leaf; absent fixture receipt.
            workspace.build_bubblewrap_argv(config, descendant, leaf_commands=[descendant]),
            capture_output=True, text=True, timeout=90, check=False,
        )
        assert rejected.returncode != 0
        assert "E_DESCENDANT_REPOSITORY" in rejected.stderr
        assert "FileNotFoundError" in rejected.stderr
        # Altered source-owned projections cannot add a live path or choose another executable.
        for key, value in (
            ("node_executable", "/usr/bin/true"), ("live_files", ["/etc/passwd"]),
            ("wsl_distro", "AnotherDistro"), ("runtime_unc", "\\\\wrong\\runtime"),
        ):
            changed = deepcopy(config)
            changed["producer_environment"][key] = value
            with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
                workspace.build_bubblewrap_argv(changed, leaf, leaf_commands=[leaf])
        with monkeypatch.context() as patched:
            patched.setattr(repair, "_resolved_node_executable", lambda: Path("/usr/bin/true"))
            with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
                workspace.build_bubblewrap_argv(config, leaf, leaf_commands=[leaf])
        original_sha = workspace._sha256
        for executable in ("node_executable", "path_translation_executable"):
            with monkeypatch.context() as patched:
                executable_path = Path(config["producer_environment"][executable])
                patched.setattr(workspace, "_sha256", lambda path, target=executable_path: "0" * 64
                                if path == target else original_sha(path))
                with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
                    workspace.build_bubblewrap_argv(config, leaf, leaf_commands=[leaf])
        original_run = subprocess.run

        def changed_mapping(argv: list[str], **kwargs: Any) -> Any:
            if argv[:2] == ["/usr/bin/wslpath", "-w"]:
                return subprocess.CompletedProcess(argv, 0, "\\\\wrong\\runtime\n", "")
            return original_run(argv, **kwargs)

        with monkeypatch.context() as patched:
            patched.setattr(subprocess, "run", changed_mapping)
            with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
                workspace.build_bubblewrap_argv(config, leaf, leaf_commands=[leaf])
        scratch_lock = scratch / "node-project/pnpm-lock.yaml"
        locked = scratch_lock.read_bytes()
        scratch_lock.write_bytes(locked + b"\n# changed scratch lock\n")
        with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
            workspace.build_bubblewrap_argv(config, leaf, leaf_commands=[leaf])
        scratch_lock.write_bytes(locked)
        package = scratch / "python-env/lib/python3.12/site-packages/rfc8785/_impl.py"
        original = package.read_bytes()
        package.unlink()  # Detach any package-cache hardlink before deliberate test corruption.
        package.write_bytes(original + b"\n# changed scratch package\n")
        with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
            workspace.build_bubblewrap_argv(config, leaf, leaf_commands=[leaf])
