"""Native qualification must execute Ingestor, not the RunStore-only fixture."""

from __future__ import annotations

import copy
import importlib
from pathlib import Path
from typing import Any, cast

import pytest


@pytest.fixture(scope="module")
def owner() -> Any:
    name = "tools.run_native_ingestor_qualification"
    assert importlib.util.find_spec(name) is not None, "Missing native Ingestor owner"
    return importlib.import_module(name)


@pytest.fixture(scope="module")
def report(owner: Any, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return cast(
        dict[str, Any], owner.run_native_ingestor(tmp_path_factory.mktemp("native-ingestor"))
    )


def test_actual_native_ingestor_boundaries(owner: Any, report: dict[str, Any]) -> None:
    assert report["result"] == "PASS"
    assert [len(row["after"]["tables"]["raw_commits"]) for row in report["cases"]] == [0, 1]
    for row in report["cases"]:
        assert len(row["replayed"]["tables"]["raw_commits"]) == 1
        assert row["replayed"] == row["replayed_again"]
        assert row["termination"]["mechanism"] == "WINDOWS_TERMINATE_PROCESS_OWNED_HANDLE"
    owner.verify_native_ingestor(report)


@pytest.mark.parametrize("reuse", ["distinct_creation", "duplicate_identity", "live_controller"])
def test_sequential_native_identity_uses_creation_time(
    owner: Any, report: dict[str, Any], reuse: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    row = copy.deepcopy(report)
    first, later = row["cases"][0]["processes"][0], row["cases"][0]["processes"][4]
    previous = first["observed"] if reuse != "live_controller" else row["controller"]
    observed = later["observed"]
    observed["pid"] = observed["cim"]["ProcessId"] = previous["pid"]
    if reuse == "duplicate_identity":
        observed["cim"]["CreationDate"] = previous["cim"]["CreationDate"]
    else:
        assert observed["cim"]["CreationDate"] != previous["cim"]["CreationDate"]
    observed["cim_raw"] = json.dumps(observed["cim"])
    later["value"]["pid"] = previous["pid"]
    read = Path.read_bytes
    virtual: dict[Path, bytes] = {}

    def replace(descriptor: dict[str, str], value: Any) -> None:
        content = json.dumps(value).encode()
        virtual[owner.localpath(descriptor["path"])] = content
        descriptor["sha256"] = hashlib.sha256(content).hexdigest()

    replace(later["stdout"], later["value"])
    raw = json.loads(read(owner.localpath(row["stdout"]["path"])))
    raw["cases"] = row["cases"]
    replace(row["stdout"], raw)
    monkeypatch.setattr(Path, "read_bytes", lambda path: virtual.get(path, read(path)))
    if reuse == "distinct_creation":
        owner.verify_native_ingestor(row)
    else:
        with pytest.raises(ValueError, match="E_NATIVE_INGESTOR_EVIDENCE") as error:
            owner.verify_native_ingestor(row)
        assert str(error.value.__cause__) in {
            "independent process identity",
            "E_ENV_NATIVE_OBSERVATION",
        }


def test_native_ingestor_records_actual_loaded_modules(report: dict[str, Any]) -> None:
    for case in report["cases"]:
        for process in case["processes"]:
            loaded = process["value"].get("loaded_dependencies")
            assert loaded is not None, "Missing actual native dependency import evidence"
            assert len(loaded["modules"]) == 7
            assert loaded["native_rpds"]["path"].endswith("rpds.cp312-win_amd64.pyd")


def test_environment_aggregate_consumes_verified_native_ingestor(
    owner: Any, report: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import run_environment_qualification as environment

    fixtures = [
        (
            "run_native_storage",
            "native-terminal.json",
            {"cases": [], "native_ingestor": "OLD_HOLD"},
        ),
        (
            "run_filesystem_faults",
            "filesystem-terminal.json",
            {"faults": [], "commit_io": {"records": []}},
        ),
        ("run_browser_restart", "browser-terminal.json", {"result": "PASS"}),
        (
            "run_windows_browser",
            "windows-browser-terminal.json",
            {"result": "PASS", "restart_result": "PASS", "observed_error": None},
        ),
    ]
    for name, terminal, value in fixtures:

        def other(path: Path, value: Any = value, terminal: str = terminal) -> Any:
            path.mkdir(parents=True)
            environment.save(path / terminal, value)
            return value

        monkeypatch.setattr(environment, name, other)

    def native(path: Path) -> dict[str, Any]:
        path.mkdir(parents=True)
        environment.save(path / "native-ingestor-terminal.json", report)
        return report

    monkeypatch.setattr(owner, "run_native_ingestor", native)
    aggregate = environment.run_environment_qualification(tmp_path / "aggregate")
    matches = [row for row in aggregate["cases"] if row["case_id"] == "NATIVE-WINDOWS-INGESTOR"]
    assert matches[0]["result"] == "PASS", (
        "Aggregate still disconnected from executed native Ingestor"
    )
    assert aggregate["reports"]["native_ingestor"] == report
    assert (
        next(
            row for row in aggregate["cases"] if row["case_id"] == "NATIVE-WINDOWS-SQL06-COMMIT-IO"
        )["result"]
        == "PASS"
    )
    assert {row["case_id"] for row in report["cases"]} <= {
        row["case_id"] for row in aggregate["cases"]
    }


@pytest.mark.parametrize(
    "damage",
    [
        "reader_exit",
        "missing_store",
        "stale_identity",
        "oracle",
        "rollback",
        "durable",
        "replay_duplicate",
        "dependency",
        "graceful",
        "creation",
    ],
)
def test_native_ingestor_evidence_rejects_damage(
    owner: Any, report: dict[str, Any], damage: str
) -> None:
    row = copy.deepcopy(report)
    case = row["cases"][0]
    if damage == "reader_exit":
        case["processes"][2]["exit"] = 1
    elif damage == "missing_store":
        case["after"] = {"observed_error": "E_RESTART_MISSING_DATABASE"}
    elif damage == "stale_identity":
        case["checkpoint"]["identity"]["run_id"] = "stale"
    elif damage == "oracle":
        case["inputs"]["read"]["value"]["expected"] = "injected"
    elif damage == "rollback":
        case["after"] = copy.deepcopy(case["replayed"])
    elif damage == "durable":
        row["cases"][1]["after"] = copy.deepcopy(row["cases"][1]["before"])
    elif damage == "replay_duplicate":
        case["replayed_again"]["tables"]["raw_commits"].append(
            copy.deepcopy(case["replayed_again"]["tables"]["raw_commits"][0])
        )
    elif damage == "dependency":
        row["dependency"]["files"]["rpds/rpds.cp312-win_amd64.pyd"] = "0" * 64
    elif damage == "creation":
        del case["writer"]["cim"]["CreationDate"]
    else:
        case["termination"]["mechanism"] = "GRACEFUL"
    with pytest.raises(ValueError, match="E_NATIVE_INGESTOR_EVIDENCE"):
        owner.verify_native_ingestor(row)


@pytest.mark.parametrize(
    "damage", ["rollback", "replay_duplicate", "reader_error", "oracle", "creation"]
)
def test_coherent_native_evidence_cannot_replace_state_or_identity(
    owner: Any, report: dict[str, Any], damage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    row = copy.deepcopy(report)
    case = row["cases"][0]
    virtual: dict[Path, bytes] = {}
    read = Path.read_bytes

    def replace(descriptor: dict[str, str], value: Any) -> None:
        content = json.dumps(value).encode()
        virtual[owner.localpath(descriptor["path"])] = content
        descriptor["sha256"] = hashlib.sha256(content).hexdigest()

    if damage == "rollback":
        case["after"] = copy.deepcopy(case["replayed"])
        process = case["processes"][2]
        process["value"]["state"] = case["after"]
        replace(process["stdout"], process["value"])
    elif damage == "replay_duplicate":
        state = case["replayed_again"]
        state["tables"]["raw_commits"].append(copy.deepcopy(state["tables"]["raw_commits"][0]))
        process = case["processes"][4]
        process["value"]["state"] = state
        replace(process["stdout"], process["value"])
    elif damage == "reader_error":
        process = case["processes"][2]
        process["value"]["observed_error"] = "E_RESTART_MISSING_DATABASE"
        replace(process["stdout"], process["value"])
    elif damage == "oracle":
        item = case["inputs"]["read"]
        item["value"]["expected"] = "injected"
        replace(item["artifact"], item["value"])
    else:
        process = case["processes"][2]
        del process["observed"]["cim"]["CreationDate"]
        process["observed"]["cim_raw"] = json.dumps(process["observed"]["cim"])
    raw = json.loads(read(owner.localpath(row["stdout"]["path"])))
    raw["cases"] = row["cases"]
    replace(row["stdout"], raw)
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: virtual[path] if path in virtual else read(path)
    )
    with pytest.raises(ValueError, match="E_NATIVE_INGESTOR_EVIDENCE") as rejected:
        owner.verify_native_ingestor(row)
    assert str(rejected.value.__cause__) in {
        "E_SQLITE_JOURNAL_STATE",
        "reader success",
        "oracle-free child input",
        "E_ENV_NATIVE_OBSERVATION",
    }, rejected.value.__cause__


@pytest.mark.parametrize("damage", ["payload", "rehashed_preparation"])
def test_native_dependency_payload_cannot_be_rehashed_as_authority(
    owner: Any, damage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    from tools.native_ingestor_probe import dependency_payload

    root = owner.DEPENDENCIES
    payload = root / "site-packages/rpds/rpds.cp312-win_amd64.pyd"
    preparation = root / "preparation.json"
    read = Path.read_bytes
    changed = read(payload) + b"changed-native-payload"
    virtual = {payload: changed}
    if damage == "rehashed_preparation":
        value = json.loads(read(preparation))
        value["file_sha256"]["rpds/rpds.cp312-win_amd64.pyd"] = hashlib.sha256(changed).hexdigest()
        virtual[preparation] = json.dumps(value).encode()
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: virtual[path] if path in virtual else read(path)
    )
    with pytest.raises(ValueError, match="E_NATIVE_DEPENDENCY_(PAYLOAD|PREPARATION)"):
        dependency_payload(root)


@pytest.mark.parametrize(
    "damage,error",
    [
        ("missing", "E_RESTART_MISSING_DATABASE"),
        ("oracle", "E_NATIVE_INGESTOR_INPUT"),
        ("identity", "E_NATIVE_INGESTOR_IDENTITY"),
    ],
)
def test_real_native_reader_rejects_input_without_creating_store(
    owner: Any, tmp_path: Path, damage: str, error: str
) -> None:
    import json
    import subprocess
    from uuid import uuid4

    case = owner.WINDOWS_PARENT / ("native-ingestor-negative-" + str(uuid4()))
    case.mkdir()
    run_id = str(uuid4())
    run_dir = case / run_id
    identity = {"run_id": run_id, "case_id": owner.PHASES[0], "checkpoint_id": owner.PHASES[0]}
    value = {
        "root": owner.winpath(owner.ROOT),
        "dependency_root": owner.winpath(owner.DEPENDENCIES),
        "run_dir": owner.winpath(run_dir),
        "identity": identity,
    }
    if damage == "oracle":
        value["expected"] = "injected"
    elif damage == "identity":
        identity["run_id"] = "stale"
    path = tmp_path / "input.json"
    path.write_text(json.dumps(value))
    (case / "read.start").touch()  # Release only this negative reader, not a crash checkpoint.
    command = [
        str(owner.NATIVE),
        "-I",
        "-B",
        owner.winpath(owner.SCRIPT),
        "read",
        owner.winpath(path),
    ]
    assert not run_dir.exists()
    process = subprocess.run(command, capture_output=True, timeout=30)  # noqa: S603
    (tmp_path / "stdout").write_bytes(process.stdout)
    (tmp_path / "stderr").write_bytes(process.stderr)
    assert process.returncode == 1
    assert error in process.stderr.decode()
    assert process.stdout == b""
    assert not run_dir.exists()
