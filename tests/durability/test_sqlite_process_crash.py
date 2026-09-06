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
    return _descriptor(row[name])


def _descriptor(artifact: dict[str, str]) -> Any:
    path = Path(artifact["path"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
    return json.loads(path.read_text())


def _replace_artifact(row: dict[str, Any], name: str, value: object, suffix: str) -> None:
    path = Path(row["case_directory"]) / f"mutation-{suffix}-{name}.json"
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


def _error(row: dict[str, Any]) -> str:
    result = aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "FAIL"
    assert len(result["errors"]) == 1
    error = result["errors"][0]["error"]
    assert isinstance(error, str)
    return error


def _rehash_snapshot_mutation(
    row: dict[str, Any], table: str, field: str, value: object
) -> None:
    run = row["reader_provenance"]["runs"][0]
    output = json.loads(Path(run["path"]).read_text())
    output["state"]["tables"][table][0][field] = value
    _replace_artifact(row, "mutated_reader_output", output, f"ddl-{table}-{field}")
    run.update(row.pop("mutated_reader_output"))
    row["actual"]["before"] = output["state"]
    _replace_artifact(row, "actual_artifact", row["actual"], f"ddl-{table}-{field}")
    terminal = dict(row)
    terminal.pop("terminal_artifact")
    _replace_artifact(row, "terminal_artifact", terminal, f"ddl-{table}-{field}")


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
        for artifact in row["reader_input_artifacts"].values():
            reader_input = _descriptor(artifact)
            assert not _contains_oracle(reader_input)
            assert set(reader_input) == {
                "run_dir", "run_id", "case_id", "checkpoint_id", "phase"
            }
        assert "expected" not in " ".join(row["launch_provenance"]["argv"]).lower()
        assert all(
            "expected" not in " ".join(item["argv"]).lower()
            for item in row["reader_provenance"]["runs"]
        )


@pytest.mark.parametrize(
    "damage", ["wrong_oracle", "stale_run", "stale_case", "stale_checkpoint", "wrong_error"]
)
def test_semantically_wrong_terminal_record_is_rejected(
    report: dict[str, Any], damage: str
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
        boundary = _artifact(row, "boundary_artifact")
        boundary["identity"][field] = "stale"
        _replace_artifact(row, "checkpoint_artifact", checkpoint, damage)
        _replace_artifact(row, "boundary_artifact", boundary, damage)
    expected = (
        "E_SQLITE_TERMINAL_RECORD"
        if damage in {"wrong_oracle", "wrong_error"}
        else "E_SQLITE_CHECKPOINT_IDENTITY"
    )
    assert _error(row) == expected


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


@pytest.mark.parametrize("damage", ["duplicate", "swap", "wrong_run"])
def test_reader_output_identity_and_phase_are_enforced(
    report: dict[str, Any], damage: str
) -> None:
    row = copy.deepcopy(report["records"][0])
    runs = row["reader_provenance"]["runs"]
    if damage == "duplicate":
        runs[1] = copy.deepcopy(runs[0])
    elif damage == "swap":
        runs.reverse()
    else:
        output = json.loads(Path(runs[0]["path"]).read_text())
        output["identity"]["run_id"] = "00000000-0000-4000-8000-000000000099"
        _replace_artifact(row, "reader_before_output_artifact", output, damage)
        runs[0].update(row["reader_before_output_artifact"])
    assert _error(row) == "E_SQLITE_READER_OUTPUT"


@pytest.mark.parametrize("damage", ["raw", "cursor", "table"])
def test_rehashed_journal_corruption_reaches_semantic_validator(
    report: dict[str, Any], damage: str
) -> None:
    row = copy.deepcopy(report["records"][6])
    runs = row["reader_provenance"]["runs"]
    output = json.loads(Path(runs[0]["path"]).read_text())
    tables = output["state"]["tables"]
    if damage == "raw":
        tables["raw_commits"][0]["raw_observation_content_hash"] = "f" * 64
    elif damage == "cursor":
        tables["reducer_cursors"][0]["cursor_hash"] = "f" * 64
    else:
        tables["ack_outbox"].clear()
    _replace_artifact(row, "reader_before_output_artifact", output, damage)
    runs[0].update(row["reader_before_output_artifact"])
    row["actual"]["before"] = output["state"]
    _replace_artifact(row, "actual_artifact", row["actual"], damage)
    assert _error(row) == "E_SQLITE_JOURNAL_STATE"


@pytest.mark.parametrize(
    ("table", "field", "value"),
    [
        ("run_meta", "run_status", "INVALID"),
        ("coherence_epochs", "epoch_status_at_record", "INVALID"),
    ],
)
def test_validly_rehashed_complete_snapshot_must_satisfy_exact_ddl(
    report: dict[str, Any], table: str, field: str, value: object
) -> None:
    row = copy.deepcopy(report["records"][6])
    _rehash_snapshot_mutation(row, table, field, value)
    assert _error(row) == "E_SQLITE_DDL_STATE"


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        ("child_argv", "E_SQLITE_CHILD_PROVENANCE"),
        ("reader_argv", "E_SQLITE_READER_PROVENANCE"),
        ("termination", "E_SQLITE_TERMINATION"),
        ("terminal", "E_SQLITE_TERMINAL_ARTIFACT"),
    ],
)
def test_process_and_terminal_bindings_are_enforced(
    report: dict[str, Any], damage: str, expected: str
) -> None:
    row = copy.deepcopy(report["records"][0])
    if damage == "child_argv":
        row["launch_provenance"]["argv"][3] = "WRONG"
    elif damage == "reader_argv":
        row["reader_provenance"]["runs"][0]["argv"][3] = "WRONG"
    elif damage == "termination":
        row["termination_mechanism"] = "WRONG"
    else:
        path = Path(row["terminal_artifact"]["path"])
        damaged = path.with_name("mutation-terminal.json")
        damaged.write_bytes(path.read_bytes() + b"\n")
        row["terminal_artifact"]["path"] = str(damaged)
    assert _error(row) == expected


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        ("child_executable", "E_SQLITE_CHILD_PROVENANCE"),
        ("reader_executable", "E_SQLITE_READER_PROVENANCE"),
        ("reader_input", "E_SQLITE_READER_INPUT"),
        ("reader_exit", "E_SQLITE_READER_PROVENANCE"),
        ("recovery_exit", "E_SQLITE_RECOVERY_PROVENANCE"),
        ("checkpoint_sha", "E_SQLITE_TERMINATION"),
        ("terminal_content", "E_SQLITE_TERMINAL_ARTIFACT"),
        ("terminal_missing", "E_SQLITE_TERMINAL_ARTIFACT"),
    ],
)
def test_all_process_exit_input_and_terminal_content_bindings_are_enforced(
    report: dict[str, Any], damage: str, expected: str
) -> None:
    row = copy.deepcopy(report["records"][0])
    if damage == "child_executable":
        row["launch_provenance"]["executable"]["path"] = "/usr/bin/false"
    elif damage == "reader_executable":
        row["reader_provenance"]["executable"]["path"] = "/usr/bin/false"
    elif damage == "reader_input":
        reader_input = _descriptor(row["reader_input_artifacts"]["before"])
        reader_input["case_id"] = "SQL-99-WRONG"
        _replace_artifact(row, "mutated_reader_input", reader_input, damage)
        row["reader_input_artifacts"]["before"] = row.pop("mutated_reader_input")
    elif damage == "reader_exit":
        row["reader_provenance"]["runs"][0]["exit"] = 3
    elif damage == "recovery_exit":
        row["recovery_runs"][0]["exit"] = 3
    elif damage == "checkpoint_sha":
        row["checkpoint_sha256"] = "f" * 64
    elif damage == "terminal_content":
        terminal = _descriptor(row["terminal_artifact"])
        terminal["observed_error"] = "E_FORGED"
        _replace_artifact(row, "mutated_terminal", terminal, damage)
        row["terminal_artifact"] = row.pop("mutated_terminal")
    else:
        row["terminal_artifact"]["path"] = str(
            Path(row["case_directory"]) / "missing-terminal.json"
        )
    assert _error(row) == expected
