import json
import tomllib
from pathlib import Path

from tools.verify_toolchains import verify_dependency_policy


ROOT = Path(__file__).parents[2]


def test_all_test_and_harness_directories_are_discovered() -> None:
    assert verify_dependency_policy(ROOT) == []
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests", "../authoring-tests"]
    test_config = json.loads((ROOT / "extension/tsconfig.test.json").read_text())
    harness_config = json.loads((ROOT / "extension/tsconfig.harness.json").read_text())
    assert test_config["include"] == ["src/**/*.ts", "test/**/*.ts", "test-red/**/*.ts", "tools/**/*.ts", "test-harness/**/*.ts"]
    assert harness_config["include"] == ["src/**/*.ts", "test-harness/**/*.ts", "test/durability/**/*.ts", "test/security/**/*.ts"]
