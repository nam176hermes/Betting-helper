"""Owned real Chrome probe using the existing pipe launcher; no oracle input."""

import json
import shutil
from pathlib import Path
from subprocess import Popen
from time import monotonic, sleep
from typing import Any, cast
from uuid import uuid4

from tools.qualify_chrome_indexeddb import (
    _browser_process_observation,
    _kill_owned_process_group,
    _pid_process_observation,
    _pipe_browser_command,
    _pipe_node_environment,
    _pipe_work,
    _prepare_test_extension,
)

ROOT = Path(__file__).resolve().parents[1]


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
