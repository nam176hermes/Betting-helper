"""Qualify real extension-origin IndexedDB durability in an isolated Chrome."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
from pathlib import Path
from secrets import token_hex
from signal import SIGKILL
from subprocess import DEVNULL, Popen, run
from time import monotonic, sleep
from typing import cast
from urllib.request import urlopen
from uuid import uuid4

_CDP = r'''
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
'''


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
            [
                str(command),
                "--headless=new",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-component-extensions-with-background-pages",
                "--disable-default-apps",
                "--disable-gpu",
                "--disable-sync",
                "--metrics-recording-only",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
                extension_url,
            ],
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
    shutil.copy2(source_root / "node_modules/canonicalize/lib/canonicalize.js",
                 extension / "src/canonicalize.js")
    shutil.copy2(build_root / "test-harness/indexeddb-crash-child.js",
                 extension / "indexeddb-crash-child.js")
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
) -> dict[str, object]:
    """Commit a random sentinel, SIGKILL owned Chrome, and read it after restart."""
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--browser-binary", type=Path)
    parser.add_argument("--repository-root", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            qualify_chrome_indexeddb_environment(
                args.workspace,
                browser_binary=args.browser_binary,
                repository_root=args.repository_root,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
