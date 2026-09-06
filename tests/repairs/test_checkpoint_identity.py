"""A synchronization marker alone cannot qualify the real backend harness."""

import json
from pathlib import Path

import pytest

from tests.repairs.test_loopback_actual_crashes import entry, runner
from tests.repairs.test_restart_evidence_boundary import _checkpoint_child
from tests.repairs.test_shared_ingest_persistence import observation


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
        runner().run_backend_case(
            entry("SQL-07"),
            observation(),
            tmp_path / "runs",
            command_prefix=_checkpoint_child(tmp_path, wrong_field=wrong_field),
        )
    assert not list(tmp_path.rglob("actual-state.json"))


@pytest.mark.parametrize(
    "behavior,error", [("ready", "E_CRASH_BOUNDARY_MISSING"), ("fail", "E_CRASH_CHILD_FAILED")]
)
def test_dummy_ready_child_or_early_exit_cannot_qualify(
    tmp_path: Path, behavior: str, error: str
) -> None:
    with pytest.raises(RuntimeError, match=error):
        runner().run_backend_case(
            entry("SQL-07"),
            observation(),
            tmp_path / "runs",
            command_prefix=_checkpoint_child(tmp_path, behavior=behavior),
        )


def test_stale_ready_file_does_not_qualify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.inspect_restart_state as inspector

    monkeypatch.setattr(inspector, "CHECKPOINT_TIMEOUT_SECONDS", 0.1)
    (tmp_path / "checkpoint.json").write_text(json.dumps({"case_id": "SQL-07"}))
    with pytest.raises(RuntimeError, match="E_CRASH_CHECKPOINT_MISSING"):
        runner().run_backend_case(
            entry("SQL-07"),
            observation(),
            tmp_path / "runs",
            command_prefix=_checkpoint_child(tmp_path, behavior="missing"),
        )
