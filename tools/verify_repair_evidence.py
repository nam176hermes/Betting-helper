"""Local evidence validation; no release signing or live authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from pathlib import Path
from shutil import which
from subprocess import run
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"
STATUSES = {"PASS", "FAIL", "BLOCKED_ENVIRONMENT", "NOT_IMPLEMENTED", "NOT_EXECUTED"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_binding() -> dict[str, Any]:
    """Capture tested working bytes as well as HEAD; reports are not self-hashed."""
    git = which("git")
    if git is None:
        raise FileNotFoundError("E_REPAIR_GIT_PREREQUISITE")
    revision = run(  # noqa: S603 -- fixed read-only local git command
        [git, "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True,
        text=True, timeout=10,
    ).stdout.strip()
    sources = [p for directory, suffix in (
        ("src", ".py"), ("tools", ".py"), ("extension/src", ".ts"),
        ("extension/test-harness", ".ts"),
    ) for p in (ROOT / directory).rglob("*" + suffix)]
    sources += [ROOT / name for name in (
        "pyproject.toml", "extension/package.json", "extension/tsconfig.test.json",
        "extension/.test-build/src/contracts/clock-vectors.js",
    ) if (ROOT / name).is_file()]
    node = which("node")
    return {
        "revision": revision,
        "source_sha256": {str(p.relative_to(ROOT)): _sha(p) for p in sorted(sources)},
        "vendor_sha256": {str(p.relative_to(ROOT)): _sha(p)
                          for p in sorted(PACK.rglob("*")) if p.is_file()},
        "lock_sha256": {name: _sha(ROOT / name) for name in (
            "schema-lock.json", "uv.lock", "pnpm-lock.yaml",
        )},
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "python_executable": str(Path(sys.executable).resolve()),
                        "python_sha256": _sha(Path(sys.executable)), "node": node,
                        "node_sha256": _sha(Path(node)) if node else None},
    }


def full_required_ids() -> list[str]:
    crash = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())
    clock = json.loads((PACK / "docs/registries/clock-vector-coverage.v1.json").read_text())
    return [entry["vector_id"] for group in (crash, clock) for entry in group["entries"]]


def _verify_clock(row: dict[str, Any], current: dict[str, Any]) -> None:
    # Import lazily: the clock producer captures this module's binding before execution.
    from tools import run_clock_vector_qualification as clock

    if row["evidence_binding"] != current:
        raise ValueError("E_REPAIR_STALE_BINDING")
    if row["code"]["revision"] != current["revision"]:
        raise ValueError("E_REPAIR_REVISION")
    if row["environment"] != {"python": platform.python_version(),
                              "platform": platform.platform(), "node": which("node")}:
        raise ValueError("E_REPAIR_ENVIRONMENT")
    if not row["code"]["sha256"] or any(
        _sha(Path(path)) != digest for path, digest in row["code"]["sha256"].items()
    ):
        raise ValueError("E_REPAIR_SOURCE")
    if not clock.verify_record(row):
        raise ValueError("E_REPAIR_ARTIFACT")
    if row["status"] != "PASS":
        return
    coverage = json.loads((PACK / clock._COVERAGE_PATH).read_text())
    vectors = json.loads((PACK / clock._VECTOR_PATH).read_text())
    entry = next(e for e in coverage["entries"] if e["vector_id"] == row["case_id"])
    canonical = clock._case(entry, vectors)
    if (any(row[key] != canonical[key] for key in ("input", "expected", "family"))
            or row["source_section"] != canonical["section"]
            or row["registry_version"] != coverage["schema_version"]):
        raise ValueError("E_REPAIR_REGISTERED_ORACLE")
    if (row["execution_kind"] != "OFFLINE_SHARED_CLOCK_EVALUATOR"
            or row["executed"] is not True or row["comparison"]["matched"] is not True
            or row["cross_language_drift"] is not False
            or set(row["actual"]) != {"python", "typescript", "execution_error"}
            or row["actual"]["execution_error"] is not None
            or row["observed_error"] != row["expected"]["error"]
            or set(row["command_exit"]) != {"python", "typescript"}
            or any(type(value) is not int or value != 0
                   for value in row["command_exit"].values())
            or any(clock._diff(row["actual"][language], row["expected"])
                   for language in ("python", "typescript"))):
        raise ValueError("E_REPAIR_EXECUTION_COMPARISON")


def aggregate_repair_evidence(
    required_ids: list[str], results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate exact terminal records. An unsupported execution never qualifies."""
    errors: list[dict[str, str]] = []
    ids = [row.get("case_id", row.get("vector_id", "")) for row in results]
    exact = (bool(required_ids) and all(isinstance(i, str) and i for i in required_ids)
             and len(required_ids) == len(set(required_ids))
             and Counter(ids) == Counter(required_ids))
    if not exact:
        errors.append({"case_id": "", "error": "E_REPAIR_REQUIRED_ID_SET"})
    try:
        current = capture_binding() if any("evidence_binding" in row for row in results) else {}
    except (OSError, ValueError) as error:
        current = {}
        errors.append({"case_id": "", "error": f"E_REPAIR_BINDING_UNAVAILABLE:{error}"})
    for case_id, row in zip(ids, results, strict=True):
        try:
            status = row["status"]
            if "scoped_evidence" in row or "scoped_result" in row:
                raise ValueError("E_REPAIR_SUPPLEMENTAL_MUST_BE_SEPARATE")
            if status not in STATUSES:
                raise ValueError("E_REPAIR_STATUS")
            if "case_id" in row and "vector_id" in row and row["case_id"] != row["vector_id"]:
                raise ValueError("E_REPAIR_CASE_ID")
            if status == "PASS":
                _verify_clock(row, current)
            elif status == "FAIL":
                raise ValueError("E_REPAIR_REPORTED_FAILURE")
            else:
                if row.get("executed", False) is not False:
                    raise ValueError("E_REPAIR_UNEXECUTED_STATUS")
                if not (row.get("reason") or row.get("observed_error")):
                    raise ValueError("E_REPAIR_REASON_REQUIRED")
                if status == "BLOCKED_ENVIRONMENT":
                    prerequisite = row["prerequisite"]
                    if not prerequisite["name"] or prerequisite["available"] is not False:
                        raise ValueError("E_REPAIR_PREREQUISITE")
                # Existing evidence cannot disappear behind a non-PASS status.
                if "actual_artifact" in row or "evidence_binding" in row:
                    _verify_clock(row, current)
        except (KeyError, ValueError, TypeError, OSError, StopIteration) as error:
            errors.append({"case_id": str(case_id), "error": str(error)})
    full = exact and set(required_ids) == set(full_required_ids())
    counts = Counter(str(row.get("status", "INVALID")) for row in results)
    result = "FAIL" if errors else "PASS" if counts["PASS"] == len(required_ids) else "HOLD"
    return {
        "result": result, "qualification_scope": "FULL" if full else "SUBSET",
        "legacy_full_qualification": "PASS" if full and result == "PASS" else "HOLD",
        "required_id_set_complete": exact, "status_counts": dict(counts), "errors": errors,
        "pending_cases": [{"case_id": case_id, "status": row.get("status"),
                           "reason": row.get("reason", row.get("observed_error"))}
                          for case_id, row in zip(ids, results, strict=True)
                          if row.get("status") != "PASS"],
        "security_review": "NOT_REVIEWED", "production_authority": "NONE",
        "live_authority": "NONE", "money_authority": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="JSON with required_ids and results")
    args = parser.parse_args()
    payload = json.loads(args.evidence.read_text())
    result = aggregate_repair_evidence(payload["required_ids"], payload["results"])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "PASS" else 2 if result["result"] == "HOLD" else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
