"""Executable denial checks for the enabled seam; no independent review claim."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from moj_discovery import live_preflight_batched as gate
from moj_discovery.live_config import load_live_config
from moj_discovery.live_intent import RunIntentReceipt
from moj_discovery.providers import api_football


def test_untrusted_review_never_chooses_trust_key_or_grants_live(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from tools import issue_review_launch_authorization as host

    def denied(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("untrusted review must fail before host trust access")

    monkeypatch.setattr(host, "review_public_key", denied)
    for forged in [
        {"review_kind": "SELF_ONLY", "PASS": True},
        {"independent": True, "signature": "TEST_ONLY_FORGED", "public_key": "ATTACKER"},
        {
            "schema_version": "part-b-review-evidence/v1",
            "scope": {},
            "result": {},
            "authorization": {},
            "receipt": {},
        },
    ]:
        with pytest.raises((ValueError, KeyError)):
            gate.verify_external_review(forged, {}, tmp_path, datetime.now(UTC))


def test_forged_run_admission_cannot_construct_provider_opener(monkeypatch: Any) -> None:
    def denied() -> Any:
        raise AssertionError("no provider opener before current external evidence")

    monkeypatch.setattr(api_football, "build_fixed_opener", denied)
    config = load_live_config(Path("config/live-batched.example.json"))
    with pytest.raises(ValueError, match="PENDING"):
        gate.admit_live_run(config, {"approved": True, "key_present": True})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="AUTHORITY"):
        gate.verify_receiver_authority({"authority": {"approved": True}})


def test_local_intent_without_live_review_cannot_authorize_live_http(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from tests.live.test_run_intents import make_intent

    intent, config, _, _ = make_intent(tmp_path)
    receipt = RunIntentReceipt(intent, config, "TEST_ONLY", 0, "", 0)
    with pytest.raises(ValueError, match="AUTHORITY"):
        gate.verify_live_receipt(receipt)


def test_live_manifest_has_no_generic_http_or_privileged_browser_api() -> None:
    import json

    manifest = json.loads(Path("extension/manifest.live.json").read_text())
    assert set(manifest["permissions"]) == {"storage", "sidePanel", "scripting", "activeTab"}
    assert manifest["host_permissions"] == []
    assert manifest["optional_host_permissions"] == ["https://miseojeuplus.espacejeux.com/*"]
    assert manifest["web_accessible_resources"] == []
    assert (
        manifest["content_security_policy"]["extension_pages"]
        == "script-src 'self'; object-src 'none'; connect-src ws://127.0.0.1:8765"
    )


def test_verifier_rejects_collection_skips_failures_and_empty_results(tmp_path: Path) -> None:
    from tools.verify_part_b import executed_tests

    report = tmp_path / "observed.xml"
    report.write_text(
        '<testsuites><testsuite><testcase classname="actual" name="ran"/></testsuite></testsuites>'
    )
    assert executed_tests(report) == {"actual::ran": "PASS"}
    for body in [
        '<testcase classname="actual" name="ran"><skipped/></testcase>',
        '<testcase classname="actual" name="ran"><failure/></testcase>',
        "",
    ]:
        report.write_text("<testsuites><testsuite>" + body + "</testsuite></testsuites>")
        with pytest.raises(ValueError):
            executed_tests(report)


def test_transport_worker_deadline_kills_only_owned_backend_without_secret_env(
    monkeypatch: Any,
) -> None:
    import subprocess
    import sys
    import time
    from urllib.request import Request

    actual_popen = subprocess.Popen
    children = []
    sentinel = "TEST_ONLY_PRIVATE_PIPE_KEY"

    def sleeping_child(argv: Any, **kwargs: Any) -> Any:
        assert sentinel not in repr(argv) and kwargs["env"] == {}
        assert kwargs["stderr"] == subprocess.DEVNULL and kwargs["close_fds"] is True
        child = actual_popen([sys.executable, "-I", "-c", "import time; time.sleep(5)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(api_football.subprocess, "Popen", sleeping_child)
    request = Request(api_football.BASE + "/status", headers={"x-apisports-key": sentinel})  # noqa: S310
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        api_football._isolated_open(request, 0.1)
    assert time.monotonic() - started < 2
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].stdin.closed and children[0].stdout.closed


def test_worker_uses_fixed_http_path_and_projects_headers(monkeypatch: Any) -> None:
    import base64
    import io
    import json
    import signal
    from types import SimpleNamespace

    from tests.live.test_api_football import MockHTTP, Reply

    sentinel = "TEST_ONLY_WORKER_KEY"
    response = Reply(
        {"response": []},
        headers={"Set-Cookie": "PRIVATE_COOKIE"},
        url=api_football.BASE + "/status",
    )
    response.code = 200
    http = MockHTTP([response])
    output = io.StringIO()
    alarms = []
    monkeypatch.setattr(api_football, "build_fixed_opener", lambda: http)
    monkeypatch.setattr(api_football.sys, "stdout", output)
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    monkeypatch.setattr(signal, "setitimer", lambda *args: alarms.append(args))
    body = {"url": api_football.BASE + "/status", "key": sentinel, "timeout": 0.5}
    monkeypatch.setattr(
        api_football.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(body).encode()))
    )
    api_football._request_worker()
    record = json.loads(output.getvalue())
    assert record["status"] == 200 and base64.b64decode(record["body"]) == b'{"response": []}'
    assert sentinel not in output.getvalue() and "PRIVATE_COOKIE" not in output.getvalue()
    assert http.calls[0][0].get_header("X-apisports-key") == sentinel and alarms
    body["url"] = "https://untrusted.invalid/status"
    monkeypatch.setattr(
        api_football.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(body).encode()))
    )
    with pytest.raises(ValueError, match="SCOPE"):
        api_football._request_worker()
    assert len(http.calls) == 1


def test_private_worker_roundtrip_uses_actual_isolated_python(monkeypatch: Any) -> None:
    import subprocess
    from urllib.request import Request

    actual_popen = subprocess.Popen
    children = []

    def local_mock_worker(argv: Any, **kwargs: Any) -> Any:
        assert argv[:3] == [api_football.sys.executable, "-I", "-c"] and kwargs["env"] == {}
        program = argv[3]
        assert program.endswith(";_request_worker()")
        # Only the transport is synthetic. The actual worker parser/limits/IPC run in a child.
        program = (
            program.removesuffix(";_request_worker()")
            + """
import io
from types import SimpleNamespace
from moj_discovery.providers import api_football as api
class Reply(io.BytesIO):
    code=200
    headers={"Content-Length":"2","Set-Cookie":"PRIVATE_NOT_FORWARDED"}
    def __init__(self): super().__init__(b"{}")
    def geturl(self): return api.BASE+"/status"
api.build_fixed_opener=lambda:SimpleNamespace(open=lambda request,timeout:Reply())
_request_worker()
"""
        )
        child = actual_popen([*argv[:3], program], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(api_football.subprocess, "Popen", local_mock_worker)
    request = Request(  # noqa: S310 -- fixed provider authority; injected local reply.
        api_football.BASE + "/status", headers={"x-apisports-key": "TEST_ONLY_CHILD_KEY"}
    )  # noqa: S310
    with api_football._isolated_open(request, 5) as response:
        assert response.status == 200 and response.read1() == b"{}"
        assert response.headers == {"Content-Length": "2"}
    assert len(children) == 1 and children[0].returncode == 0
