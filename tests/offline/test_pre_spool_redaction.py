"""Exercise the compiled production projector, not a Python replacement."""

import shutil
import subprocess
from pathlib import Path


def test_real_typescript_projector() -> None:
    node = shutil.which("node")
    assert node
    subprocess.run(  # noqa: S603 -- installed Node and fixed compiled test.
        [node, "--test", "extension/.test-build/test/offline/redaction.test.js"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        timeout=30,
    )
