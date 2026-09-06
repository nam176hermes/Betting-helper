from pathlib import Path

from tools.qualify_chrome_indexeddb import qualify_chrome_indexeddb_environment


def test_real_chrome_indexeddb_survives_abrupt_process_kill(tmp_path: Path) -> None:
    result = qualify_chrome_indexeddb_environment(tmp_path)
    assert result["result"] == "PASS"
    assert result["browser_process"] == "google-chrome"
    assert result["abrupt_kill"] is True
    assert result["durable_sentinel"] == "HD636_INDEXEDDB_SENTINEL"
