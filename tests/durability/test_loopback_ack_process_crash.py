"""Real browser/SQLite ACK checkpoints and fail-closed terminal records."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.run_loopback_ack_crash_matrix import run_loopback_ack_crash_matrix
from tools.verify_repair_evidence import _contains_expected, aggregate_repair_evidence

ROOT = Path(__file__).parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return run_loopback_ack_crash_matrix(PACK, tmp_path_factory.mktemp("browser-ack"))


def test_ack_never_crosses_uncommitted_or_gapped_position(evidence: dict[str, Any]) -> None:
    result = evidence
    assert result["result"] == "PASS", result
    assert result["killed_child_count"] == 6  # ACK-06 registers NONE.
    assert result["executed_vector_ids"][0] == "SEND-01-AFTER-SEND-BEFORE-BACKEND-BEGIN"
    assert result["executed_vector_ids"][-1] == "ACK-06-DUPLICATE-IDENTICAL"
    aggregate = aggregate_repair_evidence(result["executed_vector_ids"], result["records"])
    assert aggregate["result"] == "PASS", aggregate
    for row in result["records"]:
        assert row["qualification_scope"] == "BROWSER_LOOPBACK_ACK"
        assert row["actual"]["worker_id"] != row["worker_id"]
        assert row["actual"]["origin"].startswith("chrome-extension://")
        assert len(row["backend_after"]["tables"]["ack_cursors"]) == 1
        assert row["browser_after"]["states"][0]["ack_sequence"] == "1"
        assert len(row["browser_after"]["entries"]) == 1
        assert row["backend_processes"][0]["pid"] != row["backend_processes"][1]["pid"]
        for item in row["inputs"].values():
            assert not _contains_expected(json.loads(Path(item["path"]).read_text()))


@pytest.mark.parametrize(
    "mutation",
    [
        "oracle",
        "run",
        "checkpoint",
        "revision",
        "error",
        "missing",
        "duplicate",
        "browser-row",
        "sql-row",
        "reader-exit",
        "child-exit",
        "worker",
        "termination",
        "reader-duplicate",
        "reader-argv",
        "terminal",
        "input-oracle",
    ],
)
def test_terminal_evidence_rejects_mutations(evidence: dict[str, Any], mutation: str) -> None:
    rows = [copy.deepcopy(evidence["records"][0])]
    required_ids = [rows[0]["case_id"]]
    assert rows[0]["status"] == "PASS"
    row = rows[0]
    if mutation == "oracle":
        row["expected"]["extension_ack"] = "GEN0_Q1_H1"
    elif mutation in {"run", "checkpoint"}:
        row["identity"][mutation + "_id"] = "wrong"
    elif mutation == "revision":
        row["evidence_binding"]["revision"] = "0" * 40
    elif mutation == "error":
        row["observed_error"] = "wrong"
    elif mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(row))
    elif mutation == "browser-row":
        row["actual"]["entries"].clear()
    elif mutation == "sql-row":
        row["backend_before"]["tables"]["run_meta"][0]["run_status"] = "INVALID"
    elif mutation == "reader-exit":
        row["reader_runs"][0]["exit"] = 1
    elif mutation == "child-exit":
        row["backend_processes"][0]["exit"] = 0
    elif mutation == "worker":
        row["actual"]["worker_id"] = row["worker_id"]
    elif mutation == "termination":
        row["termination"]["method"] = "GRACEFUL"
    elif mutation == "reader-duplicate":
        row["reader_runs"][1] = copy.deepcopy(row["reader_runs"][0])
    elif mutation == "reader-argv":
        row["reader_runs"][0]["argv"][1] = "-E"
    elif mutation == "terminal":
        row["terminal_artifact"]["sha256"] = "0" * 64
    elif mutation == "input-oracle":
        row["inputs"]["reader-before"]["sha256"] = "0" * 64
    result = aggregate_repair_evidence(required_ids, rows)
    assert result["result"] == "FAIL", (mutation, result)


def test_shared_confirmation_is_bound_idempotent_and_durable(tmp_path: Path) -> None:
    from moj_discovery.ingest import Ingestor
    from tools.loopback_ack_crash_child import provision
    from tools.restart_state_reader import read_restart_state
    from tools.run_indexeddb_crash_matrix import _observations

    raw = _observations("11111111-1111-4111-8111-111111111111")[0]
    store = provision(tmp_path, raw)
    ingest = Ingestor(store)
    with pytest.raises(ValueError, match="E_ACK_CONFIRMATION_BINDING"):
        ingest.confirm_ack({"ack_outbox_id": "missing"})
    ack = ingest.apply(raw)
    for field in ("cursor_hash", "run_id", "highest_contiguous_sequence"):
        wrong = {**ack, field: "wrong"}
        with pytest.raises(ValueError, match="E_ACK_CONFIRMATION_BINDING"):
            ingest.confirm_ack(wrong)
    confirmation = ingest.confirm_ack(ack)
    assert ingest.confirm_ack(ack) == confirmation
    actual = read_restart_state(store.db_path.parent)
    assert actual["tables"]["ack_cursors"] == [confirmation]
    assert actual["tables"]["ack_outbox"] == [ack]


@pytest.mark.parametrize("mutation", ["sql-ddl", "browser-ack", "wire", "oracle"])
def test_coherently_rehashed_evidence_still_checks_semantics(
    evidence: dict[str, Any],
    mutation: str,
) -> None:
    row = copy.deepcopy(evidence["records"][1])
    preserved: dict[Path, bytes] = {}

    def rewrite(descriptor: dict[str, Any], value: Any) -> None:
        path = Path(descriptor["path"])
        preserved.setdefault(path, path.read_bytes())
        content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(content)

        def rehash(item: Any) -> None:
            if isinstance(item, dict):
                if item.get("path") == str(path):
                    item["sha256"] = hashlib.sha256(content).hexdigest()
                for value in item.values():
                    rehash(value)
            elif isinstance(item, list):
                for value in item:
                    rehash(value)

        rehash(row)

    try:
        if mutation == "sql-ddl":
            row["backend_before"]["tables"]["run_meta"][0]["run_status"] = "INVALID"
            rewrite(row["artifacts"]["backend-before"], row["backend_before"])
            reader = json.loads(Path(row["reader_runs"][0]["artifact"]["path"]).read_text())
            reader["state"] = row["backend_before"]
            rewrite(row["reader_runs"][0]["artifact"], reader)
        elif mutation == "browser-ack":
            row["actual"]["states"][0]["ack_sequence"] = "1"
            rewrite(row["artifacts"]["browser-before"], row["actual"])
        elif mutation == "wire":
            descriptor = next(iter(row["wire_artifacts"].values()))
            wire = json.loads(Path(descriptor["path"]).read_text())
            wire["request"]["token"] = "0" * 64
            rewrite(descriptor, wire)
        else:
            row["expected"]["recovery_action"] = "WRONG"
            rewrite(row["artifacts"]["expected"], row["expected"])
        rewrite(
            row["terminal_artifact"],
            {key: value for key, value in row.items() if key != "terminal_artifact"},
        )
        result = aggregate_repair_evidence([row["case_id"]], [row])
        assert result["result"] == "FAIL", (mutation, result)
    finally:
        for path, data in preserved.items():
            path.write_bytes(data)


@pytest.mark.parametrize("component", ["child", "reader"])
def test_actual_subprocess_failure_cannot_qualify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component: str,
) -> None:
    from tools import run_loopback_ack_crash_matrix as runner

    if component == "child":
        original = subprocess.Popen

        def bad_child(command: list[str], **kwargs: Any) -> Any:
            if "--browser-server" in command:
                command = [sys.executable, "-I", "-c", "raise SystemExit(7)"]
            return original(command, **kwargs)  # noqa: S603 -- owned failure fixture

        monkeypatch.setattr(subprocess, "Popen", bad_child)
        with pytest.raises(RuntimeError, match="E_ACK_SERVER_FAILED"):
            runner.run_loopback_ack_crash_matrix(PACK, tmp_path)
    else:
        original_run = subprocess.run

        def bad_reader(command: list[str], **kwargs: Any) -> Any:
            if any(str(value).endswith("restart_state_reader.py") for value in command):
                command = [sys.executable, "-I", "-c", "raise SystemExit(9)"]
            return original_run(command, **kwargs)  # noqa: S603 -- owned failure fixture

        monkeypatch.setattr(subprocess, "run", bad_reader)
        with pytest.raises(subprocess.CalledProcessError):
            runner.run_loopback_ack_crash_matrix(PACK, tmp_path)
        assert list(tmp_path.rglob("backend-checkpoint.json"))


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "oracle"])
def test_exact_registry_required(tmp_path: Path, mutation: str) -> None:
    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    rows = [row for row in registry["entries"] if row["harness"] == "LOOPBACK_ACK"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(rows[0])
    else:
        rows[0]["expected_post_restart_state"]["extension_ack"] = "WRONG"
    target = tmp_path / "pack/docs/registries/crash-harness-registry.v1.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"entries": rows}))
    with pytest.raises(ValueError, match="E_ACK_REQUIRED_CASES"):
        run_loopback_ack_crash_matrix(tmp_path / "pack", tmp_path / "cases")
