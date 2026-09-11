from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tools import run_command_registry


def test_source_identity_excludes_only_declared_compiler_dirt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = ["extension/dist/compiler.js"]
    monkeypatch.setattr(
        run_command_registry, "_declared_compiler_outputs", lambda root: set(changed)
    )
    source_dirty = False

    def git(argv: list[str], **kwargs: Any) -> Any:
        args = argv[3:]
        if args == ["rev-parse", "--show-toplevel"]:
            out = str(tmp_path)
        elif args == ["rev-parse", "HEAD"]:
            out = "a" * 40
        elif args == ["rev-parse", "HEAD^{tree}"]:
            out = "b" * 40
        elif args == ["diff", "--name-only"]:
            out = "\n".join(changed + (["src/unauthorized.py"] if source_dirty else []))
        elif args in (
            ["diff", "--cached", "--name-only"],
            ["ls-files", "--others", "--exclude-standard"],
        ):
            out = ""
        else:
            pytest.fail("An empty git diff pathspec would include compiler bytes")
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(subprocess, "run", git)
    expected = {"head": "a" * 40, "tree": "b" * 40, "source_diff": ""}
    assert run_command_registry._git_source_identity(tmp_path) == expected
    changed.append("extension/dist/second.js")
    assert run_command_registry._git_source_identity(tmp_path) == expected
    source_dirty = True
    with pytest.raises(ValueError, match="LOCAL_GIT"):
        run_command_registry._git_source_identity(tmp_path)


def test_phase_issue_candidate_and_retained_checks_reject_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import phase_evidence as phase
    from tools.full_verifier_config import load_controller_config
    from tools.retained_artifact_io import RetainedArtifactIO

    root = Path(__file__).resolve().parents[2]
    original = load_controller_config(
        root / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"
    )
    spec = phase.contract(original)
    assert spec is not None
    config = replace(
        original,
        current_checkout_root=tmp_path / "runtime",
        governed_source_pack=tmp_path / "pack",
        evidence_root=tmp_path / "observed",
        candidate_command_evidence=tmp_path / "observed/candidate.json",
        descendant_repository_receipt=tmp_path / "descendant.json",
    )
    config.evidence_root.mkdir()
    source: dict[str, object] = {"head": "a" * 40, "tree": "b" * 40, "source_diff": ""}
    monkeypatch.setattr(run_command_registry, "_git_source_identity", lambda root: source.copy())
    docs = config.governed_source_pack / "docs"
    paths = [
        "tasks/task-manifest.v6.3.6.json",
        "registries/artifact-ownership.v1.json",
        "schemas/artifact-ownership.schema.json",
        *[
            "registries/" + n
            for n in (
                "task-command-registry.v1.json",
                "review-command-registry.v1.json",
                "cybersecurity-command-registry.v1.json",
                "baseline-replay-command-registry.v1.json",
            )
        ],
    ]
    for name in paths:
        path = docs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    contract_path = config.governed_source_pack / phase.CONTRACT
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(json.dumps(spec))
    identifiers = sorted({i for row in spec["phases"].values() for i in row})
    # Registered synthetic commands read finite expected input files. Actual stdout
    # is captured by the same runner used in the campaign, never copied from oracle.
    registered = [
        {
            "command_id": i,
            "argv": [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())",
                str(tmp_path / (i + ".input")),
            ],
            "cwd": str(tmp_path),
            "expected_exit": 0,
        }
        for i in identifiers
    ]
    (docs / paths[3]).write_text(json.dumps({"commands": registered}))
    inputs = {name: hashlib.sha256((docs / name).read_bytes()).hexdigest() for name in paths}
    observed = []
    for command in registered:
        identifier = command["command_id"]
        payload: Any = "TEST_ONLY_OBSERVATION"
        if identifier in phase.CURRENT_COMMANDS:
            payload = {
                "gate": "CURRENT_DECLARATION_VALID"
                if identifier == "VALIDATE_CURRENT_DECLARATION"
                else "CURRENT_DESCENDANT_SOURCE_VALID",
                "result": "PASS",
                "production_authority": "NONE",
                "source_identity": source,
                "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                "input_hashes": inputs,
                "adopted_source": spec["adopted_source"],
                "historical_receipt_sha256": spec["historical_migration_sha256"],
                "historical_regressions": {"exit_code": 0},
                "historical_acceptance": "NOT_INFERRED",
            }
        (tmp_path / (identifier + ".input")).write_text(json.dumps(payload))
        observed.append(
            run_command_registry.evaluate_invocation(
                command,
                environment={},
                working_directory=tmp_path,
                log_directory=config.evidence_root / "command-logs",
            )
        )
    extras = [r for r in observed if r["command_id"] in phase.CURRENT_COMMANDS]
    candidate = {
        "controller_binding": config.binding(),
        "results": [r for r in observed if r not in extras],
    }
    config.candidate_command_evidence.write_text(json.dumps(candidate))
    with pytest.raises(ValueError, match="E_PHASE_EVIDENCE"):
        phase.issue_phases(config, extras[:-1], source.copy())
    original_identity = source.copy()
    source["head"] = "c" * 40
    with pytest.raises(ValueError, match="E_PHASE_SOURCE_DRIFT"):
        phase.issue_phases(config, extras, original_identity)
    source.update(original_identity)
    phase.issue_phases(config, extras, original_identity)
    proofs = [
        json.loads((config.evidence_root / (task + ".json")).read_bytes())
        for task in spec["phases"]
    ]
    for proof in proofs:
        phase.verify_phase(proof, config)
    with pytest.raises(ValueError, match="E_PHASE_EVIDENCE"):
        phase.verify_phase({**proofs[0], "commands": []}, config)
    assert config.descendant_repository_receipt is not None
    config.descendant_repository_receipt.write_text(
        json.dumps({"repository_commit": source["head"], "repository_tree": source["tree"]})
    )
    retained = tmp_path / "retained"
    retained.mkdir()
    records = []
    for index, path in enumerate(
        [contract_path, *(docs / n for n in paths), config.descendant_repository_receipt]
    ):
        raw = path.read_bytes()
        name = str(index)
        (retained / name).write_bytes(raw)
        records.append(
            {
                "recorded_locator": str(path),
                "recorded_boundary": str(tmp_path),
                "copied_relative_path": name,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        path.unlink()
    artifacts = RetainedArtifactIO.from_manifest(
        {
            "schema_version": "retained-artifact-manifest/v1",
            "recorded_boundaries": [str(tmp_path)],
            "files": records,
        },
        retained,
    )
    source["head"] = "d" * 40  # Originals gone and live HEAD changed; retained proof remains bound.
    for proof in proofs:
        phase.verify_phase(proof, config, artifacts)
    (retained / "0").write_text("tamper")
    with pytest.raises(ValueError, match="E_RETAINED_ARTIFACT"):
        phase.verify_phase(proofs[0], config, artifacts)


def test_actual_command_logs_are_retained_exclusively(tmp_path: Path) -> None:
    command = {
        "command_id": "CHECK",
        "argv": [sys.executable, "-c", "print('observed')"],
        "expected_exit": 0,
    }
    result = run_command_registry.evaluate_invocation(
        command, environment={}, working_directory=tmp_path, log_directory=tmp_path / "logs"
    )
    assert result["passed"] is True
    assert (tmp_path / "logs/CHECK.stdout").read_bytes() == b"observed\n"
    assert result["stdout_sha256"] == hashlib.sha256(b"observed\n").hexdigest()
    with pytest.raises((ValueError, FileExistsError)):
        run_command_registry.evaluate_invocation(
            command, environment={}, working_directory=tmp_path, log_directory=tmp_path / "logs"
        )


def test_phase_record_rejects_changed_logs_missing_result_or_wrong_invocation(
    tmp_path: Path,
) -> None:
    from tools.phase_evidence import validate_execution

    command = {
        "command_id": "CHECK",
        "argv": [sys.executable, "-c", "pass"],
        "expected_exit": 0,
        "cwd": str(tmp_path),
    }
    result = run_command_registry.evaluate_invocation(
        command, environment={}, working_directory=tmp_path
    )
    execution = {"result": result, "stdout": "", "stderr": ""}
    validate_execution(command, execution)
    for broken in (
        {**execution, "stdout": base64.b64encode(b"invented").decode()},
        {**execution, "result": {**result, "passed": False}},
        {**execution, "result": {**result, "argv": ["unregistered"]}},
        {**execution, "result": {**result, "exit_code": True}},
    ):
        with pytest.raises(ValueError, match="E_PHASE_EVIDENCE"):
            validate_execution(command, broken)


def test_controller_stops_between_stages_when_clean_commit_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    from tools import phase_evidence, verify_local
    from tools.full_verifier_config import load_controller_config

    root = Path(__file__).resolve().parents[2]
    config = load_controller_config(
        root / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"
    )
    config = replace(
        config, evidence_root=tmp_path, candidate_command_evidence=tmp_path / "commands.json"
    )
    identity = {"head": "a" * 40, "tree": "b" * 40, "source_diff": ""}
    monkeypatch.setattr(run_command_registry, "_git_source_identity", lambda root: identity.copy())
    monkeypatch.setattr(
        verify_local, "_execute_external_authoring_suite", lambda config: {"passed": True}
    )
    monkeypatch.setattr(verify_local, "_validate_bootstrap_receipt", lambda *args: None)
    monkeypatch.setattr(verify_local, "_validate_authoring_tests", lambda *args: None)
    invoked = []

    def run(command: Any, **kwargs: Any) -> Any:
        invoked.append(command["command_id"])
        identity["head"] = "c" * 40
        return {"passed": True}

    monkeypatch.setattr(run_command_registry, "evaluate_invocation", run)
    assert verify_local._delegate_controller(config) == 1
    assert len(invoked) == 1 and invoked[0] in phase_evidence.CURRENT_COMMANDS
    assert "E_CONTROLLER_SOURCE_DRIFT" in capsys.readouterr().out
    assert not config.candidate_command_evidence.exists()
