"""Real extension-origin executions; a Node marker cannot satisfy these cases."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools import run_indexeddb_crash_matrix as matrix

ROOT = Path(__file__).parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"


def committed_case() -> dict[str, Any]:
    entries = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    return dict(next(row for row in entries if row["vector_id"] == "IDB-04-AFTER-COMMIT"))


def test_shared_spool_runs_all_four_real_browser_crashes(tmp_path: Path) -> None:
    result = matrix.run_indexeddb_crash_matrix(PACK, tmp_path)
    assert result["result"] == "PASS", result
    assert result["executed_vector_ids"] == [
        "IDB-01-BEFORE-TRANSACTION",
        "IDB-02-DURING-SEQUENCE-ALLOCATION",
        "IDB-03-DURING-ROW-PUT",
        "IDB-04-AFTER-COMMIT",
    ]
    records = result["records"]
    assert isinstance(records, list) and len(records) == 4
    for record in records:
        assert record["termination"]["method"] == "Worker.terminate"
        assert record["termination"]["worker_id"] == record["checkpoint"]["worker_id"]
        assert record["actual"]["worker_id"] != record["checkpoint"]["worker_id"]
        assert record["actual"]["origin"].startswith("chrome-extension://")
        assert record["actual"]["module_sha256"] == record["identity"]["module_sha256"]
    assert [len(record["actual"]["entries"]) for record in records] == [0, 0, 0, 1]
    assert result["killed_child_count"] == 4


def test_abort_duplicate_ack_and_retained_rows_use_real_shared_spool(tmp_path: Path) -> None:
    result = matrix.run_indexeddb_case(
        committed_case(), tmp_path / "exercise", operation="exercise"
    )
    assert result["result"] == "PASS", result
    checkpoint = result["checkpoint"]
    assert checkpoint["aborted"] is True
    assert checkpoint["duplicate"] == checkpoint["first"]
    assert checkpoint["invalid_ack"] == "Error: E_SPOOL_ACK"
    assert checkpoint["pending"] == [checkpoint["second"]]
    assert len(result["actual"]["entries"]) == 2
    assert result["actual"]["states"][0]["next_sequence"] == "3"
    assert result["actual"]["states"][0]["ack_sequence"] == "1"


@pytest.mark.parametrize("mutation", ["delete-row", "corrupt-ack"])
def test_actual_durable_mutations_are_rejected(tmp_path: Path, mutation: str) -> None:
    with pytest.raises(ValueError, match="E_INDEXEDDB_STATE"):
        matrix.run_indexeddb_case(committed_case(), tmp_path / mutation, mutation=mutation)


@pytest.mark.parametrize(
    "field,value", [("indexeddb_spool_delta", 0), ("extension_ack", "WRONG_ACK")]
)
def test_wrong_parent_expected_is_rejected_after_actual_execution(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    entry = committed_case()
    entry["expected_post_restart_state"][field] = value
    with pytest.raises(ValueError, match="E_INDEXEDDB_(STATE|EXPECTED)"):
        matrix.run_indexeddb_case(entry, tmp_path / "wrong-expected")


@pytest.mark.parametrize("field", ["run_id", "case_id", "profile_id", "origin", "module_sha256"])
def test_fresh_execution_rejects_stale_or_substituted_identity(tmp_path: Path, field: str) -> None:
    record = matrix.run_indexeddb_case(committed_case(), tmp_path / field)
    assert record["result"] == "PASS", record
    actual = copy.deepcopy(record["actual"])
    actual[field] = "wrong-identity"
    (tmp_path / "mutated-observation.json").write_text(json.dumps(actual))
    with pytest.raises(ValueError, match="E_INDEXEDDB_IDENTITY:" + field):
        matrix.compare_indexeddb_state(actual, record["identity"], record["observations"], 1)


def test_missing_browser_is_blocked_without_a_node_success_route(tmp_path: Path) -> None:
    record = matrix.run_indexeddb_case(
        committed_case(), tmp_path / "missing", browser_binary=tmp_path / "no-browser"
    )
    assert record["result"] == "BLOCKED_ENVIRONMENT"
    assert record["attempted_real_browser"] is False


def test_post_launch_environment_block_has_complete_hold_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import verify_repair_evidence
    from tools.qualify_chrome_indexeddb import _EnvironmentBlocked

    browser = tmp_path / "chrome"
    browser.write_bytes(b"test browser")
    extension = tmp_path / "extension"
    extension.mkdir()
    process = SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(verify_repair_evidence, "capture_binding", lambda: {})
    monkeypatch.setattr(matrix, "_prepare_test_extension", lambda *_: (extension, "id", "hash"))
    monkeypatch.setattr(matrix, "_start_chrome", lambda *_: (process, "socket"))
    monkeypatch.setattr(matrix, "_process_executable", lambda _: browser)
    monkeypatch.setattr(matrix, "_canonical_browser_executable", lambda _: browser)
    monkeypatch.setattr(
        matrix,
        "_wait_for_probe",
        lambda _: (_ for _ in ()).throw(
            _EnvironmentBlocked("E_EXTENSION_TARGET_UNAVAILABLE", "test")
        ),
    )
    monkeypatch.setattr(matrix, "_kill_owned_process_group", lambda _: None)

    row = matrix.run_indexeddb_case(
        committed_case(), tmp_path / "post-launch", browser_binary=browser
    )
    assert row["result"] == row["status"] == "BLOCKED_ENVIRONMENT"
    assert row["executed"] is row["launch_attempted"] is False
    assert row["attempted_real_browser"] is True
    assert row["case_id"] == row["vector_id"]
    assert row["prerequisite"]["available"] is False
    aggregate = verify_repair_evidence.aggregate_repair_evidence([row["case_id"]], [row])
    assert aggregate["result"] == "HOLD"
    assert aggregate["errors"] == []


@pytest.mark.parametrize("mode", ["empty", "duplicate", "missing"])
def test_matrix_rejects_missing_or_duplicate_required_cases(tmp_path: Path, mode: str) -> None:
    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    selected = [entry for entry in registry["entries"] if entry["harness"] == "CHROME_INDEXEDDB"]
    registry["entries"] = (
        [] if mode == "empty" else selected[:-1] if mode == "missing" else [*selected, selected[0]]
    )
    target = tmp_path / "pack/docs/registries/crash-harness-registry.v1.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="E_INDEXEDDB_REQUIRED_CASES"):
        matrix.run_indexeddb_crash_matrix(tmp_path / "pack", tmp_path / "runs")
