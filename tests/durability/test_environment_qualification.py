"""Environment evidence is real, bounded and never physical-power qualification."""

import copy
import hashlib
import importlib
import json
import shutil
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


def owner() -> ModuleType:
    try:
        return importlib.import_module("tools.run_environment_qualification")
    except ModuleNotFoundError:
        pytest.fail(
            "environment owner absent: native handles, corruption and browser restart unqualified"
        )


def test_checked_uses_explicit_retained_boundary_without_original_fallback(
    tmp_path: Path,
) -> None:
    from tools.retained_artifact_io import RetainedArtifactIO

    recorded_root = "/mnt/c/Users/thenam/Documents/native-case"
    recorded = recorded_root + "/input.json"
    data = b'{"native":true}'
    closure = tmp_path / "closure"
    (closure / "files").mkdir(parents=True)
    (closure / "files/input.json").write_bytes(data)
    artifacts = RetainedArtifactIO.from_manifest(
        {
            "schema_version": "retained-artifact-manifest/v1",
            "recorded_boundaries": [recorded_root],
            "files": [
                {
                    "recorded_locator": recorded,
                    "recorded_boundary": recorded_root,
                    "copied_relative_path": "files/input.json",
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            ],
        },
        closure,
    )
    descriptor = {
        "path": r"C:\Users\thenam\Documents\native-case\input.json",
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    with pytest.raises(ValueError, match="E_ENV_ARTIFACT_BOUNDARY"):
        owner().checked(descriptor, artifacts=artifacts)
    assert (
        owner().checked(
            descriptor,
            artifacts=artifacts,
            recorded_boundary=r"C:\Users\thenam\Documents\native-case",
        )
        == data
    )


def test_environment_aggregate_dispatches_every_owner_and_keeps_power_hold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = owner()
    seen: list[str] = []
    monkeypatch.setattr(module, "capture_binding", lambda: {"source": "current"})
    for name in (
        "verify_native_storage",
        "verify_filesystem_faults",
        "verify_browser_restart",
        "verify_windows_browser",
    ):
        monkeypatch.setattr(
            module,
            name,
            lambda _report, *, artifacts=None, owner=name: seen.append(owner),
        )
    import tools.run_native_ingestor_qualification as native

    monkeypatch.setattr(
        native,
        "verify_native_ingestor",
        lambda _report, *, artifacts=None: seen.append("native_ingestor"),
    )
    monkeypatch.setattr(
        native,
        "verify_native_commit_io",
        lambda _report, *, artifacts=None: seen.append("native_commit_io"),
    )
    reports = {
        "native": {"cases": []},
        "filesystem": {"faults": [], "commit_io": {"records": []}},
        "linux_browser": {"result": "PASS"},
        "windows_browser": {
            "restart_result": "PASS",
            "result": "HOLD",
            "observed_error": "NO_TARGET",
        },
        "native_ingestor": {"result": "PASS", "cases": []},
        "native_commit_io": {"native_sql06": "PASS"},
    }
    terminal_files = []
    for name, value in reports.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value, sort_keys=True))
        terminal_files.append(
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    report = {
        "result": "PARTIAL_HOLD",
        "binding": {"source": "current"},
        "cases": module._environment_case_projection(reports),
        "reports": reports,
        "scope": "SUPPLEMENTAL_ENVIRONMENT_ONLY",
        "production_authority": "NONE",
        "live_authority": "NONE",
        "money_authority": "NONE",
        "full111": "NOT_RERUN_AT_THIS_SOURCE",
        "security_review": "NOT_REVIEWED",
        "terminal_files": terminal_files,
    }
    module.verify_environment_qualification(report)
    assert set(seen) == {
        "verify_native_storage",
        "verify_filesystem_faults",
        "verify_browser_restart",
        "verify_windows_browser",
        "native_ingestor",
        "native_commit_io",
    }
    report["result"] = "PASS"
    with pytest.raises(ValueError, match="E_ENVIRONMENT_QUALIFICATION"):
        module.verify_environment_qualification(report)


def test_supplemental_evidence_replays_from_closed_copy_without_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.run_full_repair_qualification import (
        collect_retained_sources,
        write_closed_inventory,
    )

    module = owner()
    monkeypatch.setattr(module, "capture_binding", lambda: {"source": "current"})
    for name in (
        "verify_native_storage",
        "verify_filesystem_faults",
        "verify_browser_restart",
        "verify_windows_browser",
    ):
        monkeypatch.setattr(module, name, lambda _report, *, artifacts=None: None)
    import tools.run_native_ingestor_qualification as native

    monkeypatch.setattr(native, "verify_native_ingestor", lambda _report, *, artifacts=None: None)
    monkeypatch.setattr(native, "verify_native_commit_io", lambda _report, *, artifacts=None: None)
    workspace = tmp_path / "original"
    workspace.mkdir()
    reports = {
        "native": {"cases": []},
        "filesystem": {"faults": [], "commit_io": {"records": []}},
        "linux_browser": {"result": "PASS"},
        "windows_browser": {
            "restart_result": "PASS",
            "result": "HOLD",
            "observed_error": "NO_TARGET",
        },
        "native_ingestor": {"result": "PASS", "cases": []},
        "native_commit_io": {"native_sql06": "PASS"},
    }
    terminals = []
    for name, value in reports.items():
        path = workspace / f"{name}.json"
        path.write_text(json.dumps(value, sort_keys=True))
        terminals.append(
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    aggregate = workspace / "environment-aggregate.json"
    report = {
        "result": "PARTIAL_HOLD",
        "binding": {"source": "current"},
        "cases": module._environment_case_projection(reports),
        "reports": reports,
        "scope": "SUPPLEMENTAL_ENVIRONMENT_ONLY",
        "production_authority": "NONE",
        "live_authority": "NONE",
        "money_authority": "NONE",
        "full111": "NOT_RERUN_AT_THIS_SOURCE",
        "security_review": "NOT_REVIEWED",
        "terminal_files": terminals,
    }
    aggregate.write_text(json.dumps(report, sort_keys=True))
    inventory = tmp_path / "evidence/inventory.json"
    inventory.parent.mkdir()
    sources = [
        (aggregate, str(aggregate), str(workspace)),
        *collect_retained_sources(
            report, retained_boundaries=(workspace,), live_roots=(Path(__file__).parents[2],)
        ),
    ]
    manifest = write_closed_inventory(sources, inventory)
    qualification = SimpleNamespace(
        environment_qualification_aggregate=aggregate,
        environment_qualification_inventory=inventory,
    )
    config = SimpleNamespace(qualification_evidence=qualification, chrome_path=Path(__file__))
    shutil.rmtree(workspace)

    proof = module.verify_environment_qualification_evidence(aggregate, inventory, config)
    assert proof["result"] == "PARTIAL_HOLD"
    terminal_row = next(
        row for row in manifest["files"] if row["recorded_locator"] == terminals[0]["path"]
    )
    copied = inventory.parent / "retained" / terminal_row["copied_relative_path"]
    copied.write_bytes(b"changed")
    with pytest.raises(ValueError, match="E_ENVIRONMENT_QUALIFICATION"):
        module.verify_environment_qualification_evidence(aggregate, inventory, config)
    report["result"] = "PARTIAL_HOLD"
    report["cases"].append(dict(report["cases"][0]))
    with pytest.raises(ValueError, match="E_ENVIRONMENT_QUALIFICATION"):
        module.verify_environment_qualification(report)


def test_native_owned_termination_preserves_only_committed_state(tmp_path: Path) -> None:
    report = owner().run_native_storage(tmp_path)
    assert report["result"] == "PASS"
    assert [row["after"]["tables"]["run_meta"][0]["run_status"] for row in report["cases"]] == [
        "OPEN",
        "CLOSED",
    ]
    assert all(
        row["termination"]["mechanism"] == "WINDOWS_TERMINATE_PROCESS_OWNED_HANDLE"
        for row in report["cases"]
    )
    owner().verify_native_storage(report)


@pytest.fixture(scope="module")
def native_storage_identity_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return dict(owner().run_native_storage(tmp_path_factory.mktemp("native-storage-identities")))


@pytest.mark.parametrize("reuse", ["distinct_creation", "duplicate_identity", "live_controller"])
def test_native_storage_sequential_identity_uses_creation_time(
    native_storage_identity_report: dict[str, Any], reuse: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = owner()
    row = copy.deepcopy(native_storage_identity_report)
    first, later = row["cases"][0]["processes"][0], row["cases"][0]["processes"][2]
    previous = first["observed"]
    pid = previous["pid"] if reuse != "live_controller" else row["pid"]
    observed = later["observed"]
    later["pid"] = observed["pid"] = observed["cim"]["ProcessId"] = pid
    if reuse == "duplicate_identity":
        observed["cim"]["CreationDate"] = previous["cim"]["CreationDate"]
    else:
        assert observed["cim"]["CreationDate"] != previous["cim"]["CreationDate"]
    observed["cim_raw"] = json.dumps(observed["cim"])
    read = Path.read_bytes
    virtual: dict[Path, bytes] = {}

    def replace(descriptor: dict[str, str], value: Any) -> None:
        content = json.dumps(value).encode()
        virtual[module.localpath(descriptor["path"])] = content
        descriptor["sha256"] = hashlib.sha256(content).hexdigest()

    output = json.loads(read(module.localpath(later["stdout"]["path"])))
    output["pid"] = pid
    replace(later["stdout"], output)
    raw = json.loads(read(module.localpath(row["owner_stdout"]["path"])))
    raw["cases"] = row["cases"]
    replace(row["owner_stdout"], raw)
    monkeypatch.setattr(Path, "read_bytes", lambda path: virtual.get(path, read(path)))
    if reuse == "distinct_creation":
        module.verify_native_storage(row)
    else:
        with pytest.raises(ValueError, match="E_ENV_NATIVE_EVIDENCE") as error:
            module.verify_native_storage(row)
        assert str(error.value.__cause__) in {"independent processes", "E_ENV_NATIVE_OBSERVATION"}


def test_filesystem_corruption_is_rejected_by_actual_restart_reader(tmp_path: Path) -> None:
    report = owner().run_filesystem_faults(tmp_path)
    assert report["result"] == "PASS"
    assert [row["observed_error"] for row in report["faults"]] == [
        "E_RESTART_DATABASE",
        "E_RESTART_DATABASE",
        "E_STORE_SCHEMA",
        "E_RESTART_MISSING_DATABASE",
    ]
    assert report["physical_power_loss"] == "HOLD_NOT_EXECUTED"
    assert report["commit_io"]["result"] == "PASS"


def test_browser_process_restart_reads_actual_spool(tmp_path: Path) -> None:
    report = owner().run_browser_restart(tmp_path)
    assert report["result"] == "PASS"
    assert len(report["before"]["entries"]) == len(report["after"]["entries"]) == 2
    assert report["before"]["entries"] == report["after"]["entries"]
    assert report["before"]["aborted"] is True
    assert report["processes"][0]["pid"] != report["processes"][1]["pid"]


def test_native_substitution_and_physical_claim_cannot_pass(tmp_path: Path) -> None:
    module = owner()
    with pytest.raises(ValueError, match="E_ENV_NATIVE_EVIDENCE"):
        module.verify_native_storage({"result": "PASS", "cases": []})
    with pytest.raises(ValueError, match="E_ENV_WINDOWS_BROWSER_EVIDENCE"):
        module.verify_windows_browser(
            {"result": "PASS", "termination": {"remaining_observed_descendants": 0}}
        )


def test_native_owned_windows_chrome_has_explicit_origin_result(tmp_path: Path) -> None:
    report = owner().run_windows_browser(tmp_path)
    assert report["result"] in {"PASS", "HOLD"}
    assert report["termination"]["mechanism"] == "WINDOWS_JOB_KILL_ON_CONTROLLER_TERMINATION"
    assert (
        report["browser"]["executable"] == r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )
    if report["result"] == "HOLD":
        assert report["observed_error"] == "E_EXTENSION_TARGET_UNAVAILABLE"
    else:
        assert report["origin"].startswith("chrome-extension://")


def test_retained_browser_evidence_rejects_tampering(tmp_path: Path) -> None:
    module = owner()
    report = module.run_browser_restart(tmp_path)
    for damage in ("pid", "rows", "power", "origin", "module"):
        altered = copy.deepcopy(report)
        if damage == "pid":
            altered["processes"][1]["pid"] = altered["processes"][0]["pid"]
        elif damage == "rows":
            altered["after"]["entries"].clear()
        elif damage == "power":
            altered["physical_power_loss"] = "PASS"
        elif damage == "origin":
            altered["origin"] = "https://example.invalid"
        else:
            altered["modules"]["src/spool.js"] = "0" * 64
        with pytest.raises(ValueError, match="E_ENV_BROWSER_EVIDENCE"):
            module.verify_browser_restart(altered)


@pytest.fixture(scope="module")
def browser_survivor_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return dict(owner().run_browser_restart(tmp_path_factory.mktemp("browser-survivors")))


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate_survivor",
        "aborted_survivor",
        "first",
        "second",
        "duplicate",
        "pending",
        "invalid_ack",
        "aborted_nonbool",
        "input_oracle",
        "input_observation",
    ],
)
def test_coherent_survivor_substitutions_are_rejected(
    browser_survivor_report: dict[str, Any],
    damage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consistent readbacks cannot turn the wrong observations into durable survivors."""
    report = copy.deepcopy(browser_survivor_report)
    case = Path(report["case_directory"])
    original_text, original_bytes = Path.read_text, Path.read_bytes
    replacements: dict[Path, bytes] = {}
    input_path = Path(report["inputs"][0]["path"])
    request = json.loads(original_bytes(input_path))
    if damage == "duplicate_survivor":
        for phase in ("before", "after"):
            report[phase]["entries"][1] = copy.deepcopy(report[phase]["entries"][0])
    elif damage == "aborted_survivor":
        for phase in ("before", "after"):
            report[phase]["entries"][1]["sanitized_observation"] = json.loads(
                request["request"]["observations"][2]
            )
    elif damage in {"first", "second", "duplicate"}:
        report["before"][damage] = {"substituted": True}
    elif damage == "pending":
        report["before"]["pending"] = [report["before"]["first"]]
    elif damage == "invalid_ack":
        report["before"]["invalid_ack"] = ""
    elif damage == "aborted_nonbool":
        report["before"]["aborted"] = "yes"
    else:
        if damage == "input_oracle":
            request["request"]["expected"] = {"survivors": 2}
        else:
            request["request"]["observations"][1] = request["request"]["observations"][0]
        replacements[input_path] = json.dumps(request, sort_keys=True).encode()
        report["inputs"][0]["sha256"] = hashlib.sha256(replacements[input_path]).hexdigest()
    for phase in ("before", "after"):
        replacements[case / f"{phase}-worker.json"] = json.dumps(
            report[phase], sort_keys=True
        ).encode()

    def read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        return (
            replacements[path].decode()
            if path in replacements
            else original_text(path, *args, **kwargs)
        )

    def read_bytes(path: Path) -> bytes:
        return replacements[path] if path in replacements else original_bytes(path)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(ValueError, match="E_ENV_BROWSER_EVIDENCE"):
        owner().verify_browser_restart(report)
