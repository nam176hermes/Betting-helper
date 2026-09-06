from __future__ import annotations

import copy
import json
from pathlib import Path
from signal import SIGKILL
from typing import cast

import pytest

from tools.qualify_chrome_indexeddb import (
    QualificationRejected,
    qualify_chrome_indexeddb_environment,
    validate_qualification_evidence,
)

ROOT = Path(__file__).parents[2]
CHROME_CANDIDATES = (Path("/usr/bin/google-chrome"), Path("/opt/google/chrome/chrome"))


def _valid_evidence() -> dict[str, object]:
    return {
        "result": "PASS",
        "browser": {
            "expected_executable": "/opt/google/chrome/chrome",
            "first_process_executable": "/opt/google/chrome/chrome",
            "second_process_executable": "/opt/google/chrome/chrome",
            "sha256": "a" * 64,
            "first_process_sha256": "a" * 64,
            "second_process_sha256": "a" * 64,
        },
        "profile": {
            "expected_id": "profile-1",
            "first_id": "profile-1",
            "second_id": "profile-1",
            "fresh": True,
        },
        "extension": {
            "expected_id": "abcdefghijklmnopabcdefghijklmnop",
            "first_id": "abcdefghijklmnopabcdefghijklmnop",
            "second_id": "abcdefghijklmnopabcdefghijklmnop",
            "first_origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
            "second_origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
            "first_protocol": "chrome-extension:",
            "second_protocol": "chrome-extension:",
        },
        "module": {
            "expected_sha256": "b" * 64,
            "first_sha256": "b" * 64,
            "second_sha256": "b" * 64,
            "first_url": (
                "chrome-extension://abcdefghijklmnopabcdefghijklmnop/src/spool.js"
            ),
            "second_url": (
                "chrome-extension://abcdefghijklmnopabcdefghijklmnop/src/spool.js"
            ),
        },
        "sentinel": {
            "expected": "random-sentinel",
            "committed": "random-sentinel",
            "durable": "random-sentinel",
            "profile_id": "profile-1",
        },
        "termination": {
            "method": "SIGKILL_PROCESS_GROUP",
            "signal": 9,
            "returncode": -9,
            "graceful": False,
            "owned_process_group": True,
        },
    }


@pytest.mark.parametrize(
    ("path", "value", "error"),
    [
        (("profile", "second_id"), "profile-2", "E_PROFILE_MISMATCH"),
        (("extension", "second_protocol"), "http:", "E_EXTENSION_ORIGIN"),
        (
            ("browser", "second_process_executable"),
            "/usr/bin/not-chrome",
            "E_BROWSER_BINARY_MISMATCH",
        ),
        (("termination", "graceful"), True, "E_GRACEFUL_ONLY_SHUTDOWN"),
    ],
)
def test_qualification_rejects_identity_and_shutdown_mutations(
    path: tuple[str, str], value: object, error: str
) -> None:
    evidence = copy.deepcopy(_valid_evidence())
    section = evidence[path[0]]
    assert isinstance(section, dict)
    section[path[1]] = value

    with pytest.raises(QualificationRejected, match=error):
        validate_qualification_evidence(evidence)


def test_valid_extension_crash_evidence_is_accepted() -> None:
    validate_qualification_evidence(_valid_evidence())


def test_test_extension_has_fixed_separate_identity_and_no_permissions() -> None:
    production = json.loads((ROOT / "extension/manifest.json").read_text())
    repair = json.loads(
        (ROOT / "extension/test-harness/repair-manifest.json").read_text()
    )

    assert repair["key"] != production["key"]
    assert repair["permissions"] == []
    assert repair["host_permissions"] == []
    assert repair["web_accessible_resources"] == []


def test_real_isolated_extension_indexeddb_survives_owned_sigkill(tmp_path: Path) -> None:
    browser = next((path for path in CHROME_CANDIDATES if path.is_file()), None)
    result = qualify_chrome_indexeddb_environment(
        tmp_path,
        browser_binary=browser,
        repository_root=ROOT,
    )

    if result["result"] == "BLOCKED_ENVIRONMENT":
        blocker_code = result["blocker_code"]
        assert blocker_code in {
            "E_BROWSER_UNAVAILABLE",
            "E_CHROME_START_FAILED",
            "E_EXTENSION_TARGET_UNAVAILABLE",
        }
        assert isinstance(result["blocker_detail"], str) and result["blocker_detail"]
        assert result["attempted_real_browser"] is (blocker_code != "E_BROWSER_UNAVAILABLE")
        assert cast(dict[str, object], result["profile"])["fresh"] is True
        assert cast(dict[str, object], result["extension"])["load_requested"] is True
        pytest.skip(f"{blocker_code}:{result['blocker_detail']}")

    assert result["result"] == "PASS"
    validate_qualification_evidence(result)
    sentinel = cast(dict[str, object], result["sentinel"])
    assert sentinel["expected"] == sentinel["committed"] == sentinel["durable"]
    termination = cast(dict[str, object], result["termination"])
    assert termination == {
        "method": "SIGKILL_PROCESS_GROUP",
        "signal": SIGKILL,
        "returncode": -SIGKILL,
        "graceful": False,
        "owned_process_group": True,
    }
    profile = cast(dict[str, object], result["profile"])
    assert profile["expected_id"] == profile["first_id"] == profile["second_id"]
    extension = cast(dict[str, object], result["extension"])
    assert extension["first_protocol"] == extension["second_protocol"] == "chrome-extension:"
    module = cast(dict[str, object], result["module"])
    assert module["expected_sha256"] == module["first_sha256"] == module["second_sha256"]
