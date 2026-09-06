from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/verification.yml"
ACTION_PINS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",
    "astral-sh/setup-uv": "37802adc94f370d6bfd71619e3f0bf239e1f3b78",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}


def _workflow() -> dict[str, Any]:
    assert WORKFLOW.is_file(), "BH-R10 workflow contract is absent"
    return cast(dict[str, Any], json.loads(WORKFLOW.read_text()))


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], job["steps"])


def _run(job: dict[str, Any], name: str) -> str:
    return cast(str, next(step["run"] for step in _steps(job) if step["name"] == name))


def _all_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in _steps(job)]


def test_ci_profiles_are_read_only_pinned_and_separate() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert set(workflow["jobs"]) == {"portable", "browser-qualification"}

    serialized = json.dumps(workflow)
    assert "secrets." not in serialized
    assert "self-hosted" not in serialized
    assert all(f"{name}@{pin}" in serialized for name, pin in ACTION_PINS.items())
    for step in _all_steps(workflow):
        if uses := step.get("uses"):
            assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", uses)
        assert step.get("continue-on-error") is not True
        if command := step.get("run"):
            assert re.search(r"(?m)^\s*exit\s+0\s*$", command) is None

    portable = workflow["jobs"]["portable"]
    assert portable["runs-on"] == "ubuntu-24.04"
    assert "uv sync --frozen" in _run(portable, "Provision locked dependencies")
    assert "pnpm install --frozen-lockfile" in _run(
        portable, "Provision locked dependencies"
    )
    portable_verify = _run(portable, "Run portable verification offline")
    portable_step = next(
        step
        for step in _steps(portable)
        if step["name"] == "Run portable verification offline"
    )
    assert portable_step["shell"] == "bash"
    assert "uv run --frozen --offline python tools/verify_local.py --profile portable" in (
        portable_verify
    )
    assert "install" not in portable_verify

    browser = workflow["jobs"]["browser-qualification"]
    assert browser["runs-on"] == "ubuntu-24.04"
    assert browser["if"] == "github.event_name == 'workflow_dispatch'"
    assert "qualify_chrome_indexeddb.py" in _run(
        browser, "Run isolated browser qualification"
    )
    assert "BLOCKED_ENVIRONMENT" in _run(
        browser, "Run isolated browser qualification"
    )
    assert "sys.exit(2)" in _run(browser, "Run isolated browser qualification")

    browser_upload = next(
        step for step in _steps(browser) if step.get("name") == "Publish sanitized evidence"
    )
    assert browser_upload["if"] == "always()"
    assert browser_upload["with"]["path"] == ".local/ci/browser-summary.json"
    assert "raw" not in json.dumps(browser_upload).lower()
