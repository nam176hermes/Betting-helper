import json
from pathlib import Path

import pytest

from tools.compute_governed_content_root import compute_governed_content_root


def _registry(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "seal-exclusions/v2",
                "governed_root_exclusions": [
                    "GOVERNED_CONTENT_ROOT.json",
                    "SELF_REVIEW_REPORT.md",
                    "SELF_REVIEW_REPORT.json",
                    "MANIFEST_SHA256.json",
                ],
                "external_outputs_must_be_outside_root": True,
            }
        )
    )
    return path


def test_root_is_acyclic_and_exclusion_registry_is_closed(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "artifact.txt").write_text("one")
    registry = _registry(tmp_path / "seal-exclusions.json")
    first = compute_governed_content_root(pack, registry)
    (pack / "SELF_REVIEW_REPORT.md").write_text("unbound")
    second = compute_governed_content_root(pack, registry)
    assert first["root_sha256"] == second["root_sha256"]

    registry.write_text(json.dumps({"schema_version": "seal-exclusions/v2"}))
    with pytest.raises(ValueError, match="E_GOVERNED_ROOT"):
        compute_governed_content_root(pack, registry)
