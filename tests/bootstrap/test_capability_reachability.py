import json
import shutil
from pathlib import Path

import pytest

from moj_discovery.governance import validate_capability_artifacts


def test_no_privileged_extension_source_exists_before_projection() -> None:
    validate_capability_artifacts()
    sources = "\n".join(path.read_text() for path in Path("extension/src").rglob("*.ts"))
    assert (
        "fetch(" not in sources
        and "XMLHttpRequest" not in sources
        and "new WebSocket" not in sources
    )


@pytest.mark.parametrize("field", ["vectors", "required_allowed_controls"])
def test_capability_vector_id_sets_are_exact(tmp_path: Path, field: str) -> None:
    vendor = tmp_path / "vendor"
    shutil.copytree(Path("vendor/hybrid-discovery-v6.3.6"), vendor)
    path = vendor / "vectors/capability-negative-v1.json"
    vectors = json.loads(path.read_text())
    vectors[field][0]["vector_id" if field == "vectors" else "control_id"] = "CAP-DRIFT"
    path.write_text(json.dumps(vectors))

    with pytest.raises(AssertionError):
        validate_capability_artifacts(vendor)
