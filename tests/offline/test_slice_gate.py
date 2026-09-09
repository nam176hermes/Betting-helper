from pathlib import Path

from tools.run_offline_slice import run_scenario
from tools.verify_offline_slice import verify_offline_slice


def test_actual_single_stream_has_independently_verified_evidence(tmp_path: Path) -> None:
    output = tmp_path / "campaign"
    actual = run_scenario("single-stream", output, Path("/opt/google/chrome/chrome"))
    assert actual["verified"] is True
    assert actual["OFFLINE_SLICE_PASS"] == "NO"  # noqa: S105 -- qualification status, not a secret
    assert verify_offline_slice(output / "result.json")["verified"] is True


def test_forged_inventory_artifacts_and_stale_source_are_rejected(tmp_path: Path) -> None:
    import copy
    import json

    import pytest

    from tools.offline_browser import ROOT

    output = tmp_path / "campaign"
    run_scenario("single-stream", output, Path("/opt/google/chrome/chrome"))
    baseline = json.loads((output / "result.json").read_text())
    for kind in ["forged", "duplicate", "hash", "missing-reader", "identity"]:
        poisoned = copy.deepcopy(baseline)
        if kind == "forged":
            poisoned["OFFLINE_SLICE_PASS"] = "YES"  # noqa: S105 -- qualification status, not a secret
        elif kind == "duplicate":
            poisoned["records"].append(copy.deepcopy(poisoned["records"][0]))
        elif kind == "hash":
            poisoned["records"][0]["artifacts"][0]["sha256"] = "0" * 64
        elif kind == "missing-reader":
            poisoned["records"][0]["artifacts"] = [
                r
                for r in poisoned["records"][0]["artifacts"]
                if r["relative_path"] != "OFF-01/readback.json"
            ]
        else:
            poisoned["provenance"]["extension_origin"] = "chrome-extension://" + "a" * 32
        target = output / (kind + ".json")
        target.write_text(json.dumps(poisoned))
        with pytest.raises(ValueError):
            verify_offline_slice(target)
    # Rebind the modified artifact hash: rejection must be the timeout gate itself.
    from tools.offline_results import reference

    command = output / "commands/OFF-01.json"
    original_command = command.read_bytes()
    try:
        value = json.loads(original_command)
        value["elapsed_seconds"] = 31
        command.write_text(json.dumps(value))
        poisoned = copy.deepcopy(baseline)
        poisoned["records"][0]["artifacts"] = [
            reference(command, output) if ref["relative_path"] == "commands/OFF-01.json" else ref
            for ref in poisoned["records"][0]["artifacts"]
        ]
        target = output / "timeout.json"
        target.write_text(json.dumps(poisoned))
        with pytest.raises(ValueError, match="E_OFFLINE_CASE_TIMEOUT"):
            verify_offline_slice(target)
    finally:
        command.write_bytes(original_command)
    source = ROOT / "config/live.example.json"
    previous = source.read_bytes()
    try:
        source.write_bytes(previous + b"\n")
        with pytest.raises(ValueError, match="E_OFFLINE_SOURCE_STALE"):
            verify_offline_slice(output / "result.json")
    finally:
        source.write_bytes(previous)


def test_gate_reopens_actual_indexeddb_instead_of_trusting_reader_json(tmp_path: Path) -> None:
    import json

    import pytest

    from tools.offline_browser import OfflineBrowser

    output = tmp_path / "campaign"
    run_scenario("single-stream", output, Path("/opt/google/chrome/chrome"))
    directory = output / "OFF-01"
    context = json.loads((directory / "run/context.json").read_text())
    browser = OfflineBrowser(
        output / "tamper",
        directory / "offline-extension",
        context["allowed_extension_origin"],
        profile=directory / "browser/profile",
    )
    try:
        assert (
            browser.command({"operation": "INIT", "context": context, "credentials": []})["status"]
            == "OK"
        )
        assert browser.command({"operation": "TAMPER_RECORD"})["status"] == "REJECTED"
    finally:
        browser.close()
    with pytest.raises(ValueError, match="E_OFFLINE_STORAGE_CHANGED"):
        verify_offline_slice(output / "result.json")
