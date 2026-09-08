"""Strict source-owned inputs for the full candidate controller."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from tools.retained_artifact_io import canonical_recorded_locator

if TYPE_CHECKING:
    from tools.retained_artifact_io import RetainedArtifactIO


@dataclass(frozen=True)
class QualificationEvidenceConfig:
    full_repair_aggregate: Path
    full_repair_inventory: Path
    environment_qualification_aggregate: Path
    environment_qualification_inventory: Path
    p03_proof: Path
    p04_proof: Path

    def binding(self) -> dict[str, str]:
        return {
            "full_repair_aggregate": str(self.full_repair_aggregate),
            "full_repair_inventory": str(self.full_repair_inventory),
            "environment_qualification_aggregate": str(self.environment_qualification_aggregate),
            "environment_qualification_inventory": str(self.environment_qualification_inventory),
            "p03_proof": str(self.p03_proof),
            "p04_proof": str(self.p04_proof),
        }


@dataclass(frozen=True)
class FullVerifierConfig:
    schema_version: str
    production_authority: str
    accepted_authoring_ancestor: str
    current_checkout_root: Path
    governed_source_pack: Path
    evidence_root: Path
    external_authoring_tests: Path
    external_authoring_source_sha256: str
    external_authoring_cwd: Path
    external_authoring_argv: tuple[str, ...]
    uv_cache: Path
    pnpm_store: Path
    chrome_path: Path
    chrome_sha256: str
    authoring_repository_receipt: Path
    candidate_command_evidence: Path
    proof_coverage_evidence: Path
    candidate_issuance_evidence: Path
    candidate_qualification_receipt: Path
    audited_runtime_ancestor: str | None
    qualification_evidence: QualificationEvidenceConfig | None
    descendant_repository_receipt: Path | None
    source_path: Path
    source_sha256: str

    def binding(self) -> dict[str, object]:
        binding: dict[str, object] = {
            "schema_version": (
                "full-verifier-controller-binding/v2"
                if self.schema_version == "full-verifier-controller/v2"
                else "full-verifier-controller-binding/v1"
            ),
            "config_sha256": self.source_sha256,
            "accepted_authoring_ancestor": self.accepted_authoring_ancestor,
            "current_checkout_root": str(self.current_checkout_root),
            "governed_source_pack": str(self.governed_source_pack),
            "evidence_root": str(self.evidence_root),
            "external_authoring_tests": str(self.external_authoring_tests),
            "external_authoring_source_sha256": self.external_authoring_source_sha256,
            "external_authoring_command": {
                "cwd": str(self.external_authoring_cwd),
                "argv": list(self.external_authoring_argv),
            },
            "uv_cache": str(self.uv_cache),
            "pnpm_store": str(self.pnpm_store),
            "chrome": {"path": str(self.chrome_path), "sha256": self.chrome_sha256},
            "receipts": {
                "authoring_repository": str(self.authoring_repository_receipt),
                "candidate_command_evidence": str(self.candidate_command_evidence),
                "proof_coverage_evidence": str(self.proof_coverage_evidence),
                "candidate_issuance_evidence": str(self.candidate_issuance_evidence),
                "candidate_qualification": str(self.candidate_qualification_receipt),
            },
        }
        if self.schema_version == "full-verifier-controller/v2":
            if (
                self.audited_runtime_ancestor is None
                or self.qualification_evidence is None
                or self.descendant_repository_receipt is None
            ):
                _fail()
            binding["audited_runtime_ancestor"] = self.audited_runtime_ancestor
            binding["qualification_evidence"] = self.qualification_evidence.binding()
            receipts = cast(dict[str, str], binding["receipts"])
            receipts["descendant_repository"] = str(self.descendant_repository_receipt)
        return binding


def _fail() -> NoReturn:
    raise ValueError("E_CONTROLLER_CONFIG")


def _absolute(value: object) -> Path:
    if not isinstance(value, str):
        _fail()
    path = Path(value)
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _fail()
    return path


def load_controller_config(
    path: Path,
    *,
    mode: Literal["LIVE", "SEALED"] = "LIVE",
    artifacts: RetainedArtifactIO | None = None,
    recorded_locator: str | None = None,
) -> FullVerifierConfig:
    if mode not in {"LIVE", "SEALED"}:
        _fail()
    if mode == "LIVE" and (artifacts is not None or recorded_locator is not None):
        _fail()
    if mode == "SEALED" and (artifacts is None or recorded_locator is None):
        _fail()
    try:
        info = path.lstat()
        canonical_path = path.resolve(strict=True)
        if mode == "SEALED":
            assert artifacts is not None and recorded_locator is not None
            recorded_boundary = artifacts.recorded_boundary(recorded_locator)
            mapped = artifacts.physical_path(recorded_locator, recorded_boundary=recorded_boundary)
            if canonical_path != mapped.resolve(strict=True):
                _fail()
            raw = artifacts.read_bytes(recorded_locator, recorded_boundary=recorded_boundary)
        else:
            raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("E_CONTROLLER_CONFIG") from error
    schema_version = value.get("schema_version") if isinstance(value, dict) else None
    base_keys = {
        "schema_version",
        "production_authority",
        "accepted_authoring_ancestor",
        "current_checkout_root",
        "governed_source_pack",
        "evidence_root",
        "external_authoring_tests",
        "external_authoring_source_sha256",
        "external_authoring_command",
        "uv_cache",
        "pnpm_store",
        "chrome",
        "receipts",
    }
    expected_keys = (
        base_keys | {"audited_runtime_ancestor", "qualification_evidence"}
        if schema_version == "full-verifier-controller/v2"
        else base_keys
    )
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or not isinstance(value, dict)
        or set(value) != expected_keys
        or schema_version not in {"full-verifier-controller/v1", "full-verifier-controller/v2"}
        or value.get("production_authority") != "NONE"
        or not isinstance(value.get("accepted_authoring_ancestor"), str)
        or re.fullmatch(r"[0-9a-f]{40}", cast(str, value.get("accepted_authoring_ancestor")))
        is None
        or not isinstance(value.get("external_authoring_source_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", cast(str, value.get("external_authoring_source_sha256")))
        is None
    ):
        _fail()
    chrome = value.get("chrome")
    receipts = value.get("receipts")
    external_command = value.get("external_authoring_command")
    receipt_keys = {
        "authoring_repository",
        "candidate_command_evidence",
        "proof_coverage_evidence",
        "candidate_issuance_evidence",
        "candidate_qualification",
    }
    if schema_version == "full-verifier-controller/v2":
        receipt_keys.add("descendant_repository")
    qualification = value.get("qualification_evidence")
    qualification_keys = {
        "full_repair_aggregate",
        "full_repair_inventory",
        "environment_qualification_aggregate",
        "environment_qualification_inventory",
        "p03_proof",
        "p04_proof",
    }
    if (
        not isinstance(chrome, dict)
        or set(chrome) != {"path", "sha256"}
        or not isinstance(chrome.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", cast(str, chrome["sha256"])) is None
        or not isinstance(receipts, dict)
        or not isinstance(external_command, dict)
        or set(external_command) != {"cwd", "argv"}
        or not isinstance(external_command.get("argv"), list)
        or not external_command["argv"]
        or any(not isinstance(item, str) or not item for item in external_command["argv"])
        or set(receipts) != receipt_keys
        or (
            schema_version == "full-verifier-controller/v2"
            and (
                not isinstance(value.get("audited_runtime_ancestor"), str)
                or re.fullmatch(r"[0-9a-f]{40}", cast(str, value.get("audited_runtime_ancestor")))
                is None
                or not isinstance(qualification, dict)
                or set(qualification) != qualification_keys
            )
        )
        or (schema_version == "full-verifier-controller/v1" and qualification is not None)
    ):
        _fail()
    values = cast(dict[str, Any], value)
    evidence_root = _absolute(values["evidence_root"])
    receipt_paths = {key: _absolute(item) for key, item in receipts.items()}
    qualification_paths = (
        {key: _absolute(item) for key, item in cast(dict[str, object], qualification).items()}
        if schema_version == "full-verifier-controller/v2"
        else {}
    )
    checkout_root = _absolute(values["current_checkout_root"])
    source_pack = _absolute(values["governed_source_pack"])
    external_tests = _absolute(values["external_authoring_tests"])
    external_cwd = _absolute(external_command["cwd"])
    protected = (checkout_root, source_pack, external_tests.parent)
    paths_to_protect = (evidence_root, *receipt_paths.values(), *qualification_paths.values())
    if (
        len(set((*receipt_paths.values(), *qualification_paths.values())))
        != len(receipt_paths) + len(qualification_paths)
        or any(
            not item.is_relative_to(evidence_root)
            for item in (*receipt_paths.values(), *qualification_paths.values())
        )
        or any(
            (mode == "LIVE" and candidate.resolve(strict=False) != candidate)
            or candidate == boundary
            or candidate.is_relative_to(boundary)
            or boundary.is_relative_to(candidate)
            for candidate in paths_to_protect
            for boundary in protected
        )
    ):
        _fail()
    version_number = "v1" if schema_version == "full-verifier-controller/v1" else "v2"
    source_copy = source_pack / f"docs/configs/full-verifier-controller.{version_number}.json"
    try:
        source_raw = (
            artifacts.read_bytes(str(source_copy), recorded_boundary=str(source_pack))
            if mode == "SEALED" and artifacts is not None
            else source_copy.read_bytes()
        )
        if source_raw != raw:
            _fail()
    except (OSError, ValueError) as error:
        raise ValueError("E_CONTROLLER_CONFIG") from error
    return FullVerifierConfig(
        schema_version=cast(str, schema_version),
        production_authority="NONE",
        accepted_authoring_ancestor=cast(str, values["accepted_authoring_ancestor"]),
        current_checkout_root=checkout_root,
        governed_source_pack=source_pack,
        evidence_root=evidence_root,
        external_authoring_tests=external_tests,
        external_authoring_source_sha256=cast(str, values["external_authoring_source_sha256"]),
        external_authoring_cwd=external_cwd,
        external_authoring_argv=tuple(cast(list[str], external_command["argv"])),
        uv_cache=_absolute(values["uv_cache"]),
        pnpm_store=_absolute(values["pnpm_store"]),
        chrome_path=_absolute(chrome["path"]),
        chrome_sha256=cast(str, chrome["sha256"]),
        authoring_repository_receipt=receipt_paths["authoring_repository"],
        candidate_command_evidence=receipt_paths["candidate_command_evidence"],
        proof_coverage_evidence=receipt_paths["proof_coverage_evidence"],
        candidate_issuance_evidence=receipt_paths["candidate_issuance_evidence"],
        candidate_qualification_receipt=receipt_paths["candidate_qualification"],
        audited_runtime_ancestor=cast(str, values["audited_runtime_ancestor"])
        if schema_version == "full-verifier-controller/v2"
        else None,
        qualification_evidence=QualificationEvidenceConfig(**qualification_paths)
        if schema_version == "full-verifier-controller/v2"
        else None,
        descendant_repository_receipt=receipt_paths.get("descendant_repository"),
        source_path=Path(canonical_recorded_locator(cast(str, recorded_locator)))
        if mode == "SEALED" else canonical_path,
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )
