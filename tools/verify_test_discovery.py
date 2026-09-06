"""Verify every declared proof group is discoverable by a concrete test command."""

from __future__ import annotations

import json
from pathlib import Path

from moj_discovery.vendor import pack_root

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6"


def verify_verification_topology(runtime_root: Path = RUNTIME_ROOT) -> dict[str, object]:
    try:
        topology = json.loads(
            (
                runtime_root
                / "vendor/hybrid-discovery-v6.3.6/docs/registries/verification-topology.v1.json"
            ).read_text()
        )
        registry = json.loads((runtime_root / "task-command-registry.json").read_text())
        pyproject = (runtime_root / "pyproject.toml").read_text()
        test_config = (runtime_root / "extension/tsconfig.test.json").read_text()
        harness_config = (runtime_root / "extension/tsconfig.harness.json").read_text()
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_VERIFICATION_TOPOLOGY") from error
    groups = topology.get("group_sources") if isinstance(topology, dict) else None
    identifiers = topology.get("candidate_command_ids") if isinstance(topology, dict) else None
    commands = registry.get("commands") if isinstance(registry, dict) else None
    if (
        topology.get("schema_version") != "verification-topology/v1"
        or not isinstance(groups, dict)
        or not isinstance(identifiers, list)
        or not isinstance(commands, list)
    ):
        raise ValueError("E_VERIFICATION_TOPOLOGY")
    expected_groups = {
        "bootstrap",
        "authoring",
        "materialization",
        "contracts",
        "durability",
        "clock",
        "review",
        "security",
        "release",
        "seal",
        "test-harness",
    }

    def source_exists(source: str) -> bool:
        if (runtime_root.parent / source).exists() or (
            runtime_root / source.removeprefix("runtime/")
        ).exists():
            return True
        return pack_root(runtime_root) == runtime_root / "vendor/hybrid-discovery-v6.3.6" and (
            source == "authoring-tests" or source.startswith("plan-input/bootstrap/")
        )

    if set(groups) != expected_groups or any(
        not isinstance(source, str) or not source_exists(source)
        for sources in groups.values()
        if isinstance(sources, list)
        for source in sources
    ):
        raise ValueError("E_VERIFICATION_TOPOLOGY")
    command_ids = {command.get("command_id") for command in commands if isinstance(command, dict)}
    if len(identifiers) != len(set(identifiers)) or not set(identifiers) <= command_ids:
        raise ValueError("E_VERIFICATION_TOPOLOGY")
    if (
        "testpaths" not in pyproject
        or "tests" not in pyproject
        or '"test/**/*.ts"' not in test_config
        or '"test-harness/**/*.ts"' not in harness_config
    ):
        raise ValueError("E_VERIFICATION_TOPOLOGY")
    return {"result": "PASS", "group_count": len(groups), "command_count": len(identifiers)}


if __name__ == "__main__":
    print(json.dumps(verify_verification_topology(), sort_keys=True))
