"""Resolve the closed task-manifest reference surface without executing it."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from moj_discovery.vendor import pack_root as runtime_pack_root
from moj_discovery.vendor import plan_root

PACK_ROOT = runtime_pack_root(RUNTIME_ROOT)
SEALED_PACK_ROOT = Path(
    "/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6"
)


def _path(value: str, runtime_root: Path, pack_root: Path, *, sealed: bool = False) -> Path:
    if sealed:
        evidence = Path("/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6")
        authoring = Path("/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring")
        plan_input = Path("/home/thenam176/betting-helper/plan-input")
        path = Path(value)
        if path.is_absolute() and path.is_relative_to(evidence):
            return pack_root / "evidence" / path.relative_to(evidence)
        if path.is_absolute() and path.is_relative_to(authoring):
            return pack_root / "authoring-source/workspace" / path.relative_to(authoring)
        if path.is_absolute() and path.is_relative_to(plan_input):
            return pack_root / "authoring-source/plan-input" / path.relative_to(plan_input)
        if value.startswith(("authoring-tools/", "authoring-tests/")):
            return pack_root / "authoring-source" / value
        if value.startswith("bootstrap/"):
            return pack_root / "authoring-source" / value
        if value.startswith("pack/"):
            return pack_root / value.removeprefix("pack/")
    if value.startswith("runtime/"):
        return runtime_root / value.removeprefix("runtime/")
    if value.startswith("pack/"):
        return pack_root / value.removeprefix("pack/")
    if value.startswith(("src/", "tests/", "tools/", "extension/")):
        return runtime_root / value
    if value.startswith("bootstrap/"):
        return plan_root(runtime_root) / value
    return runtime_root.parent / value


def _pointer(document: object, reference: str) -> object:
    if not reference.startswith("#/"):
        raise ValueError("E_EXECUTABLE_REFERENCE")
    current = document
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdecimal() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError("E_EXECUTABLE_REFERENCE")
    return current


def _test_case_methods(tree: ast.Module) -> set[str]:
    methods: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {
            base.id if isinstance(base, ast.Name) else base.attr
            for base in node.bases
            if isinstance(base, (ast.Name, ast.Attribute))
        }
        if "TestCase" in bases:
            methods.update(
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return methods


def _symbol(path: Path, symbol: str) -> bool:
    if path.suffix not in {".py", ".ts"}:
        return True
    try:
        tree = ast.parse(path.read_text()) if path.suffix == ".py" else None
    except (OSError, SyntaxError) as error:
        raise ValueError("E_EXECUTABLE_REFERENCE") from error
    if tree is None:
        return symbol in path.read_text()
    callables = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if symbol in callables or symbol in _test_case_methods(tree):
        return True
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if (
            any(isinstance(target, ast.Name) and target.id == symbol for target in targets)
            and isinstance(value, ast.Name)
            and value.id in callables
        ):
            return True
    return False


def verify_executable_references(
    runtime_root: Path = RUNTIME_ROOT, pack_root: Path = PACK_ROOT, *, sealed: bool = False
) -> dict[str, object]:
    if sealed and pack_root == PACK_ROOT:
        pack_root = SEALED_PACK_ROOT
    manifest_path = pack_root / "docs/tasks/task-manifest.v6.3.6.json"
    registry_path = runtime_root / "task-command-registry.json"
    ownership_path = pack_root / "docs/registries/artifact-ownership.v1.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        registry = json.loads(registry_path.read_text())
        ownership = json.loads(ownership_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_EXECUTABLE_REFERENCE") from error
    tasks = manifest.get("tasks") if isinstance(manifest, dict) else None
    commands = registry.get("commands") if isinstance(registry, dict) else None
    if not isinstance(tasks, list) or not isinstance(commands, list):
        raise ValueError("E_EXECUTABLE_REFERENCE")
    ownership_entries = ownership.get("entries") if isinstance(ownership, dict) else None
    if not isinstance(ownership_entries, list):
        raise ValueError("E_EXECUTABLE_REFERENCE")
    owned = {
        entry.get("path"): entry
        for entry in ownership_entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    task_order = {
        task["task_id"]: index
        for index, task in enumerate(tasks)
        if isinstance(task, dict) and isinstance(task.get("task_id"), str)
    }
    cutoff = task_order["V636-P06-T01"]

    def future_owner(file_name: str) -> bool:
        entry = owned.get(file_name)
        if not isinstance(entry, dict):
            return False
        candidates = [entry.get("creation_owner"), entry.get("qualification_owner")]
        modifiers = entry.get("modifying_tasks", [])
        if isinstance(modifiers, list):
            candidates.extend(modifiers)
        return any(
            isinstance(task_id, str) and task_order.get(task_id, -1) > cutoff
            for task_id in candidates
        )

    command_ids = {command.get("command_id") for command in commands if isinstance(command, dict)}
    for command_file in pack_root.rglob("*command*registry*.json"):
        try:
            nested = json.loads(command_file.read_text()).get("commands", [])
        except (OSError, json.JSONDecodeError):
            continue
        command_ids |= {
            command.get("command_id") for command in nested if isinstance(command, dict)
        }
    unresolved: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("E_EXECUTABLE_REFERENCE")
        for file_name in task.get("exact_files", []):
            if not isinstance(file_name, str) or (
                not _path(file_name, runtime_root, pack_root, sealed=sealed).is_file()
                and not future_owner(file_name)
            ):
                unresolved.append(str(file_name))
        for reference in task.get("exact_schema_refs", []):
            if not isinstance(reference, str) or "#" not in reference:
                unresolved.append(str(reference))
                continue
            filename, pointer = reference.split("#", 1)
            try:
                _pointer(
                    json.loads(_path(filename, runtime_root, pack_root, sealed=sealed).read_text()),
                    f"#{pointer}",
                )
            except (OSError, ValueError, json.JSONDecodeError):
                unresolved.append(reference)
        for symbol_ref in task.get("exact_symbols", []):
            delimiter = "::" if isinstance(symbol_ref, str) and "::" in symbol_ref else "#"
            if not isinstance(symbol_ref, str) or delimiter not in symbol_ref:
                unresolved.append(str(symbol_ref))
                continue
            filename, symbol = symbol_ref.split(delimiter, 1)
            path = _path(filename, runtime_root, pack_root, sealed=sealed)
            if (not path.is_file() or not _symbol(path, symbol)) and not future_owner(filename):
                unresolved.append(symbol_ref)
        for command_id in task.get("exact_command_ids", []):
            if command_id not in command_ids:
                unresolved.append(str(command_id))
    for path in runtime_root.rglob("*.py"):
        if (
            path.relative_to(runtime_root).as_posix() == "tools/verify_executable_references.py"
            or "tests" in path.parts
            or ".venv" in path.parts
        ):
            continue
        relative = path.relative_to(runtime_root).as_posix()
        if "E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T02" in path.read_text() and not future_owner(
            f"runtime/{relative}"
        ):
            unresolved.append(relative)
    if unresolved:
        raise ValueError("E_EXECUTABLE_REFERENCE:" + ",".join(sorted(set(unresolved))))
    return {"result": "PASS", "task_count": len(tasks), "command_count": len(command_ids)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("candidate", "sealed-review"), default="candidate")
    args = parser.parse_args()
    print(
        json.dumps(
            verify_executable_references(sealed=args.mode == "sealed-review"), sort_keys=True
        )
    )
