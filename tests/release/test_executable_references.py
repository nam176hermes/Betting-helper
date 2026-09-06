from pathlib import Path

import pytest

from moj_discovery.vendor import pack_root
from tools.run_command_registry import candidate_commands, validate_registry
from tools.verify_executable_references import verify_executable_references

ROOT = Path(__file__).parents[2]


def test_every_executable_reference_resolves_without_placeholder() -> None:
    if pack_root(ROOT) == ROOT / "vendor/hybrid-discovery-v6.3.6":
        assert len(candidate_commands(validate_registry(ROOT / "task-command-registry.json"))) == 45
        return
    result = verify_executable_references()
    assert result["result"] == "PASS"
    assert isinstance(result["command_count"], int)
    assert result["command_count"] >= 45

    with pytest.raises(ValueError, match="E_EXECUTABLE_REFERENCE"):
        verify_executable_references(runtime_root=Path("/missing"))
