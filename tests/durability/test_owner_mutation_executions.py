"""Registered SQL/browser mutations must be fresh validated executions."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.run_indexeddb_crash_matrix import PACK, run_indexeddb_crash_matrix
from tools.run_loopback_ack_crash_matrix import run_loopback_ack_crash_matrix
from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix


@pytest.mark.parametrize(
    "harness,count", [("SQLITE_TRANSACTION", 14), ("CHROME_INDEXEDDB", 8), ("LOOPBACK_ACK", 14)]
)
def test_registered_mutations_are_executed(tmp_path: Path, harness: str, count: int) -> None:
    owners: dict[str, Callable[..., dict[str, Any]]] = {
        "SQLITE_TRANSACTION": run_sqlite_crash_matrix,
        "CHROME_INDEXEDDB": run_indexeddb_crash_matrix,
        "LOOPBACK_ACK": run_loopback_ack_crash_matrix,
    }
    report = owners[harness](PACK, tmp_path)
    mutations = report.get("mutation_results", [])
    assert len(mutations) == count
    assert all(mutation["detected"] is True for mutation in mutations)
    from tools.verify_repair_evidence import capture_binding, verify_owner_mutation

    binding = capture_binding()
    case_directories = [mutation["execution"]["case_directory"] for mutation in mutations]
    assert len(set(case_directories)) == count
    assert len({mutation["execution"]["identity"]["run_id"] for mutation in mutations}) == count
    for mutation in mutations:
        verify_owner_mutation(harness, mutation, binding)
        if mutation["kind"] == "INPUT":
            execution = mutation["execution"]
            if harness == "SQLITE_TRANSACTION":
                assert execution["before"] == execution["after"]
                assert execution["observed_error"] == "CONTENT_HASH_MISMATCH"
            else:
                assert execution["backend_before"] == execution["backend_after"]
                assert execution["actual"]["entries"] == execution["browser_after"]["entries"] == []
                assert all(
                    "observed" in reader and "raw" in reader for reader in execution["reader_runs"]
                )
                assert execution["observed_error"] == "E_SPOOL_OBSERVATION_BINDING"
    missing_terminal = copy.deepcopy(mutations[0])
    missing_terminal.pop("terminal_artifact")
    with pytest.raises(ValueError, match="E_OWNER_MUTATION_TERMINAL"):
        verify_owner_mutation(harness, missing_terminal, binding)
    for damage, error in (
        ("id", "E_OWNER_MUTATION_BINDING"),
        ("run", "E_OWNER_MUTATION_IDENTITY"),
        ("oracle", "E_OWNER_MUTATION_ORACLE"),
        ("exit", "E_OWNER_MUTATION_PROCESS"),
        ("detected", "E_OWNER_MUTATION_BINDING"),
    ):
        altered = copy.deepcopy(mutations[0])
        if damage == "id":
            altered["mutation"] += "-wrong"
        elif damage == "run":
            altered["execution"]["identity"]["run_id"] = altered["control"]["identity"]["run_id"]
        elif damage == "oracle":
            altered["oracle"] = {"retained_rows": 0}
        elif damage == "exit":
            altered["process"]["exit"] = 1
        else:
            altered["detected"] = False
        with pytest.raises(ValueError, match=error):
            verify_owner_mutation(harness, altered, binding)
