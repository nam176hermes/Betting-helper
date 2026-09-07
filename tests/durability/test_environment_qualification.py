"""Environment evidence is real, bounded and never physical-power qualification."""

import copy
import importlib
from pathlib import Path
from types import ModuleType

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
