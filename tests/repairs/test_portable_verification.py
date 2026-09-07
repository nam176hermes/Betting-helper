from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import run_command_registry, verify_local

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "tools/verify_local.py"


def test_portable_profile_runs_repo_local_checks_from_another_cwd(tmp_path: Path) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed checkout-owned CLI.
        [sys.executable, str(VERIFY), "--profile", "portable"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["profile"] == "portable"
    assert report["status"] == "PASS"
    results = {row["check_id"]: row for row in report["results"]}
    assert list(results) == [
        "compile_all_tests",
        "registry_self_check",
        "implemented_repair_tests",
        "collect_all_repair_tests",
    ]
    assert results["compile_all_tests"]["argv"][-2:] == ["-p", "tsconfig.test.json"]
    assert "passed" in results["implemented_repair_tests"]["stdout"]
    assert "tests collected" in results["collect_all_repair_tests"]["stdout"]
    serialized = json.dumps(report)
    assert "../authoring-tests" not in serialized
    assert str(Path.home()) not in serialized


def test_full_profile_holds_without_guessing_external_prerequisites(tmp_path: Path) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed checkout-owned CLI.
        [sys.executable, str(VERIFY), "--profile", "full"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2, completed.stderr
    report = json.loads(completed.stdout)
    assert report["profile"] == "full"
    assert report["status"] == "HOLD"
    assert report["authoritative_controller"] == "NOT_EXECUTED"
    configured = report["prerequisites"]
    assert {item["status"] for item in configured} == {"MISSING_CONFIGURATION"}
    assert all(item["path"] is None for item in configured)
    assert report["hold_codes"] == ["CONTROLLER_CONFIG_UNBOUND"]


def test_registry_default_is_anchored_to_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    registry = run_command_registry.validate_registry()
    assert registry["schema_version"] == "command-registry/v1"


def _git(root: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git is not None
    completed = subprocess.run(  # noqa: S603 - fixed local test-repository command.
        [git, "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": str(Path("/usr/bin")), "HOME": str(root)},
    )
    return completed.stdout.strip()


def test_bootstrap_receipt_requires_actual_git_head_tree_and_clean_state(
    tmp_path: Path,
) -> None:
    authoring = tmp_path / "authoring"
    authoring.mkdir()
    _git(authoring, "init", "-b", "main")
    _git(authoring, "config", "user.name", "R09 Test")
    _git(authoring, "config", "user.email", "r09@example.invalid")
    (authoring / "tracked.txt").write_text("tracked\n")
    _git(authoring, "add", "tracked.txt")
    _git(authoring, "commit", "-m", "fixture")
    pack = authoring / "pack"
    pack.mkdir()
    receipt_path = tmp_path / "receipt.json"
    accepted_ancestor = _git(authoring, "rev-parse", "HEAD")
    receipt = {
        "schema_version": "current-authoring-repository-receipt/v1",
        "accepted_authoring_ancestor": accepted_ancestor,
        "root": str(authoring),
        "head": accepted_ancestor,
        "tree": _git(authoring, "rev-parse", "HEAD^{tree}"),
        "status": "",
    }
    receipt_path.write_text(json.dumps(receipt))
    verify_local._validate_bootstrap_receipt(receipt_path, pack, accepted_ancestor)

    receipt_path.write_text(
        json.dumps({**receipt, "schema_version": "boot0-authoring-repository-receipt/v2"})
    )
    with pytest.raises(ValueError, match="receipt content mismatch"):
        verify_local._validate_bootstrap_receipt(receipt_path, pack, accepted_ancestor)

    for field in ("head", "tree"):
        receipt_path.write_text(json.dumps({**receipt, field: "0" * 40}))
        with pytest.raises(ValueError, match="receipt content mismatch"):
            verify_local._validate_bootstrap_receipt(receipt_path, pack, accepted_ancestor)

    receipt_path.write_text(json.dumps(receipt))
    (authoring / "dirty.txt").write_text("dirty\n")
    with pytest.raises(ValueError, match="receipt content mismatch"):
        verify_local._validate_bootstrap_receipt(receipt_path, pack, accepted_ancestor)


def test_portable_uses_extended_budget_only_for_implemented_repairs() -> None:
    assert verify_local._portable_timeout("implemented_repair_tests") == 900
    assert verify_local._portable_timeout("compile_all_tests") == 300


def test_portable_timeout_retains_partial_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        verify_local, "_portable_commands", lambda: (("implemented_repair_tests", ["probe"]),)
    )

    def timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(
            cmd=["probe"], timeout=900, output=b"partial stdout", stderr=b"partial stderr"
        )

    monkeypatch.setattr(verify_local.subprocess, "run", timeout)
    assert verify_local._run_portable() == 1
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["stdout"] == "partial stdout"
    assert "partial stderr" in row["stderr"]
    assert "TimeoutExpired" in row["stderr"]


def test_portable_environment_rejects_pytest_and_python_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    monkeypatch.setenv("PYTEST_PLUGINS", "attacker")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "attacker"))
    monkeypatch.setattr(
        verify_local, "_portable_commands", lambda: (("registry_self_check", ["probe"]),)
    )
    seen: list[dict[str, str]] = []

    def complete(*_args: object, **kwargs: object) -> object:
        seen.append(kwargs["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(["probe"], 0, "ok", "")

    monkeypatch.setattr(verify_local.subprocess, "run", complete)
    assert verify_local._run_portable() == 0
    assert len(seen) == 1
    assert "PYTEST_ADDOPTS" not in seen[0]
    assert "PYTEST_PLUGINS" not in seen[0]
    assert "PYTHONPATH" not in seen[0]
    assert seen[0]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_empty_external_test_and_cache_directories_do_not_pass(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="E_EXTERNAL_AUTHORING_TESTS"):
        verify_local._validate_authoring_tests(empty)
    with pytest.raises(ValueError, match="E_UV_CACHE"):
        verify_local._validate_cache(empty, "uv")
    with pytest.raises(ValueError, match="E_PNPM_STORE"):
        verify_local._validate_cache(empty, "pnpm")


def test_unbound_controller_configuration_never_delegates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    delegated = False

    def delegate(_config: object) -> int:
        nonlocal delegated
        delegated = True
        return 0

    monkeypatch.setattr(verify_local, "_delegate_controller", delegate)
    assert verify_local._run_full(None) == 2
    assert delegated is False
    assert json.loads(capsys.readouterr().out)["authoritative_controller"] == "NOT_EXECUTED"
