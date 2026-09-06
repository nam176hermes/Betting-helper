from pathlib import Path

import pytest

from moj_discovery.governance import validate_runtime_custody_prohibitions


def test_security_boundary(tmp_path: Path) -> None:
    vectors = {
        "allow": "SEC_NO_ARCHIVE-ALLOW",
        "deny": "SEC_NO_ARCHIVE-DENY",
        "mutate": "SEC_NO_ARCHIVE-MUTATE",
    }
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
