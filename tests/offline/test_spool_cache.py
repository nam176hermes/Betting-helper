import json
from pathlib import Path

import pytest

from moj_discovery.synthetic_source import load_synthetic_observations
from tests.offline.test_synthetic_source import context, scenario
from tools.offline_browser import OfflineBrowser, prepare_offline_extension


@pytest.mark.parametrize("operation", ["TAMPER_RECORD", "TAMPER_REGISTRY"])
def test_cached_spool_proof_rejects_changed_indexeddb(tmp_path: Path, operation: str) -> None:
    extension, identity = prepare_offline_extension(tmp_path)
    ctx = context()
    ctx["allowed_extension_origin"] = "chrome-extension://" + identity
    rows = load_synthetic_observations(scenario(tmp_path / "scenario.json", ctx))
    browser = OfflineBrowser(tmp_path / "browser", extension, ctx["allowed_extension_origin"])
    try:
        assert (
            browser.command({"operation": "INIT", "context": ctx, "credentials": []})["status"]
            == "OK"
        )
        assert browser.command({"operation": "APPEND", "observations": rows})["status"] == "OK"
        warm = browser.command({"operation": "READ"})
        assert warm["state"]["pendingCount"] == 3
        tampered = browser.command({"operation": operation})
        assert tampered == {"status": "REJECTED", "code": "E_SPOOL_CHAIN"}
        browser.command({"operation": "RESTART_WORKER"})
        reopened = browser.command({"operation": "INIT", "context": ctx, "credentials": []})
        if operation == "TAMPER_RECORD":
            assert reopened == {"status": "REJECTED", "code": "E_SPOOL_CHAIN"}
        else:
            assert reopened["status"] == "OK"
    finally:
        browser.close()


def test_append_and_verified_ack_serialize_same_spool(tmp_path: Path) -> None:
    extension, identity = prepare_offline_extension(tmp_path)
    ctx = context()
    ctx["allowed_extension_origin"] = "chrome-extension://" + identity
    source = scenario(tmp_path / "scenario.json", ctx)
    manifest = json.loads(source.read_text())
    manifest["record_count"] = 4
    source.write_text(json.dumps(manifest))
    rows = load_synthetic_observations(source)
    browser = OfflineBrowser(tmp_path / "browser", extension, ctx["allowed_extension_origin"])
    try:
        assert (
            browser.command({"operation": "INIT", "context": ctx, "credentials": []})["status"]
            == "OK"
        )
        assert browser.command({"operation": "APPEND", "observations": rows[:3]})["status"] == "OK"
        actual = browser.command({"operation": "CONCURRENT_APPEND_ACK", "observations": rows[3:]})
        assert actual["status"] == "OK"
        assert actual["state"]["nextSequence"] == "5"
        assert actual["state"]["ackSequence"] == "3"
        assert len(actual["retained"]) == 4
    finally:
        browser.close()
