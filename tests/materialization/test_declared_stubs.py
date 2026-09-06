import json
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import cast

import pytest

from tools.materialize_declared_stubs import STUB_ERROR, _task_outputs, materialize_declared_stubs

ROOT = Path(__file__).parents[2]


def test_delivered_runtime_uses_vendored_task_manifest(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    manifest = runtime / "vendor/hybrid-discovery-v6.3.6/docs/tasks/task-manifest.v6.3.6.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(
        (ROOT / "vendor/hybrid-discovery-v6.3.6/docs/tasks/task-manifest.v6.3.6.json").read_bytes()
    )
    (tmp_path / "plan-input").mkdir()
    assert _task_outputs(runtime) == _task_outputs(ROOT)


def test_every_declared_path_exists_or_is_classified_external() -> None:
    assert materialize_declared_stubs(ROOT, check=True) == []
    registry = json.loads((ROOT / ".contract-stub-registry.json").read_text())
    for entry in registry["entries"]:
        if entry["classification"] == "internal":
            path = ROOT / Path(*PurePosixPath(entry["path"]).parts[1:])
            assert path.is_file() and not path.is_symlink()
            if path.suffix == ".py":
                compile(path.read_text(), str(path), "exec")
        else:
            assert Path(entry["path"]).is_absolute()


def test_declared_stubs_reject_missing_or_linked_files_and_raise_exact_error(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    manifest = tmp_path / "plan-input/docs/tasks/task-manifest.v6.3.6.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "V636-P01-T02",
                        "outputs": [
                            "runtime/src/future.py",
                            "runtime/extension/src/future.ts",
                            "/evidence/V636-P01-T02.json",
                        ],
                    }
                ]
            }
        )
    )
    runtime.mkdir()
    assert materialize_declared_stubs(runtime) == []
    python_stub = runtime / "src/future.py"
    namespace: dict[str, object] = {}
    exec(python_stub.read_text(), namespace)  # noqa: S102 - execute the generated stub
    with pytest.raises(RuntimeError, match=STUB_ERROR):
        cast(Callable[[], None], namespace["contract_not_implemented"])()
    assert STUB_ERROR in (runtime / "extension/src/future.ts").read_text()

    python_stub.unlink()
    assert materialize_declared_stubs(runtime, check=True) == [
        "E_CONTRACT_STUBS:MISSING:runtime/src/future.py"
    ]
    materialize_declared_stubs(runtime)
    python_stub.unlink()
    python_stub.symlink_to("../extension/src/future.ts")
    assert materialize_declared_stubs(runtime, check=True) == [
        "E_CONTRACT_STUBS:FILE:runtime/src/future.py"
    ]
