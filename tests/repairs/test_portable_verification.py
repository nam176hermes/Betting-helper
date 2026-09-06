from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import run_command_registry

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

    assert completed.returncode == 0, completed.stderr
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
    assert {item["status"] for item in report["prerequisites"]} == {
        "MISSING_CONFIGURATION"
    }
    assert all(item["path"] is None for item in report["prerequisites"])


def test_registry_default_is_anchored_to_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    registry = run_command_registry.validate_registry()
    assert registry["schema_version"] == "command-registry/v1"
