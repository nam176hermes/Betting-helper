import copy
import json
from pathlib import Path

import pytest

from moj_discovery.vendor import plan_root
from tools.verify_cybersecurity_registry import verify_cybersecurity_command_registry

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)


def test_every_security_area_has_exact_executable_commands() -> None:
    registry = json.loads(
        (PLAN / "docs/registries/cybersecurity-command-registry.v1.json").read_text()
    )
    matrix = json.loads((PLAN / "docs/registries/cybersecurity-attack-matrix.v1.json").read_text())
    assert verify_cybersecurity_command_registry(registry, matrix) == {
        "result": "PASS",
        "security_area_count": 14,
    }
    changed = copy.deepcopy(registry)
    changed["commands"][0]["network"] = "ALLOW"
    with pytest.raises(ValueError, match="E_CYBERSECURITY_REGISTRY"):
        verify_cybersecurity_command_registry(changed, matrix)


def test_registry_rejects_leaf_without_declared_attack_vectors(tmp_path: Path) -> None:
    registry = {
        "commands": [
            {
                "command_id": f"SEC_{index}",
                "argv": ["pytest"],
                "required": True,
                "expected_exit": 0,
                "network": "DENY",
                "authenticated_operator_access": "DENY",
                "provider_access": "DENY",
            }
            for index in range(14)
        ]
    }
    matrix = {
        "entries": [
            {
                "command_id": f"SEC_{index}",
                "source": f"runtime/tests/security/test_{index}.py",
                "positive_vector_id": f"SEC_{index}-ALLOW",
                "negative_vector_id": f"SEC_{index}-DENY",
                "mutation_vector_id": f"SEC_{index}-MUTATE",
                "proof": "Call the pinned boundary",
            }
            for index in range(14)
        ]
    }
    for index in range(14):
        path = tmp_path / f"tests/security/test_{index}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_stub(): pass\n")

    with pytest.raises(ValueError, match="E_CYBERSECURITY_REGISTRY"):
        verify_cybersecurity_command_registry(registry, matrix, tmp_path)
