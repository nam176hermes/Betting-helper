"""Clock batching retains actual byte authentication at each operation boundary."""
from __future__ import annotations

import copy
import hashlib
import os
from collections.abc import Callable
from contextvars import copy_context
from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired
from typing import Any

import pytest

from tools import run_clock_vector_qualification as runner
from tools import verify_repair_evidence as gate

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"


@pytest.fixture(scope="module")
def campaign(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], list[str]]:
    original = gate._typescript_compile_binding
    calls: list[str] = []

    def observed(current: dict[str, Any]) -> str:
        digest = original(current)
        calls.append(digest)
        return digest

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(gate, "_typescript_compile_binding", observed)
        report = runner.run_clock_vector_qualification(
            PACK, ROOT, evidence_dir=tmp_path_factory.mktemp("clock-batch-campaign"),
        )
    return report, calls


def test_campaign_uses_one_authenticated_clock_batch(
    campaign: tuple[dict[str, Any], list[str]],
) -> None:
    report, calls = campaign
    assert report["result"] == "PASS"
    assert report["covered_vector_count"] == 65
    assert report["mutation_executions"] == 13
    assert report["mutation_survivors"] == 0
    assert report["required_id_set_complete"] is True
    assert report["mutation_id_set_complete"] is True
    assert len(calls) == 2
    assert calls[0] == calls[1]


def test_summary_recursion_and_standalone_calls_each_authenticate_twice(
    campaign: tuple[dict[str, Any], list[str]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, _ = campaign
    original = gate._typescript_compile_binding
    calls = []

    def observed(current: dict[str, Any]) -> str:
        digest = original(current)
        calls.append(digest)
        return digest

    monkeypatch.setattr(gate, "_typescript_compile_binding", observed)
    assert runner.summarize(report["required_vector_ids"], report["records"])["result"] == "PASS"
    assert len(calls) == 2
    for expected_calls in (4, 6):
        assert runner.verify_record(report["mutation_records"][0])
        assert len(calls) == expected_calls


def test_supplied_binding_cannot_authorize_stale_record(
    campaign: tuple[dict[str, Any], list[str]],
) -> None:
    row = copy.deepcopy(campaign[0]["records"][0])
    row["evidence_binding"]["revision"] = "TEST_ONLY-stale"
    assert not runner.verify_record(row, _current_binding=row["evidence_binding"])


@pytest.fixture
def identity_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path]:
    """TEST_ONLY identity fixture: real byte hashes, no dummy compiler/Node execution."""
    files = {
        "node": tmp_path / "node",
        "compiler": tmp_path / "extension/node_modules/typescript/lib/_tsc.js",
        "canonicalize": tmp_path / "extension/node_modules/canonicalize/lib/canonicalize.js",
        "config": tmp_path / "extension/tsconfig.json",
        "source": tmp_path / "source.py",
    }
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}\n")
    (tmp_path / "extension/tsconfig.test.json").write_text('{"extends":"./tsconfig.json"}')
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "_resolved_node_executable", lambda: files["node"])

    def captured() -> dict[str, Any]:
        return {"revision": "TEST_ONLY", "source_sha256": {
            key: hashlib.sha256(files[key].read_bytes()).hexdigest()
            for key in ("source", "config", "node")
        }}

    monkeypatch.setattr(gate, "capture_binding", captured)
    return files


def change_same_stat(path: Path) -> None:
    before = path.stat()
    content = path.read_bytes()
    path.write_bytes(content.replace(b"{}\n", b"{ }", 1))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("target", ["compiler", "config", "node", "canonicalize"])
def test_between_batches_same_stat_bytes_refresh_compile_key(
    identity_files: dict[str, Path], target: str,
) -> None:
    with gate._clock_validation_scope():
        before = gate._clock_compile_binding(gate._clock_current_binding())
    change_same_stat(identity_files[target])
    with gate._clock_validation_scope():
        after = gate._clock_compile_binding(gate._clock_current_binding())
    assert before != after


@pytest.mark.parametrize("target", ["compiler", "config", "node", "canonicalize", "source"])
def test_persistent_midbatch_same_stat_drift_rejects_and_resets(
    identity_files: dict[str, Path], target: str,
) -> None:
    with (
        pytest.raises(ValueError, match="E_REPAIR_VALIDATION_INPUT_DRIFT"),
        gate._clock_validation_scope(),
    ):
        gate._clock_compile_binding(gate._clock_current_binding())
        change_same_stat(identity_files[target])
    assert gate._CLOCK_VALIDATION.get() is None
    with gate._clock_validation_scope():
        assert gate._clock_compile_binding(gate._clock_current_binding())


def test_missing_toolchain_at_exit_rejects(identity_files: dict[str, Path]) -> None:
    with (
        pytest.raises(ValueError, match="E_REPAIR_VALIDATION_INPUT_DRIFT"),
        gate._clock_validation_scope(),
    ):
        gate._clock_compile_binding(gate._clock_current_binding())
        identity_files["canonicalize"].unlink()
    assert gate._CLOCK_VALIDATION.get() is None


def test_malformed_config_at_exit_is_a_boundary_failure(
    identity_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = gate.capture_binding

    def captured() -> dict[str, Any]:
        # Exercise the actual config parser used by capture_binding, not a fake exception.
        gate._typescript_config_closure(gate.ROOT / "extension/tsconfig.test.json")
        return original()

    monkeypatch.setattr(gate, "capture_binding", captured)
    with (
        pytest.raises(ValueError, match="E_REPAIR_VALIDATION_INPUT_DRIFT"),
        gate._clock_validation_scope(),
    ):
        gate._clock_compile_binding(gate._clock_current_binding())
        identity_files["config"].write_text("[]")
    assert gate._CLOCK_VALIDATION.get() is None


def test_scope_snapshot_alias_exception_and_inherited_context_are_safe(
    identity_files: dict[str, Path],
) -> None:
    with gate._clock_validation_scope():
        current = gate._clock_current_binding()
        saved = copy.deepcopy(current)
        current["source_sha256"]["source"] = "untrusted"
        assert gate._clock_current_binding() == saved
        with pytest.raises(ValueError, match="E_REPAIR_STALE_BINDING"):
            gate._clock_compile_binding(current)
        inherited = copy_context()
    with pytest.raises(ValueError, match="E_REPAIR_VALIDATION_INPUT_DRIFT"):
        inherited.run(gate._clock_current_binding)
    with (
        pytest.raises(RuntimeError, match="TEST_ONLY-body-failed"),
        gate._clock_validation_scope(),
    ):
        gate._clock_current_binding()
        raise RuntimeError("TEST_ONLY-body-failed")
    assert gate._CLOCK_VALIDATION.get() is None


@pytest.mark.parametrize("bound", [False, True])
def test_unsupported_aggregate_does_not_require_clock_toolchain(
    monkeypatch: pytest.MonkeyPatch, bound: bool,
) -> None:
    def forbidden(_current: dict[str, Any]) -> str:
        raise AssertionError("clock prerequisite was acquired for unsupported evidence")

    monkeypatch.setattr(gate, "_typescript_compile_binding", forbidden)
    row: dict[str, Any] = {
        "case_id": "TEST_ONLY-unsupported", "status": "NOT_IMPLEMENTED",
        "reason": "missing adapter", "implementation_marker": "TEST_ONLY",
        "executed": False, "launch_attempted": False,
    }
    if bound:
        row["evidence_binding"] = gate.capture_binding()
    result = gate.aggregate_repair_evidence([row["case_id"]], [row])
    assert result["result"] == ("FAIL" if bound else "HOLD")
    assert gate.aggregate_repair_evidence([], [])["result"] == "FAIL"


def test_binding_unavailable_remains_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> dict[str, Any]:
        raise OSError("TEST_ONLY-unavailable")

    monkeypatch.setattr(gate, "capture_binding", unavailable)
    result = gate.aggregate_repair_evidence(["x"], [{
        "case_id": "x", "status": "PASS", "executed": True,
        "launch_attempted": True, "evidence_binding": {},
    }])
    assert result["result"] == "FAIL"
    assert result["errors"][0]["error"].startswith("E_REPAIR_BINDING_UNAVAILABLE:")


def install_owned_compiler_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Callable[[], None]:
    """Read-hook identity test only; real compiler and validators remain unmodified."""
    compiler = ROOT / "extension/node_modules/typescript/lib/_tsc.js"
    owned = tmp_path / "TEST_ONLY-compiler-bytes.js"
    owned.write_bytes(compiler.read_bytes())
    original_sha = gate._sha
    original_binding = gate._typescript_compile_binding
    calls = 0

    def sha(path: Path) -> str:
        return original_sha(owned if path == compiler else path)

    def observed(current: dict[str, Any]) -> str:
        nonlocal calls
        digest = original_binding(current)
        calls += 1
        if calls == 1:
            content = owned.read_bytes()
            before = owned.stat()
            owned.write_bytes(b"!" + content[1:])
            os.utime(owned, ns=(before.st_atime_ns, before.st_mtime_ns))
        return digest

    monkeypatch.setattr(gate, "_sha", sha)
    monkeypatch.setattr(gate, "_typescript_compile_binding", observed)

    def assert_exit_checked() -> None:
        assert calls == 2
        assert gate._CLOCK_VALIDATION.get() is None

    return assert_exit_checked


@pytest.mark.parametrize("boundary", ["record", "summary", "aggregate"])
def test_actual_validation_cannot_return_success_after_identity_drift(
    campaign: tuple[dict[str, Any], list[str]], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, boundary: str,
) -> None:
    row = campaign[0]["records"][0]
    checked = install_owned_compiler_drift(tmp_path, monkeypatch)
    if boundary == "record":
        assert runner.verify_record(row) is False
    elif boundary == "summary":
        result = runner.summarize([row["case_id"]], [row])
        assert result["result"] == "FAIL"
        assert result["covered_vector_count"] == result["executed_vector_count"] == 0
    else:
        result = gate.aggregate_repair_evidence([row["case_id"]], [row])
        assert result["result"] == "FAIL"
        assert result["errors"] == [{
            "case_id": "", "error": "E_REPAIR_VALIDATION_INPUT_DRIFT",
        }]
        assert gate._RETAINED_ARTIFACTS.get() is None
    checked()


def test_campaign_drift_cannot_publish_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked = install_owned_compiler_drift(tmp_path, monkeypatch)
    evidence = tmp_path / "evidence"
    with pytest.raises(ValueError, match="E_REPAIR_VALIDATION_INPUT_DRIFT"):
        runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=evidence)
    assert not (evidence / "qualification.json").exists()
    assert len(list(evidence.glob("*/actual.json"))) == 65
    checked()


def test_changed_compiler_identity_recompiles_identical_graph_between_calls(
    campaign: tuple[dict[str, Any], list[str]], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # TEST_ONLY read transport: changed owned identity bytes, real unchanged compiler.
    # This proves fresh cache lookup, not execution of the modified compiler copy.
    compiler = ROOT / "extension/node_modules/typescript/lib/_tsc.js"
    owned = tmp_path / "TEST_ONLY-compiler.js"
    owned.write_bytes(compiler.read_bytes())
    original_sha = gate._sha

    def sha(path: Path) -> str:
        return original_sha(owned if path == compiler else path)

    monkeypatch.setattr(gate, "_sha", sha)
    row = campaign[0]["records"][0]
    assert runner.verify_record(row)
    misses = gate._compiled_typescript_module_hashes.cache_info().misses
    content = owned.read_bytes()
    before = owned.stat()
    owned.write_bytes(b"!" + content[1:])
    os.utime(owned, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert runner.verify_record(row)
    assert gate._compiled_typescript_module_hashes.cache_info().misses == misses + 1


def test_nested_producer_cannot_publish_before_owner_exit(tmp_path: Path) -> None:
    with (
        gate._clock_validation_scope(),
        pytest.raises(ValueError, match="E_CLOCK_NESTED_PRODUCER"),
    ):
        runner.run_clock_vector_qualification(PACK, ROOT, evidence_dir=tmp_path / "evidence")
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize("boundary", ["record", "summary", "aggregate"])
@pytest.mark.parametrize("fault", [CalledProcessError(1, "TEST_ONLY"), TimeoutExpired(
    "TEST_ONLY", 1,
)])
def test_exit_subprocess_failure_keeps_public_fail_closed_envelope(
    campaign: tuple[dict[str, Any], list[str]], monkeypatch: pytest.MonkeyPatch,
    boundary: str, fault: Exception,
) -> None:
    original = gate.capture_binding
    calls = 0

    def captured() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise fault
        return original()

    monkeypatch.setattr(gate, "capture_binding", captured)
    row = campaign[0]["records"][0]
    if boundary == "record":
        assert runner.verify_record(row) is False
    elif boundary == "summary":
        assert runner.summarize([row["case_id"]], [row])["result"] == "FAIL"
    else:
        result = gate.aggregate_repair_evidence([row["case_id"]], [row])
        assert result["result"] == "FAIL"
        assert result["errors"][-1]["error"] == "E_REPAIR_VALIDATION_INPUT_DRIFT"
    assert calls == 2
    assert gate._CLOCK_VALIDATION.get() is None


@pytest.fixture
def retained_browser_graph(
    identity_files: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], Any, Path]:
    """TEST_ONLY compiler boundary; retained bytes, hashes and path checks are real."""
    import json

    from tools.retained_artifact_io import RetainedArtifactIO

    case = tmp_path / "case"
    extension = case / "test-extension"
    names = {
        "indexeddb-crash-child.js", "repair-probe.js", "src/canonical.js",
        "src/canonicalize.js", "src/errors.js", "src/spool.js",
        "src/storage/durable_idb.js", "src/offline/validators.js",
    }
    contents = {str(extension / name): (
        b'import value from "./canonicalize.js";' if name == "src/canonical.js"
        else name.encode()
    ) for name in names}
    modules = {name: hashlib.sha256(contents[str(extension / name)]).hexdigest()
               for name in names}
    binding = {"before": modules, "after": modules}
    descriptor = case / "typescript-execution-binding.json"
    contents[str(descriptor)] = json.dumps(binding).encode()
    # A similarly named sibling must not be mistaken for an in-scope module.
    contents[str(case / "test-extension-other/extra.js")] = b"TEST_ONLY"
    retained = tmp_path / "retained-browser"
    retained.mkdir()
    rows = []
    for index, (locator, raw) in enumerate(contents.items()):
        relative = str(index)
        (retained / relative).write_bytes(raw)
        rows.append({"recorded_locator": locator, "recorded_boundary": str(tmp_path),
                     "copied_relative_path": relative, "size_bytes": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()})
    artifacts = RetainedArtifactIO.from_manifest({
        "schema_version": "retained-artifact-manifest/v1",
        "recorded_boundaries": [str(tmp_path)], "files": rows,
    }, retained)
    row = {"case_directory": str(case), "identity": {"module_sha256": modules["src/spool.js"]},
           "module_hashes": modules, "typescript_execution_binding": binding,
           "typescript_execution_binding_artifact": {"path": str(descriptor),
               "sha256": hashlib.sha256(contents[str(descriptor)]).hexdigest()}}
    monkeypatch.setattr(gate, "_compiled_browser_module_hashes", lambda _binding: modules.copy())
    return row, artifacts, extension


def test_browser_graph_batch_authenticates_toolchain_at_both_boundaries(
    retained_browser_graph: tuple[dict[str, Any], Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, artifacts, _ = retained_browser_graph
    original = gate._typescript_compile_binding
    calls = []

    def observed(current: dict[str, Any]) -> str:
        value = original(current)
        calls.append(value)
        return value

    monkeypatch.setattr(gate, "_typescript_compile_binding", observed)
    token = gate._RETAINED_ARTIFACTS.set(artifacts)
    try:
        with gate._clock_validation_scope():
            current = gate._clock_current_binding()
            for _ in range(3):
                gate._verify_retained_typescript_graph(row, current, "E_TEST_GRAPH")
        assert len(calls) == 2
        assert calls[0] == calls[1]
        gate._verify_retained_typescript_graph(row, gate.capture_binding(), "E_TEST_GRAPH")
        assert len(calls) == 4  # A standalone operation must authenticate anew.
    finally:
        gate._RETAINED_ARTIFACTS.reset(token)


def test_browser_graph_batch_rejects_same_stat_compiler_drift(
    retained_browser_graph: tuple[dict[str, Any], Any, Path],
    identity_files: dict[str, Path],
) -> None:
    row, artifacts, _ = retained_browser_graph
    token = gate._RETAINED_ARTIFACTS.set(artifacts)
    try:
        with (
            pytest.raises(ValueError, match="E_REPAIR_VALIDATION_INPUT_DRIFT"),
            gate._clock_validation_scope(),
        ):
            gate._verify_retained_typescript_graph(
                row, gate._clock_current_binding(), "E_TEST_GRAPH",
            )
            change_same_stat(identity_files["compiler"])
        assert gate._CLOCK_VALIDATION.get() is None
    finally:
        gate._RETAINED_ARTIFACTS.reset(token)


def test_browser_graph_batch_rechecks_retained_bytes_on_every_call(
    retained_browser_graph: tuple[dict[str, Any], Any, Path],
) -> None:
    row, artifacts, extension = retained_browser_graph
    token = gate._RETAINED_ARTIFACTS.set(artifacts)
    try:
        with gate._clock_validation_scope():
            current = gate._clock_current_binding()
            gate._verify_retained_typescript_graph(row, current, "E_TEST_GRAPH")
            path = artifacts.physical_path(str(extension / "src/spool.js"),
                recorded_boundary=artifacts.recorded_boundary(str(extension / "src/spool.js")))
            before = path.stat()
            raw = path.read_bytes()
            path.write_bytes(b"X" + raw[1:])
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            with pytest.raises(ValueError, match="E_RETAINED_ARTIFACT"):
                gate._verify_retained_typescript_graph(row, current, "E_TEST_GRAPH")
    finally:
        gate._RETAINED_ARTIFACTS.reset(token)
