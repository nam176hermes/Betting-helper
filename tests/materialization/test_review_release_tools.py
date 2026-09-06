import ast
import json
import re
from pathlib import Path

from moj_discovery.vendor import pack_root, plan_root

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)
PACK = pack_root(ROOT)
REVIEW_PACK_ROOT = Path("/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6")
BAD_ARGV = re.compile(r"(?i)(?:\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|\.\.\.|<[^>]+>|\$\{|\$\(|`)")


def _bound_json(relative: str) -> dict[str, object]:
    plan_path = PLAN / relative
    pack_path = PACK / relative
    assert plan_path.is_file() and not plan_path.is_symlink()
    assert pack_path.is_file() and not pack_path.is_symlink()
    plan_bytes = plan_path.read_bytes()
    assert pack_path.read_bytes() == plan_bytes
    value = json.loads(plan_bytes)
    assert isinstance(value, dict)
    return value


def _p01_t05_outputs(tasks: dict[str, object]) -> set[str]:
    rows = tasks["tasks"]
    assert isinstance(rows, list)
    task = next(
        item for item in rows if isinstance(item, dict) and item["task_id"] == "V636-P01-T05"
    )
    outputs = task["outputs"]
    assert isinstance(outputs, list)
    return {item for item in outputs if isinstance(item, str)}


def _tool_path(relative: str) -> Path:
    path = ROOT / relative.removeprefix("runtime/")
    assert path.is_file() and not path.is_symlink()
    ast.parse(path.read_text())
    return path


def _dependency_closure(tasks: dict[str, object], task_id: str) -> set[str]:
    rows = tasks["tasks"]
    assert isinstance(rows, list)
    by_id = {
        item["task_id"]: item
        for item in rows
        if isinstance(item, dict) and isinstance(item.get("task_id"), str)
    }
    seen: set[str] = set()

    def collect(current: str) -> None:
        for dependency in by_id[current]["dependencies"]:
            assert isinstance(dependency, str) and dependency in by_id
            if dependency not in seen:
                seen.add(dependency)
                collect(dependency)

    collect(task_id)
    return seen


def _assert_exact_argv(command: object) -> None:
    assert isinstance(command, dict)
    argv = command["argv"]
    assert isinstance(argv, list) and argv
    assert all(isinstance(token, str) and token.strip() for token in argv)
    assert not any(BAD_ARGV.search(token) for token in argv)
    assert not any(token.endswith(".md") or "docs/prompts/" in token for token in argv)
    for token in argv:
        if token.startswith("tools/"):
            _tool_path(token)


def test_all_review_release_tools_exist_before_candidate_qualification() -> None:
    tasks = _bound_json("docs/tasks/task-manifest.v6.3.6.json")
    ownership = _bound_json("docs/registries/artifact-ownership.v1.json")
    outputs = _p01_t05_outputs(tasks)
    assert len(outputs) == 11
    for output in outputs:
        _tool_path(output)

    entries = ownership["entries"]
    assert isinstance(entries, list)
    owned = {
        entry["path"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    assert len(owned) == len(entries)
    for output in outputs:
        entry = owned[output]
        assert entry["classification"] == "TASK_OUTPUT"
        assert entry["creation_owner"] == "V636-P01-T02"
        assert entry["materialization_required"] is True
        assert "V636-P01-T05" in entry["modifying_tasks"]
        assert "V636-P01-T05" in entry["consumers"]

    aggregate = owned["runtime/tools/aggregate_reviews.py"]
    assert aggregate["qualification_owner"] == "V636-P05-T08"
    assert "V636-P10-T04" in aggregate["consumers"]
    for consumer in ("V636-P10-T01", "V636-P10-T02", "V636-P10-T04"):
        closure = _dependency_closure(tasks, consumer)
        assert {"V636-P01-T05", "V636-P05-T08"} <= closure

    bindings = {
        "review-a.v1.json": (
            "review-command-registry.v1.json",
            "CODEX_IMPLEMENTATION_READINESS_REVIEW_PROMPT.md",
        ),
        "review-b.v1.json": (
            "cybersecurity-command-registry.v1.json",
            "CODEX_CYBERSECURITY_REVIEW_PROMPT.md",
        ),
    }
    for config_name, (registry_name, prompt_name) in bindings.items():
        config = _bound_json(f"docs/configs/{config_name}")
        registry = _bound_json(f"docs/registries/{registry_name}")
        assert config["command_registry_path"] == str(
            REVIEW_PACK_ROOT / "docs/registries" / registry_name
        )
        assert config["prompt_path"] == str(REVIEW_PACK_ROOT / "docs/prompts" / prompt_name)
        commands = registry["commands"]
        assert isinstance(commands, list)
        command_ids = {
            command["command_id"]
            for command in commands
            if isinstance(command, dict) and isinstance(command.get("command_id"), str)
        }
        mechanical_ids = config["mechanical_command_ids"]
        assert isinstance(mechanical_ids, list)
        assert set(mechanical_ids) <= command_ids
        for command in commands:
            _assert_exact_argv(command)


def test_review_command_placeholder_rejection_is_complete() -> None:
    for token in ("TODO", "TBD", "FIXME", "PLACEHOLDER", "...", "<slot>", "${x}", "$(x)", "`x`"):
        assert BAD_ARGV.search(token)
