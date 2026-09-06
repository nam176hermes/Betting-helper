"""A synchronization marker alone cannot qualify the real backend harness."""

import json
import sys
import textwrap
from pathlib import Path

import pytest

from tests.repairs.test_loopback_actual_crashes import entry, runner
from tests.repairs.test_restart_evidence_boundary import _checkpoint_child
from tests.repairs.test_shared_ingest_persistence import observation
from tools.inspect_restart_state import execute_crash_matrix
from tools.restart_state_reader import read_restart_state


@pytest.mark.parametrize("inline", [True, False])
def test_forged_transaction_and_tcp_witness_cannot_substitute_child(
    tmp_path: Path,
    inline: bool,
) -> None:
    source = textwrap.dedent("""
        import argparse, json, os, signal
        from pathlib import Path
        from contextlib import closing
        from tools.loopback_ack_crash_child import provision
        from moj_discovery.store import read_journal
        parser = argparse.ArgumentParser()
        for flag in ("vector-id", "ready", "run-id", "case-id", "checkpoint-id",
                     "component", "ordinal", "test-nonce"):
            parser.add_argument("--" + flag)
        parser.add_argument("--hold", action="store_true")
        args = parser.parse_args()
        ready = Path(args.ready)
        scenario = json.loads((ready.parent / "scenario.json").read_text())
        store = provision(ready.parent, scenario["observation"])
        with closing(store.connect()) as connection:
            tables = read_journal(connection)
        tables["raw_commits"] = [{}]  # Entirely invented uncommitted INSERT.
        identity = {"run_id": args.run_id, "case_id": args.case_id,
                    "checkpoint_id": args.checkpoint_id, "component": args.component,
                    "ordinal": int(args.ordinal), "test_nonce": args.test_nonce,
                    "pid": os.getpid()}
        witness = {"identity": identity, "phase": scenario["phase"],
                   "in_transaction": True, "tables": tables,
                   "received_observation_hash": scenario["delivery"]["content_hash"],
                   "transport_address": ["127.0.0.1", 54321],
                   "wire_ack": None, "ingest_result": None}
        (ready.parent / "boundary.json").write_text(json.dumps(witness))
        ready.write_text(json.dumps(identity))
        while True:
            signal.pause()
    """)
    if inline:
        command = [sys.executable, "-c", source]
    else:
        script = tmp_path / "forged-child.py"
        root = Path(__file__).resolve().parents[2]
        script.write_text(
            "import sys\nsys.path[:0] = " + repr([str(root), str(root / "src")]) + "\n" + source
        )
        command = [sys.executable, str(script)]
    with pytest.raises(ValueError, match="^E_CRASH_CHILD_PROVENANCE$"):
        runner().run_backend_case(
            entry("SQL-01"),
            observation(),
            tmp_path / "runs",
            command_prefix=command,
        )
    assert not (tmp_path / "runs").exists()


def test_unknown_checkpoint_name_is_not_a_real_boundary(tmp_path: Path) -> None:
    case = entry("SQL-07")
    case["crash_checkpoint"] = "made_up_checkpoint"
    with pytest.raises(ValueError, match="E_CRASH_REGISTERED_BOUNDARY_MISMATCH"):
        runner().run_backend_case(case, observation(), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "wrong_field",
    ["run_id", "case_id", "checkpoint_id", "component", "pid", "ordinal", "test_nonce"],
)
def test_wrong_marker_never_reaches_actual_inspection(tmp_path: Path, wrong_field: str) -> None:
    with pytest.raises(RuntimeError, match="E_CRASH_CHECKPOINT_MISMATCH"):
        execute_crash_matrix(
            [entry("SQL-07")],
            _checkpoint_child(tmp_path, wrong_field=wrong_field),
            tmp_path / "runs",
            state_reader=read_restart_state,
        )
    assert not list(tmp_path.rglob("actual-state.json"))


@pytest.mark.parametrize(
    "behavior,error", [("ready", "E_ACTUAL_STATE_READER_FAILED"), ("fail", "E_CRASH_CHILD_FAILED")]
)
def test_dummy_ready_child_or_early_exit_cannot_qualify(
    tmp_path: Path, behavior: str, error: str
) -> None:
    with pytest.raises(RuntimeError, match=error):
        execute_crash_matrix(
            [entry("SQL-07")],
            _checkpoint_child(tmp_path, behavior=behavior),
            tmp_path / "runs",
            state_reader=read_restart_state,
        )


def test_stale_ready_file_does_not_qualify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.inspect_restart_state as inspector

    monkeypatch.setattr(inspector, "CHECKPOINT_TIMEOUT_SECONDS", 0.1)
    (tmp_path / "checkpoint.json").write_text(json.dumps({"case_id": "SQL-07"}))
    with pytest.raises(RuntimeError, match="E_CRASH_CHECKPOINT_MISSING"):
        execute_crash_matrix(
            [entry("SQL-07")],
            _checkpoint_child(tmp_path, behavior="missing"),
            tmp_path / "runs",
            state_reader=read_restart_state,
        )
