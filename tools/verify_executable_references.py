"""Resolve the closed task-manifest reference surface without executing it."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from moj_discovery.vendor import pack_root as runtime_pack_root
from moj_discovery.vendor import plan_root
from tools.full_verifier_config import FullVerifierConfig
from tools.retained_artifact_io import RetainedArtifactIO

PACK_ROOT = runtime_pack_root(RUNTIME_ROOT)
SEALED_PACK_ROOT = Path("/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6")


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


def _symbol(path: Path, symbol: str, *, recorded_suffix: str | None = None) -> bool:
    suffix = path.suffix if recorded_suffix is None else recorded_suffix
    if suffix not in {".py", ".ts"}:
        return True
    try:
        tree = ast.parse(path.read_text()) if suffix == ".py" else None
    except (OSError, SyntaxError) as error:
        raise ValueError("E_EXECUTABLE_REFERENCE") from error
    if tree is None:
        from tools.verify_repair_evidence import _resolved_node_executable

        # Parse transported source as its recorded language; never execute it.
        script = """
const ts = require(process.argv[1]);
const text = require('fs').readFileSync(0, 'utf8');
const source = ts.createSourceFile('reference.ts', text, ts.ScriptTarget.Latest, true);
if (source.parseDiagnostics.length) process.exit(2);
const names = source.statements.flatMap(n =>
  ts.isVariableStatement(n) ? n.declarationList.declarations
    .filter(d => ts.isIdentifier(d.name)).map(d => d.name.text) :
  (ts.isFunctionDeclaration(n) || ts.isClassDeclaration(n) || ts.isInterfaceDeclaration(n) ||
   ts.isTypeAliasDeclaration(n) || ts.isEnumDeclaration(n)) && n.name ? [n.name.text] : []);
process.stdout.write(JSON.stringify(names));
"""
        checked = subprocess.run(  # noqa: S603 -- fixed compiler parser; source is stdin data.
            [
                str(_resolved_node_executable()),
                "-e",
                script,
                str(RUNTIME_ROOT / "extension/node_modules/typescript"),
            ],
            input=path.read_text(),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if checked.returncode:
            raise ValueError("E_EXECUTABLE_REFERENCE")
        return symbol in json.loads(checked.stdout)
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
    runtime_root: Path = RUNTIME_ROOT,
    pack_root: Path = PACK_ROOT,
    *,
    sealed: bool = False,
    config: FullVerifierConfig | None = None,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, object]:
    if config is None and artifacts is None:
        return _verify_executable_references(runtime_root, pack_root, sealed=sealed)
    try:
        return _verify_executable_references(
            runtime_root,
            pack_root,
            sealed=sealed,
            config=config,
            artifacts=artifacts,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        if isinstance(error, ValueError) and str(error).startswith("E_EXECUTABLE_REFERENCE"):
            raise
        raise ValueError("E_EXECUTABLE_REFERENCE") from error


def _verify_executable_references(
    runtime_root: Path,
    pack_root: Path,
    *,
    sealed: bool,
    config: FullVerifierConfig | None = None,
    artifacts: RetainedArtifactIO | None = None,
) -> dict[str, object]:
    current = config is not None or artifacts is not None
    if current:
        try:
            from tools.assemble_review_pack import (
                CONFIG_COPY,
                UNION_MANIFEST,
                UNION_ROOT,
                _document,
                _exports,
                load_sealed_assembly_context,
            )

            if (
                not sealed
                or not isinstance(config, FullVerifierConfig)
                or not isinstance(artifacts, RetainedArtifactIO)
                or config.schema_version != "full-verifier-controller/v2"
                or runtime_root != config.current_checkout_root
                or runtime_root != runtime_root.resolve(strict=True)
            ):
                raise ValueError("E_EXECUTABLE_REFERENCE")
            checked_config, checked_artifacts = load_sealed_assembly_context(
                pack_root,
                pack_root / CONFIG_COPY,
                str(config.source_path),
                pack_root / UNION_MANIFEST,
                pack_root / UNION_ROOT,
            )
            if checked_config != config or checked_artifacts != artifacts:
                raise ValueError("E_EXECUTABLE_REFERENCE")
            exports = _exports(
                config,
                _document(
                    config.governed_source_pack / "docs/registries/delivery-map.v1.json", artifacts
                ),
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError("E_EXECUTABLE_REFERENCE") from error
    if sealed and pack_root == PACK_ROOT:
        pack_root = SEALED_PACK_ROOT
    manifest_path = pack_root / "docs/tasks/task-manifest.v6.3.6.json"
    registry_path = runtime_root / "task-command-registry.json"
    ownership_path = pack_root / "docs/registries/artifact-ownership.v1.json"
    try:
        if current:
            assert config is not None
            manifest = _document(
                config.governed_source_pack / "docs/tasks/task-manifest.v6.3.6.json", artifacts
            )
            ownership = _document(
                config.governed_source_pack / "docs/registries/artifact-ownership.v1.json",
                artifacts,
            )
        else:
            manifest = json.loads(manifest_path.read_text())
            ownership = json.loads(ownership_path.read_text())
        registry = json.loads(registry_path.read_text())
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
    cutoff = task_order["V636-P09-T01" if current else "V636-P06-T01"]
    required = set()
    if current:
        required = set(
            next(
                task["inputs"] + task["outputs"]
                for task in tasks
                if task["task_id"] == "V636-P09-T01"
            )
        )

    def resolve(file_name: str) -> Path:
        if not current:
            return _path(file_name, runtime_root, pack_root, sealed=sealed)
        assert config is not None and artifacts is not None
        value = Path(file_name)
        if value.as_posix() != file_name or ".." in value.parts or "\\" in file_name:
            raise ValueError("E_EXECUTABLE_REFERENCE")
        if file_name in {"pack/" + UNION_ROOT, "pack/" + UNION_MANIFEST}:
            return pack_root / file_name.removeprefix("pack/")
        if file_name.startswith("runtime/"):
            return runtime_root / file_name.removeprefix("runtime/")
        if file_name.startswith(("src/", "tests/", "tools/", "extension/")):
            return runtime_root / file_name
        if file_name.startswith("pack/"):
            relative = file_name.removeprefix("pack/")
            recorded = exports.get(relative, str(config.governed_source_pack / relative))
        elif value.is_absolute():
            recorded = file_name
        else:
            export_name = "authoring-source/" + file_name.removeprefix("plan-input/")
            if export_name not in exports:
                raise ValueError("E_EXECUTABLE_REFERENCE")
            recorded = exports[export_name]
        artifacts.read_bytes(recorded, recorded_boundary=artifacts.recorded_boundary(recorded))
        return artifacts.physical_path(
            recorded, recorded_boundary=artifacts.recorded_boundary(recorded)
        )

    def future_owner(file_name: str) -> bool:
        entry = owned.get(file_name)
        if not isinstance(entry, dict):
            return False
        if current:
            assert artifacts is not None
            # A required retained input is never waived by a later modifier or
            # qualification owner. Only genuinely not-yet-created outputs defer.
            return (
                file_name not in required
                and file_name not in artifacts.recorded_locators()
                and task_order.get(entry.get("creation_owner"), -1) > cutoff
                and entry.get("classification")
                in {"TASK_OUTPUT", "EVIDENCE_OUTPUT", "GENERATED_OUTPUT"}
            )
        candidates = [entry.get("creation_owner"), entry.get("qualification_owner")]
        modifiers = entry.get("modifying_tasks", [])
        if isinstance(modifiers, list):
            candidates.extend(modifiers)
        return any(
            isinstance(task_id, str) and task_order.get(task_id, -1) > cutoff
            for task_id in candidates
        )

    command_ids = {command.get("command_id") for command in commands if isinstance(command, dict)}
    command_files = (
        [
            resolve(value)
            for value in owned
            if isinstance(value, str)
            and value.startswith("pack/docs/registries/")
            and "command" in Path(value).name
            and "registry" in Path(value).name
            and value.endswith(".json")
            and not future_owner(value)
        ]
        if current
        else pack_root.rglob("*command*registry*.json")
    )
    for command_file in command_files:
        try:
            nested = json.loads(command_file.read_text()).get("commands", [])
        except (OSError, json.JSONDecodeError):
            if current:
                raise ValueError("E_EXECUTABLE_REFERENCE") from None
            continue
        command_ids |= {
            command.get("command_id") for command in nested if isinstance(command, dict)
        }
    unresolved: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("E_EXECUTABLE_REFERENCE")
        for file_name in task.get("exact_files", []):
            try:
                if not isinstance(file_name, str):
                    raise ValueError("E_EXECUTABLE_REFERENCE")
                if future_owner(file_name):
                    continue
                path = resolve(file_name)
                if not path.is_file() and not (
                    current and file_name == "pack/" + UNION_ROOT and path.is_dir()
                ):
                    raise ValueError("E_EXECUTABLE_REFERENCE")
            except (OSError, ValueError):
                unresolved.append(str(file_name))
        for reference in task.get("exact_schema_refs", []):
            if not isinstance(reference, str) or "#" not in reference:
                unresolved.append(str(reference))
                continue
            filename, pointer = reference.split("#", 1)
            try:
                _pointer(
                    json.loads(resolve(filename).read_text()),
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
            try:
                if future_owner(filename):
                    continue
                path = resolve(filename)
                if not path.is_file() or not _symbol(
                    path, symbol, recorded_suffix=Path(filename).suffix if current else None
                ):
                    raise ValueError("E_EXECUTABLE_REFERENCE")
            except (OSError, ValueError):
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("candidate", "sealed-review"), default="candidate")
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--recorded-config")
    parser.add_argument("--retained-manifest", type=Path)
    parser.add_argument("--retained-root", type=Path)
    args = parser.parse_args()
    config, artifacts = None, None
    if any(
        value is not None
        for value in (
            args.pack,
            args.config,
            args.recorded_config,
            args.retained_manifest,
            args.retained_root,
        )
    ):
        if args.mode != "sealed-review" or any(
            value is None
            for value in (
                args.pack,
                args.config,
                args.recorded_config,
                args.retained_manifest,
                args.retained_root,
            )
        ):
            raise ValueError("E_EXECUTABLE_REFERENCE")
        from tools.assemble_review_pack import load_sealed_assembly_context

        try:
            config, artifacts = load_sealed_assembly_context(
                args.pack,
                args.config,
                args.recorded_config,
                args.retained_manifest,
                args.retained_root,
            )
        except ValueError as error:
            raise ValueError("E_EXECUTABLE_REFERENCE") from error
    print(
        json.dumps(
            verify_executable_references(
                config.current_checkout_root if config is not None else RUNTIME_ROOT,
                args.pack if args.pack is not None else PACK_ROOT,
                sealed=args.mode == "sealed-review",
                config=config,
                artifacts=artifacts,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
