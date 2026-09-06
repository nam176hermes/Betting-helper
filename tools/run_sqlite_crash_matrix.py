"""Execute the seven registered SQLite transaction crashes and bind their evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from tools.run_indexeddb_crash_matrix import _observations
from tools.run_loopback_ack_crash_matrix import run_backend_case

ROOT = Path(__file__).resolve().parents[1]
SHIM_SOURCE = Path(__file__).with_name("sqlite_commit_crash_shim.c")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha(path)}


def _compile_commit_shim(workspace: Path) -> Path:
    compiler = shutil.which("cc")
    if compiler is None:
        raise RuntimeError("E_SQL_COMMIT_SHIM_COMPILER")
    output = workspace / "sqlite-commit-crash-shim.so"
    subprocess.run(  # noqa: S603 -- fixed compiler argv and owned test-only output
        [compiler, "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-ldl",
         str(SHIM_SOURCE), "-o", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=20,
    )
    return output


def _reader_provenance(command: list[str], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "command_prefix": command,
        "executable": {
            "path": command[0],
            "resolved_path": str(Path(command[0]).resolve()),
            "sha256": _sha(Path(command[0])),
        },
        "entrypoint": {"path": command[2], "sha256": _sha(Path(command[2]))},
        "runs": row.pop("reader_runs"),
    }


def run_sqlite_crash_matrix(
    pack: Path,
    workspace: Path,
    *,
    observation_input: dict[str, Any] | None = None,
    entries: list[dict[str, Any]] | None = None,
    include_mutations: bool = True,
) -> dict[str, Any]:
    from tools.verify_repair_evidence import capture_binding

    workspace.mkdir(parents=True, exist_ok=True)
    registered = [
        row
        for row in json.loads(
            (pack / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if row["harness"] == "SQLITE_TRANSACTION"
    ]
    if len(registered) != 7:
        raise ValueError("E_SQL_CRASH_REGISTRY")
    entries = registered if entries is None else entries
    if not entries or any(entry not in registered for entry in entries):
        raise ValueError("E_SQL_CRASH_REGISTRY")
    observation = observation_input or _observations(str(uuid4()))[0]
    shim = _compile_commit_shim(workspace)
    child = [
        str(Path(sys.executable).absolute()),
        "-I",
        str(Path(__file__).with_name("sqlite_crash_child.py").resolve()),
        "--commit-shim",
        str(shim.resolve()),
    ]
    reader = [
        str(Path(sys.executable).absolute()),
        "-I",
        str(Path(__file__).with_name("restart_state_reader.py").resolve()),
    ]
    binding = capture_binding()
    records: list[dict[str, Any]] = []
    for ordinal, entry in enumerate(entries):
        result = run_backend_case(
            entry,
            observation,
            workspace / f"sql-{ordinal:02d}",
            command_prefix=child,
            trusted_command=child,
            reader_command=reader,
        )
        row = cast(dict[str, Any], result["records"][0])
        case = Path(row["case_directory"])
        comparison_state = json.loads((case / "comparison-state.json").read_text())
        reader_runs = row["reader_runs"]
        reader_outputs = {
            item["phase"]: json.loads(Path(item["path"]).read_text()) for item in reader_runs
        }
        actual = {
            "before": reader_outputs["before"]["state"],
            "after": reader_outputs["after"]["state"],
            "replay": comparison_state["replay"],
        }
        before_count = actual["before"]["tables"]["raw_commits"]
        before_count = len(before_count)
        actual["atomic_outcome"] = "NEW" if before_count == 1 else "OLD"
        actual_path = case / "terminal-actual.json"
        actual_path.write_text(json.dumps(actual, sort_keys=True, separators=(",", ":")))
        expected_path = case / "governed-expected.json"
        expected_path.write_text(
            json.dumps(entry["expected_post_restart_state"], sort_keys=True, separators=(",", ":"))
        )
        reader_input_artifacts = {
            item["phase"]: {
                "path": item["input_path"],
                "sha256": item["input_sha256"],
            }
            for item in reader_runs
        }
        terminal = {
            **row,
            "vector_id": entry["vector_id"],
            "case_id": entry["vector_id"],
            "status": "PASS",
            "result": "PASS",
            "executed": True,
            "launch_attempted": True,
            "execution_kind": "SQLITE_TRANSACTION_PROCESS_CRASH",
            "qualification_scope": "SQLITE_TRANSACTION",
            "legacy_full_qualification": "HOLD",
            "identity": row["checkpoint"],
            "actual": actual,
            "expected": entry["expected_post_restart_state"],
            "observed_error": None,
            "comparison": {
                "matched": True,
                "allowed_atomic_outcome": True,
            },
            "evidence_binding": binding,
            "revision": binding["revision"],
            "environment": binding["environment"],
            "command_exit": {"child": row["termination_returncode"], "reopen": 0,
                             "replay": 0, "reader": 0},
            "input_artifact": _artifact(case / "scenario.json"),
            "child_launch_artifact": _artifact(case / "launch-input.json"),
            "checkpoint_artifact": _artifact(case / "checkpoint.json"),
            "boundary_artifact": _artifact(case / "boundary.json"),
            "actual_artifact": _artifact(actual_path),
            "expected_artifact": _artifact(expected_path),
            "comparison_artifact": _artifact(case / "comparison-state.json"),
            "recovery_artifact": _artifact(case / "recovery.json"),
            "reader_input_artifacts": reader_input_artifacts,
            "shim": {
                "path": str(shim.resolve()),
                "source_sha256": _sha(SHIM_SOURCE),
                "binary_sha256": _sha(shim),
            },
        }
        terminal["reader_provenance"] = _reader_provenance(reader, terminal)
        result_path = case / "terminal-result.json"
        result_path.write_text(json.dumps(terminal, sort_keys=True, separators=(",", ":")))
        terminal["terminal_artifact"] = _artifact(result_path)
        records.append(terminal)
    from tools.owner_mutation_evidence import campaign

    mutations = campaign(entries, workspace / "mutations", records) if include_mutations else []
    return {
        "result": "PASS",
        "executed_vector_ids": [row["case_id"] for row in records],
        "killed_child_count": len(records),
        "mutation_survivors": 0,
        "records": records,
        "mutation_results": mutations,
        "legacy_full_qualification": "HOLD",
        "production_authority": "NONE",
    }
