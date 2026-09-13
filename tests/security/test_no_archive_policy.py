from pathlib import Path
from shutil import copytree

import pytest

from moj_discovery.governance import validate_runtime_custody_prohibitions


def test_security_boundary(tmp_path: Path) -> None:
    vectors = {
        "allow": "SEC_NO_ARCHIVE-ALLOW",
        "deny": "SEC_NO_ARCHIVE-DENY",
        "mutate": "SEC_NO_ARCHIVE-MUTATE",
    }
    root = Path(__file__).resolve().parents[2]
    validate_runtime_custody_prohibitions(root)
    copied = tmp_path / "candidate"
    for relative in ("src", "tools", "extension/src"):
        copytree(root / relative, copied / relative)
    validate_runtime_custody_prohibitions(copied)
    for relative in ("src", "tools", "extension/src"):
        suffix = ".ts" if relative == "extension/src" else ".py"
        mutation = copied / relative / ("TEST_ONLY_custody_mutation" + suffix)
        mutation.write_text("function automatic_archive() {}\n" if suffix == ".ts"
                            else "def automatic_archive(): pass\n")
        with pytest.raises(AssertionError) as denied:
            validate_runtime_custody_prohibitions(copied)
        assert str(denied.value) == f"E_CUSTODY_PATH_DENIED:{mutation.relative_to(copied)}"
        mutation.unlink()
    source = tmp_path / "src"
    source.mkdir()
    candidate = source / "receipt.py"
    candidate.write_text("def write_receipt() -> None:\n    pass\n")
    validate_runtime_custody_prohibitions(tmp_path)
    assert vectors["allow"]

    for index, symbol in enumerate(("automatic_archive", "automatic_backup", "compact_records")):
        candidate.write_text(f"def {symbol}() -> None:\n    pass\n")
        with pytest.raises(AssertionError, match="E_CUSTODY_PATH_DENIED"):
            validate_runtime_custody_prohibitions(tmp_path)
        assert (vectors["deny"], vectors["mutate"])[index > 0]


@pytest.mark.parametrize("suffix", [".py", ".ts"])
def test_custody_scanner_uses_identifiers_and_ack_tokens(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / "src"
    source.mkdir()
    candidate = source / ("receipt" + suffix)

    def definition(symbol: str) -> str:
        return (
            f"# Restore display subscriptions\ndef {symbol}(): pass\n"
            if suffix == ".py"
            else f"// Restore display subscriptions\nfunction {symbol}() {{}}\n"
        )

    candidate.write_text(definition("delete_backend"))
    validate_runtime_custody_prohibitions(tmp_path)
    for symbol in ("delete_acked_record", "deleteAckedRecord", "deleteACK", "deleteackrecord",
                   "acknowledged_record_delete", "restore_backup", "automatic_archive"):
        candidate.write_text(definition(symbol))
        with pytest.raises(AssertionError, match="E_CUSTODY_PATH_DENIED"):
            validate_runtime_custody_prohibitions(tmp_path)
    if suffix == ".ts":
        for text in ("store[`delete_acked_${suffix}`]();",
                     "store[`allowed_${deleteAckedRecord()}`]();",
                     "store[`allowed_${suffix}restore_backup`]();",
                     'store["delete_acked_record"]();',
                     "class Store { #delete_acked_record() {} }",
                     "store[/delete_acked_record/.source]();",
                     r"function delete\u005facked_record() {}",
                     r'store["delete\u005facked_record"]();'):
            candidate.write_text(text)
            with pytest.raises(AssertionError, match="E_CUSTODY_PATH_DENIED"):
                validate_runtime_custody_prohibitions(tmp_path)
        candidate.write_text("function incomplete( {")
        with pytest.raises(AssertionError, match="E_CUSTODY_SOURCE_PARSE"):
            validate_runtime_custody_prohibitions(tmp_path)
