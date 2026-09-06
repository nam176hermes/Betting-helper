import json
from pathlib import Path

import pytest

from moj_discovery.governance import (
    validate_custody_and_authority,
    validate_runtime_custody_prohibitions,
)


def test_runtime_has_no_production_authority() -> None:
    validate_custody_and_authority()
    validate_runtime_custody_prohibitions()


def test_runtime_rejects_pack_held_signing_keys(tmp_path: Path) -> None:
    security = tmp_path / "security"
    security.mkdir()
    (security / "discovery-capability-manifest.v1.json").write_text(
        json.dumps({"production_authority": "NONE", "body_classes": []})
    )
    (security / "trust-root.v1.json").write_text(
        json.dumps(
            {
                "trusted_keys": [],
                "production_authority": "NONE",
                "signing_key_custody": "PACK_HELD_PRIVATE_KEYS",
            }
        )
    )
    with pytest.raises(AssertionError):
        validate_custody_and_authority(tmp_path)


@pytest.mark.parametrize(
    "symbol",
    [
        "automatic_backup",
        "automatic_archive",
        "compact_records",
        "rolling_deletion",
        "retention_daemon",
        "automatic_cleanup",
        "restore_backup",
        "delete_acked_record",
    ],
)
def test_runtime_rejects_automatic_or_individual_custody_paths(
    tmp_path: Path, symbol: str
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "forbidden.py").write_text(f"def {symbol}() -> None:\n    pass\n")

    with pytest.raises(AssertionError, match="E_CUSTODY_PATH_DENIED"):
        validate_runtime_custody_prohibitions(tmp_path)
