"""Native pipe qualification must prove actual restart, not a target URL."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast

import pytest

from tools import qualify_chrome_indexeddb as chrome
from tools import run_environment_qualification as environment


def test_pipe_owner_drops_unbound_node_preload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    import subprocess

    preload = tmp_path / "preload.cjs"
    preload.write_text('process.stdout.write("INJECTED");')
    monkeypatch.setenv("NODE_OPTIONS", "--require=" + str(preload))
    monkeypatch.setenv("NODE_PATH", str(tmp_path))
    clean = getattr(chrome, "_pipe_node_environment", None)
    assert callable(clean), "Pipe owner inherits unbound Node preload environment"
    env = clean()
    assert not {"NODE_OPTIONS", "NODE_PATH"} & {key.upper() for key in env}
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(  # noqa: S603 -- installed Node and exact local test program.
        [node, "-e", 'process.stdout.write("BOUND")'],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "BOUND"


def test_pipe_opt_in_preserves_existing_browser_default(tmp_path: Path) -> None:
    args = chrome._browser_command(Path("/browser"), tmp_path, tmp_path, "url", 1234)
    assert "--remote-debugging-port=1234" in args
    pipe = getattr(chrome, "_pipe_browser_command", None)
    assert callable(pipe), "Missing explicit isolated pipe launch"
    command = pipe(Path("/browser"), tmp_path)
    assert "--remote-debugging-pipe" in command
    assert "--enable-unsafe-extension-debugging" in command
    assert not any(
        arg.startswith(("--load-extension=", "--remote-debugging-port=")) for arg in command
    )
    assert command[-1] == "about:blank"


@pytest.fixture(scope="module")
def native_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return environment.run_windows_browser(tmp_path_factory.mktemp("native-pipe"))


def test_native_pipe_restarts_actual_spool(native_report: dict[str, Any]) -> None:
    assert native_report["result"] == "PASS"
    assert native_report.get("restart_result") == "PASS", "No native restart qualification"
    assert native_report["case_id"] == "WINDOWS-CHROME-PROCESS-RESTART"
    assert native_report["before"]["entries"] == native_report["after"]["entries"]
    assert len(native_report["before"]["entries"]) == 2
    assert len(native_report["phases"]) == 2
    identities = [
        environment._verify_native_observation(
            phase["browser"], phase["browser"]["argv"], phase["node"]["pid"]
        )
        for phase in native_report["phases"]
    ]
    assert identities[0] != identities[1]


@pytest.mark.parametrize(
    "reuse", ["distinct_creation", "duplicate_identity", "live_controller", "same_phase"]
)
def test_native_browser_restart_identity_uses_creation_time(
    native_report: dict[str, Any], reuse: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    row = copy.deepcopy(native_report)
    first, later = row["phases"]
    previous = first["leader"]
    observed = later["leader"]
    old_pid = observed["pid"]
    pid = (
        row["controller"]["pid"]
        if reuse == "live_controller"
        else later["node"]["pid"]
        if reuse == "same_phase"
        else previous["pid"]
    )
    later["leader_pid"] = observed["pid"] = observed["cim"]["ProcessId"] = pid
    if reuse == "duplicate_identity":
        observed["cim"]["CreationDate"] = previous["cim"]["CreationDate"]
    else:
        assert observed["cim"]["CreationDate"] != previous["cim"]["CreationDate"]
    observed["cim_raw"] = json.dumps(observed["cim"])
    later["node"]["cim"]["ParentProcessId"] = pid
    later["node"]["cim_raw"] = json.dumps(later["node"]["cim"])
    for item in later["descendants"]:
        if item["ParentProcessId"] == old_pid:
            item["ParentProcessId"] = pid
    later["descendants_raw"] = json.dumps(later["descendants"])
    read = Path.read_bytes
    path = Path(row["stdout"]["path"])
    raw = json.loads(read(path))
    raw["phases"][1] = {key: later[key] for key in raw["phases"][1]}
    content = json.dumps(raw).encode()
    row["stdout"]["sha256"] = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(Path, "read_bytes", lambda value: content if value == path else read(value))
    if reuse == "distinct_creation":
        environment.verify_windows_browser(row)
    else:
        with pytest.raises(ValueError, match="E_ENV_WINDOWS_BROWSER_EVIDENCE") as error:
            environment.verify_windows_browser(row)
        assert str(error.value.__cause__) in {"restart process", "E_ENV_NATIVE_OBSERVATION"}


@pytest.mark.parametrize("damage", ["missing", "null", "empty", "malformed", "overflow", "extra"])
def test_native_creation_identity_is_required(native_report: dict[str, Any], damage: str) -> None:
    import json

    observed = copy.deepcopy(native_report["phases"][0]["node"])
    command = observed["argv"]
    parent = observed["cim"]["ParentProcessId"]
    environment._verify_native_observation(observed, command, parent)
    if damage == "missing":
        del observed["cim"]["CreationDate"]
    elif damage == "extra":
        observed["cim"]["UnboundIdentity"] = "extra"
    else:
        observed["cim"]["CreationDate"] = {
            "null": None,
            "empty": "",
            "malformed": "/Date(not-a-timestamp)/",
            "overflow": "/Date(99999999999999999999999999999999999999)/",
        }[damage]
    observed["cim_raw"] = json.dumps(observed["cim"])
    with pytest.raises(ValueError, match="E_ENV_NATIVE_OBSERVATION"):
        environment._verify_native_observation(observed, command, parent)


@pytest.mark.parametrize(
    "damage",
    [
        "graceful",
        "node_as_chrome",
        "stale_run",
        "missing_reader",
        "duplicate_survivor",
        "wrong_origin",
        "wrong_script",
        "missing_transcript",
        "wrong_extension",
        "wrong_path",
    ],
)
def test_native_pipe_evidence_rejects_substitution(
    native_report: dict[str, Any], damage: str
) -> None:
    row = copy.deepcopy(native_report)
    assert "phases" in row, "Missing source-bound native pipe phase evidence"
    first = row["phases"][0]
    if damage == "graceful":
        first["termination"]["mechanism"] = "Browser.close"
    elif damage == "node_as_chrome":
        first["browser"]["pid"] = first["node"]["pid"]
    elif damage == "stale_run":
        row["profile_id"] = "stale"
    elif damage == "missing_reader":
        row["phases"] = row["phases"][:1]
    elif damage == "duplicate_survivor":
        row["after"]["entries"][1] = copy.deepcopy(row["after"]["entries"][0])
    elif damage == "wrong_origin":
        row["origin"] = "http://127.0.0.1"
    elif damage == "wrong_script":
        row["script"]["sha256"] = "0" * 64
    elif damage == "missing_transcript":
        first["transcript"]["path"] += ".missing"
    elif damage == "wrong_extension":
        first["result"]["loaded"]["id"] = "a" * 32
    elif damage == "wrong_path":
        first["config"]["extension"] += "-other"
    with pytest.raises(ValueError, match="E_ENV_WINDOWS_BROWSER_EVIDENCE"):
        environment.verify_windows_browser(row)


@pytest.mark.parametrize(
    "damage",
    [
        "api_error",
        "missing_reply",
        "duplicate_reply",
        "wrong_load_path",
        "wrong_load_id",
        "wrong_expression",
        "malformed",
        "exception_payload",
    ],
)
def test_raw_pipe_protocol_rejects_false_success(
    native_report: dict[str, Any], damage: str
) -> None:
    import json

    phase = native_report["phases"][0]
    rows = [
        json.loads(line) for line in Path(phase["transcript"]["path"]).read_bytes().splitlines()
    ]
    reply = next(
        row
        for row in rows
        if row["direction"] == "receive" and json.loads(row["raw"]).get("id") == 2
    )
    if damage == "api_error":
        reply["raw"] = json.dumps({"id": 2, "error": {"code": -32601, "message": "unavailable"}})
    elif damage == "missing_reply":
        rows.remove(reply)
    elif damage == "duplicate_reply":
        rows.append(copy.deepcopy(reply))
    elif damage == "wrong_load_path":
        next(row["request"] for row in rows if row.get("request", {}).get("id") == 2)["params"][
            "path"
        ] += "-other"
    elif damage == "wrong_load_id":
        reply["raw"] = json.dumps({"id": 2, "result": {"id": "a" * 32}})
    elif damage == "wrong_expression":
        next(
            row["request"]
            for row in rows
            if row.get("request", {}).get("method") == "Runtime.evaluate"
        )["params"]["expression"] = "true"
    elif damage == "malformed":
        reply["raw"] = "{"
    else:
        last = next(
            row
            for row in reversed(rows)
            if row["direction"] == "receive" and "id" in json.loads(row["raw"])
        )
        payload = json.loads(last["raw"])
        payload["result"]["exceptionDetails"] = {"text": "Uncaught"}
        last["raw"] = json.dumps(payload)
    content = b"\n".join(json.dumps(row).encode() for row in rows)
    with pytest.raises((ValueError, KeyError)):
        chrome._verify_pipe_transcript(content, phase["config"], phase["work"], phase["result"])


@pytest.mark.parametrize("damage", ["missing", "duplicate", "corrupt"])
def test_coherent_restart_storage_damage_is_not_success(
    native_report: dict[str, Any], damage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rehash every enclosing capture so the ordinary state comparator is reached."""
    import hashlib
    import json

    row = copy.deepcopy(native_report)
    after = row["after"]
    if damage == "missing":
        after["entries"].pop()
    elif damage == "duplicate":
        after["entries"][1] = copy.deepcopy(after["entries"][0])
    else:
        after["entries"][0]["sanitized_observation"]["observation_id"] = "corrupt"
    phase = row["phases"][1]
    phase["result"]["worker"] = after
    real_read = Path.read_bytes
    virtual: dict[Path, bytes] = {}

    def replace(descriptor: dict[str, Any], content: bytes) -> None:
        virtual[Path(descriptor["path"])] = content
        descriptor["sha256"] = hashlib.sha256(content).hexdigest()

    replace(phase["result_artifact"], json.dumps(phase["result"]).encode())
    transcript = [
        json.loads(line) for line in real_read(Path(phase["transcript"]["path"])).splitlines()
    ]
    reply = next(
        item
        for item in reversed(transcript)
        if item["direction"] == "receive" and "id" in json.loads(item["raw"])
    )
    payload = json.loads(reply["raw"])
    payload["result"]["result"]["value"] = after
    reply["raw"] = json.dumps(payload)
    replace(phase["transcript"], b"\n".join(json.dumps(item).encode() for item in transcript))
    raw = json.loads(real_read(Path(row["stdout"]["path"])))
    raw["phases"][1]["result"]["worker"] = after
    replace(row["stdout"], json.dumps(raw).encode())
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda path: virtual.get(path, b"") if path in virtual else real_read(path),
    )
    with pytest.raises(ValueError, match="E_ENV_WINDOWS_BROWSER_EVIDENCE") as rejected:
        environment.verify_windows_browser(row)
    assert str(rejected.value.__cause__).startswith("E_"), rejected.value.__cause__


@pytest.fixture(scope="module")
def hosted_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    import inspect

    from tools.run_indexeddb_crash_matrix import CHROME

    assert (
        "transport" in inspect.signature(chrome.qualify_chrome_indexeddb_environment).parameters
    ), "No hosted pipe opt-in"
    return cast(
        dict[str, Any],
        chrome.qualify_chrome_indexeddb_environment(
            tmp_path_factory.mktemp("hosted-pipe"), browser_binary=CHROME, transport="pipe"
        ),
    )


def test_hosted_pipe_is_explicit_and_crash_qualified(hosted_report: dict[str, Any]) -> None:
    result = hosted_report
    assert result["result"] == "PASS"
    assert result["transport"] == "pipe"
    assert result["termination"]["graceful"] is False
    assert result["pipe_phases"][0]["browser"]["pid"] != result["pipe_phases"][0]["owner"]["pid"]
    assert result["pipe_phases"][0]["browser"]["pid"] != result["pipe_phases"][1]["browser"]["pid"]
    chrome.validate_qualification_evidence(result)


def test_hosted_summary_cannot_replace_actual_sentinel(hosted_report: dict[str, Any]) -> None:
    row = copy.deepcopy(hosted_report)
    for key in ("expected", "committed", "durable"):
        row["sentinel"][key] = "coherently-wrong"
    with pytest.raises(chrome.QualificationRejected, match="E_PIPE_QUALIFICATION_EVIDENCE"):
        chrome.validate_qualification_evidence(row)
