import os
from pathlib import Path

from tools.qualify_chrome_indexeddb import (
    qualify_chrome_indexeddb_environment,
    validate_qualification_evidence,
)


def test_real_chrome_indexeddb_survives_abrupt_process_kill(tmp_path: Path) -> None:
    configured_browser = os.environ.get("BH_CHROME_BINARY")
    assert configured_browser, "E_BROWSER_CONFIGURATION_REQUIRED"
    browser = Path(configured_browser)
    assert browser.is_absolute() and browser.is_file(), "E_BROWSER_UNAVAILABLE"
    result = qualify_chrome_indexeddb_environment(
        tmp_path, browser_binary=browser, transport="pipe"
    )
    assert result["result"] == "PASS", result
    assert result["transport"] == "pipe"
    assert result["attempted_real_browser"] is True
    validate_qualification_evidence(result)
