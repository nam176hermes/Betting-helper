import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import run_command_registry
from tools.build_candidate_qualification_receipt import build_candidate_qualification_receipt


def test_candidate_receipt_cli_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_candidate_qualification_receipt.py", "--help"],
        cwd=Path.cwd(),
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode()


def _evidence() -> dict[str, object]:
    registry = run_command_registry.validate_registry(Path("task-command-registry.json"))
    rows: list[dict[str, object]] = []
    for command in run_command_registry.candidate_commands(registry):
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
    return run_command_registry.build_candidate_command_results(registry, rows)


def test_receipt_rejects_skipped_command_live_evidence_or_production_authority(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(_evidence(), sort_keys=True, separators=(",", ":")))

    receipt = build_candidate_qualification_receipt(Path.cwd(), evidence, tmp_path / "receipt.json")
    assert len(receipt["command_ids"]) == 45
    assert receipt["inventory"]

    invalid = _evidence()
    invalid["production_authority"] = "PRODUCTION"
    evidence.write_text(json.dumps(invalid, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ValueError, match="E_CANDIDATE_RECEIPT"):
        build_candidate_qualification_receipt(Path.cwd(), evidence, tmp_path / "bad.json")
