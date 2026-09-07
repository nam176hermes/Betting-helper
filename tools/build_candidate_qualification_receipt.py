"""Bind passed candidate replay evidence to the exact source inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from tools.retained_artifact_io import RetainedArtifactIO

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_ROOT))

from tools import run_command_registry  # noqa: E402
from tools.full_verifier_config import FullVerifierConfig, load_controller_config  # noqa: E402
from tools.verify_proof_coverage import verify_proof_coverage_matrix  # noqa: E402


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _git(root: Path, *args: str) -> bytes:
    git = shutil.which("git")
    if git is None:
        raise ValueError("E_CANDIDATE_RECEIPT")
    completed = subprocess.run(  # noqa: S603 - fixed read-only Git operation.
        [git, "-C", str(root), *args],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError("E_CANDIDATE_RECEIPT")
    return completed.stdout


def _inventory(root: Path, generated_outputs: object = None) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("E_CANDIDATE_RECEIPT")
    if _git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root.resolve()):
        raise ValueError("E_CANDIDATE_RECEIPT")
    ownership = root / "vendor/hybrid-discovery-v6.3.6/docs/registries/artifact-ownership.v1.json"
    declared_generated = (
        run_command_registry._declared_compiler_outputs(root) if ownership.is_file() else set()
    )
    changed = {
        item.decode()
        for command in (
            ("diff", "--name-only", "-z"),
            ("diff", "--cached", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        )
        for item in _git(root, *command).split(b"\0")
        if item
    }
    if not changed.issubset(declared_generated):
        raise ValueError("E_CANDIDATE_RECEIPT")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    tree = _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    if re.fullmatch(r"[0-9a-f]{40}", head) is None or re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise ValueError("E_CANDIDATE_RECEIPT")
    entries: list[dict[str, str]] = []
    raw = _git(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            metadata, encoded_path = item.split(b"\t", 1)
            mode, kind, object_id = metadata.decode().split(" ")
            relative = encoded_path.decode("utf-8")
        except (UnicodeError, ValueError) as error:
            raise ValueError("E_CANDIDATE_RECEIPT") from error
        if relative in declared_generated:
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("E_CANDIDATE_RECEIPT")
        contents = (root / relative).read_bytes()
        if (
            hashlib.sha1(  # noqa: S324 - Git object identity is SHA-1 by protocol.
                f"blob {len(contents)}\0".encode() + contents,
                usedforsecurity=False,
            ).hexdigest()
            != object_id
        ):
            raise ValueError("E_CANDIDATE_RECEIPT")
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(contents).hexdigest(),
                "size": str(len(contents)),
                "mode": mode,
            }
        )
    inventory: dict[str, object] = {"head": head, "tree": tree, "entries": entries}
    if declared_generated:
        inventory["source_entries"] = inventory.pop("entries")
        inventory["generated_outputs"] = generated_outputs
    return inventory


def _read_bytes(path: Path, artifacts: RetainedArtifactIO | None = None) -> bytes:
    if artifacts is None:
        return path.read_bytes()
    recorded = str(path)
    return artifacts.read_bytes(recorded, recorded_boundary=artifacts.recorded_boundary(recorded))


def _read_evidence(path: Path, artifacts: RetainedArtifactIO | None = None) -> dict[str, object]:
    try:
        value = json.loads(_read_bytes(path, artifacts))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_CANDIDATE_RECEIPT") from error
    if not isinstance(value, dict):
        raise ValueError("E_CANDIDATE_RECEIPT")
    return cast(dict[str, object], value)


def _validate_command_evidence(
    source: Path, evidence: dict[str, object], config: FullVerifierConfig
) -> None:
    if evidence.get("schema_version") != "candidate-command-results/v3":
        raise ValueError("E_CANDIDATE_RECEIPT")
    try:
        run_command_registry.validate_external_authoring_result(
            evidence.get("external_authoring_result"), config
        )
        registry = run_command_registry.validate_registry(source / "task-command-registry.json")
        expected = run_command_registry.build_candidate_command_results(
            registry,
            evidence.get("results"),
            config,
            evidence.get("generated_outputs"),
        )
    except ValueError as error:
        raise ValueError("E_CANDIDATE_RECEIPT") from error
    expected["schema_version"] = "candidate-command-results/v3"
    expected["external_authoring_result"] = evidence["external_authoring_result"]
    if evidence != expected or evidence.get(
        "generated_outputs"
    ) != run_command_registry.collect_generated_outputs(source):
        raise ValueError("E_CANDIDATE_RECEIPT")


def _validate_proof_coverage(
    config: FullVerifierConfig, artifacts: RetainedArtifactIO | None = None
) -> dict[str, object]:
    proof = _read_evidence(config.proof_coverage_evidence, artifacts)
    evidence = proof.get("evidence")
    if (
        proof.get("schema_version") != "proof-coverage-result/v2"
        or proof.get("result") != "PASS"
        or proof.get("production_authority") != "NONE"
        or proof.get("control_count") != 18
        or proof.get("controller_binding") != config.binding()
        or not isinstance(evidence, list)
        or len(evidence) != 18
    ):
        raise ValueError("E_CANDIDATE_RECEIPT")
    try:
        source = config.governed_source_pack / "docs/registries/proof-coverage-matrix.v1.json"
        matrix = _read_evidence(source, artifacts)
        expected = verify_proof_coverage_matrix(
            matrix, config.evidence_root, "CANDIDATE", config, artifacts=artifacts
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("E_CANDIDATE_RECEIPT") from error
    if proof != expected or (artifacts is None and not source.is_file()):
        raise ValueError("E_CANDIDATE_RECEIPT")
    return proof


def _proof_coverage_sha256(
    config: FullVerifierConfig, artifacts: RetainedArtifactIO | None = None
) -> str:
    return hashlib.sha256(_read_bytes(config.proof_coverage_evidence, artifacts)).hexdigest()


def validate_candidate_qualification_receipt(
    source: Path,
    command_evidence: Path,
    receipt: dict[str, object],
    config: FullVerifierConfig | None = None,
    *,
    artifacts: RetainedArtifactIO | None = None,
) -> None:
    evidence = _read_evidence(command_evidence, artifacts)
    if config is None:
        raise ValueError("E_CANDIDATE_RECEIPT")
    _validate_command_evidence(source, evidence, config)
    if artifacts is None:
        _validate_proof_coverage(config)
    else:
        _validate_proof_coverage(config, artifacts)
    inventory = _inventory(source, evidence.get("generated_outputs"))
    required = {
        "schema_version",
        "production_authority",
        "command_result_root",
        "command_evidence_sha256",
        "command_ids",
        "inventory",
        "controller_binding",
        "proof_coverage_sha256",
    }
    if (
        set(receipt) != required
        or receipt.get("schema_version") != "candidate-qualification-receipt/v2"
        or receipt.get("production_authority") != "NONE"
        or receipt.get("command_result_root")
        != hashlib.sha256(
            b"HD636/CANDIDATE-COMMAND-RESULTS/v2\0" + _canonical(evidence)
        ).hexdigest()
        or receipt.get("command_evidence_sha256")
        != hashlib.sha256(_read_bytes(command_evidence, artifacts)).hexdigest()
        or receipt.get("command_ids")
        != [entry["command_id"] for entry in cast(list[dict[str, object]], evidence["results"])]
        or receipt.get("inventory") != inventory
        or config is None
        or receipt.get("controller_binding") != config.binding()
        or receipt.get("proof_coverage_sha256")
        != (
            _proof_coverage_sha256(config)
            if artifacts is None
            else _proof_coverage_sha256(config, artifacts)
        )
    ):
        raise ValueError("E_CANDIDATE_RECEIPT")


def build_candidate_qualification_receipt(
    source: Path,
    command_evidence: Path,
    output: Path,
    config: FullVerifierConfig,
) -> dict[str, object]:
    evidence = _read_evidence(command_evidence)
    _validate_command_evidence(source, evidence, config)
    _validate_proof_coverage(config)
    results = cast(list[dict[str, object]], evidence["results"])
    record: dict[str, object] = {
        "schema_version": "candidate-qualification-receipt/v2",
        "production_authority": "NONE",
        "command_result_root": hashlib.sha256(
            b"HD636/CANDIDATE-COMMAND-RESULTS/v2\0" + _canonical(evidence)
        ).hexdigest(),
        "command_evidence_sha256": hashlib.sha256(command_evidence.read_bytes()).hexdigest(),
        "command_ids": [item["command_id"] for item in results],
        "inventory": _inventory(source, evidence.get("generated_outputs")),
        "controller_binding": config.binding(),
        "proof_coverage_sha256": _proof_coverage_sha256(config),
    }
    validate_candidate_qualification_receipt(source, command_evidence, record, config)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--command-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = load_controller_config(args.config)
    result = build_candidate_qualification_receipt(
        args.source, args.command_evidence, args.output, config
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
