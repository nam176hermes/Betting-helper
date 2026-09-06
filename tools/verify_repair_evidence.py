"""Local evidence validation; no release signing or live authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from shutil import which
from subprocess import run
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"
STATUSES = {"PASS", "FAIL", "BLOCKED_ENVIRONMENT", "NOT_IMPLEMENTED", "NOT_EXECUTED"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_binding() -> dict[str, Any]:
    """Capture tested working bytes as well as HEAD; reports are not self-hashed."""
    git = which("git")
    if git is None:
        raise FileNotFoundError("E_REPAIR_GIT_PREREQUISITE")
    revision = run(  # noqa: S603 -- fixed read-only local git command
        [git, "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True,
        text=True, timeout=10,
    ).stdout.strip()
    sources = [p for directory, suffix in (
        ("src", ".py"), ("tools", ".py"), ("extension/src", ".ts"),
        ("extension/test-harness", ".ts"),
    ) for p in (ROOT / directory).rglob("*" + suffix)]
    sources += [ROOT / name for name in (
        "pyproject.toml", "extension/package.json", "extension/tsconfig.test.json",
        "extension/test-harness/repair-manifest.json", "extension/test-harness/repair-probe.html",
    ) if (ROOT / name).is_file()]
    node = which("node")
    return {
        "revision": revision,
        "source_sha256": {str(p.relative_to(ROOT)): _sha(p) for p in sorted(sources)},
        "vendor_sha256": {str(p.relative_to(ROOT)): _sha(p)
                          for p in sorted(PACK.rglob("*")) if p.is_file()},
        "lock_sha256": {name: _sha(ROOT / name) for name in (
            "schema-lock.json", "uv.lock", "pnpm-lock.yaml",
        )},
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "python_executable": str(Path(sys.executable).resolve()),
                        "python_sha256": _sha(Path(sys.executable)), "node": node,
                        "node_sha256": _sha(Path(node)) if node else None},
    }


def full_required_ids() -> list[str]:
    crash = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    clock = json.loads((PACK / "docs/registries/clock-vector-coverage.v1.json").read_text())
    return [entry["vector_id"] for group in (crash, clock) for entry in group["entries"]]


def validate_case_status(row: dict[str, Any]) -> None:
    """Reject contradictions before status-specific evidence validation can return."""
    status = row["status"]
    if status not in STATUSES:
        raise ValueError("E_REPAIR_STATUS")
    if status in {"PASS", "FAIL"}:
        if row.get("executed") is not True or row.get("launch_attempted") is not True:
            raise ValueError("E_REPAIR_EXECUTED_STATUS")
        return
    if row.get("executed", False) is not False or row.get("launch_attempted", False) is not False:
        raise ValueError("E_REPAIR_UNEXECUTED_STATUS")
    execution_fields = {"actual", "comparison", "cross_language_drift", "detected"}
    if any(key in execution_fields or key.startswith(("actual_", "command_", "mutation_"))
           for key in row):
        raise ValueError("E_REPAIR_UNEXECUTED_OUTPUT")
    if status == "NOT_IMPLEMENTED" and not (
        row.get("implementation_marker") or row.get("reason")
    ):
        raise ValueError("E_REPAIR_IMPLEMENTATION_MARKER")
    if status == "BLOCKED_ENVIRONMENT":
        prerequisite = row["prerequisite"]
        if (not prerequisite["name"] or prerequisite["available"] is not False
                or row.get("launch_attempted") is not False):
            raise ValueError("E_REPAIR_PREREQUISITE")


def _verify_clock(row: dict[str, Any], current: dict[str, Any]) -> None:
    # Import lazily: the clock producer captures this module's binding before execution.
    from tools import run_clock_vector_qualification as clock

    validate_case_status(row)
    if row["evidence_binding"] != current:
        raise ValueError("E_REPAIR_STALE_BINDING")
    if row["code"]["revision"] != current["revision"]:
        raise ValueError("E_REPAIR_REVISION")
    if row["environment"] != {"python": platform.python_version(),
                              "platform": platform.platform(), "node": which("node")}:
        raise ValueError("E_REPAIR_ENVIRONMENT")
    if not row["code"]["sha256"] or any(
        _sha(Path(path)) != digest for path, digest in row["code"]["sha256"].items()
    ):
        raise ValueError("E_REPAIR_SOURCE")
    if not clock.verify_record(row, _current_binding=current):
        raise ValueError("E_REPAIR_ARTIFACT")
    if row["status"] != "PASS":
        return
    coverage = json.loads((PACK / clock._COVERAGE_PATH).read_text())
    vectors = json.loads((PACK / clock._VECTOR_PATH).read_text())
    entry = next(e for e in coverage["entries"] if e["vector_id"] == row["case_id"])
    canonical = clock._case(entry, vectors)
    if (any(row[key] != canonical[key] for key in ("input", "expected", "family"))
            or row["source_section"] != canonical["section"]
            or row["registry_version"] != coverage["schema_version"]):
        raise ValueError("E_REPAIR_REGISTERED_ORACLE")
    if (row["execution_kind"] != "OFFLINE_SHARED_CLOCK_EVALUATOR"
            or row["executed"] is not True or row["comparison"]["matched"] is not True
            or row["cross_language_drift"] is not False
            or set(row["actual"]) != {"python", "typescript", "execution_error"}
            or row["actual"]["execution_error"] is not None
            or row["observed_error"] != row["expected"]["error"]
            or set(row["command_exit"]) != {"python", "typescript"}
            or any(type(value) is not int or value != 0
                   for value in row["command_exit"].values())
            or any(clock._diff(row["actual"][language], row["expected"])
                   for language in ("python", "typescript"))):
        raise ValueError("E_REPAIR_EXECUTION_COMPARISON")


def _contains_expected(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in {"expected", "expected_post_restart_state"}
            or _contains_expected(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_expected(item) for item in value)
    return False


def _indexeddb_artifact(row: dict[str, Any], name: str) -> object:
    artifact = row[name]
    path = Path(artifact["path"])
    if _sha(path) != artifact["sha256"]:
        raise ValueError("E_INDEXEDDB_ARTIFACT:" + name)
    return json.loads(path.read_text())


def _verify_indexeddb(row: dict[str, Any], current: dict[str, Any]) -> None:
    """Validate browser spool evidence without using the clock adapter."""
    from tools.run_indexeddb_crash_matrix import PRODUCER, STREAM, compare_indexeddb_state

    validate_case_status(row)
    if row["evidence_binding"] != current:
        raise ValueError("E_REPAIR_STALE_BINDING")
    if row["revision"] != current["revision"]:
        raise ValueError("E_REPAIR_REVISION")
    if row["source_sha256"] != current["source_sha256"]["extension/src/spool.ts"]:
        raise ValueError("E_INDEXEDDB_SOURCE")
    if row["environment"] != {"system": platform.system(), "release": platform.release()}:
        raise ValueError("E_INDEXEDDB_ENVIRONMENT")
    if (
        set(row["command_exit"]) != {"browser", "worker", "reader"}
        or any(type(value) is not int or value != 0 for value in row["command_exit"].values())
    ):
        raise ValueError("E_INDEXEDDB_COMMAND")
    if _contains_expected(row["actual"]):
        raise ValueError("E_INDEXEDDB_ACTUAL_ORACLE")
    if set(row["actual"]) != set(row["identity"]) | {
        "worker_id", "entries", "states", "keys",
    }:
        raise ValueError("E_INDEXEDDB_READBACK")
    if _indexeddb_artifact(row, "actual_artifact") != row["actual"]:
        raise ValueError("E_INDEXEDDB_ARTIFACT:actual")
    worker = _indexeddb_artifact(row, "worker_input_artifact")
    reader = _indexeddb_artifact(row, "reader_input_artifact")
    if not isinstance(worker, dict) or not isinstance(reader, dict):
        raise ValueError("E_INDEXEDDB_INPUT")
    if (
        row["input_sha256"] != row["worker_input_artifact"]["sha256"]
        or row["expected_sha256"] != row["expected_artifact"]["sha256"]
    ):
        raise ValueError("E_INDEXEDDB_ARTIFACT:binding")
    if _contains_expected(worker) or _contains_expected(reader):
        raise ValueError("E_INDEXEDDB_INPUT_ORACLE")
    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    entry = next(item for item in registry["entries"] if item["vector_id"] == row["case_id"])
    expected = entry["expected_post_restart_state"]
    if entry["harness"] != "CHROME_INDEXEDDB" or row["expected"] != expected:
        raise ValueError("E_INDEXEDDB_EXPECTED")
    if _indexeddb_artifact(row, "expected_artifact") != expected:
        raise ValueError("E_INDEXEDDB_EXPECTED_ARTIFACT")
    if (
        row["execution_kind"] != "EXTENSION_DEDICATED_WORKER_TERMINATION"
        or row["comparison"] != {"matched": True, "scope": "INDEXEDDB_SPOOL_ONLY"}
        or row["identity"]["case_id"] != row["case_id"]
        or row["actual"]["module_sha256"] != row["identity"]["module_sha256"]
        or row["module_hashes"].get("src/spool.js") != row["identity"]["module_sha256"]
        or row["identity"]["module_sha256"]
        != _sha(ROOT / "extension/.test-build/src/spool.js")
        or row["module_hashes"].get("indexeddb-crash-child.js")
        != _sha(ROOT / "extension/.test-build/test-harness/indexeddb-crash-child.js")
    ):
        raise ValueError("E_INDEXEDDB_COMPARISON")
    browser = Path(row["browser"]["executable"])
    if _sha(browser) != row["browser"]["sha256"]:
        raise ValueError("E_INDEXEDDB_BROWSER")
    identity = row["identity"]
    request_identity = {
        key: identity[key]
        for key in (
            "run_id", "case_id", "checkpoint_id", "test_nonce", "profile_id",
            "component", "ordinal", "pid",
        )
    }
    input_fields = {"identity", "options", "operation", "observations"}
    reader_expected: dict[str, object] = {
        "identity": request_identity,
        "options": worker.get("options"),
        "operation": "read",
        "observations": [],
    }
    options = worker.get("options")
    options_expected: dict[str, object] = {
        "browser_run_id": request_identity["run_id"],
        "producer_id": PRODUCER,
        "stream_id": STREAM,
        "generation": "0",
        "registry": json.loads(
            (PACK / "registries/canonical-hash-domains.v1.json").read_text()
        ),
    }
    if (
        set(worker) != input_fields
        or set(reader) not in (input_fields, input_fields | {"mutation"})
        or not isinstance(options, dict)
        or options != options_expected
        or worker.get("identity") != request_identity
        or any(reader.get(key) != value for key, value in reader_expected.items())
        or reader.get("mutation") not in (None, "delete-row", "corrupt-ack")
    ):
        raise ValueError("E_INDEXEDDB_INPUT")
    compare_indexeddb_state(
        row["actual"], identity, row["observations"], expected["indexeddb_spool_delta"],
    )


def _sqlite_artifact(row: dict[str, Any], name: str) -> Any:
    return _sqlite_descriptor(row, row[name], "E_SQLITE_ARTIFACT:" + name)


def _sqlite_file(row: dict[str, Any], path_value: object, digest: object, error: str) -> Path:
    if not isinstance(path_value, str) or not isinstance(digest, str):
        raise ValueError(error)
    path = Path(path_value)
    case = Path(row["case_directory"]).resolve()
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(case):
        raise ValueError(error)
    if _sha(path) != digest:
        raise ValueError(error)
    return path


def _sqlite_descriptor(
    row: dict[str, Any], artifact: object, error: str
) -> Any:
    if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256"}:
        raise ValueError(error)
    path = _sqlite_file(row, artifact["path"], artifact["sha256"], error)
    try:
        return json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(error) from exc


def _sqlite_process_prefix(
    provenance: object, entrypoint: Path, current: dict[str, Any], error: str
) -> list[str]:
    if not isinstance(provenance, dict):
        raise ValueError(error)
    python = str(Path(sys.executable).absolute())
    expected = [python, "-I", str(entrypoint.resolve())]
    executable = provenance.get("executable")
    script = provenance.get("entrypoint")
    if (
        provenance.get("command_prefix") != expected
        or not isinstance(executable, dict)
        or executable
        != {
            "path": python,
            "resolved_path": current["environment"]["python_executable"],
            "sha256": current["environment"]["python_sha256"],
        }
        or not isinstance(script, dict)
        or script
        != {
            "path": str(entrypoint.resolve()),
            "sha256": current["source_sha256"][str(entrypoint.relative_to(ROOT))],
        }
    ):
        raise ValueError(error)
    return expected


def _validate_sqlite_ddl_snapshot(tables: dict[str, list[dict[str, Any]]]) -> None:
    """Rehydrate every returned row under the exact governed SQLite DDL."""
    from moj_discovery.store import TABLES, verified_ddl

    insertion_order = (
        "run_meta",
        "stream_generations",
        "raw_commits",
        "raw_conflicts",
        "application_records",
        "derived_revisions",
        "reducer_cursors",
        "ack_outbox",
        "ack_cursors",
        "coherence_epochs",
        "shock_observations",
        "coherence_controllers",
        "coherence_transitions",
        "gap_records",
        "gap_epoch_bindings",
        "generation_transitions",
    )
    if set(insertion_order) != set(TABLES):
        raise ValueError("E_SQLITE_DDL_STATE")
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(verified_ddl())
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN")
            for name in insertion_order:
                columns = [
                    str(item[1])
                    for item in connection.execute(f'PRAGMA table_info("{name}")')  # noqa: S608
                ]
                for row in tables[name]:
                    if not isinstance(row, dict) or set(row) != set(columns):
                        raise ValueError("E_SQLITE_DDL_STATE")
                    column_sql = ",".join(f'"{column}"' for column in columns)
                    placeholders = ",".join("?" for _ in columns)
                    # Names come only from the fixed table allowlist and governed DDL.
                    statement = (
                        f'INSERT INTO "{name}" ({column_sql}) VALUES ({placeholders})'  # noqa: S608
                    )
                    connection.execute(
                        statement,
                        tuple(row[column] for column in columns),
                    )
            connection.commit()
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("E_SQLITE_DDL_STATE")
    except (KeyError, TypeError, sqlite3.DatabaseError) as exc:
        raise ValueError("E_SQLITE_DDL_STATE") from exc


def _validate_sqlite_state(
    state: object, scenario: dict[str, Any], committed: int
) -> dict[str, Any]:
    from moj_discovery.store import TABLES, validate_journal, verified_ddl
    from tools.run_loopback_ack_crash_matrix import CHAIN, _oracle, _snapshot

    run_id = scenario["observation"]["discovery_run_id"]
    if (
        not isinstance(state, dict)
        or set(state) != {"schema_version", "run_id", "ddl_sha256", "tables"}
        or state["schema_version"] != 1
        or state["run_id"] != run_id
        or state["ddl_sha256"] != hashlib.sha256(verified_ddl().encode()).hexdigest()
        or not isinstance(state["tables"], dict)
        or set(state["tables"]) != set(TABLES)
        or any(not isinstance(rows, list) for rows in state["tables"].values())
        or any(
            item.get("run_id") != run_id
            for rows in state["tables"].values()
            for item in rows
            if isinstance(item, dict) and "run_id" in item
        )
    ):
        raise ValueError("E_SQLITE_JOURNAL_STATE")
    try:
        validate_journal(state["tables"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("E_SQLITE_JOURNAL_STATE") from exc
    _validate_sqlite_ddl_snapshot(state["tables"])
    try:
        observed = _snapshot(state)
        wanted = _oracle(scenario["observation"], bool(committed), False)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("E_SQLITE_JOURNAL_STATE") from exc
    if observed != wanted or any(
        len(state["tables"][name]) != committed for name in CHAIN
    ):
        raise ValueError("E_SQLITE_JOURNAL_STATE")
    return observed
def _verify_sqlite(row: dict[str, Any], current: dict[str, Any]) -> None:
    """Validate fixed SQLite terminal evidence against registry and current bytes."""
    from tools.run_loopback_ack_crash_matrix import CHAIN, PHASES, _snapshot

    validate_case_status(row)
    if row["evidence_binding"] != current or row["revision"] != current["revision"]:
        raise ValueError("E_REPAIR_STALE_BINDING")
    if row["environment"] != current["environment"]:
        raise ValueError("E_REPAIR_ENVIRONMENT")
    registry = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    entry = next(item for item in registry["entries"] if item["vector_id"] == row["case_id"])
    if (
        entry["harness"] != "SQLITE_TRANSACTION"
        or row["vector_id"] != row["case_id"]
        or row["expected"] != entry["expected_post_restart_state"]
        or row["execution_kind"] != "SQLITE_TRANSACTION_PROCESS_CRASH"
        or row["qualification_scope"] != "SQLITE_TRANSACTION"
        or row["observed_error"] is not None
        or row["comparison"] != {"matched": True, "allowed_atomic_outcome": True}
        or row["command_exit"]
        != {"child": -signal.SIGKILL, "reopen": 0, "replay": 0, "reader": 0}
    ):
        raise ValueError("E_SQLITE_TERMINAL_RECORD")
    actual = _sqlite_artifact(row, "actual_artifact")
    expected = _sqlite_artifact(row, "expected_artifact")
    scenario = _sqlite_artifact(row, "input_artifact")
    checkpoint = _sqlite_artifact(row, "checkpoint_artifact")
    boundary = _sqlite_artifact(row, "boundary_artifact")
    if actual != row["actual"] or expected != row["expected"] or _contains_expected(scenario):
        raise ValueError("E_SQLITE_ARTIFACT_CONTENT")
    identity = row["identity"]
    case_directory = Path(row["case_directory"])
    outer_run = case_directory.parent.name.removeprefix("run-")
    if (
        checkpoint != identity
        or identity["run_id"] != outer_run
        or identity["case_id"] != row["case_id"]
        or identity["checkpoint_id"] != entry["crash_checkpoint"]
        or identity["component"] != "SQLITE_TRANSACTION"
        or identity["pid"] != row["pid"]
        or boundary["identity"] != identity
    ):
        raise ValueError("E_SQLITE_CHECKPOINT_IDENTITY")

    child = row["launch_provenance"]
    reader = row["reader_provenance"]
    shim = row["shim"]
    child_prefix = _sqlite_process_prefix(
        {**child, "command_prefix": child["command_prefix"][:3]},
        ROOT / "tools/sqlite_crash_child.py",
        current,
        "E_SQLITE_CHILD_PROVENANCE",
    )
    if (
        child["command_prefix"]
        != [*child_prefix, "--commit-shim", str(Path(shim["path"]).resolve())]
        or child["argv"] != row["command"]
    ):
        raise ValueError("E_SQLITE_CHILD_PROVENANCE")
    expected_child_argv = [
        *child["command_prefix"],
        "--vector-id", row["case_id"],
        "--ready", str((case_directory / "checkpoint.json").resolve()),
        "--run-id", identity["run_id"],
        "--case-id", row["case_id"],
        "--checkpoint-id", entry["crash_checkpoint"],
        "--component", "SQLITE_TRANSACTION",
        "--ordinal", str(identity["ordinal"]),
        "--test-nonce", identity["test_nonce"],
        "--hold",
    ]
    if row["command"] != expected_child_argv:
        raise ValueError("E_SQLITE_CHILD_PROVENANCE")
    child_launch = _sqlite_artifact(row, "child_launch_artifact")
    if child_launch != {
        "command_prefix": child["command_prefix"],
        "executable": child["executable"],
        "entrypoint": child["entrypoint"],
        "scenario_sha256": row["input_artifact"]["sha256"],
    }:
        raise ValueError("E_SQLITE_CHILD_PROVENANCE")
    if (
        shim["source_sha256"] != _sha(ROOT / "tools/sqlite_commit_crash_shim.c")
        or _sha(Path(shim["path"])) != shim["binary_sha256"]
    ):
        raise ValueError("E_SQLITE_SHIM")
    phase = PHASES["-".join(row["case_id"].split("-")[:2])]
    if boundary["phase"] != phase:
        raise ValueError("E_SQLITE_BOUNDARY")
    if row["case_id"] == "SQL-06-DURING-COMMIT" and (
        boundary != {
            "identity": identity,
            "phase": "during_commit",
            "commit_armed": True,
            "operation": boundary.get("operation"),
            "target": boundary.get("target"),
            "sqlite_path": boundary.get("sqlite_path"),
        }
        or boundary["operation"] not in {"fsync", "fdatasync"}
        or boundary["target"] not in {"rollback_journal", "database"}
    ):
        raise ValueError("E_SQLITE_COMMIT_IO")

    if (
        row["termination_returncode"] != -signal.SIGKILL
        or row["termination_mechanism"] != "POSIX_OWNED_PROCESS_GROUP_SIGKILL"
        or row["checkpoint_sha256"] != row["checkpoint_artifact"]["sha256"]
        or row["pid"] != identity["pid"]
    ):
        raise ValueError("E_SQLITE_TERMINATION")

    if not isinstance(reader, dict):
        raise ValueError("E_SQLITE_READER_PROVENANCE")
    reader_prefix = _sqlite_process_prefix(
        reader,
        ROOT / "tools/restart_state_reader.py",
        current,
        "E_SQLITE_READER_PROVENANCE",
    )
    runs = reader.get("runs")
    inputs = row.get("reader_input_artifacts")
    if (
        not isinstance(runs, list)
        or len(runs) != 2
        or [item.get("phase") for item in runs if isinstance(item, dict)]
        != ["before", "after"]
        or not isinstance(inputs, dict)
        or set(inputs) != {"before", "after"}
    ):
        raise ValueError("E_SQLITE_READER_OUTPUT")
    reader_states: dict[str, dict[str, Any]] = {}
    used_paths: set[Path] = set()
    for phase_name, reader_run in zip(("before", "after"), runs, strict=True):
        if not isinstance(reader_run, dict) or reader_run.get("exit") != 0:
            raise ValueError("E_SQLITE_READER_PROVENANCE")
        reader_input = _sqlite_descriptor(
            row, inputs[phase_name], "E_SQLITE_READER_INPUT"
        )
        expected_input = {
            "run_dir": str(
                (case_directory / scenario["observation"]["discovery_run_id"]).resolve()
            ),
            "run_id": scenario["observation"]["discovery_run_id"],
            "case_id": row["case_id"],
            "checkpoint_id": entry["crash_checkpoint"],
            "phase": phase_name,
        }
        if _contains_expected(reader_input) or reader_input != expected_input:
            raise ValueError("E_SQLITE_READER_INPUT")
        if (
            reader_run.get("input_path") != inputs[phase_name]["path"]
            or reader_run.get("input_sha256") != inputs[phase_name]["sha256"]
            or reader_run.get("argv")
            != [
                *reader_prefix,
                expected_input["run_dir"],
                "--identity",
                inputs[phase_name]["path"],
            ]
        ):
            raise ValueError("E_SQLITE_READER_PROVENANCE")
        output_path = _sqlite_file(
            row,
            reader_run.get("path"),
            reader_run.get("sha256"),
            "E_SQLITE_READER_OUTPUT",
        )
        input_path = Path(inputs[phase_name]["path"]).resolve()
        if output_path.resolve() in used_paths or input_path in used_paths:
            raise ValueError("E_SQLITE_READER_OUTPUT")
        used_paths.update({output_path.resolve(), input_path})
        try:
            envelope = json.loads(output_path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("E_SQLITE_READER_OUTPUT") from exc
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"identity", "state"}
            or envelope["identity"] != expected_input
            or not isinstance(envelope["state"], dict)
        ):
            raise ValueError("E_SQLITE_READER_OUTPUT")
        reader_states[phase_name] = envelope["state"]
    if (
        actual.get("before") != reader_states["before"]
        or actual.get("after") != reader_states["after"]
    ):
        raise ValueError("E_SQLITE_READER_OUTPUT")

    recovery_runs = row.get("recovery_runs")
    if not isinstance(recovery_runs, list) or len(recovery_runs) != 2:
        raise ValueError("E_SQLITE_RECOVERY_PROVENANCE")
    for replay, recovery_run in zip((False, True), recovery_runs, strict=True):
        phase_name = "replay" if replay else "reopen"
        argv = [
            *child["command_prefix"], "--recover", str(case_directory),
            *(["--replay"] if replay else []),
        ]
        if (
            not isinstance(recovery_run, dict)
            or recovery_run.get("phase") != phase_name
            or recovery_run.get("argv") != argv
            or recovery_run.get("exit") != 0
        ):
            raise ValueError("E_SQLITE_RECOVERY_PROVENANCE")
        for artifact_name in ("launch", "stdout", "stderr"):
            artifact_path = _sqlite_file(
                row,
                recovery_run.get(artifact_name + "_path"),
                recovery_run.get(artifact_name + "_sha256"),
                "E_SQLITE_RECOVERY_PROVENANCE",
            )
            if artifact_name == "launch":
                try:
                    launch = json.loads(artifact_path.read_text())
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError("E_SQLITE_RECOVERY_PROVENANCE") from exc
                if launch != {
                    "command_prefix": child["command_prefix"],
                    "executable": child["executable"],
                    "entrypoint": child["entrypoint"],
                    "argv": argv,
                }:
                    raise ValueError("E_SQLITE_RECOVERY_PROVENANCE")

    before_count = len(reader_states["before"]["tables"]["raw_commits"])
    after_count = len(reader_states["after"]["tables"]["raw_commits"])
    before_projection = _validate_sqlite_state(reader_states["before"], scenario, before_count)
    after_projection = _validate_sqlite_state(reader_states["after"], scenario, after_count)
    comparison = _sqlite_artifact(row, "comparison_artifact")
    recovery = _sqlite_artifact(row, "recovery_artifact")
    if (
        comparison
        != {"before": before_projection, "after": after_projection, "replay": actual["replay"]}
        or recovery.get("after") != reader_states["after"]
        or recovery.get("replay", {}).get("error", "ACK") != actual["replay"]
    ):
        raise ValueError("E_SQLITE_JOURNAL_STATE")
    before = _snapshot(reader_states["before"])["counts"]
    after = _snapshot(reader_states["after"])["counts"]
    old_or_new = before["raw_commits"]
    allowed = {0, 1} if row["case_id"] == "SQL-06-DURING-COMMIT" else {
        entry["expected_post_restart_state"]["sql_row_deltas"]["raw_commits"]
    }
    if (
        old_or_new not in allowed
        or [before[name] for name in CHAIN] != [old_or_new] * len(CHAIN)
        or [after[name] for name in CHAIN] != [1] * len(CHAIN)
        or actual["replay"] != "ACK"
        or actual["atomic_outcome"] != ("NEW" if old_or_new else "OLD")
    ):
        raise ValueError("E_SQLITE_ATOMIC_OUTCOME")

    terminal = _sqlite_descriptor(
        row, row.get("terminal_artifact"), "E_SQLITE_TERMINAL_ARTIFACT"
    )
    terminal_row = dict(row)
    terminal_row.pop("terminal_artifact", None)
    if terminal != terminal_row:
        raise ValueError("E_SQLITE_TERMINAL_ARTIFACT")


def _verify_executed(row: dict[str, Any], current: dict[str, Any]) -> None:
    if row.get("execution_kind") == "DISPOSABLE_DESTRUCTION_PROCESS_CRASH":
        from tools.verify_destruction_evidence import verify_destruction

        verify_destruction(row, current)
    elif row.get("execution_kind") == "BROWSER_LOOPBACK_ACK":
        _verify_browser_ack(row, current)
    elif row.get("execution_kind") == "EXTENSION_DEDICATED_WORKER_TERMINATION":
        _verify_indexeddb(row, current)
    elif row.get("execution_kind") == "OFFLINE_SHARED_CLOCK_EVALUATOR":
        _verify_clock(row, current)
    elif row.get("execution_kind") == "SQLITE_TRANSACTION_PROCESS_CRASH":
        _verify_sqlite(row, current)
    elif row.get("execution_kind") == "GAP_GENERATION_COHERENCE_PROCESS":
        from tools.run_gap_coherence_crash_matrix import verify_gap_record

        verify_gap_record(row, current)
    else:
        raise ValueError("E_REPAIR_EXECUTION_KIND")


def verify_owner_mutation(
    harness: str, row: dict[str, Any], current: dict[str, Any]
) -> None:
    """Recursively validate fresh registered SQL/browser mutation executions."""
    from tools.owner_mutation_evidence import verify_mutation

    verify_mutation(harness, row, current)


def _verify_browser_binding(row: dict[str, Any], current: dict[str, Any]) -> None:
    """Bind the actual browser assets, profile and OS observations to the pinned launch."""
    from tools.qualify_chrome_indexeddb import _browser_command, _canonical_browser_executable
    from tools.run_indexeddb_crash_matrix import CHROME

    case = Path(row["case_directory"]).resolve()
    extension, profile = case / "test-extension", case / "chrome-profile"
    identity = row["identity"]
    assets = row["loaded_assets"]
    if extension.is_symlink() or set(assets) != {"manifest.json", "repair-probe.html"}:
        raise ValueError("E_ACK_LOADED_ASSET")
    for name, source in (
        ("manifest.json", "repair-manifest.json"),
        ("repair-probe.html", "repair-probe.html"),
    ):
        descriptor = assets[name]
        path = _sqlite_file(row, descriptor["path"], descriptor["sha256"], "E_ACK_LOADED_ASSET")
        source_path = "extension/test-harness/" + source
        if (
            path != extension / name
            or descriptor["sha256"] != current["source_sha256"][source_path]
            or path.read_bytes() != (ROOT / source_path).read_bytes()
        ):
            raise ValueError("E_ACK_LOADED_ASSET")
    manifest = json.loads((extension / "manifest.json").read_text())
    if (
        manifest["host_permissions"] != ["http://127.0.0.1/*"]
        or manifest["permissions"] != []
        or manifest["web_accessible_resources"] != []
    ):
        raise ValueError("E_ACK_LOADED_ASSET_PERMISSIONS")

    readbacks = row["profile_readbacks"]
    if profile.is_symlink() or set(readbacks) != {"before", "after", "marker", "sentinel"}:
        raise ValueError("E_ACK_PROFILE")
    marker = _sqlite_file(
        row, readbacks["marker"]["path"], readbacks["marker"]["sha256"], "E_ACK_PROFILE_MARKER"
    )
    if marker != profile / "BH_R05_PROFILE_ID" or marker.read_text() != identity["profile_id"]:
        raise ValueError("E_ACK_PROFILE_MARKER")
    expected_profile = {
        "profile_path": str(profile),
        "marker": identity["profile_id"],
        "sentinel": {
            "extensionId": identity["origin"].removeprefix("chrome-extension://"),
            "moduleSha256": identity["module_sha256"],
            "moduleUrl": identity["module_url"],
            "origin": identity["origin"],
            "profileId": identity["profile_id"],
            "protocol": "chrome-extension:",
            "sentinel": readbacks["sentinel"],
            "spoolConstructor": "Spool",
        },
    }
    if not isinstance(readbacks["sentinel"], str) or len(readbacks["sentinel"]) != 64:
        raise ValueError("E_ACK_PROFILE_SENTINEL")
    for phase in ("before", "after"):
        value = _sqlite_descriptor(row, readbacks[phase], "E_ACK_PROFILE_READBACK")
        if value != expected_profile or value != _sqlite_descriptor(
            row, row["artifacts"]["profile-" + phase], "E_ACK_PROFILE_READBACK"
        ):
            raise ValueError("E_ACK_PROFILE_SENTINEL")

    configured = _canonical_browser_executable(
        Path(os.environ.get("BH_CHROME_BINARY", str(CHROME)))
    )
    expected_browser = {"executable": str(configured), "sha256": _sha(configured)}
    if row["browser"] != expected_browser:
        raise ValueError("E_ACK_BROWSER_CONFIGURED_EXECUTABLE")
    provenance = row["browser_provenance"]
    if set(provenance) != {"launch", "before", "after"}:
        raise ValueError("E_ACK_BROWSER_PROVENANCE")
    launch = _sqlite_descriptor(row, provenance["launch"], "E_ACK_BROWSER_LAUNCH")
    if launch != _sqlite_descriptor(
        row, row["artifacts"]["browser-launch"], "E_ACK_BROWSER_LAUNCH"
    ):
        raise ValueError("E_ACK_BROWSER_LAUNCH")
    ports = [
        value.removeprefix("--remote-debugging-port=")
        for value in launch["argv"]
        if isinstance(value, str) and value.startswith("--remote-debugging-port=")
    ]
    if len(ports) != 1 or not ports[0].isdigit() or not 0 < int(ports[0]) < 65536:
        raise ValueError("E_ACK_BROWSER_LAUNCH")
    expected_argv = _browser_command(
        configured, profile, extension, identity["origin"] + "/repair-probe.html", int(ports[0])
    )
    expected_launch = {
        **expected_browser,
        "argv": expected_argv,
        "pid": identity["pid"],
        "pgid": identity["pid"],
        "profile_path": str(profile),
        "extension_path": str(extension),
        "origin": identity["origin"],
    }
    if launch != expected_launch:
        raise ValueError("E_ACK_BROWSER_LAUNCH")
    # This Chrome build rewrites /proc argv to one display string and inserts
    # four headless switches. Accept only this exact observed representation.
    headless_argv = [
        " ".join(
            [
                *expected_argv[:-1],
                "--noerrdialogs",
                "--ozone-platform=headless",
                "--ozone-override-screen-size=800,600",
                "--use-angle=swiftshader-webgl",
                expected_argv[-1],
            ]
        )
    ]
    start_times = []
    for phase in ("before", "after"):
        observed = _sqlite_descriptor(row, provenance[phase], "E_ACK_BROWSER_OBSERVATION")
        if observed != _sqlite_descriptor(
            row, row["artifacts"]["browser-process-" + phase], "E_ACK_BROWSER_OBSERVATION"
        ):
            raise ValueError("E_ACK_BROWSER_OBSERVATION")
        try:
            raw_argv = (
                bytes.fromhex(observed["proc_cmdline_hex"]).rstrip(b"\0").decode().split("\0")
            )
            proc_pid, _, proc_state = observed["proc_stat"].partition("(")
            fields = proc_state.rpartition(")")[2].split()
            raw_pid, raw_pgid, start_time = int(proc_pid), int(fields[2]), int(fields[19])
        except (ValueError, IndexError, TypeError, KeyError) as error:
            raise ValueError("E_ACK_BROWSER_OBSERVATION") from error
        if (
            set(observed)
            != {"pid", "pgid", "executable", "sha256", "argv", "proc_cmdline_hex", "proc_stat"}
            or observed["pid"] != identity["pid"]
            or raw_pid != identity["pid"]
            or observed["pgid"] != raw_pgid
            or raw_pgid != identity["pid"]
            or observed["executable"] != str(configured)
            or observed["sha256"] != expected_browser["sha256"]
            or observed["argv"] != raw_argv
            or raw_argv not in (expected_argv, headless_argv)
            or start_time <= 0
        ):
            raise ValueError("E_ACK_BROWSER_OBSERVATION")
        start_times.append(start_time)
    if start_times[0] != start_times[1]:
        raise ValueError("E_ACK_BROWSER_PROCESS_REPLACED")


def _verify_browser_ack(
    row: dict[str, Any],
    current: dict[str, Any],
    *,
    terminal: bool = True,
    input_mutation: bool = False,
) -> None:
    """Validate actual cross-component records against the registered parent-only oracle."""
    from tools.run_indexeddb_crash_matrix import (
        PRODUCER,
        REGISTRY,
        STREAM,
        compare_indexeddb_state,
    )

    validate_case_status(row)
    if bool(row.get("input_rejection")) != input_mutation:
        raise ValueError("E_OWNER_MUTATION_IDENTITY")
    if row["evidence_binding"] != current or row["revision"] != current["revision"]:
        raise ValueError("E_REPAIR_STALE_BINDING")
    if (
        row["environment"] != current["environment"]
        or row["observed_error"] != ("E_SPOOL_OBSERVATION_BINDING" if input_mutation else None)
        or row["comparison"] != {"matched": True}
        or row["qualification_scope"] != "BROWSER_LOOPBACK_ACK"
    ):
        raise ValueError("E_ACK_EXECUTION")
    entries = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    entry = next(value for value in entries if value["vector_id"] == row["case_id"])
    if entry["harness"] not in {"CHROME_INDEXEDDB", "LOOPBACK_ACK"}:
        raise ValueError("E_ACK_CASE")
    expected = entry["expected_post_restart_state"]
    if row["expected"] != expected:
        raise ValueError("E_ACK_ORACLE")
    identity = row["identity"]
    if (
        identity["case_id"] != entry["vector_id"]
        or identity["checkpoint_id"] != entry["crash_checkpoint"]
        or identity["component"] != entry["harness"]
        or identity["origin"] != "chrome-extension://jnegjfjalhnpdeejfcjlobpbdpabdfhp"
        or identity["protocol"] != "chrome-extension:"
        or identity["module_url"] != identity["origin"] + "/src/spool.js"
        or not isinstance(identity["pid"], int)
        or identity["pid"] <= 0
        or not identity["profile_id"]
        or len(identity["test_nonce"]) != 32
    ):
        raise ValueError("E_ACK_IDENTITY")
    browser = Path(row["browser"]["executable"])
    if _sha(browser) != row["browser"]["sha256"]:
        raise ValueError("E_ACK_BROWSER")
    _verify_browser_binding(row, current)
    modules = row["module_hashes"]
    extension = Path(row["case_directory"]) / "test-extension"
    # Every loaded module is retained and bound, including the canonical dependency.
    if (
        not modules
        or set(modules) != {str(path.relative_to(extension)) for path in extension.rglob("*.js")}
        or any(_sha(extension / name) != digest for name, digest in modules.items())
        or modules.get("src/spool.js") != identity["module_sha256"]
    ):
        raise ValueError("E_ACK_MODULE_GRAPH")
    for name in ("spool", "errors"):
        if modules.get(f"src/{name}.js") != _sha(ROOT / f"extension/.test-build/src/{name}.js"):
            raise ValueError("E_ACK_MODULE_GRAPH")
    canonical = (
        (ROOT / "extension/.test-build/src/canonical.js")
        .read_text()
        .replace('from "canonicalize"', 'from "./canonicalize.js"')
    )
    if modules.get("src/canonical.js") != hashlib.sha256(
        canonical.encode()
    ).hexdigest() or modules.get("src/canonicalize.js") != _sha(
        ROOT / "extension/node_modules/canonicalize/lib/canonicalize.js"
    ):
        raise ValueError("E_ACK_MODULE_GRAPH")
    for name in ("indexeddb-crash-child", "repair-probe"):
        if modules.get(name + ".js") != _sha(
            ROOT / f"extension/.test-build/test-harness/{name}.js"
        ):
            raise ValueError("E_ACK_MODULE_GRAPH")
    inputs = {
        name: _sqlite_descriptor(row, value, "E_ACK_INPUT:" + name)
        for name, value in row["inputs"].items()
    }
    artifacts = {
        name: _sqlite_descriptor(row, value, "E_ACK_ARTIFACT:" + name)
        for name, value in row["artifacts"].items()
    }
    if input_mutation:
        from tools.owner_mutation_evidence import verify_browser_input

        verify_browser_input(row, inputs, artifacts, terminal=terminal)
        return
    if set(inputs) != {
        "server-input-0",
        "server-input-1",
        "worker",
        "recovery-worker",
        "reader-before",
        "reader-after",
        "browser-reader-before",
        "browser-reader-after",
    }:
        raise ValueError("E_ACK_INPUT_SET")
    if _contains_expected(inputs):
        raise ValueError("E_ACK_INPUT_ORACLE")
    request_identity = {
        key: identity[key]
        for key in (
            "run_id",
            "case_id",
            "checkpoint_id",
            "test_nonce",
            "profile_id",
            "component",
            "ordinal",
            "pid",
        )
    }
    options = {
        "browser_run_id": identity["run_id"],
        "producer_id": PRODUCER,
        "stream_id": STREAM,
        "generation": "0",
        "registry": json.loads(REGISTRY.read_text()),
    }
    worker = inputs["worker"]
    if (
        set(worker) != {"identity", "options", "operation", "observations", "transport"}
        or worker["identity"] != request_identity
        or worker["options"] != options
        or [json.loads(raw) for raw in worker["observations"]] != row["observations"]
        or worker["operation"] != ("crash" if entry["harness"] == "CHROME_INDEXEDDB" else "deliver")
        or row["observations"][0]["discovery_run_id"] != identity["run_id"]
    ):
        raise ValueError("E_ACK_WORKER_INPUT")
    if (
        artifacts["expected"] != expected
        or artifacts["checkpoint"] != row["checkpoint"]
        or artifacts["browser-before"] != row["actual"]
        or artifacts["browser-after"] != row["browser_after"]
        or artifacts["backend-before"] != row["backend_before"]
        or artifacts["backend-after"] != row["backend_after"]
    ):
        raise ValueError("E_ACK_ARTIFACT_LINK")
    count = expected["indexeddb_spool_delta"] if entry["harness"] == "CHROME_INDEXEDDB" else 1
    ack = int(expected["extension_ack"] == "GEN0_Q1_H1")
    for value in (row["actual"], row["browser_after"]):
        if set(value) != set(identity) | {"worker_id", "entries", "states", "keys"}:
            raise ValueError("E_ACK_BROWSER_STATE_FIELDS")
    compare_indexeddb_state(row["actual"], identity, row["observations"], count, ack=ack)
    compare_indexeddb_state(row["browser_after"], identity, row["observations"], 1, ack=1)
    workers = [
        row["worker_id"],
        row["actual"]["worker_id"],
        row["browser_after"]["worker_id"],
        artifacts["recovery-worker-output"]["worker_id"],
    ]
    if len(set(workers)) != 4:
        raise ValueError("E_ACK_WORKER_IDENTITY")
    if count and row["actual"]["entries"] != row["browser_after"]["entries"]:
        raise ValueError("E_ACK_RETAINED_ROWS")
    recovery_output = artifacts["recovery-worker-output"]
    compare_indexeddb_state(recovery_output, identity, row["observations"], 1, ack=1)
    if (
        recovery_output["boundary"] != ""
        or recovery_output["wire_ack"] != row["backend_after"]["tables"]["ack_outbox"][0]
    ):
        raise ValueError("E_ACK_RECOVERY_OUTPUT")
    for phase in ("before", "after"):
        if inputs["browser-reader-" + phase] != {
            "identity": request_identity,
            "options": options,
            "operation": "read",
            "observations": [],
        }:
            raise ValueError("E_ACK_READER_INPUT")
    child_identity = {
        key: value for key, value in request_identity.items() if key not in {"pid", "profile_id"}
    }
    processes = row["backend_processes"]
    if len(processes) != 2 or processes[0]["pid"] == processes[1]["pid"]:
        raise ValueError("E_ACK_PROCESS_IDENTITY")
    for ordinal, process in enumerate(processes):
        prefix = _sqlite_process_prefix(
            process["provenance"],
            ROOT / "tools/loopback_ack_crash_child.py",
            current,
            "E_ACK_PROCESS_PROVENANCE",
        )
        config = inputs[f"server-input-{ordinal}"]
        if (
            config
            != {
                "identity": child_identity,
                "observation": row["observations"][0],
                "origin": identity["origin"],
                "token": config["token"],
                "restart": bool(ordinal),
            }
            or len(config["token"]) != 64
            or process["identity"] != {**child_identity, "pid": process["pid"]}
            or process["pgid"] != process["pid"]
            or process["argv"]
            != [*prefix, "--browser-server", row["inputs"][f"server-input-{ordinal}"]["path"]]
        ):
            raise ValueError("E_ACK_PROCESS_INPUT")
        killed = ordinal == 0 and entry["kill_action"] == "SIGKILL_BACKEND_CHILD"
        if process["exit"] != (-signal.SIGKILL if killed else -signal.SIGTERM) or process[
            "mechanism"
        ] != (
            "POSIX_OWNED_PROCESS_GROUP_SIGKILL"
            if killed
            else "POSIX_OWNED_PROCESS_GROUP_SIGTERM_CLEANUP"
        ):
            raise ValueError("E_ACK_PROCESS_EXIT")
        ready = _sqlite_descriptor(row, process["ready"], "E_ACK_SERVER_READY")
        if (
            ready != artifacts[f"server-ready-{ordinal}"]
            or ready["identity"] != process["identity"]
        ):
            raise ValueError("E_ACK_SERVER_READY")
        transport = worker["transport"] if ordinal == 0 else inputs["recovery-worker"]["transport"]
        if ready["address"][0] != "127.0.0.1" or transport != {
            "endpoint": "http://127.0.0.1:" + str(ready["address"][1]),
            "token": config["token"],
        }:
            raise ValueError("E_ACK_TRANSPORT")
    if inputs["server-input-0"]["token"] == inputs["server-input-1"]["token"]:
        raise ValueError("E_ACK_STALE_PAIRING")
    if inputs["recovery-worker"] != {
        **worker,
        "operation": "recover",
        "transport": inputs["recovery-worker"]["transport"],
        "observations": worker["observations"][:1] if not count else [],
    }:
        raise ValueError("E_ACK_RECOVERY_INPUT")
    checkpoint = row["checkpoint"]
    if entry["kill_action"] == "SIGKILL_BACKEND_CHILD":
        if checkpoint != processes[0]["identity"] or row["termination"] != {
            "method": "POSIX_OWNED_PROCESS_GROUP_SIGKILL",
            "pid": processes[0]["pid"],
            "returncode": -signal.SIGKILL,
        }:
            raise ValueError("E_ACK_TERMINATION")
        boundary = artifacts["backend-boundary"]
        if (
            boundary["identity"] != checkpoint
            or boundary["in_transaction"] is not False
            or boundary["tables"] != row["backend_before"]["tables"]
            or boundary["path"] != ("/ingest" if row["case_id"].startswith("SEND") else "/confirm")
            or boundary["value"]
            != (
                row["observations"][0]
                if row["case_id"].startswith("SEND")
                else row["backend_before"]["tables"]["ack_outbox"][0]
            )
        ):
            raise ValueError("E_ACK_CHECKPOINT_BOUNDARY")
    else:
        if (
            any(checkpoint.get(key) != value for key, value in identity.items())
            or checkpoint["worker_id"] != row["worker_id"]
            or checkpoint["boundary"] != entry["crash_checkpoint"]
            or row["termination"]
            != (
                {"method": "NONE"}
                if entry["kill_action"] == "NONE"
                else {"method": "Worker.terminate", "worker_id": row["worker_id"]}
            )
        ):
            raise ValueError("E_ACK_TERMINATION")
        if (
            entry["harness"] == "LOOPBACK_ACK"
            and checkpoint["wire_ack"] != row["backend_before"]["tables"]["ack_outbox"][0]
        ):
            raise ValueError("E_ACK_WIRE_CHECKPOINT")
    readers = row["reader_runs"]
    if len(readers) != 2 or [item["phase"] for item in readers] != ["before", "after"]:
        raise ValueError("E_ACK_READER_SET")
    for reader in readers:
        phase = reader["phase"]
        run_dir = str((Path(row["case_directory"]) / identity["run_id"]).resolve())
        reader_input = inputs["reader-" + phase]
        argv = [
            str(Path(sys.executable).absolute()),
            "-I",
            str(ROOT / "tools/restart_state_reader.py"),
            run_dir,
            "--identity",
            row["inputs"]["reader-" + phase]["path"],
        ]
        output = _sqlite_descriptor(row, reader["artifact"], "E_ACK_READER_ARTIFACT")
        if (
            reader_input
            != {
                "run_dir": run_dir,
                "run_id": identity["run_id"],
                "case_id": entry["vector_id"],
                "checkpoint_id": entry["crash_checkpoint"],
                "phase": phase,
            }
            or reader["exit"] != 0
            or reader["argv"] != argv
            or output != {"identity": reader_input, "state": row["backend_" + phase]}
        ):
            raise ValueError("E_ACK_READER_OUTPUT")
        state = row["backend_" + phase]
        _validate_sqlite_ddl_snapshot(state["tables"])
        confirms = state["tables"]["ack_cursors"]
        confirmed = phase == "after" or row["case_id"].startswith(("ACK-05", "ACK-06"))
        if len(confirms) != int(confirmed):
            raise ValueError("E_ACK_CONFIRMATION_STATE")
        if confirmed:
            outbox = state["tables"]["ack_outbox"][0]
            expected_confirmation = {
                "ack_cursor_id": "confirmation:" + outbox["cursor_hash"],
                **{
                    key: outbox[key]
                    for key in (
                        "run_id",
                        "browser_run_id",
                        "producer_id",
                        "stream_id",
                        "generation",
                        "highest_contiguous_sequence",
                        "cursor_hash",
                    )
                },
                "owner": "BACKEND",
                "chain_verified": 1,
                "verified_against": "BACKEND_DURABLE_CHAIN",
                "previous_ack_cursor_id": None,
                "recorded_at_us": confirms[0]["recorded_at_us"],
            }
            if confirms != [expected_confirmation]:
                raise ValueError("E_ACK_CONFIRMATION_STATE")
        stripped = {**state, "tables": {**state["tables"], "ack_cursors": []}}
        committed = int(phase == "after" or expected["backend_ack"] == "GEN0_Q1_H1")
        _validate_sqlite_state(stripped, {"observation": row["observations"][0]}, committed)
    for name, rows in row["backend_before"]["tables"].items():
        if rows and rows != row["backend_after"]["tables"][name]:
            raise ValueError("E_ACK_RETAINED_JOURNAL")
    first_count = (
        0
        if entry["harness"] == "CHROME_INDEXEDDB" or row["case_id"].startswith("SEND")
        else 4
        if entry["kill_action"] == "NONE"
        else 1
    )
    wire_names = {
        f"wire-{ordinal}-{serial}.json"
        for ordinal, count in ((0, first_count), (1, 2))
        for serial in range(1, count + 1)
    }
    if set(row["wire_artifacts"]) != wire_names:
        raise ValueError("E_ACK_WIRE_SET")
    for name, descriptor in row["wire_artifacts"].items():
        wire = _sqlite_descriptor(row, descriptor, "E_ACK_WIRE_ARTIFACT")
        _, ordinal_text, serial_text = name.removesuffix(".json").split("-")
        ordinal, serial = int(ordinal_text), int(serial_text)
        ingest = serial % 2 == 1
        outbox = row["backend_after"]["tables"]["ack_outbox"][0]
        confirmation = row["backend_after"]["tables"]["ack_cursors"][0]
        wanted_wire = {
            "identity": processes[ordinal]["identity"],
            "serial": serial,
            "path": "/ingest" if ingest else "/confirm",
            "request": {
                "token": inputs[f"server-input-{ordinal}"]["token"],
                "value": row["observations"][0] if ingest else outbox,
            },
            "response": {"ack": outbox} if ingest else {"confirmation": confirmation},
        }
        if wire != wanted_wire or wire != artifacts[name.removesuffix(".json")]:
            raise ValueError("E_ACK_WIRE_BINDING")
    if terminal:
        saved = _sqlite_descriptor(row, row["terminal_artifact"], "E_ACK_TERMINAL_ARTIFACT")
        if saved != {key: value for key, value in row.items() if key != "terminal_artifact"}:
            raise ValueError("E_ACK_TERMINAL_ARTIFACT")


def aggregate_repair_evidence(
    required_ids: list[str], results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate exact terminal records. An unsupported execution never qualifies."""
    errors: list[dict[str, str]] = []
    ids = [row.get("case_id", row.get("vector_id", "")) for row in results]
    exact = (bool(required_ids) and all(isinstance(i, str) and i for i in required_ids)
             and len(required_ids) == len(set(required_ids))
             and Counter(ids) == Counter(required_ids))
    if not exact:
        errors.append({"case_id": "", "error": "E_REPAIR_REQUIRED_ID_SET"})
    try:
        current = capture_binding() if any("evidence_binding" in row for row in results) else {}
    except (OSError, ValueError) as error:
        current = {}
        errors.append({"case_id": "", "error": f"E_REPAIR_BINDING_UNAVAILABLE:{error}"})
    for case_id, row in zip(ids, results, strict=True):
        try:
            status = row["status"]
            if "scoped_evidence" in row or "scoped_result" in row:
                raise ValueError("E_REPAIR_SUPPLEMENTAL_MUST_BE_SEPARATE")
            validate_case_status(row)
            if "case_id" in row and "vector_id" in row and row["case_id"] != row["vector_id"]:
                raise ValueError("E_REPAIR_CASE_ID")
            if status == "PASS":
                _verify_executed(row, current)
            elif status == "FAIL":
                _verify_executed(row, current)
                raise ValueError("E_REPAIR_REPORTED_FAILURE")
            else:
                if not (row.get("reason") or row.get("observed_error")):
                    raise ValueError("E_REPAIR_REASON_REQUIRED")
                # Existing evidence cannot disappear behind a non-PASS status.
                if "actual_artifact" in row or "evidence_binding" in row:
                    _verify_executed(row, current)
        except (KeyError, ValueError, TypeError, OSError, StopIteration) as error:
            errors.append({"case_id": str(case_id), "error": str(error)})
    full = exact and set(required_ids) == set(full_required_ids())
    counts = Counter(str(row.get("status", "INVALID")) for row in results)
    result = "FAIL" if errors else "PASS" if counts["PASS"] == len(required_ids) else "HOLD"
    return {
        "result": result, "qualification_scope": "FULL" if full else "SUBSET",
        "legacy_full_qualification": "PASS" if full and result == "PASS" else "HOLD",
        "required_id_set_complete": exact, "status_counts": dict(counts), "errors": errors,
        "pending_cases": [{"case_id": case_id, "status": row.get("status"),
                           "reason": row.get("reason", row.get("observed_error"))}
                          for case_id, row in zip(ids, results, strict=True)
                          if row.get("status") != "PASS"],
        "security_review": "NOT_REVIEWED", "production_authority": "NONE",
        "live_authority": "NONE", "money_authority": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="JSON with required_ids and results")
    args = parser.parse_args()
    payload = json.loads(args.evidence.read_text())
    result = aggregate_repair_evidence(payload["required_ids"], payload["results"])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "PASS" else 2 if result["result"] == "HOLD" else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
