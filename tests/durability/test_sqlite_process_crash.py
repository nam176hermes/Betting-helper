"""Full terminal evidence for the seven governed SQLite crash vectors."""

from __future__ import annotations

import copy
import hashlib
import json
import signal
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.vendor import pack_root
from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix
from tools.verify_repair_evidence import aggregate_repair_evidence

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)
SQL_IDS = [
    row["vector_id"]
    for row in json.loads(
        (PACK / "docs/registries/crash-harness-registry.v1.json").read_text()
    )["entries"]
    if row["harness"] == "SQLITE_TRANSACTION"
]


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return run_sqlite_crash_matrix(PACK, tmp_path_factory.mktemp("sqlite-crash"))


def _artifact(row: dict[str, Any], name: str) -> Any:
    artifact = row[name]
    path = Path(artifact["path"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
    return json.loads(path.read_text())


def _replace_artifact(row: dict[str, Any], name: str, value: object, tmp_path: Path) -> None:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    row[name] = {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _contains_oracle(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in {"expected", "expected_post_restart_state", "oracle"}
            or _contains_oracle(item)
            for key, item in value.items()
        )
    return isinstance(value, list) and any(_contains_oracle(item) for item in value)


def test_sql_transaction_emits_exact_full_terminal_evidence(report: dict[str, Any]) -> None:
    assert report["result"] == "PASS"
    assert report["executed_vector_ids"] == SQL_IDS
    assert report["killed_child_count"] == 7
    assert report["mutation_survivors"] == 0
    assert [row["case_id"] for row in report["records"]] == SQL_IDS
    assert {row["status"] for row in report["records"]} == {"PASS"}
    assert {row["execution_kind"] for row in report["records"]} == {
        "SQLITE_TRANSACTION_PROCESS_CRASH"
    }
    assert all(row["termination_returncode"] == -signal.SIGKILL for row in report["records"])
    assert aggregate_repair_evidence(SQL_IDS, report["records"])["result"] == "PASS"


def test_sql06_checkpoint_is_inside_real_sqlite_commit_io(report: dict[str, Any]) -> None:
    row = next(item for item in report["records"] if item["case_id"] == "SQL-06-DURING-COMMIT")
    witness = _artifact(row, "boundary_artifact")
    assert witness["phase"] == "during_commit"
    assert witness["commit_armed"] is True
    assert witness["operation"] in {"fsync", "fdatasync"}
    assert witness["target"] in {"rollback_journal", "database"}
    assert witness["sqlite_path"].endswith(("run.sqlite3-journal", "run.sqlite3"))
    assert row["actual"]["atomic_outcome"] in {"OLD", "NEW"}
    assert row["comparison"] == {"matched": True, "allowed_atomic_outcome": True}


def test_child_and_independent_reader_never_receive_the_oracle(report: dict[str, Any]) -> None:
    for row in report["records"]:
        assert not _contains_oracle(_artifact(row, "input_artifact"))
        reader_input = _artifact(row, "reader_input_artifact")
        assert not _contains_oracle(reader_input)
        assert set(reader_input) == {"run_dir", "run_id", "case_id", "checkpoint_id"}
        assert "expected" not in " ".join(row["launch_provenance"]["argv"]).lower()
        assert "expected" not in " ".join(row["reader_provenance"]["argv"]).lower()


@pytest.mark.parametrize(
    "damage", ["wrong_oracle", "stale_run", "stale_case", "stale_checkpoint", "wrong_error"]
)
def test_semantically_wrong_terminal_record_is_rejected(
    report: dict[str, Any], tmp_path: Path, damage: str
) -> None:
    row = copy.deepcopy(report["records"][5])
    if damage == "wrong_oracle":
        row["expected"]["allowed_atomic_outcomes"] = []
    elif damage == "wrong_error":
        row["observed_error"] = "E_WRONG_EXPECTED_ERROR"
    else:
        field = damage.removeprefix("stale_") + "_id"
        row["identity"][field] = "stale"
        checkpoint = _artifact(row, "checkpoint_artifact")
        checkpoint[field] = "stale"
        _replace_artifact(row, "checkpoint_artifact", checkpoint, tmp_path)
    result = aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "FAIL"
    assert result["errors"]


def test_missing_duplicate_and_tampered_records_are_rejected(
    report: dict[str, Any], tmp_path: Path
) -> None:
    row = copy.deepcopy(report["records"][0])
    assert aggregate_repair_evidence([row["case_id"]], [])["result"] == "FAIL"
    duplicate = aggregate_repair_evidence([row["case_id"]], [row, copy.deepcopy(row)])
    assert duplicate["result"] == "FAIL"
    actual = Path(row["actual_artifact"]["path"])
    tampered = tmp_path / "actual.json"
    tampered.write_bytes(actual.read_bytes() + b"\n")
    row["actual_artifact"]["path"] = str(tampered)
    assert aggregate_repair_evidence([row["case_id"]], [row])["result"] == "FAIL"
