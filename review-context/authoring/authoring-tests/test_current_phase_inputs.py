import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def tool():
    spec = importlib.util.spec_from_file_location("current_phase", ROOT / "authoring-tools/validate_current_phase_inputs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_declaration_binds_every_registry_without_writing_receipt(tmp_path):
    m = tool()
    shutil.copytree(ROOT / "pack", tmp_path / "pack")
    receipt = tmp_path / "pack/docs/receipts/declaration-complete.v1.json"
    before = receipt.read_bytes()
    result = m.declaration(tmp_path)
    assert len(result["input_hashes"]) == 7
    assert result["gate"] == "CURRENT_DECLARATION_VALID"
    p = tmp_path / "pack/docs/registries/review-command-registry.v1.json"
    v = json.loads(p.read_text()); v["commands"][0]["purpose"] += " test"
    p.write_text(json.dumps(v))
    changed = m.declaration(tmp_path)
    assert changed["input_hashes"] != result["input_hashes"]
    assert receipt.read_bytes() == before
    p.unlink()
    with pytest.raises((ValueError, OSError)):
        m.declaration(tmp_path)


def test_logical_resolution_is_closed_and_rejects_intermediate_alias(tmp_path):
    m = tool()
    a, r = tmp_path / "a", tmp_path / "r"
    a.mkdir(); r.mkdir(); (a / "pack").mkdir()
    (r / "file").write_text("data")
    assert m.resolve(a, r, "runtime/file") == r / "file"
    (r / "link").symlink_to(r, target_is_directory=True)
    for name in ("runtime/link/file", "runtime/../file", "runtime//file", "runtime/./file", "/runtime/file", "authoring/file"):
        with pytest.raises(ValueError, match="E_CURRENT_PATH"):
            m.resolve(a, r, name)
    with pytest.raises(ValueError, match="E_CURRENT_PATH"):
        m.resolve(a, a, "runtime/file")


def test_changed_bytes_require_declared_owner_and_immutable_fixture_wins(tmp_path):
    m = tool()
    owner = {"runtime/src/a.py": {"creation_owner": "BASE", "modifying_tasks": []}}
    approved = {"runtime/src/a.py": "FIX"}
    with pytest.raises(ValueError, match="E_CURRENT_OWNER"):
        m.validate_changed_paths(["src/a.py"], approved, owner, set())
    owner["runtime/src/a.py"]["modifying_tasks"] = ["FIX"]
    m.validate_changed_paths(["src/a.py"], approved, owner, set())
    with pytest.raises(ValueError, match="E_CURRENT_UNDECLARED"):
        m.validate_changed_paths(["src/other.py"], approved, owner, set())
