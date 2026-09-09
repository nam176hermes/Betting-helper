from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from moj_discovery.governance import validate_task_dependencies
from moj_discovery.task_contracts import validate_task_manifest_semantics
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)


def _inputs() -> tuple[dict[str, object], list[dict[str, object]], set[str]]:
    manifest = json.loads((PLAN / "docs/tasks/task-manifest.v6.3.6.json").read_text())
    commands = [
        command
        for name in (
            "task-command-registry.v1.json",
            "review-command-registry.v1.json",
            "cybersecurity-command-registry.v1.json",
            "baseline-replay-command-registry.v1.json",
        )
        for command in json.loads((PLAN / "docs/registries" / name).read_text())["commands"]
    ]
    owned = {
        entry["path"]
        for entry in json.loads((PLAN / "docs/registries/artifact-ownership.v1.json").read_text())[
            "entries"
        ]
    }
    return manifest, commands, owned


def test_review_counterexamples_are_rejected() -> None:
    manifest, commands, owned = _inputs()
    assert validate_task_manifest_semantics(manifest, commands, owned) == {
        "result": "PASS",
        "task_count": 62,
        "command_count": 219,
    }
    cases = [
        (
            lambda value: value.update(authorized_production_phases="PAPER"),
            "E_PRODUCTION_AUTHORITY",
        ),
        (
            lambda value: value["tasks"][1].update(dependencies=["UNKNOWN"]),
            "E_DEPENDENCY_UNKNOWN_OR_FUTURE",
        ),
        (
            lambda value: value["tasks"][1].update(dependencies=["V636-P02-T03"]),
            "E_DEPENDENCY_UNKNOWN_OR_FUTURE",
        ),
        (lambda value: value["tasks"][0].update(rollback=[]), "E_EMPTY_ROLLBACK"),
        (lambda value: value.update(declared_task_count=0), "E_TASK_COUNT"),
    ]
    for mutate, error in cases:
        changed = copy.deepcopy(manifest)
        mutate(changed)
        with pytest.raises(ValueError, match=error):
            validate_task_manifest_semantics(changed, commands, owned)
    changed_commands = copy.deepcopy(commands)
    changed_commands[0]["argv"] = ["TODO"]
    with pytest.raises(ValueError, match="E_COMMAND_PLACEHOLDER"):
        validate_task_manifest_semantics(manifest, changed_commands, owned)


def test_materialized_successor_graph_is_closed() -> None:
    validate_task_dependencies()
