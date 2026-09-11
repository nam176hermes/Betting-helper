import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from moj_discovery.vendor import pack_root
from tools import gap_coherence_crash_child
from tools.run_gap_coherence_crash_matrix import (
    _validate_snapshot_ddl,
    run_gap_coherence_crash_matrix,
    verify_gap_mutation,
)
from tools.verify_repair_evidence import aggregate_repair_evidence

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)
IDS = [
    row["vector_id"]
    for row in json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    if row["harness"] == "GAP_GENERATION_COHERENCE"
]


def test_mutation_launch_publishes_complete_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = tmp_path / "launch-ready.json"
    (tmp_path / "scenario.json").write_text(json.dumps({"run_id": "test", "delivery": {}}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "child",
            "--hold",
            "--ready",
            str(tmp_path / "checkpoint.json"),
            "--launch-ready",
            str(ready),
            "--run-id",
            "test",
            "--test-nonce",
            "publication",
        ],
    )
    monkeypatch.setattr(gap_coherence_crash_child, "_bootstrap", lambda *_: None)
    original_write = Path.write_text

    def interrupted_write(path: Path, data: str, **kwargs: object) -> int:
        original_write(path, "{")
        assert not ready.exists(), "parent can observe incomplete launch identity"
        return original_write(path, data)

    def release_child(_: float) -> None:
        identity = json.loads(ready.read_text())
        assert identity["run_id"] == "test" and identity["test_nonce"] == "publication"
        original_write(tmp_path / "launch-continue.json", "{}")

    def stop_after_launch(*_: object, **__: object) -> None:
        raise RuntimeError("TEST_STOP_AFTER_LAUNCH")

    monkeypatch.setattr(Path, "write_text", interrupted_write)
    monkeypatch.setattr(gap_coherence_crash_child, "sleep", release_child)
    monkeypatch.setattr(gap_coherence_crash_child, "validate_artifact", stop_after_launch)
    with pytest.raises(RuntimeError, match="TEST_STOP_AFTER_LAUNCH"):
        gap_coherence_crash_child.main()


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    return run_gap_coherence_crash_matrix(PACK, tmp_path_factory.mktemp("gap-owner"))


def test_closed_generation_and_epoch_never_reopen(report: dict[str, object]) -> None:
    result = report
    assert result["result"] == "PASS"
    assert len(result["executed_vector_ids"]) == 21
    assert result["mutation_survivors"] == 0
    assert "EPOCH-05-NEW-SHOCK-WHILE-PENDING" in result["executed_vector_ids"]
    assert all(
        row["before_restart"]["run_id"] == row["identity"]["run_id"] for row in result["records"]
    )
    assert aggregate_repair_evidence(IDS, result["records"])["result"] == "PASS"


def test_wrong_governed_oracle_is_rejected(report: dict[str, object]) -> None:
    row = copy.deepcopy(report["records"][0])
    row["expected"]["coherence_state"] = "WRONG"
    result = aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "FAIL"
    assert result["errors"][0]["error"] == "E_GAP_ORACLE"


def test_registered_mutations_and_commit_boundaries_are_executed(
    report: dict[str, object],
) -> None:
    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    wanted = {
        mutation
        for row in registry["entries"]
        if row["harness"] == "GAP_GENERATION_COHERENCE"
        for mutation in row["mutation_vector_ids"]
    }
    assert {row["mutation"] for row in report["mutation_results"]} == wanted
    assert len(report["mutation_results"]) == 42
    for mutation in report["mutation_results"]:
        assert mutation["detected"] is True
        assert mutation["process_observation"]["pid"] == mutation["pid"]
        assert Path(mutation["case_directory"]).is_dir()
        for artifact in mutation["artifacts"]:
            path = Path(artifact["path"])
            assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
    assert report["killed_child_count"] == 16
    for case_id in ("GAP-09-DURING-COMMIT", "EPOCH-04-DURING-NEW-EPOCH-OPEN-COMMIT"):
        row = next(item for item in report["records"] if item["case_id"] == case_id)
        boundary = json.loads(Path(row["boundary_artifact"]["path"]).read_text())
        assert boundary["commit_armed"] is True
        assert boundary["phase"] == "during_commit"
        assert boundary["operation"] in {"fsync", "fdatasync"}


def test_recovery_capacity_and_oracle_boundary(report: dict[str, object]) -> None:
    gap = report["records"][0]
    assert gap["before_restart"]["tables"]["coherence_controllers"][0]["controller_state"] == "OPEN"
    assert {
        str(row["generation"]): row["generation_state"]
        for row in gap["after_restart"]["tables"]["stream_generations"]
    } == {"0": "QUARANTINED_GAP", "1": "ACTIVE"}
    capacity = next(row for row in report["records"] if row["case_id"].startswith("CAPACITY"))
    assert capacity["before_restart"]["capacity"] == {
        "accepted": False,
        "incoming": 1,
        "normal_limit": 7,
        "terminal_reserve": 1,
        "used": 7,
        "unacknowledged_rows": 1,
        "evicted": 0,
        "status": "SAFETY_STOP",
    }
    by_id = {row["case_id"]: row for row in report["records"]}
    assert (
        by_id["CLOCK-02-AFTER-CLOSURE-COMMIT-BEFORE-SHOCK"]["before_restart"]["tables"][
            "coherence_controllers"
        ][0]["controller_state"]
        == "OPEN"
    )
    assert by_id["CLOCK-02-AFTER-CLOSURE-COMMIT-BEFORE-SHOCK"]["before_restart"]["tables"][
        "clock_mapping_closures"
    ]
    assert (
        by_id["CLOCK-02-AFTER-CLOSURE-COMMIT-BEFORE-SHOCK"]["after_restart"]["tables"][
            "coherence_controllers"
        ][0]["controller_state"]
        == "SHOCKED_CLOSED"
    )
    assert (
        by_id["EPOCH-03-AFTER-PENDING-WRITES-BEFORE-COMMIT"]["before_restart"]["tables"][
            "coherence_controllers"
        ][0]["controller_state"]
        == "WAITING_FOR_RESNAPSHOT"
    )
    assert (
        by_id["EPOCH-04-DURING-NEW-EPOCH-OPEN-COMMIT"]["after_restart"]["tables"][
            "coherence_controllers"
        ][0]["controller_state"]
        == "NEW_EPOCH_OPEN"
    )
    for row in report["records"]:
        scenario = json.loads(Path(row["scenario_artifact"]["path"]).read_text())
        assert scenario["run_id"] == row["identity"]["run_id"]
        assert not ({"expected", "expected_post_restart_state", "oracle"} & set(scenario))
        for reader in row["reader_runs"]:
            assert not (
                {"expected", "expected_post_restart_state", "oracle"}
                & set(json.loads(Path(reader["input"]["path"]).read_text()))
            )


@pytest.mark.parametrize(
    ("damage", "error"),
    [
        ("run", "E_GAP_IDENTITY"),
        ("case", "E_GAP_IDENTITY"),
        ("checkpoint", "E_GAP_IDENTITY"),
        ("wrong_error", "E_GAP_COMPARISON"),
        ("artifact", "E_GAP_ARTIFACT"),
    ],
)
def test_semantic_evidence_mutations_fail_closed(
    report: dict[str, object], damage: str, error: str
) -> None:
    row = copy.deepcopy(report["records"][0])
    if damage in {"run", "case", "checkpoint"}:
        row["identity"][damage + "_id"] = "stale"
    elif damage == "wrong_error":
        row["observed_error"] = "E_WRONG"
    else:
        row["actual_artifact"]["sha256"] = "0" * 64
    result = aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "FAIL"
    assert result["errors"][0]["error"] == error


def test_missing_and_duplicate_records_fail_closed(report: dict[str, object]) -> None:
    row = report["records"][0]
    assert aggregate_repair_evidence([row["case_id"]], [])["result"] == "FAIL"
    assert (
        aggregate_repair_evidence([row["case_id"]], [row, copy.deepcopy(row)])["result"] == "FAIL"
    )


def test_coherent_component_and_pid_forgery_is_rejected(report: dict[str, object]) -> None:
    row = copy.deepcopy(report["records"][0])
    row.pop("terminal_artifact")
    row["identity"].update(component="FORGED", pid=999999)
    row["checkpoint"] = copy.deepcopy(row["identity"])
    for name in ("checkpoint_artifact", "boundary_artifact"):
        value = json.loads(Path(row[name]["path"]).read_text())
        if name == "checkpoint_artifact":
            value = row["identity"]
        else:
            value["identity"] = row["identity"]
        path = Path(row["case_directory"]) / f"forged-{name}.json"
        path.write_text(json.dumps(value, sort_keys=True))
        row[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    result = aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "FAIL"


def test_semantic_view_must_be_reprojected_from_reader_facts(report: dict[str, object]) -> None:
    row = copy.deepcopy(report["records"][0])
    row["before_restart"]["tables"]["coherence_controllers"][0]["controller_state"] = (
        "SHOCKED_CLOSED"
    )
    reader = row["reader_runs"][0]
    output = json.loads(Path(reader["output"]["path"]).read_text())
    output["state"] = row["before_restart"]
    path = Path(row["case_directory"]) / "forged-semantic-reader.json"
    path.write_text(json.dumps(output, sort_keys=True))
    reader["output"] = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    result = aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == "FAIL"
    assert result["errors"][0]["error"] == "E_GAP_STATE_EVOLUTION"


def test_new_shock_persistently_closes_named_candidate(report: dict[str, object]) -> None:
    row = next(
        item for item in report["records"] if item["case_id"] == "EPOCH-05-NEW-SHOCK-WHILE-PENDING"
    )
    tables = row["before_restart"]["tables"]
    transition = next(
        item
        for item in tables["coherence_transitions"]
        if item["transition_reason"] == "NEW_SHOCK_CLOSED_CANDIDATE"
    )
    controller = tables["coherence_controllers"][0]
    successor = next(item for item in tables["coherence_epochs"] if item["generation"] == 2)
    assert transition["from_state"] == "NEW_EPOCH_PENDING"
    assert transition["to_state"] == "WAITING_FOR_RESNAPSHOT"
    assert transition["candidate_epoch_id"] == successor["predecessor_epoch_id"] == "epoch:1"
    assert controller["candidate_epoch_id"] is None
    assert controller["active_shock_observation_id"] == transition["shock_observation_id"]
    ddl = (PACK / "sql/discovery-store-v1.sql").read_text()
    schema = (PACK / "schemas/clock-coherence-records.schema.json").read_text()
    assert "NEW_SHOCK_CLOSED_CANDIDATE" in ddl
    assert "NEW_SHOCK_CLOSED_CANDIDATE" in schema


def test_after_restart_coherent_reader_rehash_is_rejected(report: dict[str, object]) -> None:
    row = copy.deepcopy(report["records"][0])
    row["after_restart"]["tables"]["coherence_controllers"][0]["controller_state"] = "OPEN"
    reader = row["reader_runs"][1]
    output = json.loads(Path(reader["output"]["path"]).read_text())
    output["state"] = row["after_restart"]
    path = Path(row["case_directory"]) / "forged-after-reader.json"
    path.write_text(json.dumps(output, sort_keys=True))
    reader["output"] = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    assert aggregate_repair_evidence([row["case_id"]], [row])["result"] == "FAIL"


def test_coherent_pid_pgid_forgery_is_rejected(report: dict[str, object]) -> None:
    row = copy.deepcopy(report["records"][0])
    row["identity"]["pid"] = 999999
    row["process_observation"].update(pid=999999, pgid=999999)
    row["termination"].update(target_pid=999999, target_pgid=999999)
    for name in ("checkpoint_artifact", "boundary_artifact", "terminal_artifact"):
        value = json.loads(Path(row[name]["path"]).read_text())
        if name == "checkpoint_artifact":
            value["pid"] = 999999
        elif name == "boundary_artifact":
            value["identity"]["pid"] = 999999
        else:
            value["identity"]["pid"] = 999999
            value["child_process"].update(pid=999999, pgid=999999)
            value["termination"].update(target_pid=999999, target_pgid=999999)
        path = Path(row["case_directory"]) / f"pid-forged-{name}.json"
        path.write_text(json.dumps(value, sort_keys=True))
        row[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert aggregate_repair_evidence([row["case_id"]], [row])["result"] == "FAIL"


def test_mutation_rows_are_recursively_bound_and_exact(report: dict[str, object]) -> None:
    binding = report["records"][0]["evidence_binding"]
    for mutation in report["mutation_results"]:
        assert mutation["evidence_binding"] == binding
        assert mutation["revision"] == binding["revision"]
        assert mutation["environment"] == binding["environment"]
        verify_gap_mutation(mutation, binding)
    input_mutation = next(
        item for item in report["mutation_results"] if item["mutation"].endswith("MUT-INPUT")
    )
    assert input_mutation["observed_error"] == "CONTENT_HASH_MISMATCH"
    assert input_mutation["mutated_input"] != input_mutation["original_input"]
    expected_mutation = next(
        item for item in report["mutation_results"] if item["mutation"].endswith("MUT-EXPECTED")
    )
    assert expected_mutation["mutated_expected"] != expected_mutation["governed_expected"]
    assert expected_mutation["observed_error"] == "E_GAP_STATE_MISMATCH"
    forged = copy.deepcopy(input_mutation)
    forged["exit"] = 9
    forged["command_exit"] = {"child": 9}
    forged["observed_error"] = "UNRELATED_CHILD_FAILURE"
    with pytest.raises(ValueError, match="E_GAP_MUTATION_INPUT"):
        verify_gap_mutation(forged, binding)


def test_retained_snapshot_verification_is_order_independent_and_database_portable(
    report: dict[str, object],
) -> None:
    row = copy.deepcopy(report["records"][0])
    state = copy.deepcopy(row["after_restart"])
    state["tables"] = {
        name: list(reversed(rows)) for name, rows in reversed(list(state["tables"].items()))
    }
    _validate_snapshot_ddl(state)

    database = Path(row["case_directory"]) / row["identity"]["run_id"] / "run.sqlite3"
    held = database.with_suffix(".sqlite3.held")
    database.rename(held)
    try:
        assert aggregate_repair_evidence([row["case_id"]], [row])["result"] == "PASS"
    finally:
        held.rename(database)


def test_recovery_validation_survives_json_round_trip(report: dict[str, object]) -> None:
    control = json.loads(json.dumps(report["records"][0]))
    assert aggregate_repair_evidence([control["case_id"]], [control])["result"] == "PASS"

    mutation = json.loads(json.dumps(report["mutation_results"][0]))
    verify_gap_mutation(mutation, control["evidence_binding"])


def test_database_absent_controller_history_forgery_is_rejected(
    report: dict[str, object],
) -> None:
    row = copy.deepcopy(report["records"][0])
    row["after_restart"]["tables"]["coherence_controllers"][0]["predecessor_epoch_id"] = "epoch:0"
    reader = row["reader_runs"][1]
    output = json.loads(Path(reader["output"]["path"]).read_text())
    output["state"] = row["after_restart"]
    forged = Path(row["case_directory"]) / "forged-controller-history-reader.json"
    forged.write_text(json.dumps(output, sort_keys=True))
    reader["output"] = {
        "path": str(forged),
        "sha256": hashlib.sha256(forged.read_bytes()).hexdigest(),
    }
    database = Path(row["case_directory"]) / row["identity"]["run_id"] / "run.sqlite3"
    held = database.with_suffix(".sqlite3.held")
    database.rename(held)
    try:
        result = aggregate_repair_evidence([row["case_id"]], [row])
        assert result["result"] == "FAIL"
        assert result["errors"][0]["error"] == "E_GAP_STATE_EVOLUTION"
    finally:
        held.rename(database)


def test_database_absent_same_state_generation_mutation_is_rejected(
    report: dict[str, object],
) -> None:
    row = copy.deepcopy(
        next(item for item in report["records"] if item["case_id"].startswith("LATE-01"))
    )
    for phase in ("before", "after"):
        state = row[f"{phase}_restart"]
        generation = next(
            item for item in state["tables"]["stream_generations"] if item["generation"] == 0
        )
        generation["closed_at_us"] += 777
        reader = next(item for item in row["reader_runs"] if item["phase"] == phase)
        output = json.loads(Path(reader["output"]["path"]).read_text())
        output["state"] = state
        forged = Path(row["case_directory"]) / f"forged-{phase}-generation-reader.json"
        forged.write_text(json.dumps(output, sort_keys=True))
        reader["output"] = {
            "path": str(forged),
            "sha256": hashlib.sha256(forged.read_bytes()).hexdigest(),
        }
    database = Path(row["case_directory"]) / row["identity"]["run_id"] / "run.sqlite3"
    held = database.with_suffix(".sqlite3.held")
    database.rename(held)
    try:
        result = aggregate_repair_evidence([row["case_id"]], [row])
        assert result["result"] == "FAIL"
        assert result["errors"][0]["error"] == "E_GAP_STATE_EVOLUTION"
    finally:
        held.rename(database)
