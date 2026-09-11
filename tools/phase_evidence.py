"""Produce ordinary phase proofs from actual registered invocations and logs."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from tools import run_command_registry as commands
from tools.full_verifier_config import FullVerifierConfig
from tools.retained_artifact_io import RetainedArtifactIO

CONTRACT = "docs/contracts/part-b-one-ready.v1.json"
CURRENT_COMMANDS = {"VALIDATE_CURRENT_DECLARATION", "VALIDATE_CURRENT_DESCENDANT_MIGRATION"}
RESULT_KEYS = {
    "argv",
    "command_id",
    "cwd",
    "expected_exit",
    "exit_code",
    "passed",
    "stdout_sha256",
    "stdout_size_bytes",
    "stderr_sha256",
    "stderr_size_bytes",
}


def read(path: Path, artifacts: RetainedArtifactIO | None = None) -> bytes:
    if artifacts is not None:
        return artifacts.read_bytes(
            str(path), recorded_boundary=artifacts.recorded_boundary(str(path))
        )
    if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("E_PHASE_EVIDENCE")
    return path.read_bytes()


def contract(
    config: FullVerifierConfig, artifacts: RetainedArtifactIO | None = None
) -> dict[str, Any] | None:
    registry = json.loads(
        read(
            config.governed_source_pack / "docs/registries/task-command-registry.v1.json", artifacts
        )
    )
    ids = {row["command_id"] for row in registry["commands"]}
    if not ids & CURRENT_COMMANDS:
        return None  # Unamended historical contract keeps its original semantics.
    if not ids >= CURRENT_COMMANDS:
        raise ValueError("E_PHASE_EVIDENCE")
    value = json.loads(read(config.governed_source_pack / CONTRACT, artifacts))
    if (
        value.get("schema_version") != "part-b-one-ready/v1"
        or value.get("production_authority") != "NONE"
        or len(value.get("phases", {})) != 9
    ):
        raise ValueError("E_PHASE_EVIDENCE")
    return cast(dict[str, Any], value)


def expected_commands(
    config: FullVerifierConfig, artifacts: RetainedArtifactIO | None = None
) -> dict[str, dict[str, Any]]:
    registry = json.loads(
        read(
            config.governed_source_pack / "docs/registries/task-command-registry.v1.json", artifacts
        )
    )

    def rebind(value: str) -> str:
        for old, new in (
            (commands.LEGACY_AUTHORING_RUNTIME, str(config.current_checkout_root)),
            (commands.LEGACY_AUTHORING_PACK, str(config.governed_source_pack)),
        ):
            if value == old or value.startswith(old + "/"):
                return new + value[len(old) :]
        return value

    return {
        row["command_id"]: {
            **row,
            "cwd": rebind(row["cwd"]),
            "argv": [rebind(a) for a in row["argv"]],
        }
        for row in registry["commands"]
    }


def validate_execution(command: dict[str, Any], execution: dict[str, Any]) -> None:
    try:
        result = execution["result"]
        if (
            set(execution) != {"result", "stdout", "stderr"}
            or set(result) != RESULT_KEYS
            or any(
                result.get(k) != command[k] for k in ("argv", "command_id", "cwd", "expected_exit")
            )
        ):
            raise ValueError("E_PHASE_EVIDENCE")
        if (
            type(result["exit_code"]) is not int
            or result["exit_code"] != 0
            or command["expected_exit"] != 0
            or result["passed"] is not True
        ):
            raise ValueError("E_PHASE_EVIDENCE")
        for stream in ("stdout", "stderr"):
            raw = base64.b64decode(execution[stream], validate=True)
            if (
                hashlib.sha256(raw).hexdigest() != result[stream + "_sha256"]
                or str(len(raw)) != result[stream + "_size_bytes"]
            ):
                raise ValueError("E_PHASE_EVIDENCE")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("E_PHASE_EVIDENCE") from error


def validate_current_output(
    identifier: str,
    execution: dict[str, Any],
    config: FullVerifierConfig,
    identity: dict[str, object],
    artifacts: RetainedArtifactIO | None = None,
) -> None:
    if identifier not in CURRENT_COMMANDS:
        return
    value = json.loads(base64.b64decode(execution["stdout"], validate=True))
    spec = contract(config, artifacts)
    assert spec is not None
    names = [
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
    expected_gate = (
        "CURRENT_DECLARATION_VALID"
        if identifier == "VALIDATE_CURRENT_DECLARATION"
        else "CURRENT_DESCENDANT_SOURCE_VALID"
    )
    if (
        value.get("gate") != expected_gate
        or value.get("result") != "PASS"
        or value.get("production_authority") != "NONE"
        or value.get("source_identity") != identity
        or value.get("contract_sha256")
        != hashlib.sha256(read(config.governed_source_pack / CONTRACT, artifacts)).hexdigest()
        or value.get("input_hashes")
        != {
            name: hashlib.sha256(
                read(config.governed_source_pack / "docs" / name, artifacts)
            ).hexdigest()
            for name in names
        }
    ):
        raise ValueError("E_PHASE_CURRENT_INPUT")
    if identifier == "VALIDATE_CURRENT_DESCENDANT_MIGRATION" and (
        value.get("adopted_source") != spec["adopted_source"]
        or value.get("historical_receipt_sha256") != spec["historical_migration_sha256"]
        or value.get("historical_regressions", {}).get("exit_code") != 0
        or value.get("historical_acceptance") != "NOT_INFERRED"
    ):
        raise ValueError("E_PHASE_CURRENT_INPUT")


def issue_phases(
    config: FullVerifierConfig, extra_results: list[dict[str, object]], identity: dict[str, object]
) -> None:
    spec = contract(config)
    if spec is None:
        return
    before = commands._git_source_identity(config.current_checkout_root)
    if before != identity:
        raise ValueError("E_PHASE_SOURCE_DRIFT")
    candidate = json.loads(read(config.candidate_command_evidence))
    results = [*candidate["results"], *extra_results]
    by_id = {r["command_id"]: r for r in results}
    if len(by_id) != len(results) or candidate["controller_binding"] != config.binding():
        raise ValueError("E_PHASE_EVIDENCE")
    registry = expected_commands(config)
    proofs = {}
    for phase, identifiers in spec["phases"].items():
        executions = []
        for identifier in identifiers:
            result = by_id.get(identifier)
            if result is None:
                raise ValueError("E_PHASE_EVIDENCE")
            execution = {
                "result": result,
                **{
                    stream: base64.b64encode(
                        read(config.evidence_root / "command-logs" / f"{identifier}.{stream}")
                    ).decode()
                    for stream in ("stdout", "stderr")
                },
            }
            validate_execution(registry[identifier], execution)
            validate_current_output(identifier, execution, config, identity)
            executions.append(execution)
        proofs[phase] = {
            "schema_version": "current-phase-proof/v1",
            "task_id": phase,
            "result": "PASS",
            "production_authority": "NONE",
            "controller_binding": config.binding(),
            "source_identity": before,
            "contract_sha256": hashlib.sha256(
                read(config.governed_source_pack / CONTRACT)
            ).hexdigest(),
            "commands": executions,
        }
    if commands._git_source_identity(config.current_checkout_root) != before:
        raise ValueError("E_PHASE_EVIDENCE")
    if any((config.evidence_root / f"{phase}.json").exists() for phase in proofs):
        raise ValueError("E_PHASE_EVIDENCE_EXISTS")
    for phase, proof in proofs.items():
        with (config.evidence_root / f"{phase}.json").open("x") as stream:
            json.dump(proof, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")


def verify_phase(
    evidence: dict[str, Any],
    config: FullVerifierConfig,
    artifacts: RetainedArtifactIO | None = None,
) -> None:
    spec = contract(config, artifacts)
    if spec is None:
        return
    phase = evidence.get("task_id")
    if (
        set(evidence)
        != {
            "schema_version",
            "task_id",
            "result",
            "production_authority",
            "controller_binding",
            "source_identity",
            "contract_sha256",
            "commands",
        }
        or evidence["schema_version"] != "current-phase-proof/v1"
        or evidence["result"] != "PASS"
        or evidence["production_authority"] != "NONE"
        or evidence["controller_binding"] != config.binding()
        or phase not in spec["phases"]
        or evidence["contract_sha256"]
        != hashlib.sha256(read(config.governed_source_pack / CONTRACT, artifacts)).hexdigest()
    ):
        raise ValueError("E_PHASE_EVIDENCE")
    expected = spec["phases"][phase]
    executions = evidence["commands"]
    if not isinstance(executions, list) or len(executions) != len(expected):
        raise ValueError("E_PHASE_EVIDENCE")
    registry = expected_commands(config, artifacts)
    for identifier, execution in zip(expected, executions, strict=True):
        validate_execution(registry[identifier], execution)
    if artifacts is None:
        identity = commands._git_source_identity(config.current_checkout_root)
    else:
        assert config.descendant_repository_receipt is not None
        receipt = json.loads(read(config.descendant_repository_receipt, artifacts))
        identity = {
            "head": receipt["repository_commit"],
            "tree": receipt["repository_tree"],
            "source_diff": "",
        }
    if evidence["source_identity"] != identity:
        raise ValueError("E_PHASE_EVIDENCE")
    for identifier, execution in zip(expected, executions, strict=True):
        validate_current_output(identifier, execution, config, identity, artifacts)


def main() -> None:
    import argparse

    from tools.full_verifier_config import load_controller_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load_controller_config(args.config)
    inputs = json.loads(read(config.evidence_root / "CURRENT_INPUTS.json"))
    if (
        set(inputs) != {"source_identity", "results", "controller_binding"}
        or inputs["controller_binding"] != config.binding()
    ):
        raise ValueError("E_PHASE_CURRENT_INPUT")
    issue_phases(config, inputs["results"], inputs["source_identity"])
    print("CURRENT_PHASE_PROOFS_ISSUED: SOURCE_VALIDATION_ONLY")


if __name__ == "__main__":
    main()
