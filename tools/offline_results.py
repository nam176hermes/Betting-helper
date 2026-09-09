"""Parent aggregation of observed executions, with exact source provenance."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from tools.offline_browser import ROOT
from tools.offline_harness import source_hashes


def reference(path: Path, root: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "relative_path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def inventory() -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        json.loads((ROOT / "registries/offline-cases.json").read_text())["cases"],
    )


def build_result(
    root: Path,
    scenario: str,
    records: list[dict[str, Any]],
    diagnostic_name: str = "diagnostic.html",
) -> dict[str, Any]:
    first = json.loads((root / "OFF-01/browser/identity.json").read_text())
    context = json.loads((root / "OFF-01/run/context.json").read_text())
    current = source_hashes()
    provenance = {
        "schema_version": "offline-provenance/v1",
        "source_kind": "SYNTHETIC_TEST",
        "run_id": str(uuid4()),
        "scenario_id": scenario,
        "code_revision": subprocess.check_output(
            ["/usr/bin/git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_tree_sha256": hashlib.sha256(
            json.dumps(current, sort_keys=True).encode()
        ).hexdigest(),
        "browser_sha256": first["binary_sha256"],
        "browser_version": first["version"]["product"],
        "extension_origin": context["allowed_extension_origin"],
        "termination_kind": "OWNED_POSIX_PROCESS",
        "power_loss_qualified": False,
        "production_authority": "NONE",
    }
    for field, path in {
        "vendor_sha256": "vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json",
        "python_lock_sha256": "uv.lock",
        "node_lock_sha256": "pnpm-lock.yaml",
        "scenario_sha256": "registries/offline-cases.json",
    }.items():
        provenance[field] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    required = [row["case_id"] for row in inventory()] if scenario == "acceptance" else ["OFF-01"]
    return {
        "schema_version": "offline-slice-result/v1",
        "source_kind": "SYNTHETIC_TEST",
        "run_id": provenance["run_id"],
        "OFFLINE_SLICE_PASS": "YES"
        if scenario == "acceptance"
        and [r["case_id"] for r in records] == required
        and all(r["status"] == "PASS" for r in records)
        else "NO",
        "LIVE_PREFLIGHT_IMPLEMENTED": "YES",
        "LIVE_READ_ONLY_READY": "PENDING_REAL_INPUTS_AND_LIVE_REVIEW",
        "MONEY_READY": "NO",
        "LEGACY_FULL_QUALIFICATION": "HOLD",
        "INDEPENDENT_SECURITY_REVIEW": "NOT_RUN",
        "provenance": provenance,
        "required_case_ids": required,
        "records": records,
        "diagnostic": reference(root / diagnostic_name, root),
        "production_authority": "NONE",
    }


def artifacts(root: Path, case: str) -> list[dict[str, Any]]:
    return [
        reference(path, root)
        for path in sorted((root / case).rglob("*"))
        if path.is_file() and "profile" not in path.parts and "offline-extension" not in path.parts
    ]


def gate_view(result: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "verified": True,
        "OFFLINE_SLICE_PASS": result["OFFLINE_SLICE_PASS"],
        "run_id": result["run_id"],
        "source_kind": "SYNTHETIC_TEST",
        "code_revision": result["provenance"]["code_revision"],
        "cases": cases,
        "production_authority": "NONE",
        "MONEY_READY": "NO",
        "LIVE_READ_ONLY_READY": "PENDING_REAL_INPUTS_AND_LIVE_REVIEW",
    }
