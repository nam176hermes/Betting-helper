import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.store import verified_ddl
from moj_discovery.vendor import pack_root
from tools.destruction_support import consumption, content_hash, insert_consumption, validate_plan
from tools.run_destruction_crash_matrix import run_destruction_crash_matrix
from tools.verify_repair_evidence import aggregate_repair_evidence

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from tools.run_destruction_crash_matrix import run_destruction_case

    entry = next(
        entry
        for entry in json.loads(
            (PACK / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if entry["vector_id"] == "DESTROY-01-BEFORE-AUTHORITY"
    )
    return run_destruction_case(entry, tmp_path_factory.mktemp("destruction-negative") / "case")


def _plan(record: dict[str, Any]) -> dict[str, Any]:
    return dict(json.loads(Path(record["inputs"]["precommit"]["path"]).read_text()))


def test_declared_equals_executed_and_mutation_survivors_zero(tmp_path: Path) -> None:
    result = run_destruction_crash_matrix(PACK, tmp_path)
    assert result["result"] == "PASS"
    assert result["killed_child_count"] == 7
    assert result["declared_vector_ids"] == result["executed_vector_ids"]
    assert len(result["records"]) == 7
    assert result["mutation_survivors"] == 0
    assert (
        aggregate_repair_evidence(result["declared_vector_ids"], result["records"])["result"]
        == "PASS"
    )
    for row in result["records"]:
        assert row["execution_kind"] == "DISPOSABLE_DESTRUCTION_PROCESS_CRASH"
        assert row["before"]["browser"]["present"] is True
        assert row["before"]["backend"]["present"] is True
        assert row["reader_runs"][0]["pid"] != row["reader_runs"][-1]["pid"]
        assert len(row["mutations"]) == 2
        assert all(mutation["detected"] is True for mutation in row["mutations"])
        for kind in ("intent", "proof"):
            if row["after"]["external"][kind] is not None:
                assert row["artifacts"]["external-" + kind]["sha256"]
        for mutation in row["mutations"]:
            assert mutation["execution"]["case_directory"] != row["case_directory"]
            assert mutation["execution"]["identity"]["run_id"] != row["identity"]["run_id"]
            assert len(mutation["execution"]["reader_runs"]) == 3


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("run_id", "00000000-0000-4000-8000-000000000099", "E_DESTRUCTION_AUTHORITY_RUN"),
        ("pre_delete_inventory_hash", "0" * 64, "E_DESTRUCTION_INVENTORY_HASH"),
        ("accepted_sanitized_export_manifest_hash", "0" * 64, "E_DESTRUCTION_AUTHORITY_HASH"),
        (
            "destruction_authorization_id",
            "00000000-0000-4000-8000-000000000099",
            "E_DESTRUCTION_INTENT_PRECOMMIT",
        ),
        ("created_at", "2031-01-01T00:00:00.000000Z", "E_DESTRUCTION_INTENT_PRECOMMIT"),
        ("human_invocation", False, "E_DESTRUCTION_HUMAN_INVOCATION"),
        (
            "external_intent_path",
            ".local/destruction/wrong.intent.json",
            "E_DESTRUCTION_INTENT_PRECOMMIT",
        ),
    ],
)
def test_altered_intent_is_not_authority(
    record: dict[str, Any], field: str, value: Any, error: str
) -> None:
    plan = _plan(record)
    plan["intent"][field] = value
    with pytest.raises(ValueError, match=error):
        validate_plan(plan)


def test_invalid_signature_is_rejected_even_with_rehashed_intent(record: dict[str, Any]) -> None:
    plan = _plan(record)
    plan["intent"]["destruction_gate_receipt"]["signature"] = "A" * 86
    plan["intent"]["content_hash"] = content_hash(plan["intent"])
    with pytest.raises(ValueError, match="E_DESTRUCTION_AUTHORITY_SIGNATURE"):
        validate_plan(plan)


def test_pending_run_requires_actual_committed_consumption() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(verified_ddl())
        connection.execute(
            "INSERT INTO run_meta VALUES (?,1,'CLOSED','test-only:offline',?,?,0,1)",
            ("00000000-0000-4000-8000-000000000099", "a" * 64, "b" * 64),
        )
        with pytest.raises(sqlite3.IntegrityError, match="E_DESTRUCTION_AUTHORITY_REQUIRED"):
            connection.execute("UPDATE run_meta SET run_status='DESTRUCTION_PENDING'")
        assert connection.execute("SELECT run_status FROM run_meta").fetchone()[0] == "CLOSED"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        (
            "receipt_bound_run_id",
            "00000000-0000-4000-8000-000000000099",
            "E_DESTRUCTION_AUTHORITY_RUN",
        ),
        ("receipt_bound_sanitized_export_manifest_hash", "0" * 64, "E_DESTRUCTION_AUTHORITY_HASH"),
        ("receipt_record_type", "BodyClassApproval", "E_DESTRUCTION_AUTHORITY_TYPE"),
        ("receipt_scope", "IMPLEMENTATION_GATE_ONLY", "E_DESTRUCTION_AUTHORITY_SCOPE"),
        ("staged_pre_delete_inventory_hash", None, "E_DESTRUCTION_INTENT_PRECOMMIT"),
        ("replay", None, "E_DESTRUCTION_AUTHORITY_REPLAY"),
    ],
)
def test_actual_sqlite_consumption_rejects_wrong_binding(
    record: dict[str, Any], field: str, value: Any, error: str
) -> None:
    plan = _plan(record)
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(verified_ddl())
        connection.execute(
            "INSERT INTO run_meta VALUES (?,1,'CLOSED','test-only:offline',?,?,0,1)",
            (plan["run_id"], "a" * 64, "b" * 64),
        )
        values = consumption(plan)
        if field == "replay":
            insert_consumption(connection, values)
            connection.commit()
        else:
            values[field] = value
        with pytest.raises(sqlite3.IntegrityError, match=error):
            insert_consumption(connection, values)
        assert len(
            connection.execute("SELECT * FROM authorization_consumptions").fetchall()
        ) == int(field == "replay")


@pytest.mark.parametrize(
    "damage",
    [
        "revision",
        "run",
        "oracle",
        "worker",
        "reader",
        "pid",
        "exit",
        "missing",
        "duplicate",
        "mutation-run",
        "mutation-error",
    ],
)
def test_evidence_cannot_hide_wrong_run_or_unexecuted_mutation(
    record: dict[str, Any], damage: str
) -> None:
    row = copy.deepcopy(record)
    rows = [row]
    if damage == "revision":
        row["revision"] = "0" * 40
    elif damage == "run":
        row["identity"]["run_id"] = "00000000-0000-4000-8000-000000000099"
    elif damage == "oracle":
        row["expected"]["indexeddb_store"] = "DELETED"
    elif damage == "worker":
        row["after"]["browser"]["worker_id"] = row["before"]["browser"]["worker_id"]
    elif damage == "reader":
        row["reader_runs"] = row["reader_runs"][:1]
    elif damage == "pid":
        row["processes"][2]["pid"] += 1
    elif damage == "exit":
        row["processes"][2]["exit_code"] = 1
    elif damage == "missing":
        rows = []
    elif damage == "duplicate":
        rows.append(row)
    elif damage == "mutation-run":
        row["mutations"][0]["execution"]["identity"]["run_id"] = row["identity"]["run_id"]
    else:
        row["mutations"][1]["execution"]["observed_error"] = "UNRELATED_CHILD_FAILURE"
    assert aggregate_repair_evidence([record["case_id"]], rows)["result"] == "FAIL"


def test_existing_proof_must_be_validated_by_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import run_destruction_crash_matrix as runner

    original = runner._process

    def corrupt_then_run(case: Path, mode: str, input_path: Path, name: str, **kwargs: Any) -> Any:
        if mode == "recover":
            proof_path = next((case / ".local/destruction").glob("*.deletion-proof.json"))
            proof = json.loads(proof_path.read_text())
            proof["content_hash"] = "0" * 64
            proof_path.write_text(json.dumps(proof))
        return original(case, mode, input_path, name, **kwargs)

    monkeypatch.setattr(runner, "_process", corrupt_then_run)
    entry = next(
        entry
        for entry in json.loads(
            (PACK / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if entry["vector_id"] == "DESTROY-06-AFTER-PROOF"
    )
    with pytest.raises(ValueError, match="E_DESTRUCTION_CHILD_FAILED:.*E_DESTRUCTION_PROOF"):
        runner.run_destruction_case(entry, tmp_path / "case", mutation="EXPECTED")


def test_rehashed_reader_input_must_match_actual_run(record: dict[str, Any]) -> None:
    from tools.verify_destruction_evidence import verify_destruction
    from tools.verify_repair_evidence import capture_binding

    row = copy.deepcopy(record)
    path = Path(row["inputs"]["owner-input"]["path"])
    original = path.read_bytes()
    value = json.loads(original)
    value["identity"]["run_id"] = "00000000-0000-4000-8000-000000000099"
    altered = json.dumps(value).encode()

    def rehash(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("path") == str(path):
                item["sha256"] = hashlib.sha256(altered).hexdigest()
            for child in item.values():
                rehash(child)
        elif isinstance(item, list):
            for child in item:
                rehash(child)

    try:
        path.write_bytes(altered)
        rehash(row)
        with pytest.raises(ValueError, match="E_DESTRUCTION_READER_INPUT"):
            verify_destruction(row, capture_binding(), terminal=False)
    finally:
        path.write_bytes(original)
