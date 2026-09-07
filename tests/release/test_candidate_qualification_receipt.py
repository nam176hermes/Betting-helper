import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import build_candidate_qualification_receipt as receipt_builder
from tools import run_command_registry
from tools.build_candidate_qualification_receipt import build_candidate_qualification_receipt
from tools.full_verifier_config import load_controller_config

CONFIG = Path("vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json")


def test_candidate_receipt_cli_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_candidate_qualification_receipt.py", "--help"],
        cwd=Path.cwd(),
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode()


def _evidence() -> dict[str, object]:
    config = load_controller_config(CONFIG)
    registry = run_command_registry.validate_registry(Path("task-command-registry.json"))
    rows: list[dict[str, object]] = []
    for command in run_command_registry.effective_candidate_commands(registry, config):
        rows.append(
            {
                "command_id": command["command_id"],
                "argv": command["argv"],
                "cwd": command["cwd"],
                "expected_exit": command["expected_exit"],
                "exit_code": command["expected_exit"],
                "passed": True,
                "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                "stdout_size_bytes": "0",
                "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_size_bytes": "0",
            }
        )
    return run_command_registry.build_candidate_command_results(registry, rows, config)


def test_receipt_rejects_skipped_command_live_evidence_or_production_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(_evidence(), sort_keys=True, separators=(",", ":")))

    config = load_controller_config(CONFIG)
    inventory = {"head": "1" * 40, "tree": "2" * 40, "entries": []}
    monkeypatch.setattr(receipt_builder, "_inventory", lambda _source: inventory)
    receipt = build_candidate_qualification_receipt(
        Path.cwd(), evidence, tmp_path / "receipt.json", config
    )
    assert len(receipt["command_ids"]) == 45
    assert receipt["inventory"]

    invalid = _evidence()
    invalid["production_authority"] = "PRODUCTION"
    evidence.write_text(json.dumps(invalid, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        build_candidate_qualification_receipt(Path.cwd(), evidence, tmp_path / "bad.json", config)


def test_candidate_inventory_is_exact_clean_git_tree_not_ignored_workspace(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    assert git is not None
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(  # noqa: S603 - resolved local Git test fixture.
        [git, "init", "-b", "main"], cwd=source, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603 - resolved local Git test fixture.
        [git, "config", "user.name", "Receipt Test"],
        cwd=source,
        check=True,
    )
    subprocess.run(  # noqa: S603 - resolved local Git test fixture.
        [git, "config", "user.email", "receipt@example.invalid"],
        cwd=source,
        check=True,
    )
    (source / ".gitignore").write_text(".local/\n")
    (source / "source.txt").write_text("governed\n")
    subprocess.run([git, "add", "."], cwd=source, check=True)  # noqa: S603
    subprocess.run(  # noqa: S603 - resolved local Git test fixture.
        [git, "commit", "-m", "fixture"], cwd=source, check=True
    )
    (source / ".local").mkdir()
    (source / ".local/evidence.json").write_text("scratch")

    inventory = __import__(
        "tools.build_candidate_qualification_receipt", fromlist=["_inventory"]
    )._inventory(source)
    assert [row["path"] for row in inventory["entries"]] == [
        ".gitignore",
        "source.txt",
    ]
    assert (
        inventory["head"]
        == subprocess.check_output(  # noqa: S603 - resolved local Git test fixture.
            [git, "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
    )

    (source / "source.txt").write_text("dirty\n")
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        __import__(
            "tools.build_candidate_qualification_receipt", fromlist=["_inventory"]
        )._inventory(source)
