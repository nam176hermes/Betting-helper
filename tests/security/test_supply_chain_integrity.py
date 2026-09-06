import json
import shutil
from pathlib import Path

import pytest

from moj_discovery.vendor import verify_vendored_assets


def test_security_boundary(tmp_path: Path) -> None:
    vectors = {
        "allow": "SEC_SUPPLY_CHAIN-ALLOW",
        "deny": "SEC_SUPPLY_CHAIN-DENY",
        "mutate": "SEC_SUPPLY_CHAIN-MUTATE",
    }
    root = Path(__file__).parents[2]
    assert verify_vendored_assets(root), vectors["allow"]

    for index, mutation in enumerate(("vendor-byte", "untracked-dependency", "lock-byte")):
        candidate = tmp_path / str(index)
        shutil.copytree(root / "vendor", candidate / "vendor")
        shutil.copy2(root / "schema-lock.json", candidate / "schema-lock.json")
        shutil.copy2(root / "task-command-registry.json", candidate / "task-command-registry.json")
        if mutation == "vendor-byte":
            changed = candidate / "vendor/hybrid-discovery-v6.3.6/cdp/browser_protocol.json"
            changed.write_bytes(changed.read_bytes() + b"\n")
        elif mutation == "untracked-dependency":
            (candidate / "vendor/hybrid-discovery-v6.3.6/undeclared-package.json").write_text("{}")
        else:
            changed = candidate / "schema-lock.json"
            lock = json.loads(changed.read_text())
            lock["vendor_tree_sha256"] = "0" * 64
            changed.write_text(json.dumps(lock))
        with pytest.raises((AssertionError, ValueError)):
            verify_vendored_assets(candidate)
        assert (vectors["deny"], vectors["mutate"])[index > 0]
