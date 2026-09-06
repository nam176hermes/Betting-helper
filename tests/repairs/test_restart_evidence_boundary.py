import json
import os
import sqlite3
import sys
import textwrap
from collections.abc import Mapping
from pathlib import Path
from subprocess import Popen
from types import SimpleNamespace

import pytest

import tools.inspect_restart_state as restart_inspector
from tools.inspect_restart_state import execute_crash_matrix
from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"


def _case(expected: Mapping[str, object] | None = None) -> dict[str, object]:
    return {
        "vector_id": "repair-case",
        "harness": "TEST_COMPONENT",
        "crash_checkpoint": "after_commit",
        "expected_post_restart_state": dict(expected or {"committed_rows": 1}),
    }


def _checkpoint_child(
    tmp_path: Path, *, behavior: str = "ready", wrong_field: str | None = None
) -> list[str]:
    script = tmp_path / f"checkpoint-child-{behavior}-{wrong_field or 'valid'}.py"
    script.write_text(
        textwrap.dedent(
            """
            import argparse
            import json
            import os
            import sqlite3
            import sys
            import time
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument("--vector-id", required=True)
            parser.add_argument("--ready", required=True, type=Path)
            parser.add_argument("--run-id", required=True)
            parser.add_argument("--case-id", required=True)
            parser.add_argument("--checkpoint-id", required=True)
            parser.add_argument("--component", required=True)
            parser.add_argument("--ordinal", required=True, type=int)
            parser.add_argument("--test-nonce", required=True)
            parser.add_argument("--hold", action="store_true")
            args = parser.parse_args()
            if __BEHAVIOR__ == "fail":
                raise SystemExit(7)
            database = sqlite3.connect(args.ready.with_name("inspector-unit.sqlite"))
            database.execute(
                "CREATE TABLE actual_state (committed_rows INTEGER, marker TEXT)"
            )
            database.execute("INSERT INTO actual_state VALUES (17, 'actual-only')")
            database.commit()
            database.close()
            record = {
                "run_id": args.run_id,
                "case_id": args.case_id,
                "checkpoint_id": args.checkpoint_id,
                "component": args.component,
                "pid": os.getpid(),
                "ordinal": args.ordinal,
                "test_nonce": args.test_nonce,
            }
            wrong_field = __WRONG_FIELD__
            if wrong_field is not None:
                record[wrong_field] = "wrong"
            args.ready.with_name("child-argv.json").write_text(json.dumps(sys.argv[1:]))
            if __BEHAVIOR__ == "ready":
                args.ready.write_text(json.dumps(record))
            if __BEHAVIOR__ == "ready_then_fail":
                args.ready.write_text(json.dumps(record))
                raise SystemExit(7)
            if args.hold:
                while True:
                    time.sleep(1)
            """
        )
        .replace("__BEHAVIOR__", repr(behavior))
        .replace("__WRONG_FIELD__", repr(wrong_field))
    )
    return [sys.executable, str(script)]


def test_legacy_ready_only_runner_must_not_pass_without_actual_reader(tmp_path: Path) -> None:
    case: dict[str, object] = {
        "vector_id": "repair-missing-reader",
        "expected_post_restart_state": {
            "committed_rows": 999999,
            "ack_sequence": 999999,
        },
    }

    with pytest.raises(ValueError, match="E_ACTUAL_STATE_READER_REQUIRED"):
        execute_crash_matrix(
            [case],
            [sys.executable, str(ROOT / "tools/loopback_ack_crash_child.py")],
            tmp_path,
        )


def test_sqlite_owner_uses_actual_reader_for_all_registered_cases(tmp_path: Path) -> None:
    workspace = tmp_path / "sqlite-runs"
    result = run_sqlite_crash_matrix(PACK, workspace)
    assert result["result"] == "PASS"
    assert len(result["records"]) == result["killed_child_count"] == 7
    assert all(row["reader_provenance"]["runs"] for row in result["records"])


def test_non_posix_termination_is_blocked_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "unsupported-platform-runs"
    monkeypatch.setattr(restart_inspector, "os", SimpleNamespace(name="nt"))

    with pytest.raises(RuntimeError, match="E_CRASH_TERMINATION_UNSUPPORTED:nt"):
        execute_crash_matrix(
            [_case()],
            ["/missing-bh-r01-child"],
            workspace,
            state_reader=lambda _case_dir: {"committed_rows": 1},
        )

    assert not workspace.exists()


def test_actual_zero_state_cannot_pass_expected_999999(tmp_path: Path) -> None:
    expected = {"committed_rows": 999999, "ack_sequence": 999999}

    with pytest.raises(ValueError, match="E_RESTART_STATE_MISMATCH"):
        execute_crash_matrix(
            [_case(expected)],
            _checkpoint_child(tmp_path),
            tmp_path / "runs",
            state_reader=lambda _case_dir: {"committed_rows": 0, "ack_sequence": 0},
        )


def test_inspector_unit_only_sqlite_state_is_independent_of_expected(
    tmp_path: Path,
) -> None:
    reader_paths: list[Path] = []
    expected = {"committed_rows": 17, "marker": "actual-only"}

    def read_actual(case_dir: Path) -> dict[str, object]:
        reader_paths.append(case_dir)
        checkpoint = json.loads((case_dir / "checkpoint.json").read_text())
        if os.name == "posix":
            with pytest.raises(ChildProcessError):
                os.waitpid(checkpoint["pid"], os.WNOHANG)
        database = sqlite3.connect(
            f"file:{case_dir / 'inspector-unit.sqlite'}?mode=ro", uri=True
        )
        try:
            row = database.execute(
                "SELECT committed_rows, marker FROM actual_state"
            ).fetchone()
        finally:
            database.close()
        assert row is not None
        return {"committed_rows": row[0], "marker": row[1]}

    result = execute_crash_matrix(
        [_case(expected)],
        _checkpoint_child(tmp_path),
        tmp_path / "runs",
        state_reader=read_actual,
    )

    assert result["result"] == "PASS"
    assert len(reader_paths) == 1
    child_arguments = json.loads((reader_paths[0] / "child-argv.json").read_text())
    serialized_arguments = json.dumps(child_arguments, sort_keys=True)
    assert "--expected-post-restart-state" not in child_arguments
    assert json.dumps(expected, sort_keys=True) not in serialized_arguments
    assert "actual-only" not in serialized_arguments


@pytest.mark.parametrize("wrong_field", sorted(restart_inspector.CHECKPOINT_FIELDS))
def test_wrong_checkpoint_identity_is_rejected(
    tmp_path: Path, wrong_field: str
) -> None:
    reader_calls: list[Path] = []

    def read_actual(case_dir: Path) -> dict[str, object]:
        reader_calls.append(case_dir)
        return {"committed_rows": 1}

    with pytest.raises(RuntimeError, match="E_CRASH_CHECKPOINT_MISMATCH:repair-case"):
        execute_crash_matrix(
            [_case()],
            _checkpoint_child(tmp_path, wrong_field=wrong_field),
            tmp_path / "runs",
            state_reader=read_actual,
        )
    assert reader_calls == []


def test_stale_marker_and_missing_fresh_checkpoint_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "runs"
    workspace.mkdir()
    (workspace / "repair-case.ready.json").write_text('{"case_id":"repair-case"}')
    monkeypatch.setattr(restart_inspector, "CHECKPOINT_TIMEOUT_SECONDS", 0.1, raising=False)

    with pytest.raises(RuntimeError, match="E_CRASH_CHECKPOINT_MISSING:repair-case"):
        execute_crash_matrix(
            [_case()],
            _checkpoint_child(tmp_path, behavior="missing"),
            workspace,
            state_reader=lambda _case_dir: {"committed_rows": 1},
        )


@pytest.mark.parametrize("failure", [FileNotFoundError("missing"), OSError("reader failed")])
def test_reader_failure_or_missing_storage_cannot_pass(
    tmp_path: Path, failure: Exception
) -> None:
    def fail_reader(_case_dir: Path) -> dict[str, object]:
        raise failure

    with pytest.raises(RuntimeError, match="E_ACTUAL_STATE_READER_FAILED:repair-case"):
        execute_crash_matrix(
            [_case()],
            _checkpoint_child(tmp_path),
            tmp_path / "runs",
            state_reader=fail_reader,
        )


def test_child_failure_cannot_pass_or_invoke_reader(tmp_path: Path) -> None:
    reader_calls: list[Path] = []

    def read_actual(case_dir: Path) -> dict[str, object]:
        reader_calls.append(case_dir)
        return {}

    with pytest.raises(RuntimeError, match="E_CRASH_CHILD_FAILED:repair-case:7"):
        execute_crash_matrix(
            [_case()],
            _checkpoint_child(tmp_path, behavior="fail"),
            tmp_path / "runs",
            state_reader=read_actual,
        )
    assert reader_calls == []


def test_child_failure_after_checkpoint_cannot_pass_or_invoke_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader_calls: list[Path] = []
    checkpoint = restart_inspector._checkpoint

    def checkpoint_then_wait_for_failure(
        ready: Path,
        child: Popen[bytes],
        identity: dict[str, object],
        vector_id: str,
    ) -> None:
        checkpoint(ready, child, identity, vector_id)
        child.wait(timeout=5)

    monkeypatch.setattr(restart_inspector, "_checkpoint", checkpoint_then_wait_for_failure)

    def read_actual(case_dir: Path) -> dict[str, object]:
        reader_calls.append(case_dir)
        return {"committed_rows": 1}

    with pytest.raises(RuntimeError, match="E_CRASH_CHILD_FAILED:repair-case:7"):
        execute_crash_matrix(
            [_case()],
            _checkpoint_child(tmp_path, behavior="ready_then_fail"),
            tmp_path / "runs",
            state_reader=read_actual,
        )
    assert reader_calls == []
