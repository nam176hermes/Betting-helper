import ast
import json
from pathlib import Path, PurePosixPath

import pytest

from moj_discovery.vendor import pack_root

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)
ERROR = "E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04"
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


def test_all_registered_harness_entrypoints_compile_and_emit_contract_not_implemented() -> None:
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
        assert ERROR in source_text
        if source.suffix == ".py":
            ast.parse(source_text)
            assert "def main" in source_text
        else:
            assert "export const contractNotImplemented" in source_text

    with pytest.raises(AssertionError):
        _safe_source("/absolute/path")
    with pytest.raises(AssertionError):
        _safe_source("../escape")

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
