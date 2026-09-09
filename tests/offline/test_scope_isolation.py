import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_offline_build_has_no_operator_or_money_actions() -> None:
    manifest = json.loads((ROOT / "extension/manifest.offline.json").read_text())
    assert manifest.get("host_permissions", []) == ["http://127.0.0.1/*"]
    assert manifest.get("permissions", []) == []
    bootstrap = (ROOT / "extension/src/offline/bootstrap.ts").read_text()
    assert "collectors/" not in bootstrap and "chrome.cookies" not in bootstrap
    for name in ["offline_receiver", "input_journal", "live_preflight", "diagnostic"]:
        tree = ast.parse((ROOT / "src/moj_discovery" / (name + ".py")).read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any("collector" in module or "provider" in module for module in imports)


@pytest.mark.parametrize(
    "module,call",
    [
        ("tools.offline_oracle", 'assert_case("OFF-01", Path("missing"))'),
        ("tools.offline_meta", 'check_meta("OFF-20", Path("missing"), None)'),
        ("tools.verify_offline_slice", 'verify_offline_slice(Path("missing"))'),
    ],
)
def test_optimized_execution_cannot_issue_pass(module: str, call: str) -> None:
    result = subprocess.run(  # noqa: S603 -- fixed interpreter and test literals
        [
            sys.executable,
            "-O",
            "-c",
            'import sys; sys.path.insert(0, "src"); from pathlib import Path; '
            f"from {module} import *; {call}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "E_OFFLINE_OPTIMIZED_EXECUTION" in result.stderr


def test_worker_startup_does_not_load_parent_expectations() -> None:
    result = subprocess.run(  # noqa: S603 -- fixed interpreter and literal probe
        [
            sys.executable,
            "-c",
            'import sys; sys.path.insert(0, "src"); '
            "import tools.run_offline_faults; "
            'assert "tools.offline_oracle" not in sys.modules',
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
