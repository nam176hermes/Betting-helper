"""Strict source-owned inputs for the full candidate controller."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast


@dataclass(frozen=True)
class FullVerifierConfig:
    production_authority: str
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
    source_path: Path
    source_sha256: str

    def binding(self) -> dict[str, object]:
        return {
            "schema_version": "full-verifier-controller-binding/v1",
            "config_sha256": self.source_sha256,
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


def _fail() -> NoReturn:
    raise ValueError("E_CONTROLLER_CONFIG")


def _absolute(value: object) -> Path:
    if not isinstance(value, str):
        _fail()
    path = Path(value)
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _fail()
    return path


def load_controller_config(path: Path) -> FullVerifierConfig:
    try:
        info = path.lstat()
        canonical_path = path.resolve(strict=True)
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("E_CONTROLLER_CONFIG") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "production_authority",
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
        or value.get("schema_version") != "full-verifier-controller/v1"
        or value.get("production_authority") != "NONE"
        or not isinstance(value.get("external_authoring_source_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", cast(str, value.get("external_authoring_source_sha256")))
        is None
    ):
        _fail()
    chrome = value.get("chrome")
    receipts = value.get("receipts")
    external_command = value.get("external_authoring_command")
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
        or set(receipts)
        != {
            "authoring_repository",
            "candidate_command_evidence",
            "proof_coverage_evidence",
            "candidate_issuance_evidence",
            "candidate_qualification",
        }
    ):
        _fail()
    values = cast(dict[str, Any], value)
    evidence_root = _absolute(values["evidence_root"])
    receipt_paths = {key: _absolute(item) for key, item in receipts.items()}
    checkout_root = _absolute(values["current_checkout_root"])
    source_pack = _absolute(values["governed_source_pack"])
    external_tests = _absolute(values["external_authoring_tests"])
    external_cwd = _absolute(external_command["cwd"])
    protected = (checkout_root, source_pack, external_tests.parent)
    paths_to_protect = (evidence_root, *receipt_paths.values())
    if (
        len(set(receipt_paths.values())) != len(receipt_paths)
        or any(not item.is_relative_to(evidence_root) for item in receipt_paths.values())
        or any(
            candidate.resolve(strict=False) != candidate
            or candidate == boundary
            or candidate.is_relative_to(boundary)
            or boundary.is_relative_to(candidate)
            for candidate in paths_to_protect
            for boundary in protected
        )
    ):
        _fail()
    source_copy = source_pack / "docs/configs/full-verifier-controller.v1.json"
    try:
        if source_copy.read_bytes() != raw:
            _fail()
    except OSError as error:
        raise ValueError("E_CONTROLLER_CONFIG") from error
    return FullVerifierConfig(
        production_authority="NONE",
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
        source_path=canonical_path,
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )
