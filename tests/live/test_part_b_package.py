import hashlib
import json
from pathlib import Path

import pytest


def test_delivery_rejects_changed_extra_and_aliased_files(tmp_path: Path) -> None:
    from tools.package_part_b import validate_delivery

    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "app.js").write_bytes(b"source")
    record = {
        "schema_version": "part-b-delivery/v1",
        "source_commit": "a" * 40,
        "model_enabled": False,
        "money_ready": False,
        "files": {"app.js": {"sha256": hashlib.sha256(b"source").hexdigest(), "size_bytes": 6}},
    }
    (payload / "DELIVERY_MANIFEST.json").write_text(json.dumps(record))
    assert validate_delivery(payload) == record
    (payload / "app.js").write_bytes(b"changed")
    with pytest.raises(ValueError, match="E_DELIVERY"):
        validate_delivery(payload)
    (payload / "app.js").write_bytes(b"source")
    (payload / "unexpected").write_text("extra")
    with pytest.raises(ValueError, match="E_DELIVERY"):
        validate_delivery(payload)
    (payload / "unexpected").unlink()
    (payload / "alias").symlink_to(payload / "app.js")
    with pytest.raises(ValueError, match="E_DELIVERY"):
        validate_delivery(payload)


def test_delivery_paths_cannot_escape_or_hide_case_collisions(tmp_path: Path) -> None:
    from tools.package_part_b import validate_delivery

    (tmp_path / "DELIVERY_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": "part-b-delivery/v1",
                "source_commit": "a" * 40,
                "model_enabled": False,
                "money_ready": False,
                "files": {"../secret": {"sha256": "a" * 64, "size_bytes": 0}},
            }
        )
    )
    with pytest.raises(ValueError, match="E_DELIVERY"):
        validate_delivery(tmp_path)
