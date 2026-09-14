"""Create the declaration gate receipt from declared data only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from validate_artifact_ownership import validate_artifact_ownership
from validate_task_manifest import validate_task_manifest_semantics


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commands(commands_path: Path) -> list[dict[str, object]]:
    paths = [
        commands_path,
        commands_path.with_name("review-command-registry.v1.json"),
        commands_path.with_name("cybersecurity-command-registry.v1.json"),
        commands_path.with_name("baseline-replay-command-registry.v1.json"),
    ]
    return [command for path in paths for command in json.loads(path.read_text(encoding="utf-8"))["commands"]]


def validate_declaration(
    tasks_path: Path,
    ownership_path: Path,
    commands_path: Path,
    *,
    authoring_root: Path | None = None,
) -> dict[str, object]:
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
    commands = _commands(commands_path)
    schema = json.loads((ownership_path.parents[1] / "schemas/artifact-ownership.schema.json").read_text(encoding="utf-8"))
    validate_task_manifest_semantics(tasks, commands, {entry["path"] for entry in ownership["entries"]})
    validate_artifact_ownership(
        ownership,
        tasks,
        authoring_root=Path.cwd() if authoring_root is None else authoring_root,
        schema=schema,
    )
    command_ids = {command["command_id"] for command in commands}
    if len(command_ids) != len(commands):
        raise ValueError("E_DECLARATION_COMMAND_DUPLICATE")
    return {
        "schema_version": "declaration-complete/v1",
        "gate": "DECLARATION_COMPLETE",
        "result": "PASS",
        "task_count": len(tasks["tasks"]),
        "artifact_count": len(ownership["entries"]),
        "command_count": len(command_ids),
        "tasks_sha256": _sha256(tasks_path),
        "ownership_sha256": _sha256(ownership_path),
        "commands_sha256": _sha256(commands_path),
        "authorized_production_phases": "NONE",
    }


def issue_declaration_complete_receipt(
    tasks_path: Path,
    ownership_path: Path,
    commands_path: Path,
    output_path: Path,
    *,
    authoring_root: Path | None = None,
) -> dict[str, object]:
    receipt = validate_declaration(tasks_path, ownership_path, commands_path, authoring_root=authoring_root)
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["content_hash"] = hashlib.sha256(b"HD636/DECLARATION/v1\0" + payload).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--ownership", required=True, type=Path)
    parser.add_argument("--commands", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(issue_declaration_complete_receipt(args.tasks, args.ownership, args.commands, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
