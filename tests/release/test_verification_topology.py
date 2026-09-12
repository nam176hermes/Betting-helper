import json
from pathlib import Path

import pytest

from tools.verify_test_discovery import verify_verification_topology


def test_all_proof_groups_are_discovered_and_registry_bound() -> None:
    result = verify_verification_topology()
    assert result["result"] == "PASS"
    assert result["group_count"] == 11
    assert result["command_count"] == 45
    discovery = result["discovery_evidence"]
    assert isinstance(discovery, dict) and discovery["observations"]


@pytest.mark.parametrize(
    "damage", ["review_operands", "typescript_exclusion", "node_operands", "compiler_output"]
)
def test_topology_rejects_commands_or_compiler_omitting_a_group(
    tmp_path: Path, damage: str
) -> None:
    root = Path(__file__).parents[2]
    for name in ("vendor", "tests", "tools", "src", ".venv", "node_modules", "tests-red"):
        (tmp_path / name).symlink_to(root / name, target_is_directory=True)
    (tmp_path / "pyproject.toml").write_bytes((root / "pyproject.toml").read_bytes())
    ext = tmp_path / "extension"
    ext.mkdir()
    for source in (root / "extension").iterdir():
        if source.name.startswith("tsconfig") and source.suffix == ".json":
            (ext / source.name).write_bytes(source.read_bytes())
        elif source.name in {"src", "test", "test-harness", "test-red", "tools", "node_modules"}:
            (ext / source.name).symlink_to(source, target_is_directory=source.is_dir())
    registry = json.loads((root / "task-command-registry.json").read_bytes())
    if damage == "review_operands":
        for command in registry["commands"]:
            if "pytest" in command["argv"]:
                command["argv"] = [
                    token for token in command["argv"] if not token.startswith("tests/review")
                ]
    elif damage == "node_operands":
        for command in registry["commands"]:
            if command["argv"][0] == "node":
                command["argv"] = [
                    token for token in command["argv"] if "/test/security/" not in token
                ]
    else:
        path = ext / "tsconfig.test.json"
        config = json.loads(path.read_bytes())
        if damage == "compiler_output":
            config["compilerOptions"]["outDir"] = ".different-output"
        else:
            config["exclude"] = ["test/security/**"]
        path.write_text(json.dumps(config))
    (tmp_path / "task-command-registry.json").write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="E_VERIFICATION_TOPOLOGY"):
        verify_verification_topology(tmp_path)
