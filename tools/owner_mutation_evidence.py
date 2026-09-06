"""Fresh registered mutation executions using the approved ordinary owners."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from tools.inspect_restart_state import _kill_owned_child, inspect_restart_state
from tools.run_gap_coherence_crash_matrix import (
    _artifact,
    _proc_observation,
    _verify_proc_observation,
)
from tools.run_indexeddb_crash_matrix import PACK, ROOT, _observations

CHILD = ROOT / "tools/owner_mutation_child.py"


def save(path: Path, value: Any) -> dict[str, str]:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return _artifact(path)


def process(
    case: Path, mode: str, request: dict[str, Any], name: str, *, rejection: bool = False
) -> tuple[Any, dict[str, Any]]:
    descriptor = save(case / (name + "-input.json"), request)
    start = case / (name + ".start")
    command = [
        str(Path(sys.executable).absolute()),
        "-I",
        str(CHILD),
        mode,
        descriptor["path"],
        "--start",
        str(start),
    ]
    stdout, stderr = case / (name + ".stdout"), case / (name + ".stderr")
    with stdout.open("wb") as output, stderr.open("wb") as error:
        child = subprocess.Popen(command, stdout=output, stderr=error, start_new_session=True)  # noqa: S603
        try:
            deadline = monotonic() + 20
            ready = start.with_suffix(".ready")
            while not ready.exists():
                if child.poll() is not None or monotonic() > deadline:
                    raise ValueError("E_OWNER_MUTATION_START:" + stderr.read_text())
                sleep(0.01)
            observed, raw = _proc_observation(child, case / (name + "-process.json"))
            if ready.read_text() != str(child.pid):
                raise ValueError("E_OWNER_MUTATION_PROCESS")
            start.write_text(str(child.pid))
            code = child.wait(timeout=90)
        finally:
            if child.poll() is None:
                _kill_owned_child(child)
                child.wait(timeout=5)
    if code != int(rejection) or stderr.read_bytes():
        raise ValueError("E_OWNER_MUTATION_CHILD:" + stdout.read_text() + stderr.read_text())
    envelope = json.loads(stdout.read_text())
    if set(envelope) != {"pid", "result"} or envelope["pid"] != child.pid:
        raise ValueError("E_OWNER_MUTATION_PROCESS")
    return envelope["result"], {
        "name": name,
        "mode": mode,
        "command": command,
        "pid": child.pid,
        "pgid": child.pid,
        "exit": code,
        "observed": observed,
        "raw": raw,
        "input": descriptor,
        "stdout": _artifact(stdout),
        "stderr": _artifact(stderr),
    }


def verify_process(
    row: dict[str, Any],
    case: Path,
    mode: str,
    name: str,
    request: dict[str, Any],
    result: Any,
    *,
    rejection: bool = False,
) -> None:
    from tools.verify_repair_evidence import _sqlite_descriptor, _sqlite_file

    owner = {"case_directory": str(case)}
    command = [
        str(Path(sys.executable).absolute()),
        "-I",
        str(CHILD),
        mode,
        str(case / (name + "-input.json")),
        "--start",
        str(case / (name + ".start")),
    ]
    _verify_proc_observation(row["observed"], row["raw"], command)
    if (
        row["command"] != command
        or row["name"] != name
        or row["mode"] != mode
        or row["pid"] != row["pgid"]
        or row["pid"] != row["observed"]["pid"]
        or row["pgid"] != row["observed"]["pgid"]
        or row["exit"] != int(rejection)
        or row["input"]["path"] != command[4]
        or _sqlite_descriptor(owner, row["input"], "E_OWNER_MUTATION_INPUT") != request
    ):
        raise ValueError("E_OWNER_MUTATION_PROCESS")
    for stream in ("stdout", "stderr"):
        descriptor = row[stream]
        path = _sqlite_file(
            owner, descriptor["path"], descriptor["sha256"], "E_OWNER_MUTATION_OUTPUT"
        )
        if path != case / (name + "." + stream):
            raise ValueError("E_OWNER_MUTATION_OUTPUT")
        if stream == "stderr" and path.read_bytes():
            raise ValueError("E_OWNER_MUTATION_OUTPUT")
    if _sqlite_descriptor(owner, row["stdout"], "E_OWNER_MUTATION_OUTPUT") != {
        "pid": row["pid"],
        "result": result,
    }:
        raise ValueError("E_OWNER_MUTATION_OUTPUT")


def run_sql_input(entry: dict[str, Any], case: Path) -> dict[str, Any]:
    case.mkdir(parents=True, exist_ok=False)
    run_id = str(uuid4())
    original = _observations(run_id)[0]
    altered = {**original, "content_hash": "0" * 64}
    _, setup = process(case, "sql-setup", {"observation": original}, "setup")
    before, reader_before = process(case, "sql-read", {"run_id": run_id}, "reader-before")
    result, trial = process(
        case, "sql-input", {"run_id": run_id, "observation": altered}, "trial", rejection=True
    )
    after, reader_after = process(case, "sql-read", {"run_id": run_id}, "reader-after")
    return {
        "case_id": entry["vector_id"],
        "case_directory": str(case),
        "identity": {
            "run_id": run_id,
            "case_id": entry["vector_id"],
            "checkpoint_id": entry["crash_checkpoint"],
        },
        "original_input": original,
        "mutated_input": altered,
        "before": before,
        "after": after,
        "observed_error": result.get("observed_error"),
        "processes": [setup, reader_before, trial, reader_after],
    }


def compare_mutation(execution: dict[str, Any], oracle: dict[str, Any]) -> None:
    actual: dict[str, object]
    if execution.get("execution_kind") == "SQLITE_TRANSACTION_PROCESS_CRASH":
        actual = {"retained_rows": len(execution["actual"]["before"]["tables"]["raw_commits"])}
    else:
        actual = {"retained_rows": len(execution["actual"]["entries"])}
    inspect_restart_state(actual, oracle)


def campaign(
    entries: list[dict[str, Any]], workspace: Path, controls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from tools.verify_repair_evidence import capture_binding

    binding = capture_binding()
    mutations = []
    for entry, control in zip(entries, controls, strict=True):
        for kind, mutation_id in zip(
            ("EXPECTED", "INPUT"), entry["mutation_vector_ids"], strict=True
        ):
            case = (workspace / mutation_id).resolve()
            case.mkdir(parents=True, exist_ok=False)
            request = {"case_id": entry["vector_id"], "kind": kind}
            execution, launched = process(case, "case", request, "owner")
            oracle = {"retained_rows": 99} if kind == "EXPECTED" else None
            if kind == "EXPECTED":
                assert oracle is not None
                try:
                    compare_mutation(execution, oracle)
                except ValueError as error:
                    observed_error = str(error)
                else:
                    raise ValueError("E_OWNER_MUTATION_SURVIVOR")
            else:
                observed_error = execution["observed_error"]
            row = {
                "mutation": mutation_id,
                "vector_id": entry["vector_id"],
                "kind": kind,
                "case_directory": str(case),
                "execution": execution,
                "process": launched,
                "control": control,
                "oracle": oracle,
                "oracle_artifact": save(case / "oracle.json", oracle),
                "observed_error": observed_error,
                "detected": True,
                "evidence_binding": binding,
                "revision": binding["revision"],
                "environment": binding["environment"],
            }
            verify_mutation(entry["harness"], row, binding, terminal=False)
            row["terminal_artifact"] = save(case / "mutation-terminal.json", row)
            mutations.append(row)
    return mutations


def verify_mutation(
    harness: str, row: dict[str, Any], binding: dict[str, Any], *, terminal: bool = True
) -> None:
    from moj_discovery.canonical import canonical_content_hash
    from tools.verify_repair_evidence import (
        _sqlite_descriptor,
        _validate_sqlite_state,
        _verify_executed,
    )

    required = {
        "mutation",
        "vector_id",
        "kind",
        "execution",
        "process",
        "control",
        "oracle",
        "oracle_artifact",
        "observed_error",
        "detected",
        "evidence_binding",
        "revision",
        "environment",
        "case_directory",
    }
    if not required.issubset(row):
        raise ValueError("E_OWNER_MUTATION_BINDING")
    if terminal and "terminal_artifact" not in row:
        raise ValueError("E_OWNER_MUTATION_TERMINAL")
    entries = [
        item
        for item in json.loads(
            (PACK / "docs/registries/crash-harness-registry.v1.json").read_text()
        )["entries"]
        if item["vector_id"] == row["vector_id"]
    ]
    if len(entries) != 1:
        raise ValueError("E_OWNER_MUTATION_BINDING")
    entry = entries[0]
    kind = row["kind"]
    if (
        harness != entry["harness"]
        or kind not in {"INPUT", "EXPECTED"}
        or row["mutation"] != entry["mutation_vector_ids"][int(kind == "INPUT")]
        or row["evidence_binding"] != binding
        or row["revision"] != binding["revision"]
        or row["environment"] != binding["environment"]
        or row["detected"] is not True
    ):
        raise ValueError("E_OWNER_MUTATION_BINDING")
    execution, control = row["execution"], row["control"]
    _verify_executed(control, binding)
    if (
        execution["case_id"] != row["vector_id"]
        or control["case_id"] != row["vector_id"]
        or execution["identity"]["run_id"] == control["identity"]["run_id"]
        or Path(execution["case_directory"]).is_relative_to(Path(control["case_directory"]))
    ):
        raise ValueError("E_OWNER_MUTATION_IDENTITY")
    case = Path(row["case_directory"])
    if not Path(execution["case_directory"]).is_relative_to(case / "execution"):
        raise ValueError("E_OWNER_MUTATION_IDENTITY")
    verify_process(
        row["process"],
        case,
        "case",
        "owner",
        {"case_id": row["vector_id"], "kind": kind},
        execution,
    )
    if _sqlite_descriptor(row, row["oracle_artifact"], "E_OWNER_MUTATION_ORACLE") != row["oracle"]:
        raise ValueError("E_OWNER_MUTATION_ORACLE")
    if kind == "EXPECTED":
        _verify_executed(execution, binding)
        if (
            row["oracle"] != {"retained_rows": 99}
            or row["observed_error"] != "E_RESTART_STATE_MISMATCH"
        ):
            raise ValueError("E_OWNER_MUTATION_ORACLE")
        try:
            compare_mutation(execution, row["oracle"])
        except ValueError as error:
            if str(error) != row["observed_error"]:
                raise ValueError("E_OWNER_MUTATION_REJECTION") from error
        else:
            raise ValueError("E_OWNER_MUTATION_SURVIVOR")
    elif harness == "SQLITE_TRANSACTION":
        original, altered = execution["original_input"], execution["mutated_input"]
        if (
            altered != {**original, "content_hash": "0" * 64}
            or canonical_content_hash(
                "RawObservation",
                original,
                registry_path=PACK / "registries/canonical-hash-domains.v1.json",
            )
            != original["content_hash"]
            or execution["before"] != execution["after"]
            or row["oracle"] is not None
            or row["observed_error"] != "CONTENT_HASH_MISMATCH"
            or execution["observed_error"] != row["observed_error"]
        ):
            raise ValueError("E_OWNER_MUTATION_INPUT")
        _validate_sqlite_state(execution["before"], {"observation": original}, 0)
        run_id = original["discovery_run_id"]
        if execution["identity"] != {
            "run_id": run_id,
            "case_id": entry["vector_id"],
            "checkpoint_id": entry["crash_checkpoint"],
        }:
            raise ValueError("E_OWNER_MUTATION_IDENTITY")
        values = [
            ("sql-setup", "setup", {"observation": original}, {"completed": True}, False),
            ("sql-read", "reader-before", {"run_id": run_id}, execution["before"], False),
            (
                "sql-input",
                "trial",
                {"run_id": run_id, "observation": altered},
                {"observed_error": "CONTENT_HASH_MISMATCH"},
                True,
            ),
            ("sql-read", "reader-after", {"run_id": run_id}, execution["after"], False),
        ]
        if len(execution["processes"]) != 4 or len({p["pid"] for p in execution["processes"]}) != 4:
            raise ValueError("E_OWNER_MUTATION_PROCESS")
        for p, (mode, name, request, result, rejected) in zip(
            execution["processes"], values, strict=True
        ):
            verify_process(
                p,
                Path(execution["case_directory"]),
                mode,
                name,
                request,
                result,
                rejection=rejected,
            )
    else:
        from tools.verify_repair_evidence import _verify_browser_ack

        _verify_browser_ack(execution, binding, input_mutation=True)
        if row["oracle"] is not None or row["observed_error"] != "E_SPOOL_OBSERVATION_BINDING":
            raise ValueError("E_OWNER_MUTATION_REJECTION")
    if "terminal_artifact" in row and _sqlite_descriptor(
        row, row["terminal_artifact"], "E_OWNER_MUTATION_TERMINAL"
    ) != {k: v for k, v in row.items() if k != "terminal_artifact"}:
        raise ValueError("E_OWNER_MUTATION_TERMINAL")


def browser_input(
    entry: dict[str, Any],
    case: Path,
    socket: str,
    request: dict[str, Any],
    identity: dict[str, Any],
    binding: dict[str, Any],
    extension: Path,
    binary: Path,
    observations: list[dict[str, Any]],
    browser_process: subprocess.Popen[bytes],
    profile: Path,
    sentinel: str,
    inputs: dict[str, Any],
    artifacts: dict[str, Any],
    processes: list[dict[str, Any]],
    readers: list[dict[str, Any]],
    loaded_assets: dict[str, Any],
    marker: dict[str, Any],
    profile_before: dict[str, Any],
    browser_before: dict[str, Any],
    launch: dict[str, Any],
    retain: Callable[..., Any],
    read_browser: Callable[..., Any],
    read_backend: Callable[..., Any],
    stop: Callable[..., Any],
) -> dict[str, Any]:
    from tools.qualify_chrome_indexeddb import _browser_process_observation, _evaluate
    from tools.run_indexeddb_crash_matrix import _call
    from tools.verify_repair_evidence import _verify_browser_ack

    initialize = {
        "identity": request["identity"],
        "options": request["options"],
        "operation": "initialize",
        "observations": [],
    }
    retain("initialize-worker", initialize, is_input=True)
    initialize_id = str(uuid4())
    retain("initialize-output", _call(socket, "startWorker", initialize_id, initialize))
    _call(socket, "terminateWorker", initialize_id)
    before = read_browser("before")
    backend_before, reader_before = process(
        case, "sql-read", {"run_id": identity["run_id"]}, "mutation-reader-before"
    )
    altered = copy.deepcopy(request)
    raw = json.loads(altered["observations"][0])
    raw["content_hash"] = "0" * 64
    altered["observations"][0] = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    retain("mutated-worker", altered, is_input=True)
    worker_id = str(uuid4())
    result = _evaluate(
        socket,
        "globalThis.repairProbe.startWorker("
        + json.dumps(worker_id)
        + ","
        + json.dumps(altered)
        + ")",
    )
    termination = _call(socket, "terminateWorker", worker_id)
    retain("rejection", result)
    if result != {"error": "Error: E_SPOOL_OBSERVATION_BINDING", "worker_id": worker_id}:
        raise ValueError("E_OWNER_MUTATION_REJECTION:" + str(result))
    after = read_browser("after")
    backend_after, reader_after = process(
        case, "sql-read", {"run_id": identity["run_id"]}, "mutation-reader-after"
    )
    readers.extend((reader_before, reader_after))
    stop(False)
    profile_after = retain(
        "profile-after",
        {
            "profile_path": str(profile.resolve()),
            "marker": (profile / "BH_R05_PROFILE_ID").read_text(),
            "sentinel": _call(socket, "readSentinel", identity["profile_id"]),
        },
    )
    browser_after = retain("browser-process-after", _browser_process_observation(browser_process))
    retain("backend-before", backend_before)
    retain("backend-after", backend_after)
    retain("expected", entry["expected_post_restart_state"])
    row = {
        "case_id": entry["vector_id"],
        "vector_id": entry["vector_id"],
        "case_directory": str(case.resolve()),
        "status": "PASS",
        "result": "PASS",
        "executed": True,
        "launch_attempted": True,
        "qualification_scope": "BROWSER_LOOPBACK_ACK",
        "execution_kind": "BROWSER_LOOPBACK_ACK",
        "input_rejection": True,
        "identity": identity,
        "worker_id": worker_id,
        "termination": termination,
        "actual": before,
        "browser_after": after,
        "backend_before": backend_before,
        "backend_after": backend_after,
        "observations": observations,
        "expected": entry["expected_post_restart_state"],
        "observed_error": "E_SPOOL_OBSERVATION_BINDING",
        "comparison": {"matched": True},
        "evidence_binding": binding,
        "revision": binding["revision"],
        "environment": binding["environment"],
        "inputs": inputs,
        "artifacts": artifacts,
        "reader_runs": readers,
        "backend_processes": processes,
        "browser": {"executable": str(binary), "sha256": _artifact(binary)["sha256"]},
        "loaded_assets": loaded_assets,
        "profile_readbacks": {
            "before": profile_before,
            "after": profile_after,
            "marker": marker,
            "sentinel": sentinel,
        },
        "browser_provenance": {"launch": launch, "before": browser_before, "after": browser_after},
        "module_hashes": {
            str(p.relative_to(extension)): _artifact(p)["sha256"] for p in extension.rglob("*.js")
        },
    }
    _verify_browser_ack(row, binding, terminal=False, input_mutation=True)
    row["terminal_artifact"] = save(case / "terminal-result.json", row)
    return row


def verify_browser_input(
    row: dict[str, Any], inputs: dict[str, Any], artifacts: dict[str, Any], *, terminal: bool
) -> None:
    from tools.run_indexeddb_crash_matrix import PRODUCER, REGISTRY, STREAM, compare_indexeddb_state
    from tools.verify_repair_evidence import (
        _contains_expected,
        _sqlite_descriptor,
        _sqlite_process_prefix,
        _validate_sqlite_state,
    )

    identity = row["identity"]
    expected_identity = {
        k: identity[k]
        for k in (
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
    if set(inputs) != {
        "server-input-0",
        "worker",
        "initialize-worker",
        "mutated-worker",
        "browser-reader-before",
        "browser-reader-after",
    } or _contains_expected(inputs):
        raise ValueError("E_OWNER_MUTATION_INPUT")
    wanted = {
        "identity": expected_identity,
        "options": options,
        "operation": "crash" if identity["component"] == "CHROME_INDEXEDDB" else "deliver",
        "observations": [
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in row["observations"]
        ],
        "transport": worker["transport"],
    }
    altered = copy.deepcopy(wanted)
    original = row["observations"][0]
    altered["observations"][0] = json.dumps(
        {**original, "content_hash": "0" * 64}, sort_keys=True, separators=(",", ":")
    )
    if (
        worker != wanted
        or inputs["mutated-worker"] != altered
        or original["discovery_run_id"] != identity["run_id"]
    ):
        raise ValueError("E_OWNER_MUTATION_INPUT")
    from moj_discovery.canonical import canonical_content_hash

    if original["content_hash"] != canonical_content_hash(
        "RawObservation", original, registry_path=REGISTRY
    ):
        raise ValueError("E_OWNER_MUTATION_INPUT")
    initialize = {
        "identity": expected_identity,
        "options": options,
        "operation": "initialize",
        "observations": [],
    }
    if inputs["initialize-worker"] != initialize:
        raise ValueError("E_OWNER_MUTATION_INPUT")
    states = (artifacts["initialize-output"], row["actual"], row["browser_after"])
    for state in states:
        compare_indexeddb_state(state, identity, row["observations"], 0)
    workers = [state["worker_id"] for state in states] + [row["worker_id"]]
    if len(set(workers)) != 4 or row["termination"] != {
        "method": "Worker.terminate",
        "worker_id": row["worker_id"],
    }:
        raise ValueError("E_OWNER_MUTATION_PROCESS")
    if (
        artifacts["rejection"]
        != {"error": "Error: E_SPOOL_OBSERVATION_BINDING", "worker_id": row["worker_id"]}
        or row["observed_error"] != "E_SPOOL_OBSERVATION_BINDING"
    ):
        raise ValueError("E_OWNER_MUTATION_REJECTION")
    if row["backend_before"] != row["backend_after"] or len(row["backend_processes"]) != 1:
        raise ValueError("E_OWNER_MUTATION_STATE")
    server = row["backend_processes"][0]
    prefix = _sqlite_process_prefix(
        server["provenance"],
        ROOT / "tools/loopback_ack_crash_child.py",
        row["evidence_binding"],
        "E_OWNER_MUTATION_PROCESS",
    )
    command = [*prefix, "--browser-server", row["inputs"]["server-input-0"]["path"]]
    _verify_proc_observation(server["observed"], server["raw_process"], command)
    server_identity = {k: v for k, v in expected_identity.items() if k not in {"pid", "profile_id"}}
    config = inputs["server-input-0"]
    ready = artifacts["server-ready-0"]
    if (
        server["argv"] != command
        or server["pid"] != server["observed"]["pid"]
        or server["pgid"] != server["pid"]
        or server["exit"] != -15
        or server["mechanism"] != "POSIX_OWNED_PROCESS_GROUP_SIGTERM_CLEANUP"
        or config
        != {
            "identity": server_identity,
            "observation": original,
            "origin": identity["origin"],
            "token": config["token"],
            "restart": False,
        }
        or ready["identity"] != {**server_identity, "pid": server["pid"]}
        or _sqlite_descriptor(row, server["ready"], "E_OWNER_MUTATION_PROCESS") != ready
        or ready["address"][0] != "127.0.0.1"
        or worker["transport"]
        != {"endpoint": "http://127.0.0.1:" + str(ready["address"][1]), "token": config["token"]}
    ):
        raise ValueError("E_OWNER_MUTATION_PROCESS")
    if [r["name"] for r in row["reader_runs"]] != [
        "mutation-reader-before",
        "mutation-reader-after",
    ] or len({r["pid"] for r in row["reader_runs"]}) != 2:
        raise ValueError("E_OWNER_MUTATION_READER")
    for phase, state in (("before", row["actual"]), ("after", row["browser_after"])):
        if (
            artifacts["browser-" + phase] != state
            or artifacts["backend-" + phase] != row["backend_" + phase]
            or inputs["browser-reader-" + phase] != {**initialize, "operation": "read"}
        ):
            raise ValueError("E_OWNER_MUTATION_READER")
        _validate_sqlite_state(row["backend_" + phase], {"observation": original}, 0)
        reader = next(r for r in row["reader_runs"] if r["name"] == "mutation-reader-" + phase)
        verify_process(
            reader,
            Path(row["case_directory"]),
            "sql-read",
            "mutation-reader-" + phase,
            {"run_id": identity["run_id"]},
            row["backend_" + phase],
        )
    if artifacts["expected"] != row["expected"]:
        raise ValueError("E_OWNER_MUTATION_ORACLE")
    if terminal and _sqlite_descriptor(
        row, row["terminal_artifact"], "E_OWNER_MUTATION_TERMINAL"
    ) != {k: v for k, v in row.items() if k != "terminal_artifact"}:
        raise ValueError("E_OWNER_MUTATION_TERMINAL")
