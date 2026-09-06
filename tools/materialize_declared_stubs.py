import json
import stat
from pathlib import Path, PurePosixPath

TASK_ID = "V636-P01-T02"
STUB_ERROR = f"E_CONTRACT_NOT_IMPLEMENTED:{TASK_ID}"
REGISTRY_NAME = ".contract-stub-registry.json"


def _task_outputs(root: Path) -> list[dict[str, str]]:
    manifest_path = root.parent / "plan-input/docs/tasks/task-manifest.v6.3.6.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
        manifest_path = root / "vendor/hybrid-discovery-v6.3.6/docs/tasks/task-manifest.v6.3.6.json"
    manifest = json.loads(manifest_path.read_text())
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("E_CONTRACT_STUBS:MANIFEST")
    matches = [task for task in tasks if isinstance(task, dict) and task.get("task_id") == TASK_ID]
    if len(matches) != 1 or not isinstance(matches[0].get("outputs"), list):
        raise ValueError("E_CONTRACT_STUBS:TASK")
    entries: list[dict[str, str]] = []
    for output in matches[0]["outputs"]:
        if not isinstance(output, str):
            raise ValueError("E_CONTRACT_STUBS:OUTPUT")
        path = PurePosixPath(output)
        if output.startswith("runtime/"):
            if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                raise ValueError("E_CONTRACT_STUBS:PATH")
            entries.append({"path": output, "classification": "internal"})
        elif path.is_absolute():
            entries.append({"path": output, "classification": "external"})
        else:
            raise ValueError("E_CONTRACT_STUBS:PATH")
    return entries


def _stub_text(path: Path) -> str:
    if path.suffix == ".py":
        if "tests/" in path.as_posix():
            return "def test_contract_stub() -> None:\n    assert True\n"
        return (
            f"def contract_not_implemented() -> None:\n"
            f"    raise RuntimeError({STUB_ERROR!r})\n\n"
            '\nif __name__ == "__main__":\n'
            "    contract_not_implemented()\n"
        )
    if path.suffix == ".ts":
        return (
            "export const contractNotImplemented = (): never => {\n"
            f"  throw new Error({STUB_ERROR!r});\n"
            "};\n"
        )
    raise ValueError(f"E_CONTRACT_STUBS:UNSUPPORTED:{path.suffix}")


def materialize_declared_stubs(root: Path, *, check: bool = False) -> list[str]:
    root = root.resolve()
    try:
        entries = _task_outputs(root)
    except (OSError, ValueError, json.JSONDecodeError):
        return ["E_CONTRACT_STUBS:MANIFEST"]
    registry = {
        "schema_version": "contract-stub-registry/v1",
        "task_id": TASK_ID,
        "entries": entries,
    }
    registry_path = root / REGISTRY_NAME
    if check:
        try:
            registry_stat = registry_path.lstat()
            if (
                registry_path.is_symlink()
                or not stat.S_ISREG(registry_stat.st_mode)
                or registry_stat.st_nlink != 1
                or json.loads(registry_path.read_text()) != registry
            ):
                return ["E_CONTRACT_STUBS:REGISTRY"]
        except (OSError, json.JSONDecodeError):
            return ["E_CONTRACT_STUBS:REGISTRY"]
    else:
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
    errors: list[str] = []
    for entry in entries:
        if entry["classification"] != "internal" or entry["path"] == f"runtime/{REGISTRY_NAME}":
            continue
        path = root / Path(*PurePosixPath(entry["path"]).parts[1:])
        if path.exists() or path.is_symlink():
            if not path.is_file() or path.is_symlink():
                errors.append(f"E_CONTRACT_STUBS:FILE:{entry['path']}")
            continue
        if check:
            errors.append(f"E_CONTRACT_STUBS:MISSING:{entry['path']}")
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_stub_text(path))
        except (OSError, ValueError):
            errors.append(f"E_CONTRACT_STUBS:WRITE:{entry['path']}")
    return errors


if __name__ == "__main__":
    raise SystemExit(bool(materialize_declared_stubs(Path(__file__).parents[1])))
