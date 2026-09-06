"""Artifact-backed clock qualification. Inventory and stub calls are not coverage."""
# ruff: noqa: E402
from __future__ import annotations

import copy
import hashlib
import json
import platform
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from shutil import which
from subprocess import CalledProcessError, TimeoutExpired, run
from tempfile import mkdtemp
from typing import Any

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from moj_discovery.clock import ClockMapper
from moj_discovery.clock_vectors import derive_clock_mapping, validate_stored_mapping
from moj_discovery.coherence import CoherenceController
from moj_discovery.errors import ContractNotImplementedError

# Frozen local execution map. Empty handlers lack runtime adapters/fixtures.
_GROUPS = [
    ("RAW_SAMPLE", "raw", "golden_mapping", "CLOCK-GOLDEN-FOUR-TIMESTAMP-01"),
    ("RAW_SAMPLE", "raw", "mapping_negative_vectors", """
MAP-NEG-01-TARGET-ORDER MAP-NEG-02-SOURCE-ORDER MAP-NEG-03-NEGATIVE-RTT
MAP-NEG-04-WRONG-SOURCE-DOMAIN MAP-NEG-05-WRONG-TARGET-DOMAIN MAP-NEG-06-WRONG-BOOT
MAP-NEG-07-WRONG-UNIT MAP-NEG-08-WRONG-OWNER MAP-NEG-12-TOO-FEW-SAMPLES
MAP-NEG-13-SEGMENT-TOO-OLD MAP-NEG-14-WALL-STEP
MAP-NEG-15-NONINTERSECTING-TARGET-INTERVALS MAP-NEG-16-UNMAPPED-CDP"""),
    ("SERIALIZED_MAPPING_VALIDATION", "stored", "mapping_negative_vectors", """
MAP-NEG-09-INVERTED-INTERVAL MAP-NEG-10-RTT-EXCEEDED MAP-NEG-11-UNCERTAINTY-EXCEEDED"""),
    ("SERIALIZED_MAPPING_VALIDATION", "", "canonical_hash_positive_vector",
     "CLOCK-HASH-POS-01-BROWSER-OBSERVATION"),
    ("SERIALIZED_MAPPING_VALIDATION", "", "canonical_hash_negative_vector",
     "CLOCK-HASH-NEG-01-MISSING-CONTENT-HASH"),
    ("RAW_SAMPLE", "", "drift_vectors", """
DRIFT-01-AT-ANCHOR DRIFT-02-ONE-SECOND DRIFT-03-CEILING DRIFT-04-ABSOLUTE-BEFORE-ANCHOR"""),
    ("SERIALIZED_MAPPING_VALIDATION", "", "midpoint_constraint_vectors", """
MIDPOINT-POS-GOLDEN MIDPOINT-NEG-WRONG-VALUE MIDPOINT-POS-MAX-BOUNDARY MIDPOINT-NEG-OVERFLOW"""),
    ("LIFECYCLE_AND_COHERENCE", "select_stub", "mapping_selection_vectors", """
SELECT-01-NARROWEST SELECT-02-LATEST-VALIDITY-START SELECT-03-LEXICOGRAPHIC-ID"""),
    ("LIFECYCLE_AND_COHERENCE", "", "closure_vectors", """
CLOSE-01-DOMAIN-BOOT CLOSE-02-MONOTONIC CLOSE-03-WALL CLOSE-04-SLEEP CLOSE-05-DURATION
CLOSE-06-RTT CLOSE-07-UNCERTAINTY CLOSE-08-INCONSISTENT CLOSE-09-LIFECYCLE CLOSE-10-RUN
CLOSE-NEG-USE-AFTER-CLOSE"""),
    ("LIFECYCLE_AND_COHERENCE", "release_stub", "release_positive_vector", "RELEASE-POS-01"),
    ("LIFECYCLE_AND_COHERENCE", "release_stub", "release_negative_vectors", """
RELEASE-NEG-01-PREDECESSOR-NOT-CLOSED RELEASE-NEG-02-NOT-OBSERVED RELEASE-NEG-03-UNKNOWN
RELEASE-NEG-04-UNSIGNED-CAPABILITY RELEASE-NEG-05-FOOTBALL-STALE
RELEASE-NEG-06-OPERATOR-UNKNOWN RELEASE-NEG-07-BOOK-INCOMPLETE
RELEASE-NEG-08-NOT-STRICTLY-POST-SHOCK RELEASE-NEG-09-MAPPING-CLOSED
RELEASE-NEG-10-IDENTITY-MISMATCH RELEASE-NEG-11-CURSOR-GAP RELEASE-NEG-12-BLOCKING-GAP
RELEASE-NEG-13-STATE-DISAGREEMENT RELEASE-NEG-14-LATER-SHOCK RELEASE-NEG-15-REOPEN-PREDECESSOR
RELEASE-NEG-16-NO-CANDIDATE RELEASE-NEG-17-SAME-EPOCH
RELEASE-NEG-18-NON-GENESIS-PREDECESSOR-NOT-CLOSED RELEASE-NEG-19-UNBOUND-PROOF"""),
    ("LIFECYCLE_AND_COHERENCE", "", "candidate_acceptance_negative_vectors", """
CANDIDATE-NEG-01-JSON-UNKNOWN CANDIDATE-NEG-02-SQL-UNKNOWN CANDIDATE-NEG-03-NOT-OBSERVED
CANDIDATE-NEG-04-UNSIGNED-UNVERIFIED"""),
]
DISPATCH = {case_id: (family, handler, section)
            for family, handler, section, ids in _GROUPS for case_id in ids.split()}
_HANDLER_REFS = {
    "raw": ["moj_discovery.clock_vectors.derive_clock_mapping", "deriveClockMapping"],
    "stored": ["moj_discovery.clock_vectors.validate_stored_mapping", "validateStoredMapping"],
    "select_stub": ["moj_discovery.clock.ClockMapper.select"],
    "release_stub": ["moj_discovery.coherence.CoherenceController.evaluate_release"], "": [],
}
_VECTOR_PATH = "docs/vectors/inherited/clock-coherence-v6.2.json"
_COVERAGE_PATH = "docs/registries/clock-vector-coverage.v1.json"
_NODE = r'''
const { pathToFileURL } = require("node:url");
(async () => {
  const module = await import(pathToFileURL(process.argv[2]).href);
  const c = JSON.parse(process.argv[1]);
  const value = c.handler === "stored"
    ? module.validateStoredMapping(c.stored, c.raw, c.guardrails)
    : module.deriveClockMapping(c.raw, c.guardrails);
  process.stdout.write(JSON.stringify(value, (_, v) => typeof v === "bigint"
    ? (v >= BigInt(Number.MIN_SAFE_INTEGER) && v <= BigInt(Number.MAX_SAFE_INTEGER)
       ? Number(v) : v.toString()) : v));
})().catch(error => { console.error(String(error)); process.exit(1); });
'''


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _source_age(actual: dict[str, Any]) -> dict[str, Any]:
    if actual.get("error") == "SOURCE_AGE_UNKNOWN":
        actual["source_age"] = "UNKNOWN"
    return actual


def _python(case: dict[str, Any]) -> dict[str, Any]:
    actual = (validate_stored_mapping(case["stored"], case["raw"], case["guardrails"])
              if case["handler"] == "stored"
              else derive_clock_mapping(case["raw"], case["guardrails"]))
    return _source_age(dict(actual))


def _typescript(case: dict[str, Any], runtime: Path) -> dict[str, Any]:
    # Expected fields and IDs never cross the evaluator boundary.
    payload = {key: case[key] for key in ("handler", "raw", "stored", "guardrails")}
    module = runtime / "extension/.test-build/src/contracts/clock-vectors.js"
    node = which("node")
    if not node or not module.is_file():
        raise FileNotFoundError("E_CLOCK_TYPESCRIPT_PREREQUISITE:compile tsconfig.test.json")
    completed = run(  # noqa: S603 -- fixed JS bridge; data passed as JSON, no shell
        [node, "-e", _NODE, json.dumps(payload), str(module)],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return _source_age(json.loads(completed.stdout))


def _numeric_oracle(raw: dict[str, Any]) -> dict[str, Any]:
    """Independent exact interval oracle; never calls either implementation."""
    if raw["t3"] < raw["t2"] or raw["t4"] < raw["t1"]:
        left = right = padding = rtt = lower = upper = 0
    else:
        left, right = raw["t3"] - raw["t4"], raw["t2"] - raw["t1"]
        rtt = right - left
        padding = raw["source"]["resolution_us"] + raw["target"]["resolution_us"]
        lower, upper = left - padding, right + padding
    center = Fraction(lower + upper, 2)
    midpoint = center.numerator // center.denominator
    return {"raw_lower_us": left, "raw_upper_us": right, "network_rtt_us": rtt,
            "padding_us": padding, "offset_interval_us": [lower, upper],
            "offset_midpoint_us": midpoint,
            "base_uncertainty_us": max(midpoint - lower, upper - midpoint)}


def _case(entry: dict[str, Any], vectors: dict[str, Any]) -> dict[str, Any]:
    case_id = entry["vector_id"]
    family, handler, section = DISPATCH[case_id]
    source = vectors[section]
    matches = [v for v in (source if isinstance(source, list) else [source])
               if v.get("id") == case_id]
    if entry["section"] != section or len(matches) != 1:
        raise ValueError("E_CLOCK_COVERAGE:SOURCE")
    vector = copy.deepcopy(matches[0])
    expected = {k: v for k, v in vector.items() if k.startswith("expected") or k in {
        "mapping_eligible", "coherence_eligible", "permanent", "reopen_attempt_error",
    }}
    case = {"case_id": case_id, "family": family, "handler": handler, "section": section,
            "input": {k: v for k, v in vector.items() if k not in expected and k != "id"},
            "expected": expected, "evaluator_refs": _HANDLER_REFS[handler]}
    if handler not in {"raw", "stored"}:
        return case
    golden = vectors["golden_mapping"]
    raw = copy.deepcopy({k: v for k, v in golden.items() if k not in {"id", "expected"}})
    mutation = vector.get("mutation", {})
    stored = mutation if handler == "stored" else {}
    if handler == "raw":
        raw.update(mutation)
        if "source_owner" in raw:
            raw["source"]["owner"] = raw.pop("source_owner")
    expected = {**_numeric_oracle(raw), "accepted": vector.get("mapping_eligible", True),
                "error": vector.get("expected_error", "ACCEPT")}
    if "expected_source_age" in vector:
        expected.update(error=vector.get("expected_error", "SOURCE_AGE_UNKNOWN"),
                        source_age=vector["expected_source_age"])
    # Golden frozen fields are an additional oracle, not input to either evaluator.
    if section == "golden_mapping":
        case["oracle_conflict"] = _diff(
            {**vector["expected"], "error": "ACCEPT"}, expected,
        )
        expected.update(vector["expected"])
    case.update(raw=raw, stored=stored, guardrails=vectors["guardrails"], expected=expected)
    case["input"] = {k: case[k] for k in ("raw", "stored", "guardrails")}
    return case


def _diff(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {key: {"expected": expected.get(key), "actual": actual.get(key)}
            for key in sorted(actual.keys() | expected.keys())
            if key not in actual or key not in expected
            or _bytes(actual[key]) != _bytes(expected[key])}


def _record(case: dict[str, Any], actual: dict[str, Any], directory: Path,
            context: dict[str, Any], **fields: Any) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "actual.json"
    with artifact.open("xb") as stream:
        stream.write(_bytes(actual))
    return {**context, "case_id": case["case_id"], "family": case["family"],
            "source_section": case["section"], "evaluator_refs": case["evaluator_refs"],
            "input": case["input"], "expected": case["expected"],
            "input_sha256": _hash(case["input"]), "expected_sha256": _hash(case["expected"]),
            "actual": actual, "actual_artifact": {"path": str(artifact.resolve()),
                                                   "sha256": _hash(actual)}, **fields}


def _execute(case: dict[str, Any], runtime: Path, directory: Path,
             context: dict[str, Any], *, corrupt_both: bool = False) -> dict[str, Any]:
    actual: dict[str, Any] = {}
    status, error, executed = "NOT_IMPLEMENTED", "E_CLOCK_NO_EXECUTABLE_ADAPTER", False
    drift: bool | None = None
    comparison: dict[str, Any] = {"matched": False, "diff": {}}
    exits: dict[str, Any] = {"python": None, "typescript": None}
    try:
        if case["handler"] == "select_stub":
            ClockMapper().select(case["input"])
        elif case["handler"] == "release_stub":
            CoherenceController().evaluate_release(case["input"])
        elif case["handler"] in {"raw", "stored"}:
            actual["python"] = _python(case)
            exits["python"] = 0
            actual["typescript"] = _typescript(case, runtime)
            exits["typescript"] = 0
            if corrupt_both:
                for language in ("python", "typescript"):
                    actual[language]["network_rtt_us"] = 0
            diffs = {language: _diff(value, case["expected"])
                     for language, value in actual.items()}
            if case.get("oracle_conflict"):
                diffs["independent_arithmetic"] = case["oracle_conflict"]
            drift = _bytes(actual["python"]) != _bytes(actual["typescript"])
            comparison = {"matched": not any(diffs.values()), "diff": diffs}
            status = "PASS" if comparison["matched"] and not drift else "FAIL"
            error, executed = actual["python"]["error"], True
    except ContractNotImplementedError as exc:
        error = str(exc)
    except (FileNotFoundError, TimeoutExpired) as exc:
        status, error = "BLOCKED_ENVIRONMENT", str(exc)
    except CalledProcessError as exc:
        exits["typescript"] = exc.returncode
        status, error = "FAIL", str(exc.stderr)
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        status, error = "FAIL", str(exc)
    actual["execution_error"] = error if not executed else None
    return _record(case, actual, directory, context, status=status, executed=executed,
                   observed_error=error, comparison=comparison, cross_language_drift=drift,
                   command_exit=exits, execution_kind="OFFLINE_SHARED_CLOCK_EVALUATOR")


def verify_record(row: dict[str, Any]) -> bool:
    try:
        artifact = row["actual_artifact"]
        digest = hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest()
        return bool(digest == artifact["sha256"]
                and artifact["sha256"] == _hash(row["actual"])
                and row["input_sha256"] == _hash(row["input"])
                and row["expected_sha256"] == _hash(row["expected"])
                and all(verify_record(row["actual"][key]) for key in ("control", "trial")
                        if key in row["actual"]))
    except (OSError, KeyError, TypeError, ValueError):
        return False


def summarize(required_ids: list[str], records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["case_id"] for row in records)
    exact = len(required_ids) == len(set(required_ids)) and counts == Counter(required_ids)
    valid = [row for row in records if verify_record(row)]
    passed = [row for row in valid if row["status"] == "PASS" and row["executed"]
              and row["comparison"]["matched"] and row["cross_language_drift"] is False
              and all(not _diff(row["actual"][lang], row["expected"])
                      for lang in ("python", "typescript"))]
    failures = (not exact or len(valid) != len(records)
                or any(row["status"] == "FAIL" for row in records)
                or sum(row["status"] == "PASS" for row in records) != len(passed))
    status = "FAIL" if failures else "PASS" if len(passed) == len(required_ids) else "HOLD"
    return {"result": status,
            "covered_vector_count": len({row["case_id"] for row in passed}),
            "executed_vector_count": sum(row["executed"] for row in valid),
            "skipped_vectors": sum(not row["executed"] for row in records),
            "cross_language_drift": sum(row["cross_language_drift"] is True for row in valid),
            "required_id_set_complete": exact}


def _mutations(cases: list[dict[str, Any]], runtime: Path, directory: Path,
               context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    golden = next(c for c in cases if c["section"] == "golden_mapping")
    negative = next(c for c in cases if c["case_id"] == "MAP-NEG-01-TARGET-ORDER")
    for name in ("wrong_expected_error", "inverse_eligibility", "raw_timestamp",
                 "missing_result", "duplicate_result", "same_wrong_result"):
        workspace = Path(mkdtemp(prefix=name + "-", dir=directory))
        original = negative if name in {"wrong_expected_error", "inverse_eligibility"} else golden
        control = _execute(copy.deepcopy(original), runtime, workspace / "control", context)
        case = copy.deepcopy(original)
        if name == "wrong_expected_error":
            case["expected"]["error"] = "E_MUTATED_EXPECTATION"
        elif name == "inverse_eligibility":
            case["expected"]["accepted"] = not case["expected"]["accepted"]
        elif name == "raw_timestamp":
            case["raw"]["t4"] += 1
        trial = _execute(case, runtime, workspace / "trial", context,
                         corrupt_both=name == "same_wrong_result")
        observed = [trial]
        if name == "missing_result":
            observed = []
        elif name == "duplicate_result":
            observed.append(copy.deepcopy(trial))
        result = summarize([case["case_id"]], observed)
        executed = control["status"] == "PASS" and trial["executed"]
        mutation = {**case, "case_id": name,
                    "input": {"case_input": case["input"], "mutation": name},
                    "expected": {"result": "FAIL", "control": "PASS"}}
        row = _record(mutation, {"control": control, "trial": trial,
                                "observed_case_ids": [r["case_id"] for r in observed],
                                "summary": result}, workspace / "mutation", context,
                      executed=executed, detected=executed and result["result"] == "FAIL",
                      status="EXECUTED" if executed else "NOT_EXECUTED",
                      workspace=str(workspace), execution_kind="QUALIFICATION_MUTATION")
        rows.append(row)
    return rows


def run_clock_vector_qualification(
    pack: Path, runtime: Path, *, evidence_dir: Path | None = None,
) -> dict[str, Any]:
    vectors = json.loads((pack / _VECTOR_PATH).read_text())
    coverage = json.loads((pack / _COVERAGE_PATH).read_text())
    entries = coverage["entries"]
    ids = [entry["vector_id"] for entry in entries]
    if (coverage["schema_version"] != "clock-vector-coverage/v1"
            or len(ids) != coverage["total_named_vectors"] or len(ids) != len(set(ids))
            or set(ids) != set(DISPATCH)):
        raise ValueError("E_CLOCK_COVERAGE")
    cases = [_case(entry, vectors) for entry in entries]
    evidence = evidence_dir or Path(mkdtemp(prefix="clock-qualification-"))
    evidence.mkdir(parents=True, exist_ok=True)
    git = which("git")
    if not git:
        raise FileNotFoundError("E_CLOCK_GIT_PREREQUISITE")
    revision = run(  # noqa: S603 -- read-only fixed argv
        [git, "rev-parse", "HEAD"], cwd=RUNTIME_ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout.strip()
    files = [Path(__file__), RUNTIME_ROOT / "src/moj_discovery/clock_vectors.py",
             RUNTIME_ROOT / "src/moj_discovery/clock.py",
             RUNTIME_ROOT / "src/moj_discovery/coherence.py",
             runtime / "extension/src/contracts/clock-vectors.ts",
             runtime / "extension/.test-build/src/contracts/clock-vectors.js",
             pack / _VECTOR_PATH, pack / _COVERAGE_PATH]
    context = {"environment": {"python": platform.python_version(),
                               "platform": platform.platform(), "node": which("node")},
               "code": {"revision": revision, "sha256": {
                   str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in files if p.is_file()}},
               "registry_version": coverage["schema_version"]}
    records = [_execute(case, runtime, evidence / case["case_id"], context) for case in cases]
    mutations = _mutations(cases, runtime, evidence, context)
    summary = summarize(ids, records)
    executed_mutations = [r for r in mutations if r["executed"] and verify_record(r)]
    survivors = sum(not row["detected"] for row in executed_mutations)
    if survivors or len(executed_mutations) != len(mutations):
        summary["result"] = "FAIL" if survivors or summary["result"] == "FAIL" else "HOLD"
    report = {**summary, "registry_version": coverage["schema_version"],
              "registry_source_sha256": coverage["source_sha256"],
              "required_vector_ids": ids, "records": records, "mutation_records": mutations,
              "mutation_executions": len(executed_mutations), "mutation_survivors": survivors,
              "evidence_directory": str(evidence.resolve())}
    with (evidence / "qualification.json").open("xb") as stream:
        stream.write(_bytes(report))
    return report
