"""Environment evidence is real, bounded and never physical-power qualification."""

import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def owner() -> ModuleType:
    try:
        return importlib.import_module("tools.run_environment_qualification")
    except ModuleNotFoundError:
        pytest.fail(
            "environment owner absent: native handles, corruption and browser restart unqualified"
        )


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
