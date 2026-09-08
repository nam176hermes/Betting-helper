"""Registered qualification scripts must bootstrap imports without pytest's path."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.full_verifier_config import load_controller_config
from tools.run_command_registry import execution_environment

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("script", [
    "tools/run_environment_qualification.py",
    "tools/run_full_repair_qualification.py",
    "tools/verify_full_repair_qualification.py",
])
@pytest.mark.parametrize(("arguments", "exit_code"), [(["--help"], 0), ([], 2)])
def test_registered_qualification_cli_imports_before_argument_validation(
    script: str, arguments: list[str], exit_code: int,
) -> None:
    registry = json.loads((ROOT / "task-command-registry.json").read_text())
    commands = [entry for entry in registry["commands"] if script in entry["argv"]]
    assert len(commands) == 1
    command = commands[0]
    argv = command["argv"]
    assert command["cwd"] == str(ROOT)
    config = load_controller_config(Path(argv[argv.index("--config") + 1]))
    environment = {**execution_environment(config), "PYTHONDONTWRITEBYTECODE": "1"}
    assert "PYTHONPATH" not in environment
    # Never pass the registered capture/issuance arguments: help or missing args only.
    prefix = argv[:argv.index(script) + 1]
    assert prefix == ["uv", "run", "--frozen", "--offline", "python", script]
    completed = subprocess.run(  # noqa: S603 -- fixed registered CLI, no capture arguments.
        [*prefix, *arguments], cwd=ROOT, env=environment,
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert completed.returncode == exit_code, completed.stderr
    output = completed.stdout if arguments else completed.stderr
    assert "usage:" in output.lower()
    assert "--config" in output
    assert "Traceback" not in completed.stderr
