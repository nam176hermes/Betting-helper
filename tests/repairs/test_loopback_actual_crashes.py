"""Backend-only real process evidence; never extension/46-case qualification."""

import copy
import importlib
import json
import os
import shutil
import signal
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.store import RunStore
from tests.repairs.test_shared_ingest_persistence import corrupt_journal, observation
from tools.restart_state_reader import read_restart_state

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"


def runner() -> Any:
    module = importlib.import_module("tools.run_loopback_ack_crash_matrix")
    assert hasattr(module, "run_backend_case"), "BH-R03: actual backend crash path absent"
    return module


def entry(prefix: str) -> dict[str, Any]:
    entries = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    return next(row for row in entries["entries"] if row["vector_id"].startswith(prefix))


@pytest.mark.parametrize(
    "prefix", ["SEND-01", "SQL-01", "SQL-02", "SQL-03", "SQL-04", "SQL-05", "SQL-07", "ACK-06"]
)
def test_actual_ingest_checkpoint_kill_reopen_and_ack_replay(tmp_path: Path, prefix: str) -> None:
    result = runner().run_backend_case(entry(prefix), observation(), tmp_path)
    assert result["result"] == "PASS"
    row = result["records"][0]
    assert row["termination_returncode"] == -signal.SIGKILL
    with pytest.raises(ChildProcessError):
        os.waitpid(row["pid"], os.WNOHANG)
    case = Path(row["case_directory"])
    actual = json.loads((case / "actual-state.json").read_text())
    committed = prefix in {"SQL-07", "ACK-06"}
    assert len(actual["tables"]["raw_commits"]) == int(committed)
    recovery = json.loads((case / "recovery.json").read_text())
    assert recovery["replay"]["ack"]["highest_contiguous_sequence"] == 1
    assert len(recovery["after"]["tables"]["raw_commits"]) == 1
    witness = json.loads((case / "boundary.json").read_text())
    assert witness["received_observation_hash"] == observation()["content_hash"]
    assert witness["transport_address"][0] == "127.0.0.1"
    assert row["input_sha256"] and row["actual_state_sha256"] and row["checkpoint_sha256"]
    assert row["comparison"] == "PASS"
    assert "expected" not in (case / "scenario.json").read_text()


def test_wrong_expected_is_detected_after_real_execution(tmp_path: Path) -> None:
    case = copy.deepcopy(entry("SQL-07"))
    case["expected_post_restart_state"]["sql_row_deltas"]["raw_commits"] = 999999
    with pytest.raises(ValueError, match="E_RESTART_STATE_MISMATCH"):
        runner().run_backend_case(case, observation(), tmp_path)
    assert len(list(tmp_path.rglob("actual-state.json"))) == 1


@pytest.mark.parametrize(
    "table,column",
    [("raw_commits", "raw_observation_content_hash"), ("reducer_cursors", "cursor_hash")],
)
def test_copied_actual_store_mutation_is_detected(tmp_path: Path, table: str, column: str) -> None:
    result = runner().run_backend_case(entry("SQL-07"), observation(), tmp_path / "original")
    case = Path(result["records"][0]["case_directory"])
    database = next(case.rglob("run.sqlite3"))
    copied = tmp_path / "corrupt-copy" / database.parent.name
    shutil.copytree(database.parent, copied)
    corrupt_journal(RunStore(copied / "run.sqlite3"), table, column)
    with pytest.raises(ValueError, match="E_STORE_DURABLE_CHAIN"):
        read_restart_state(copied)
    assert read_restart_state(database.parent)["tables"]["raw_commits"]


def test_original_ids_stay_visible_without_full_qualification(tmp_path: Path) -> None:
    result = runner().run_loopback_ack_crash_matrix(PACK, tmp_path, observation_input=observation())
    assert result["result"] == "HOLD"
    assert len(result["records"]) == 7
    assert {row["status"] for row in result["records"]} == {"NOT_IMPLEMENTED"}
    assert sum(row.get("scoped_result") == "PASS" for row in result["records"]) == 2
    assert result["legacy_full_qualification"] == "HOLD"


def test_entire_inherited_inventory_remains_unqualified_without_executed_evidence(
    tmp_path: Path,
) -> None:
    entries = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    rows = []
    for family in {row["harness"] for row in entries["entries"]}:
        result = runner().run_family(PACK, tmp_path, family, None)
        assert result["result"] == "HOLD"
        rows.extend(result["records"])
    assert len(rows) == 46
    assert {row["vector_id"] for row in rows} == {row["vector_id"] for row in entries["entries"]}
    assert all(row["status"] == "NOT_IMPLEMENTED" for row in rows)
    assert not list(tmp_path.iterdir())
