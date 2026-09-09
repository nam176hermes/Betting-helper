"""Owned real Chrome probe using the existing pipe launcher; no oracle input."""

import hashlib
import json
import shutil
from pathlib import Path
from subprocess import PIPE, Popen, run
from time import monotonic, sleep
from typing import Any, cast
from uuid import uuid4

from tools.qualify_chrome_indexeddb import (
    _browser_process_observation,
    _extension_id,
    _kill_owned_process_group,
    _pid_process_observation,
    _pipe_browser_command,
    _pipe_node_environment,
    _pipe_work,
    _prepare_test_extension,
)

ROOT = Path(__file__).resolve().parents[1]


def prepare_offline_extension(workspace: Path) -> tuple[Path, str]:
    extension = workspace / "offline-extension"
    extension.mkdir(parents=True, exist_ok=False)
    run(  # noqa: S603 -- fixed pinned compiler or generator with owned output
        [
            shutil.which("pnpm") or "/nonexistent/pnpm",
            "--dir",
            str(ROOT / "extension"),
            "exec",
            "tsc",
            "-p",
            "tsconfig.offline.json",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    build = ROOT / ".local/offline-slice/build/src"
    modules = [
        "canonical.js",
        "errors.js",
        "spool.js",
        "security/redaction.js",
        "security/loopback.js",
        "offline/protocol.js",
        "offline/bootstrap.js",
    ]
    for name in modules:
        destination = extension / "src" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = (build / name).read_text()
        if name in ("canonical.js", "security/redaction.js"):
            source = source.replace(
                'from "canonicalize"',
                'from "./canonicalize.js"'
                if name == "canonical.js"
                else 'from "../canonicalize.js"',
            )
        destination.write_text(source)
    shutil.copy2(
        ROOT / "extension/node_modules/canonicalize/lib/canonicalize.js",
        extension / "src/canonicalize.js",
    )
    shutil.copy2(ROOT / "extension/manifest.offline.json", extension / "manifest.json")
    shutil.copy2(ROOT / "extension/src/offline/page.html", extension / "src/offline/page.html")
    shutil.copy2(
        ROOT / "vendor/hybrid-discovery-v6.3.6/registries/canonical-hash-domains.v1.json",
        extension / "src/offline/canonical-registry.json",
    )
    run(  # noqa: S603 -- fixed pinned compiler or generator with owned output
        [
            shutil.which("node") or "/nonexistent/node",
            str(ROOT / "tools/build_offline_validators.cjs"),
            str(extension / "src/offline/validators.js"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    manifest = json.loads((extension / "manifest.json").read_text())
    hashes = {
        str(p.relative_to(extension)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(extension.rglob("*"))
        if p.is_file()
    }
    (workspace / "module-hashes.json").write_text(json.dumps(hashes, indent=2))
    return extension, _extension_id(manifest["key"])


class OfflineBrowser:
    """Private stdin carries credentials; retained outputs contain observed state only."""

    def __init__(
        self,
        workspace: Path,
        extension: Path,
        origin: str,
        browser: Path = Path("/opt/google/chrome/chrome"),
        profile: Path | None = None,
    ):
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=False)
        profile = profile or self.workspace / "profile"
        boundary = extension.resolve().parent
        if not profile.resolve().is_relative_to(boundary) or any(
            p.is_symlink() for p in (profile, *profile.parents)
        ):
            raise ValueError("E_OFFLINE_PROFILE_OWNERSHIP")
        marker = profile / ".offline-owned.json"
        binding = {
            "profile": str(profile.resolve()),
            "extension": str(extension.resolve()),
            "origin": origin,
        }
        if profile.exists():
            if (
                marker.is_symlink()
                or not marker.is_file()
                or json.loads(marker.read_text()) != binding
            ):
                raise ValueError("E_OFFLINE_PROFILE_OWNERSHIP")
        else:
            profile.mkdir()
            marker.write_text(json.dumps(binding))
        config = {
            "command": _pipe_browser_command(browser, profile),
            "workspace": str(self.workspace),
            "extension": str(extension),
            "origin": origin,
            "offline": True,
        }
        (self.workspace / "input.json").write_text(json.dumps(config))
        (self.workspace / "start.json").write_text("{}")
        with (
            (self.workspace / "node.stdout").open("wb") as out,
            (self.workspace / "node.stderr").open("wb") as err,
        ):
            self.owner = Popen(  # noqa: S603 -- owned fixed Chrome helper
                [
                    shutil.which("node") or "/nonexistent/node",
                    str(ROOT / "tools/chrome_pipe.cjs"),
                    str(self.workspace / "input.json"),
                ],
                stdin=PIPE,
                stdout=out,
                stderr=err,
                start_new_session=True,
                env=_pipe_node_environment(),
            )
        self.index = 0
        try:
            self.ready = self.wait("offline-ready.json")
            observed = _pid_process_observation(self.ready["pid"])
            if (
                self.ready["node_pid"] != self.owner.pid
                or observed["pgid"] != self.owner.pid
                or self.ready["document"]["origin"] != origin
            ):
                raise RuntimeError("E_OFFLINE_BROWSER_IDENTITY")
            self.ready["process"] = observed
            self.ready["binary_sha256"] = hashlib.sha256(browser.read_bytes()).hexdigest()
            (self.workspace / "identity.json").write_text(json.dumps(self.ready, indent=2))
        except BaseException:
            self.close()
            raise

    def wait(self, name: str) -> dict[str, Any]:
        deadline = monotonic() + 130
        while not (self.workspace / name).is_file():
            if self.owner.poll() is not None or (self.workspace / "pipe-error.json").exists():
                raise RuntimeError("E_OFFLINE_BROWSER_PROBE")
            if monotonic() > deadline:
                raise RuntimeError("E_OFFLINE_BROWSER_TIMEOUT")
            sleep(0.02)
        return cast(dict[str, Any], json.loads((self.workspace / name).read_text()))

    def command(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.collect(self.submit(request))

    def submit(self, request: dict[str, Any]) -> int:
        assert self.owner.stdin is not None
        self.owner.stdin.write(json.dumps(request).encode() + b"\n")
        self.owner.stdin.flush()
        self.index += 1
        return self.index

    def collect(self, index: int) -> dict[str, Any]:
        return cast(dict[str, Any], self.wait(f"offline-result-{index}.json")["result"])

    def close(self) -> None:
        termination = _kill_owned_process_group(self.owner)
        (self.workspace / "termination.json").write_text(json.dumps(termination))


def run_worker_probe(
    workspace: Path, request: dict[str, Any], browser: Path = Path("/opt/google/chrome/chrome")
) -> dict[str, Any]:
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    profile = workspace / "profile"
    profile.mkdir()
    extension, extension_id, _ = _prepare_test_extension(ROOT, workspace)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("E_NODE_UNAVAILABLE")
    config = {
        "command": _pipe_browser_command(browser, profile),
        "workspace": str(workspace),
        "extension": str(extension),
        "origin": "chrome-extension://" + extension_id,
    }
    (workspace / "input.json").write_text(json.dumps(config))
    with (
        (workspace / "node.stdout").open("wb") as out,
        (workspace / "node.stderr").open("wb") as err,
    ):
        owner = Popen(  # noqa: S603 -- owned browser helper and fixed local input
            [node, str(ROOT / "tools/chrome_pipe.cjs"), str(workspace / "input.json")],
            stdout=out,
            stderr=err,
            start_new_session=True,
            env=_pipe_node_environment(),
        )
    try:

        def wait(name: str) -> dict[str, Any]:
            deadline = monotonic() + 30
            while not (workspace / name).is_file():
                if owner.poll() is not None or (workspace / "pipe-error.json").exists():
                    raise RuntimeError("E_OFFLINE_BROWSER_PROBE")
                if monotonic() > deadline:
                    raise RuntimeError("E_OFFLINE_BROWSER_TIMEOUT")
                sleep(0.02)
            return cast(dict[str, Any], json.loads((workspace / name).read_text()))

        ready = wait("pipe-ready.json")
        leader = _browser_process_observation(owner)
        observed = _pid_process_observation(ready["pid"])
        if ready["node_pid"] != owner.pid or observed["pgid"] != owner.pid:
            raise RuntimeError("E_OFFLINE_BROWSER_IDENTITY")
        work = _pipe_work(str(uuid4()), "before", str(uuid4()), request)
        (workspace / "start.json").write_text(json.dumps(work))
        result = wait("pipe-result.json")
        if result["document"]["origin"] != config["origin"]:
            raise RuntimeError("E_OFFLINE_BROWSER_ORIGIN")
        result["owner"] = leader
        result["browser"] = observed
    finally:
        termination = _kill_owned_process_group(owner)
    result["termination"] = termination
    (workspace / "observed.json").write_text(json.dumps(result, indent=2))
    return result
