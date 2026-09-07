"""Actual native SQLite flush callback, not a COMMIT trace relabel."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from tools import run_native_ingestor_qualification as owner
from tools.run_environment_qualification import localpath


@pytest.mark.parametrize(
    "diagnostic",
    [
        "HOLD_NATIVE_COMMIT_IO_DLL",
        "HOLD_NATIVE_COMMIT_IO_LOADED_DLL",
        "HOLD_NATIVE_COMMIT_IO_VFS",
        "HOLD_NATIVE_COMMIT_IO_SYSCALL",
        "HOLD_NATIVE_COMMIT_IO_INSTALL",
        "HOLD_NATIVE_COMMIT_IO_UNKNOWN",
        "E_UNRELATED_WRITER_FAILURE",
        "",
    ],
)
def test_writer_failure_preserves_diagnostic_before_checkpoint_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diagnostic: str
) -> None:
    import hashlib
    import json
    import subprocess
    import sys

    from tools import native_environment_probe, native_ingestor_probe

    # Real child exit/output tests only the owner boundary, not native store qualification.
    child_source = """
import json, os, sys, time
from pathlib import Path
mode, source, diagnostic = sys.argv[1:]
cfg = json.loads(Path(source).read_text())
case = Path(source).parent
started = {'pid': os.getpid(), 'identity': cfg['identity']}
(case / (mode + '.started.json')).write_text(json.dumps(started))
while not (case / (mode + '.start')).is_file():
    time.sleep(0.01)
if mode == 'setup':
    print(json.dumps({'pid': os.getpid(), 'identity': cfg['identity'], 'state': {}}))
elif diagnostic:
    raise ValueError(diagnostic)
"""
    popen = subprocess.Popen

    def launch(command: list[str], **kwargs: Any) -> Any:
        return popen([sys.executable, "-c", child_source, *command[-2:], diagnostic], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(native_ingestor_probe, "dependency_payload", lambda _: {})
    monkeypatch.setattr(native_environment_probe, "observe", lambda child: {"pid": child.pid})
    config = {
        "workspace": str(tmp_path),
        "root": str(native_ingestor_probe.ROOT),
        "dependency_root": str(tmp_path / "unused-dependency"),
        "delivery": {"discovery_run_id": "boundary-test"},
        "commit_io": "armed",
    }
    expected = (
        diagnostic
        if diagnostic
        in {
            "HOLD_NATIVE_COMMIT_IO_" + suffix
            for suffix in ("DLL", "LOADED_DLL", "VFS", "SYSCALL", "INSTALL")
        }
        else "E_NATIVE_INGESTOR_WRITER_EXIT"
        if diagnostic
        else "E_NATIVE_INGESTOR_CHECKPOINT_MISSING"
    )
    with pytest.raises(ValueError, match=expected) as error:
        native_ingestor_probe.owner(config, tmp_path / "unused-owner-input.json")
    assert "FileNotFoundError" not in str(error.value)
    case = tmp_path / native_ingestor_probe.COMMIT_PHASE
    failure = json.loads((case / "writer-failure.json").read_text())
    assert failure["diagnostic"] == expected
    assert failure["exit"] == (1 if diagnostic else 0)
    assert failure["checkpoint_present"] is False
    for name in ("stdout", "stderr"):
        raw = Path(failure[name]["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == failure[name]["sha256"]
    assert diagnostic in Path(failure["stderr"]["path"]).read_text()
    assert str(case / "writer-failure.json") in str(error.value)


def test_native_commit_io_owner_exists() -> None:
    assert callable(getattr(owner, "run_native_commit_io", None)), (
        "Native COMMIT I/O is unimplemented"
    )


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return owner.run_native_commit_io(tmp_path_factory.mktemp("native-commit-io"))


def test_actual_callback_and_independent_restart(report: dict[str, Any]) -> None:
    assert report["native_sql06"] == "PASS"
    row = report["cases"][0]
    assert row["checkpoint"]["commit_io"]["inside_callback"] is True
    assert row["checkpoint"]["in_transaction"] is True
    assert row["after"]["tables"]["raw_commits"] == []
    assert len(row["final"]["tables"]["raw_commits"]) == 1
    owner.verify_native_ingestor(report)


@pytest.mark.parametrize("mode", ["bypass", "unarmed", "postcommit"])
def test_real_hook_bypass_cannot_qualify_inside_commit(tmp_path: Path, mode: str) -> None:
    import json

    with pytest.raises(ValueError, match="E_NATIVE_INGESTOR_EVIDENCE") as error:
        owner.run_native_commit_io(tmp_path, mode=mode)
    assert str(error.value.__cause__) == "E_NATIVE_COMMIT_IO_CALLBACK"
    candidate = json.loads((tmp_path / "native-ingestor-candidate.json").read_text())
    assert candidate["result"] == "UNVERIFIED"
    assert len(candidate["cases"][0]["after"]["tables"]["raw_commits"]) == 1
    assert candidate["cases"][0]["after"] == candidate["cases"][0]["final"]


def test_bad_negative_reader_cannot_count_as_hook_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    with pytest.raises(ValueError, match="E_NATIVE_INGESTOR_EVIDENCE"):
        owner.run_native_commit_io(tmp_path, mode="bypass")
    candidate = json.loads((tmp_path / "native-ingestor-candidate.json").read_text())
    candidate["result"] = "PASS"  # Attempt the same ordinary qualification gate.
    candidate["cases"][0]["processes"][2]["exit"] = 1
    real = Path.read_bytes
    path = localpath(candidate["stdout"]["path"])
    raw = json.loads(real(path))
    raw["cases"] = candidate["cases"]
    content = json.dumps(raw).encode()
    candidate["stdout"]["sha256"] = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(Path, "read_bytes", lambda value: content if value == path else real(value))
    with pytest.raises(ValueError, match="E_NATIVE_INGESTOR_EVIDENCE") as error:
        owner.verify_native_ingestor(candidate)
    assert str(error.value.__cause__) == "reader success", (
        "Hook rejection hid unrelated reader failure"
    )


@pytest.mark.parametrize(
    "damage", ["handle", "file", "checkpoint", "dll", "unarmed", "postcommit", "missing_hook"]
)
def test_coherent_callback_substitution_rejected(
    report: dict[str, Any], damage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    row = copy.deepcopy(report)
    case = row["cases"][0]
    callback = case["checkpoint"]["commit_io"]
    if damage == "handle":
        callback["handle"] += 1
    elif damage == "file":
        callback["file"]["path"] += ".other"
    elif damage == "checkpoint":
        case["checkpoint"]["identity"]["checkpoint_id"] = "postcommit"
    elif damage == "dll":
        callback["dll"]["sha256"] = "0" * 64
    elif damage == "unarmed":
        callback["armed"] = False
    elif damage == "postcommit":
        callback["inside_callback"] = False
    else:
        callback["installed"] = False
    real = Path.read_bytes
    virtual: dict[Path, bytes] = {}

    def replace(descriptor: dict[str, str], value: Any) -> None:
        content = json.dumps(value).encode()
        virtual[localpath(descriptor["path"])] = content
        descriptor["sha256"] = hashlib.sha256(content).hexdigest()

    replace(case["checkpoint_artifact"], case["checkpoint"])
    raw = json.loads(real(localpath(row["stdout"]["path"])))
    raw["cases"] = row["cases"]
    replace(row["stdout"], raw)
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: virtual[path] if path in virtual else real(path)
    )
    with pytest.raises(ValueError, match="E_NATIVE_INGESTOR_EVIDENCE"):
        owner.verify_native_ingestor(row)
