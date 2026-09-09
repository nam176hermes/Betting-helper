import ast
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from moj_discovery.vendor import pack_root

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)
ERROR = "E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04"
MISSING_INPUT = {
    "LOOPBACK_ACK": (1, "E_CRASH_SCENARIO_REQUIRED"),
    "SQLITE_TRANSACTION": (1, "E_CRASH_SCENARIO_REQUIRED"),
    "GAP_GENERATION_COHERENCE": (1, "E_GAP_SCENARIO"),
    "WHOLE_RUN_DESTRUCTION": (2, "the following arguments are required"),
}
CHILDREN = {
    (
        "CHROME_INDEXEDDB",
        "node",
        "extension/.test-build/test-harness/indexeddb-crash-child.js",
    ),
    ("LOOPBACK_ACK", "uv-python", "tools/loopback_ack_crash_child.py"),
    ("SQLITE_TRANSACTION", "uv-python", "tools/sqlite_crash_child.py"),
    ("GAP_GENERATION_COHERENCE", "uv-python", "tools/gap_coherence_crash_child.py"),
    ("WHOLE_RUN_DESTRUCTION", "uv-python", "tools/destruction_crash_child.py"),
}
SOURCE_ENTRYPOINTS = {
    "extension/.test-build/test-harness/indexeddb-crash-child.js": (
        "extension/test-harness/indexeddb-crash-child.ts"
    ),
    "tools/loopback_ack_crash_child.py": "tools/loopback_ack_crash_child.py",
    "tools/sqlite_crash_child.py": "tools/sqlite_crash_child.py",
    "tools/gap_coherence_crash_child.py": "tools/gap_coherence_crash_child.py",
    "tools/destruction_crash_child.py": "tools/destruction_crash_child.py",
}


def _safe_source(entrypoint: str) -> Path:
    path = PurePosixPath(entrypoint)
    assert not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)
    assert entrypoint in SOURCE_ENTRYPOINTS
    source = ROOT / SOURCE_ENTRYPOINTS[entrypoint]
    assert source.is_file() and not source.is_symlink()
    return source


def test_registered_harness_entrypoints_compile_and_unowned_entries_stay_blocked(
    tmp_path: Path,
) -> None:
    children = json.loads(
        (PACK / "docs/registries/crash-child-command-registry.v1.json").read_text()
    )["entries"]
    actual_children = {
        (entry["harness"], entry["executor"], entry["entrypoint"]) for entry in children
    }
    assert actual_children == CHILDREN
    assert len(children) == len(CHILDREN)
    crash_entries = json.loads(
        (PACK / "docs/registries/crash-harness-registry.v1.json").read_text()
    )["entries"]
    assert {entry["harness"] for entry in crash_entries} == {entry[0] for entry in CHILDREN}

    for child in children:
        entrypoint = child["entrypoint"]
        source = _safe_source(entrypoint)
        source_text = source.read_text()
        if source.suffix == ".py":
            ast.parse(source_text)
            command = [sys.executable, "-I", "-B", str(source)]
            help_result = subprocess.run(  # noqa: S603 -- exact allowlisted child, help only.
                [*command, "--help"], cwd=tmp_path, capture_output=True, text=True, timeout=15,
            )
            assert help_result.returncode == 0, help_result.stderr
            assert "usage:" in help_result.stdout.lower()
            expected_exit, expected_error = MISSING_INPUT[child["harness"]]
        else:
            # Node is still not a browser owner: never qualify it as IndexedDB evidence.
            command = ["node", str(ROOT / entrypoint)]
            expected_exit, expected_error = 1, ERROR
        rejected = subprocess.run(  # noqa: S603 -- allowlisted child without execution inputs.
            command, cwd=tmp_path, capture_output=True, text=True, timeout=15,
        )
        assert rejected.returncode == expected_exit, rejected.stderr
        assert expected_error in rejected.stderr
        assert list(tmp_path.iterdir()) == []  # No store/checkpoint/ready file without inputs.

    with pytest.raises(AssertionError):
        _safe_source("/absolute/path")
    with pytest.raises(AssertionError):
        _safe_source("../escape")
    with pytest.raises(AssertionError):
        _safe_source("tools/unregistered_child.py")

    ownership_entries = json.loads(
        (PACK / "docs/registries/artifact-ownership.v1.json").read_text()
    )["entries"]
    ownership = {entry["path"]: entry for entry in ownership_entries}
    for source_path in SOURCE_ENTRYPOINTS.values():
        owner = ownership[f"runtime/{source_path}"]
        assert owner["creation_owner"] == "V636-P01-T02"
        assert "V636-P01-T04" in owner["modifying_tasks"]

    assert (
        "evaluate_clock_mapping_vector" in (ROOT / "src/moj_discovery/clock_vectors.py").read_text()
    )
    assert (
        "evaluateClockMappingVector"
        in (ROOT / "extension/src/contracts/clock-vectors.ts").read_text()
    )
    build = json.loads((ROOT / "extension/tsconfig.build.json").read_text())
    assert "test-harness" in build["exclude"]
