"""Qualify real extension-origin IndexedDB durability in an isolated Chrome."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
import signal
from pathlib import Path
from secrets import token_hex
from subprocess import DEVNULL, Popen, run
from time import monotonic, sleep
from typing import Any, cast
from urllib.request import urlopen
from uuid import uuid4

# Native Windows imports only the transport helpers; POSIX termination stays opt-in.
SIGKILL = getattr(signal, "SIGKILL", 9)

_CDP = r"""
const socket = new WebSocket(process.argv[1]);
const expression = process.argv[2];
let nextId = 1;
const pending = new Map();
const opened = new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});
socket.onmessage = event => {
  const message = JSON.parse(event.data);
  const resolve = pending.get(message.id);
  if (resolve) { pending.delete(message.id); resolve(message); }
};
const call = (method, params) => new Promise(resolve => {
  const id = nextId++;
  pending.set(id, resolve);
  socket.send(JSON.stringify({id, method, params}));
});
(async () => {
  await opened;
  const response = await call("Runtime.evaluate", {
    expression, awaitPromise: true, returnByValue: true
  });
  socket.close();
  if (response.error || response.result.exceptionDetails) {
    throw new Error(JSON.stringify(response));
  }
  process.stdout.write(JSON.stringify(response.result.result.value));
})().catch(error => { console.error(String(error)); process.exit(1); });
"""


class QualificationRejected(RuntimeError):
    """Raised when purported PASS evidence violates the qualification contract."""


class _EnvironmentBlocked(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}:{detail}")
        self.code = code
        self.detail = detail


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extension_id(encoded_public_key: str) -> str:
    digest = hashlib.sha256(base64.b64decode(encoded_public_key)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(nibble, 16)) for nibble in digest)


def _dict(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise QualificationRejected(code)
    return cast(dict[str, object], value)


def _reject_unless(condition: bool, code: str) -> None:
    if not condition:
        raise QualificationRejected(code)


def validate_qualification_evidence(evidence: dict[str, object]) -> None:
    """Reject identity drift, non-extension execution, or graceful-only shutdown."""
    _reject_unless(evidence.get("result") == "PASS", "E_QUALIFICATION_NOT_PASS")
    if evidence.get("transport") == "pipe":
        _verify_hosted_pipe(evidence)
    browser = _dict(evidence.get("browser"), "E_BROWSER_EVIDENCE")
    expected_executable = browser.get("expected_executable")
    _reject_unless(
        isinstance(expected_executable, str)
        and browser.get("first_process_executable") == expected_executable
        and browser.get("second_process_executable") == expected_executable,
        "E_BROWSER_BINARY_MISMATCH",
    )
    expected_browser_hash = browser.get("sha256")
    _reject_unless(
        isinstance(expected_browser_hash, str)
        and len(expected_browser_hash) == 64
        and browser.get("first_process_sha256") == expected_browser_hash
        and browser.get("second_process_sha256") == expected_browser_hash,
        "E_BROWSER_BINARY_MISMATCH",
    )

    profile = _dict(evidence.get("profile"), "E_PROFILE_EVIDENCE")
    expected_profile = profile.get("expected_id")
    _reject_unless(
        profile.get("fresh") is True
        and isinstance(expected_profile, str)
        and profile.get("first_id") == expected_profile
        and profile.get("second_id") == expected_profile,
        "E_PROFILE_MISMATCH",
    )

    extension = _dict(evidence.get("extension"), "E_EXTENSION_EVIDENCE")
    expected_extension = extension.get("expected_id")
    expected_origin = f"chrome-extension://{expected_extension}"
    _reject_unless(
        isinstance(expected_extension, str)
        and len(expected_extension) == 32
        and extension.get("first_id") == expected_extension
        and extension.get("second_id") == expected_extension,
        "E_EXTENSION_IDENTITY_MISMATCH",
    )
    _reject_unless(
        extension.get("first_protocol") == "chrome-extension:"
        and extension.get("second_protocol") == "chrome-extension:"
        and extension.get("first_origin") == expected_origin
        and extension.get("second_origin") == expected_origin,
        "E_EXTENSION_ORIGIN",
    )

    module = _dict(evidence.get("module"), "E_MODULE_EVIDENCE")
    expected_module_hash = module.get("expected_sha256")
    expected_module_url = f"{expected_origin}/src/spool.js"
    _reject_unless(
        isinstance(expected_module_hash, str)
        and len(expected_module_hash) == 64
        and module.get("first_sha256") == expected_module_hash
        and module.get("second_sha256") == expected_module_hash
        and module.get("first_url") == expected_module_url
        and module.get("second_url") == expected_module_url,
        "E_MODULE_IDENTITY_MISMATCH",
    )

    sentinel = _dict(evidence.get("sentinel"), "E_SENTINEL_EVIDENCE")
    expected_sentinel = sentinel.get("expected")
    _reject_unless(
        isinstance(expected_sentinel, str)
        and bool(expected_sentinel)
        and sentinel.get("committed") == expected_sentinel
        and sentinel.get("durable") == expected_sentinel,
        "E_SENTINEL_DURABILITY",
    )
    _reject_unless(sentinel.get("profile_id") == expected_profile, "E_PROFILE_MISMATCH")

    termination = _dict(evidence.get("termination"), "E_TERMINATION_EVIDENCE")
    _reject_unless(
        termination.get("method") == "SIGKILL_PROCESS_GROUP"
        and termination.get("signal") == SIGKILL
        and termination.get("returncode") == -SIGKILL
        and termination.get("graceful") is False
        and termination.get("owned_process_group") is True,
        "E_GRACEFUL_ONLY_SHUTDOWN",
    )


def _free_port() -> int:
    from socket import socket

    with socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _canonical_browser_executable(command: Path) -> Path:
    resolved = command.resolve(strict=True)
    chrome_binary = resolved.with_name("chrome")
    if resolved.name in {"google-chrome", "google-chrome-stable"} and chrome_binary.is_file():
        return chrome_binary.resolve(strict=True)
    return resolved


def _process_executable(process: Popen[bytes]) -> Path:
    try:
        return Path(f"/proc/{process.pid}/exe").resolve(strict=True)
    except OSError as error:
        raise QualificationRejected(f"E_BROWSER_PROCESS_IDENTITY:{error}") from error


def _browser_process_observation(process: Popen[bytes]) -> dict[str, object]:
    """Observe the owned live process, retaining raw proc data for later parsing."""
    if process.poll() is not None:
        raise QualificationRejected("E_BROWSER_PROCESS_EXITED")
    return _pid_process_observation(process.pid)


def _pid_process_observation(pid: int) -> dict[str, object]:
    executable = Path(f"/proc/{pid}/exe").resolve(strict=True)
    proc = Path(f"/proc/{pid}")
    cmdline = (proc / "cmdline").read_bytes()
    return {
        "pid": pid,
        "pgid": os.getpgid(pid),
        "executable": str(executable),
        "sha256": _sha256(executable),
        "argv": cmdline.rstrip(b"\0").decode().split("\0"),
        "proc_cmdline_hex": cmdline.hex(),
        "proc_stat": (proc / "stat").read_text(),
    }


def _browser_command(
    command: Path,
    profile: Path,
    extension: Path,
    extension_url: str,
    port: int,
) -> list[str]:
    """Pinned isolated-browser launch; external requests cannot bypass a system proxy."""
    return [
        str(command.resolve()),
        "--headless=new",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-gpu",
        "--disable-sync",
        "--metrics-recording-only",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
        "--proxy-server=http://127.0.0.1:9",
        "--proxy-bypass-list=127.0.0.1;localhost",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile.resolve()}",
        f"--disable-extensions-except={extension.resolve()}",
        f"--load-extension={extension.resolve()}",
        extension_url,
    ]


def _pipe_browser_command(command: Path, profile: Path) -> list[str]:
    """Explicit opt-in; established CfT owner launch defaults remain unchanged."""
    legacy = _browser_command(command, profile, profile, "about:blank", 0)
    return [
        arg
        for arg in legacy
        if not arg.startswith(
            (
                "--remote-debugging-address=",
                "--remote-debugging-port=",
                "--disable-extensions-except=",
                "--load-extension=",
            )
        )
    ][:-1] + ["--remote-debugging-pipe", "--enable-unsafe-extension-debugging", "about:blank"]


def _pipe_node_environment() -> dict[str, str]:
    """Do not let inherited Node preloads replace the hash-bound pipe program."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"NODE_OPTIONS", "NODE_PATH"}
    }


def _pipe_work(profile_id: str, phase: str, worker_id: str, request: object) -> dict[str, object]:
    arguments = (
        f"{json.dumps(profile_id)},{json.dumps(profile_id)}"
        if phase == "before"
        else json.dumps(profile_id)
    )
    method = "writeSentinel" if phase == "before" else "readSentinel"
    return {
        "worker_id": worker_id,
        "request": request,
        "sentinel_expression": f"globalThis.repairProbe.{method}({arguments})",
        "worker_expression": (
            f"globalThis.repairProbe.startWorker({json.dumps(worker_id)},"
            f"{json.dumps(request, sort_keys=True)})"
            if request is not None
            else None
        ),
    }


def _verify_pipe_transcript(
    content: bytes,
    config: dict[str, object],
    work: dict[str, object],
    result: dict[str, object],
) -> None:
    """Require exact critical requests and their real, unique successful replies."""
    requests: list[dict[str, object]] = []
    replies: dict[int, dict[str, object]] = {}
    for line in content.splitlines():
        row = json.loads(line)
        if row["direction"] == "send":
            request = row["request"]
            if request["id"] != len(requests) + 1:
                raise ValueError("E_PIPE_TRANSCRIPT_SEQUENCE")
            requests.append(request)
        elif row["direction"] == "receive":
            response = json.loads(row["raw"])
            if "id" in response:
                identity = response["id"]
                if identity in replies or not 1 <= identity <= len(requests) or "error" in response:
                    raise ValueError("E_PIPE_TRANSCRIPT_RESPONSE")
                replies[identity] = response["result"]
        else:
            raise ValueError("E_PIPE_TRANSCRIPT_DIRECTION")
    if set(replies) != set(range(1, len(requests) + 1)) or len(requests) < 6:
        raise ValueError("E_PIPE_TRANSCRIPT_MISSING")
    prefix = [
        ("Browser.getVersion", {}),
        ("Extensions.loadUnpacked", {"path": config["extension"]}),
        ("Target.createTarget", {"url": str(config["origin"]) + "/repair-probe.html"}),
        ("Target.attachToTarget", {"targetId": replies[3]["targetId"], "flatten": True}),
    ]
    for request, (method, params) in zip(requests[:4], prefix, strict=True):
        if request != {"id": request["id"], "method": method, "params": params}:
            raise ValueError("E_PIPE_TRANSCRIPT_REQUEST")
    if replies[1] != result["version"] or replies[2] != result["loaded"]:
        raise ValueError("E_PIPE_TRANSCRIPT_IDENTITY")
    loaded = _dict(result["loaded"], "E_PIPE_LOAD")
    if loaded != {"id": str(config["origin"]).split("://")[1]}:
        raise ValueError("E_PIPE_EXTENSION_ID")
    document_expression = (
        "({origin:location.origin,protocol:location.protocol,"
        "probe:Boolean(globalThis.repairProbe),extensionId:globalThis.chrome?.runtime?.id??null})"
    )
    tail = [(work["sentinel_expression"], result["sentinel"])]
    if work["worker_expression"] is not None:
        tail.append((work["worker_expression"], result["worker"]))
    document_count = len(requests) - 4 - len(tail)
    if document_count < 1 or document_count > 100:
        raise ValueError("E_PIPE_DOCUMENT_WAIT")
    for index, request in enumerate(requests[4:], 4):
        expression = (
            document_expression
            if index < 4 + document_count
            else tail[index - 4 - document_count][0]
        )
        if request != {
            "id": index + 1,
            "method": "Runtime.evaluate",
            "sessionId": replies[4]["sessionId"],
            "params": {"expression": expression, "awaitPromise": True, "returnByValue": True},
        }:
            raise ValueError("E_PIPE_EXPRESSION")
        response = replies[index + 1]
        if "exceptionDetails" in response:
            raise ValueError("E_PIPE_EVALUATE")
        value = _dict(response["result"], "E_PIPE_VALUE")["value"]
        if index >= 4 + document_count and value != tail[index - 4 - document_count][1]:
            raise ValueError("E_PIPE_VALUE")
        if index == 3 + document_count and value != result["document"]:
            raise ValueError("E_PIPE_DOCUMENT")
    if result["document"] != {
        "origin": config["origin"],
        "protocol": "chrome-extension:",
        "extensionId": loaded["id"],
        "probe": True,
    }:
        raise ValueError("E_PIPE_ORIGIN")


def _wait_for_target(process: Popen[bytes], port: int, url: str) -> str:
    endpoint = f"http://127.0.0.1:{port}/json/list"
    deadline = monotonic() + 15
    observed: set[str] = set()
    while monotonic() < deadline:
        if process.poll() is not None:
            raise _EnvironmentBlocked("E_CHROME_START_FAILED", f"exit={process.returncode}")
        try:
            pages = json.loads(urlopen(endpoint, timeout=1).read())
            for page in pages:
                page_url = str(page.get("url", ""))
                if page_url:
                    observed.add(page_url)
                if page.get("type") == "page" and page_url == url:
                    return str(page["webSocketDebuggerUrl"])
        except (OSError, json.JSONDecodeError):
            pass
        sleep(0.1)
    raise _EnvironmentBlocked(
        "E_EXTENSION_TARGET_UNAVAILABLE", "observed=" + ",".join(sorted(observed))
    )


def _start_chrome(
    command: Path,
    profile: Path,
    extension: Path,
    extension_url: str,
    log_path: Path,
) -> tuple[Popen[bytes], str]:
    port = _free_port()
    with log_path.open("ab") as log:
        process = Popen(  # noqa: S603 - caller supplies the recorded local browser.
            _browser_command(command, profile, extension, extension_url, port),
            stdin=DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    try:
        return process, _wait_for_target(process, port, extension_url)
    except Exception:
        if process.poll() is None:
            os.killpg(process.pid, SIGKILL)
            process.wait(timeout=10)
        raise


def _kill_owned_process_group(process: Popen[bytes]) -> dict[str, object]:
    if process.poll() is not None or os.getpgid(process.pid) != process.pid:
        raise QualificationRejected("E_UNOWNED_OR_EXITED_BROWSER_PROCESS")
    os.killpg(process.pid, SIGKILL)
    returncode = process.wait(timeout=10)
    evidence: dict[str, object] = {
        "method": "SIGKILL_PROCESS_GROUP",
        "signal": SIGKILL,
        "returncode": returncode,
        "graceful": False,
        "owned_process_group": True,
    }
    _reject_unless(returncode == -SIGKILL, "E_GRACEFUL_ONLY_SHUTDOWN")
    return evidence


def _evaluate(websocket_url: str, expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        raise _EnvironmentBlocked("E_NODE_UNAVAILABLE", "node")
    completed = run(  # noqa: S603 - resolved installed Node runs a fixed controller.
        [node, "-e", _CDP, websocket_url, expression],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if completed.returncode:
        raise QualificationRejected(f"E_CHROME_INDEXEDDB_EVALUATE:{completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _wait_for_probe(websocket_url: str) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        protocol = _evaluate(websocket_url, "location.protocol")
        if protocol != "chrome-extension:":
            raise _EnvironmentBlocked(
                "E_EXTENSION_TARGET_UNAVAILABLE", f"document_protocol={protocol}"
            )
        if _evaluate(websocket_url, "Boolean(globalThis.repairProbe)") is True:
            return
        sleep(0.1)
    raise QualificationRejected("E_REPAIR_PROBE_UNAVAILABLE")


def _prepare_test_extension(repository_root: Path, workspace: Path) -> tuple[Path, str, str]:
    source_root = repository_root / "extension"
    harness_root = source_root / "test-harness"
    build_root = source_root / ".test-build"
    required = {
        "manifest": harness_root / "repair-manifest.json",
        "html": harness_root / "repair-probe.html",
        "probe": build_root / "test-harness/repair-probe.js",
        "spool": build_root / "src/spool.js",
        "errors": build_root / "src/errors.js",
    }
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise _EnvironmentBlocked("E_TEST_EXTENSION_BUILD_MISSING", ",".join(missing))

    extension = workspace / "test-extension"
    (extension / "src").mkdir(parents=True)
    shutil.copy2(required["manifest"], extension / "manifest.json")
    shutil.copy2(required["html"], extension / "repair-probe.html")
    shutil.copy2(required["probe"], extension / "repair-probe.js")
    shutil.copy2(required["spool"], extension / "src/spool.js")
    shutil.copy2(required["errors"], extension / "src/errors.js")
    # Resolve the installed ESM dependency inside this isolated test extension.
    canonical = (build_root / "src/canonical.js").read_text()
    (extension / "src/canonical.js").write_text(
        canonical.replace('from "canonicalize"', 'from "./canonicalize.js"')
    )
    shutil.copy2(
        source_root / "node_modules/canonicalize/lib/canonicalize.js",
        extension / "src/canonicalize.js",
    )
    shutil.copy2(
        build_root / "test-harness/indexeddb-crash-child.js", extension / "indexeddb-crash-child.js"
    )
    manifest = cast(dict[str, object], json.loads((extension / "manifest.json").read_text()))
    key = manifest.get("key")
    if not isinstance(key, str):
        raise QualificationRejected("E_TEST_EXTENSION_KEY")
    return extension, _extension_id(key), _sha256(extension / "src/spool.js")


def _probe_evidence(value: object) -> dict[str, object]:
    return _dict(value, "E_REPAIR_PROBE_EVIDENCE")


def qualify_chrome_indexeddb_environment(
    workspace: Path,
    *,
    browser_binary: Path | None = None,
    repository_root: Path | None = None,
    transport: str = "legacy",
) -> dict[str, object]:
    """Commit a random sentinel, SIGKILL owned Chrome, and read it after restart."""
    if transport == "pipe":
        return _qualify_hosted_pipe(workspace, browser_binary, repository_root)
    if transport != "legacy":
        raise QualificationRejected("E_BROWSER_TRANSPORT")
    workspace.mkdir(parents=True, exist_ok=True)
    repository_root = repository_root or Path(__file__).parents[1]
    if browser_binary is None:
        installed_browser = shutil.which("google-chrome")
        browser_binary = Path(installed_browser) if installed_browser else None
    profile = workspace / "chrome-profile"
    fresh_profile = not profile.exists()
    if not fresh_profile:
        raise QualificationRejected("E_PROFILE_NOT_FRESH")
    profile.mkdir()
    profile_id = f"bh-r04-{uuid4()}"
    (profile / "BH_R04_PROFILE_ID").write_text(profile_id)
    extension: Path | None = None
    extension_id = ""
    module_hash = ""
    browser: dict[str, object] = {}
    first: Popen[bytes] | None = None
    second: Popen[bytes] | None = None
    attempted = False
    try:
        extension, extension_id, module_hash = _prepare_test_extension(repository_root, workspace)
        if browser_binary is None or not browser_binary.is_file():
            raise _EnvironmentBlocked("E_BROWSER_UNAVAILABLE", str(browser_binary))
        expected_executable = _canonical_browser_executable(browser_binary)
        version = run(  # noqa: S603 - selected browser is identity-checked after launch.
            [str(browser_binary), "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        browser_hash = _sha256(expected_executable)
        browser = {
            "command": str(browser_binary),
            "expected_executable": str(expected_executable),
            "version": version,
            "sha256": browser_hash,
        }
        extension_url = f"chrome-extension://{extension_id}/repair-probe.html"
        attempted = True
        first, websocket_url = _start_chrome(
            browser_binary, profile, extension, extension_url, workspace / "chrome-first.log"
        )
        first_executable = _process_executable(first)
        first_profile_id = (profile / "BH_R04_PROFILE_ID").read_text()
        _wait_for_probe(websocket_url)
        sentinel = f"bh-r04-{token_hex(32)}"
        committed = _probe_evidence(
            _evaluate(
                websocket_url,
                "globalThis.repairProbe.writeSentinel("
                f"{json.dumps(sentinel)},{json.dumps(profile_id)})",
            )
        )
        termination = _kill_owned_process_group(first)
        first = None

        second, websocket_url = _start_chrome(
            browser_binary, profile, extension, extension_url, workspace / "chrome-second.log"
        )
        second_executable = _process_executable(second)
        second_profile_id = (profile / "BH_R04_PROFILE_ID").read_text()
        _wait_for_probe(websocket_url)
        durable = _probe_evidence(
            _evaluate(
                websocket_url,
                f"globalThis.repairProbe.readSentinel({json.dumps(profile_id)})",
            )
        )
        browser.update(
            {
                "first_process_executable": str(first_executable),
                "second_process_executable": str(second_executable),
                "first_process_sha256": _sha256(first_executable),
                "second_process_sha256": _sha256(second_executable),
            }
        )
        result: dict[str, object] = {
            "result": "PASS",
            "attempted_real_browser": attempted,
            "browser": browser,
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "wsl": "microsoft" in platform.release().lower(),
            },
            "profile": {
                "path": str(profile),
                "expected_id": profile_id,
                "first_id": first_profile_id,
                "second_id": second_profile_id,
                "fresh": fresh_profile,
            },
            "extension": {
                "expected_id": extension_id,
                "first_id": committed.get("extensionId"),
                "second_id": durable.get("extensionId"),
                "first_origin": committed.get("origin"),
                "second_origin": durable.get("origin"),
                "first_protocol": committed.get("protocol"),
                "second_protocol": durable.get("protocol"),
                "load_requested": True,
            },
            "module": {
                "source_sha256": _sha256(repository_root / "extension/src/spool.ts"),
                "expected_sha256": module_hash,
                "first_sha256": committed.get("moduleSha256"),
                "second_sha256": durable.get("moduleSha256"),
                "first_url": committed.get("moduleUrl"),
                "second_url": durable.get("moduleUrl"),
            },
            "sentinel": {
                "expected": sentinel,
                "committed": committed.get("sentinel"),
                "durable": durable.get("sentinel"),
                "profile_id": durable.get("profileId"),
            },
            "termination": termination,
        }
        validate_qualification_evidence(result)
        return result
    except _EnvironmentBlocked as blocked:
        return {
            "result": "BLOCKED_ENVIRONMENT",
            "blocker_code": blocked.code,
            "blocker_detail": blocked.detail,
            "attempted_real_browser": attempted,
            "browser": browser,
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "wsl": "microsoft" in platform.release().lower(),
            },
            "profile": {
                "path": str(profile),
                "expected_id": profile_id,
                "fresh": fresh_profile,
            },
            "extension": {
                "expected_id": extension_id,
                "path": str(extension) if extension is not None else None,
                "load_requested": True,
                "module_sha256": module_hash,
            },
        }
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                os.killpg(process.pid, SIGKILL)
                process.wait(timeout=10)


def _qualify_hosted_pipe(
    workspace: Path,
    browser_binary: Path | None,
    repository_root: Path | None,
) -> dict[str, object]:
    from tools.verify_repair_evidence import capture_binding

    if browser_binary is None or not browser_binary.is_file():
        return {
            "result": "BLOCKED_ENVIRONMENT",
            "blocker_code": "E_BROWSER_UNAVAILABLE",
            "blocker_detail": str(browser_binary),
            "attempted_real_browser": False,
        }
    root = repository_root or Path(__file__).resolve().parents[1]
    workspace.mkdir(parents=True, exist_ok=True)
    profile = workspace / "chrome-profile"
    if profile.exists():
        raise QualificationRejected("E_PROFILE_NOT_FRESH")
    profile.mkdir()
    profile_id = "bh-pipe-" + str(uuid4())
    (profile / "BH_R04_PROFILE_ID").write_text(profile_id)
    extension, extension_id, module_hash = _prepare_test_extension(root, workspace)
    script = workspace / "chrome_pipe.cjs"
    shutil.copy2(root / "tools/chrome_pipe.cjs", script)
    node = shutil.which("node")
    if node is None:
        raise _EnvironmentBlocked("E_NODE_UNAVAILABLE", "node")
    node = run(  # noqa: S603 -- resolved installed Node, preload environment removed.
        [node, "-p", "process.execPath"],
        env=_pipe_node_environment(),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    command = _pipe_browser_command(browser_binary, profile)
    origin = "chrome-extension://" + extension_id
    phases = []
    for phase in ("before", "after"):
        case = workspace / phase
        case.mkdir()
        config = {
            "command": command,
            "workspace": str(case.resolve()),
            "extension": str(extension.resolve()),
            "origin": origin,
        }
        input_path = case / "input.json"
        input_path.write_text(json.dumps(config))
        invocation = [node, str(script.resolve()), str(input_path.resolve())]
        with (case / "node.stdout").open("wb") as out, (case / "node.stderr").open("wb") as err:
            owner = Popen(  # noqa: S603 -- fixed retained pipe owner, closed preload environment.
                invocation,
                stdout=out,
                stderr=err,
                start_new_session=True,
                env=_pipe_node_environment(),
            )
        try:
            deadline = monotonic() + 20
            while not (case / "pipe-ready.json").is_file():
                if owner.poll() is not None or monotonic() > deadline:
                    raise QualificationRejected("E_PIPE_OWNER_READY")
                sleep(0.02)
            ready = json.loads((case / "pipe-ready.json").read_text())
            owner_record = _browser_process_observation(owner)
            browser_record = _pid_process_observation(ready["pid"])
            if ready["node_pid"] != owner.pid or browser_record["pgid"] != owner.pid:
                raise QualificationRejected("E_PIPE_OWNER_IDENTITY")
            work = _pipe_work(profile_id, phase, "", None)
            (case / "start.json").write_text(json.dumps(work))
            deadline = monotonic() + 30
            while not (case / "pipe-result.json").is_file():
                if (case / "pipe-error.json").is_file():
                    raise QualificationRejected((case / "pipe-error.json").read_text())
                if owner.poll() is not None or monotonic() > deadline:
                    raise QualificationRejected("E_PIPE_OWNER_RESULT")
                sleep(0.02)
            result = json.loads((case / "pipe-result.json").read_text())
        finally:
            termination = _kill_owned_process_group(owner)
        phases.append(
            {
                "phase": phase,
                "config": config,
                "work": work,
                "result": result,
                "owner": owner_record,
                "browser": browser_record,
                "invocation": invocation,
                "termination": termination,
                "artifacts": {
                    name: {"path": str((case / name).resolve()), "sha256": _sha256(case / name)}
                    for name in (
                        "input.json",
                        "start.json",
                        "pipe-result.json",
                        "pipe.ndjson",
                        "node.stdout",
                        "node.stderr",
                        "chrome.stdout",
                        "chrome.stderr",
                    )
                },
            }
        )
    first, second = [row["result"]["sentinel"] for row in phases]
    executable = str(_canonical_browser_executable(browser_binary))
    evidence: dict[str, Any] = {
        "result": "PASS",
        "transport": "pipe",
        "attempted_real_browser": True,
        "binding": capture_binding(),
        "workspace": str(workspace.resolve()),
        "pipe_phases": phases,
        "script_sha256": _sha256(script),
        "browser": {
            "expected_executable": executable,
            "sha256": _sha256(Path(executable)),
            "version": phases[0]["result"]["version"]["product"],
            "first_process_executable": phases[0]["browser"]["executable"],
            "second_process_executable": phases[1]["browser"]["executable"],
            "first_process_sha256": phases[0]["browser"]["sha256"],
            "second_process_sha256": phases[1]["browser"]["sha256"],
        },
        "profile": {
            "path": str(profile),
            "expected_id": profile_id,
            "first_id": profile_id,
            "second_id": (profile / "BH_R04_PROFILE_ID").read_text(),
            "fresh": True,
        },
        "extension": {
            "expected_id": extension_id,
            "first_id": first["extensionId"],
            "second_id": second["extensionId"],
            "first_protocol": first["protocol"],
            "second_protocol": second["protocol"],
            "first_origin": first["origin"],
            "second_origin": second["origin"],
            "load_requested": True,
        },
        "module": {
            "expected_sha256": module_hash,
            "first_sha256": first["moduleSha256"],
            "second_sha256": second["moduleSha256"],
            "first_url": first["moduleUrl"],
            "second_url": second["moduleUrl"],
        },
        "sentinel": {
            "expected": profile_id,
            "committed": first["sentinel"],
            "durable": second["sentinel"],
            "profile_id": second["profileId"],
        },
        "termination": phases[0]["termination"],
    }
    validate_qualification_evidence(evidence)
    return evidence


def _verify_hosted_pipe(evidence: dict[str, Any]) -> None:
    from tools.verify_repair_evidence import (
        _compiled_browser_module_hashes,
        _typescript_compile_binding,
        capture_binding,
    )

    try:
        current = capture_binding()
        workspace = Path(evidence["workspace"])
        profile = workspace / "chrome-profile"
        extension = workspace / "test-extension"
        root = Path(__file__).resolve().parents[1]
        if (
            evidence["binding"] != current
            or _sha256(workspace / "chrome_pipe.cjs") != evidence["script_sha256"]
            or (workspace / "chrome_pipe.cjs").read_bytes()
            != (root / "tools/chrome_pipe.cjs").read_bytes()
        ):
            raise ValueError("binding")
        for name, source in (
            ("manifest.json", "repair-manifest.json"),
            ("repair-probe.html", "repair-probe.html"),
        ):
            if (extension / name).read_bytes() != (
                root / "extension/test-harness" / source
            ).read_bytes():
                raise ValueError("asset")
        modules = {
            str(path.relative_to(extension)): _sha256(path) for path in extension.rglob("*.js")
        }
        if modules != _compiled_browser_module_hashes(_typescript_compile_binding(current)):
            raise ValueError("modules")
        profile_id = evidence["profile"]["expected_id"]
        if (profile / "BH_R04_PROFILE_ID").read_text() != profile_id:
            raise ValueError("profile")
        origin = "chrome-extension://" + _extension_id(
            json.loads((extension / "manifest.json").read_text())["key"]
        )
        pids = []
        for phase, row in zip(("before", "after"), evidence["pipe_phases"], strict=True):
            case = workspace / phase
            config: dict[str, Any] = {
                "command": _pipe_browser_command(
                    Path(evidence["browser"]["expected_executable"]), profile
                ),
                "workspace": str(case.resolve()),
                "extension": str(extension.resolve()),
                "origin": origin,
            }
            work = _pipe_work(profile_id, phase, "", None)
            if row["phase"] != phase or row["config"] != config or row["work"] != work:
                raise ValueError("input")
            contents = {}
            for name, descriptor in row["artifacts"].items():
                path = case / name
                if descriptor["path"] != str(path.resolve()) or descriptor["sha256"] != _sha256(
                    path
                ):
                    raise ValueError("artifact")
                contents[name] = path.read_bytes()
            if set(contents) != {
                "input.json",
                "start.json",
                "pipe-result.json",
                "pipe.ndjson",
                "node.stdout",
                "node.stderr",
                "chrome.stdout",
                "chrome.stderr",
            }:
                raise ValueError("artifact set")
            if (
                json.loads(contents["input.json"]) != config
                or json.loads(contents["start.json"]) != work
                or json.loads(contents["pipe-result.json"]) != row["result"]
                or any(contents[name] for name in ("node.stdout", "node.stderr", "chrome.stdout"))
            ):
                raise ValueError("output")
            owner, browser = row["owner"], row["browser"]
            if (
                owner["pid"] == browser["pid"]
                or owner["pid"] != owner["pgid"]
                or browser["pgid"] != owner["pid"]
            ):
                raise ValueError("group")
            for process, command in ((owner, row["invocation"]), (browser, config["command"])):
                raw = bytes.fromhex(process["proc_cmdline_hex"]).rstrip(b"\0").decode().split("\0")
                fields = process["proc_stat"][process["proc_stat"].rindex(")") + 2 :].split()
                headless = [
                    " ".join(
                        [
                            *command[:-1],
                            "--noerrdialogs",
                            "--ozone-platform=headless",
                            "--ozone-override-screen-size=800,600",
                            "--use-angle=swiftshader-webgl",
                            command[-1],
                        ]
                    )
                ]
                allowed = (command, headless) if process is browser else (command,)
                if (
                    process["pid"] in pids
                    or not process["proc_stat"].startswith(str(process["pid"]) + " ")
                    or int(fields[2]) != owner["pid"]
                    or raw != process["argv"]
                    or raw not in allowed
                    or process["sha256"] != _sha256(Path(process["executable"]))
                    or Path(process["executable"]) != Path(command[0]).resolve()
                ):
                    raise ValueError("process")
                pids.append(process["pid"])
            if (
                int(browser["proc_stat"][browser["proc_stat"].rindex(")") + 2 :].split()[1])
                != owner["pid"]
            ):
                raise ValueError("parent")
            if row["invocation"][1:] != [
                str((workspace / "chrome_pipe.cjs").resolve()),
                str((case / "input.json").resolve()),
            ]:
                raise ValueError("owner command")
            result = row["result"]
            if result["pid"] != browser["pid"] or result["node_pid"] != owner["pid"]:
                raise ValueError("result identity")
            _verify_pipe_transcript(contents["pipe.ndjson"], config, work, result)
            if (
                result["sentinel"]["sentinel"] != profile_id
                or result["sentinel"]["profileId"] != profile_id
                or result["sentinel"]["origin"] != origin
                or result["sentinel"]["moduleSha256"] != modules["src/spool.js"]
                or row["termination"]
                != {
                    "method": "SIGKILL_PROCESS_GROUP",
                    "signal": 9,
                    "returncode": -9,
                    "graceful": False,
                    "owned_process_group": True,
                }
            ):
                raise ValueError("restart")
        first, second = [row["result"]["sentinel"] for row in evidence["pipe_phases"]]
        if (
            evidence["sentinel"]
            != {
                "expected": profile_id,
                "committed": first["sentinel"],
                "durable": second["sentinel"],
                "profile_id": second["profileId"],
            }
            or evidence["termination"] != evidence["pipe_phases"][0]["termination"]
        ):
            raise ValueError("summary")
        if evidence["module"] != {
            "expected_sha256": modules["src/spool.js"],
            "first_sha256": first["moduleSha256"],
            "second_sha256": second["moduleSha256"],
            "first_url": first["moduleUrl"],
            "second_url": second["moduleUrl"],
        }:
            raise ValueError("module summary")
        expected_extension = origin.split("://")[1]
        if evidence["extension"] != {
            "expected_id": expected_extension,
            "first_id": first["extensionId"],
            "second_id": second["extensionId"],
            "first_protocol": first["protocol"],
            "second_protocol": second["protocol"],
            "first_origin": first["origin"],
            "second_origin": second["origin"],
            "load_requested": True,
        }:
            raise ValueError("extension summary")
        for name, row in zip(("first", "second"), evidence["pipe_phases"], strict=True):
            if (
                evidence["browser"][name + "_process_executable"] != row["browser"]["executable"]
                or evidence["browser"][name + "_process_sha256"] != row["browser"]["sha256"]
            ):
                raise ValueError("browser summary")
        if (
            evidence["browser"]["version"]
            != evidence["pipe_phases"][0]["result"]["version"]["product"]
        ):
            raise ValueError("version summary")
    except (KeyError, ValueError, TypeError, OSError) as error:
        raise QualificationRejected("E_PIPE_QUALIFICATION_EVIDENCE") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--browser-binary", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--transport", choices=("legacy", "pipe"), default="legacy")
    args = parser.parse_args()
    print(
        json.dumps(
            qualify_chrome_indexeddb_environment(
                args.workspace,
                browser_binary=args.browser_binary,
                repository_root=args.repository_root,
                transport=args.transport,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
