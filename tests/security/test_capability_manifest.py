import json
import shutil
from pathlib import Path

import pytest

from moj_discovery.governance import validate_capability_artifacts

ROOT = Path(__file__).parents[2]


def test_security_boundary(tmp_path: Path) -> None:
    vectors = (
        "SEC_CAPABILITY_MANIFEST-ALLOW",
        "SEC_CAPABILITY_MANIFEST-DENY",
        "SEC_CAPABILITY_MANIFEST-MUTATE",
    )
    validate_capability_artifacts()
    vendor = tmp_path / "vendor"
    shutil.copytree(ROOT / "vendor/hybrid-discovery-v6.3.6", vendor)
    manifest_path = vendor / "security/discovery-capability-manifest.v1.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["chrome_manifest"]["permissions"].append("tabs")
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(AssertionError):
        validate_capability_artifacts(vendor)
    assert vectors
