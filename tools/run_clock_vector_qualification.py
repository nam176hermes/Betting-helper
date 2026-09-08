"""Artifact-backed clock qualification. Inventory and stub calls are not coverage."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import sqlite3
import sys
from collections import Counter
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path
from shutil import which
from subprocess import CalledProcessError, TimeoutExpired, run
from tempfile import mkdtemp
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.retained_artifact_io import RetainedArtifactIO

from jsonschema import ValidationError  # type: ignore[import-untyped]

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from moj_discovery.clock import ClockMapper
from moj_discovery.clock_vectors import (
    compute_drift,
    derive_clock_mapping,
    validate_midpoint,
    validate_stored_mapping,
    verify_clock_observation,
)
from moj_discovery.coherence import CoherenceController
from moj_discovery.schema_registry import validate_artifact

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
    ("SERIALIZED_MAPPING_VALIDATION", "verify_clock_observation", "canonical_hash_positive_vector",
     "CLOCK-HASH-POS-01-BROWSER-OBSERVATION"),
    ("SERIALIZED_MAPPING_VALIDATION", "verify_clock_observation", "canonical_hash_negative_vector",
     "CLOCK-HASH-NEG-01-MISSING-CONTENT-HASH"),
    ("RAW_SAMPLE", "compute_drift", "drift_vectors", """
DRIFT-01-AT-ANCHOR DRIFT-02-ONE-SECOND DRIFT-03-CEILING DRIFT-04-ABSOLUTE-BEFORE-ANCHOR"""),
    ("SERIALIZED_MAPPING_VALIDATION", "validate_midpoint", "midpoint_constraint_vectors", """
MIDPOINT-POS-GOLDEN MIDPOINT-NEG-WRONG-VALUE MIDPOINT-POS-MAX-BOUNDARY MIDPOINT-NEG-OVERFLOW"""),
    ("LIFECYCLE_AND_COHERENCE", "select_mapping", "mapping_selection_vectors", """
SELECT-01-NARROWEST SELECT-02-LATEST-VALIDITY-START SELECT-03-LEXICOGRAPHIC-ID"""),
    ("LIFECYCLE_AND_COHERENCE", "close_mapping", "closure_vectors", """
CLOSE-01-DOMAIN-BOOT CLOSE-02-MONOTONIC CLOSE-03-WALL CLOSE-04-SLEEP CLOSE-05-DURATION
CLOSE-06-RTT CLOSE-07-UNCERTAINTY CLOSE-08-INCONSISTENT CLOSE-09-LIFECYCLE CLOSE-10-RUN
CLOSE-NEG-USE-AFTER-CLOSE"""),
    ("LIFECYCLE_AND_COHERENCE", "evaluate_release", "release_positive_vector", "RELEASE-POS-01"),
    ("LIFECYCLE_AND_COHERENCE", "evaluate_release", "release_negative_vectors", """
RELEASE-NEG-01-PREDECESSOR-NOT-CLOSED RELEASE-NEG-02-NOT-OBSERVED RELEASE-NEG-03-UNKNOWN
RELEASE-NEG-04-UNSIGNED-CAPABILITY RELEASE-NEG-05-FOOTBALL-STALE
RELEASE-NEG-06-OPERATOR-UNKNOWN RELEASE-NEG-07-BOOK-INCOMPLETE
RELEASE-NEG-08-NOT-STRICTLY-POST-SHOCK RELEASE-NEG-09-MAPPING-CLOSED
RELEASE-NEG-10-IDENTITY-MISMATCH RELEASE-NEG-11-CURSOR-GAP RELEASE-NEG-12-BLOCKING-GAP
RELEASE-NEG-13-STATE-DISAGREEMENT RELEASE-NEG-14-LATER-SHOCK RELEASE-NEG-15-REOPEN-PREDECESSOR
RELEASE-NEG-16-NO-CANDIDATE RELEASE-NEG-17-SAME-EPOCH
RELEASE-NEG-18-NON-GENESIS-PREDECESSOR-NOT-CLOSED RELEASE-NEG-19-UNBOUND-PROOF"""),
    ("LIFECYCLE_AND_COHERENCE", "accept_candidate", "candidate_acceptance_negative_vectors", """
CANDIDATE-NEG-01-JSON-UNKNOWN CANDIDATE-NEG-02-SQL-UNKNOWN CANDIDATE-NEG-03-NOT-OBSERVED
CANDIDATE-NEG-04-UNSIGNED-UNVERIFIED"""),
]
DISPATCH = {case_id: (family, handler, section)
            for family, handler, section, ids in _GROUPS for case_id in ids.split()}
_HANDLER_REFS = {
    "raw": ["moj_discovery.clock_vectors.derive_clock_mapping", "deriveClockMapping"],
    "stored": ["moj_discovery.clock_vectors.validate_stored_mapping", "validateStoredMapping"],
    "verify_clock_observation": [
        "moj_discovery.clock_vectors.verify_clock_observation", "verifyClockObservation",
    ],
    "compute_drift": ["moj_discovery.clock_vectors.compute_drift", "computeDrift"],
    "validate_midpoint": [
        "moj_discovery.clock_vectors.validate_midpoint", "validateMidpoint",
        "vendor/hybrid-discovery-v6.3.6/sql/discovery-store-v1.sql",
    ],
    "select_mapping": ["moj_discovery.clock.ClockMapper.select", "selectClockMapping"],
    "close_mapping": [
        "moj_discovery.clock.ClockMapper.close", "moj_discovery.clock.ClockMapper.reopen",
        "closeClockMapping", "reopenClockMapping",
    ],
    "accept_candidate": ["moj_discovery.coherence.CoherenceController.accept_candidate",
                         "acceptCandidate"],
    "evaluate_release": ["moj_discovery.coherence.CoherenceController.evaluate_release",
                         "evaluateRelease"],
}
_VECTOR_PATH = "docs/vectors/inherited/clock-coherence-v6.2.json"
_COVERAGE_PATH = "docs/registries/clock-vector-coverage.v1.json"
_MUTATION_NAMES = (
    "wrong_expected_error", "inverse_eligibility", "raw_timestamp",
    "missing_result", "duplicate_result", "same_wrong_result",
    "hash_field_removal", "drift_input_change", "midpoint_corruption",
    "selection_candidate_order", "post_close_selection",
    "candidate_proof_corruption", "release_mapping_close",
)
_TYPESCRIPT_MODULES = (
    "contracts/clock-vectors.js", "contracts/clock-coherence.js",
    "canonical.js", "schema-registry.js", "errors.js",
)
_NODE = r'''
const { pathToFileURL } = require("node:url");
const { readFileSync, readdirSync } = require("node:fs");
(async () => {
  const module = await import(pathToFileURL(process.argv[2]).href);
  const coherence = await import(pathToFileURL(process.argv[5]).href);
  const c = JSON.parse(process.argv[1], (_key, value) =>
    value && typeof value === "object" && Object.keys(value).length === 1 && "$bigint" in value
      ? BigInt(value.$bigint) : value);
  let value;
  if (c.handler === "stored") value = module.validateStoredMapping(c.stored, c.raw, c.guardrails);
  else if (c.handler === "raw") value = module.deriveClockMapping(c.raw, c.guardrails);
  else if (c.handler === "compute_drift") value = {
    accepted: true, error: "ACCEPT",
    drift_us: module.computeDrift(c.input.relative_drift_ppm, c.input.source_anchor_us, c.input.x),
  };
  else if (c.handler === "validate_midpoint") value = module.validateMidpoint(c.input);
  else if (c.handler === "select_mapping") {
    const selected = module.selectClockMapping(c.input.candidates);
    value = { accepted: true, error: "ACCEPT", mapping_id: selected.mapping_id };
  } else if (c.handler === "close_mapping") {
    const createdHistory = module.closeClockMapping(c.input.mapping_id, c.input.reason);
    const history = c.mutate_closed_state
      ? createdHistory.map(closure => ({
          ...closure, mapping_id: `${closure.mapping_id}-MUTATED`,
        }))
      : createdHistory;
    const closure = history.at(-1);
    if (c.input.attempt === "SELECT_CLOSED_MAPPING_FOR_LATER_OBSERVATION") {
      try {
        const selected = module.selectClockMapping(c.input.candidates, history);
        value = {
          accepted: true, error: "ACCEPT", mapping_id: selected.mapping_id,
          reason: c.input.reason, permanent: closure?.permanent ?? false,
          reopen_permitted: closure?.reopen_permitted ?? true, history_size: history.length,
          coherence_eligible: true, closure_executed: true, history,
        };
      } catch (error) {
        value = {
          accepted: false, error: error instanceof Error ? error.message : String(error),
          mapping_id: c.input.mapping_id, reason: closure.reason, permanent: closure.permanent,
          reopen_permitted: closure.reopen_permitted, history_size: history.length,
          coherence_eligible: false, closure_executed: true, history,
        };
      }
    } else {
      let reopenError = "";
      try { module.reopenClockMapping(c.input.mapping_id, history); }
      catch (error) { reopenError = error instanceof Error ? error.message : String(error); }
      value = {
        accepted: true, error: "ACCEPT", mapping_id: closure.mapping_id,
        reason: closure.reason, permanent: closure.permanent,
        reopen_permitted: closure.reopen_permitted, history_size: history.length,
        reopen_error: reopenError, closure_executed: true, history,
      };
    }
  }
  else if (c.handler === "accept_candidate" || c.handler === "evaluate_release") {
    let input = c.input;
    let closureEvidence;
    if (c.handler === "evaluate_release" && c.release_mapping_close_bound !== null) {
      const mappingId = c.release_mapping_close_bound
        ? c.input.proof_bound_mapping_ids[0] : `MAP:${"f".repeat(64)}`;
      const history = module.closeClockMapping(mappingId, "SLEEP_RESUME");
      const valid = c.bypass_release_mapping_guard || !history.some(item =>
        c.input.proof_bound_mapping_ids.includes(item.mapping_id));
      input = { ...c.input, proof_bound_mappings_open_unclosed_valid_at_release: valid };
      closureEvidence = { mapping_close_executed: true, closed_mapping_id: mappingId, history };
    }
    value = c.handler === "accept_candidate"
      ? coherence.acceptCandidate(input) : coherence.evaluateRelease(input);
    if (closureEvidence) value.__operation_metadata = closureEvidence;
    if (c.input.schema_record) {
      const schemas = readdirSync(process.argv[3]).filter(name => name.endsWith(".json"))
        .map(name => JSON.parse(readFileSync(process.argv[3] + "/" + name, "utf8")));
      value.schema_valid = coherence.validateCoherenceArtifact(c.input.schema_record, schemas);
      value.schema_error = value.schema_valid ? null :
        (c.handler === "accept_candidate" ? "REJECT_SCHEMA" : "REJECT_RELEASE_TRANSITION");
    }
  }
  else if (c.handler === "verify_clock_observation") {
    const schemas = readdirSync(process.argv[3]).filter(name => name.endsWith(".json"))
      .map(name => JSON.parse(readFileSync(process.argv[3] + "/" + name, "utf8")));
    const registry = JSON.parse(readFileSync(process.argv[4], "utf8"));
    value = await module.verifyClockObservation(
      c.input.artifact_type, c.input.record, schemas, registry);
  } else throw new Error("E_CLOCK_NO_EXECUTABLE_ADAPTER");
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


def _python(
    case: dict[str, Any], *, mutate_closed_state: bool = False,
    release_mapping_close_bound: bool | None = None,
    bypass_release_mapping_guard: bool = False,
) -> dict[str, Any]:
    handler = case["handler"]
    actual: dict[str, Any]
    if handler == "stored":
        actual = dict(validate_stored_mapping(
            case["stored"], case["raw"], case["guardrails"],
        ))
    elif handler == "raw":
        actual = dict(derive_clock_mapping(case["raw"], case["guardrails"]))
    elif handler == "verify_clock_observation":
        actual = dict(verify_clock_observation(
            case["input"]["artifact_type"], case["input"]["record"],
            vendor=RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6",
        ))
    elif handler == "compute_drift":
        actual = {"accepted": True, "error": "ACCEPT", "drift_us": compute_drift(
            case["input"]["relative_drift_ppm"], case["input"]["source_anchor_us"],
            case["input"]["x"],
        )}
    elif handler == "validate_midpoint":
        actual = dict(validate_midpoint(case["input"]))
    elif handler == "select_mapping":
        selected = ClockMapper().select(case["input"]["candidates"])
        actual = {"accepted": True, "error": "ACCEPT", "mapping_id": selected["mapping_id"]}
    elif handler == "close_mapping":
        mapper = ClockMapper()
        created_history = mapper.close(
            case["input"]["mapping_id"], case["input"]["reason"],
        )
        history = (
            tuple(replace(closure, mapping_id=f"{closure.mapping_id}-MUTATED")
                  for closure in created_history)
            if mutate_closed_state else created_history
        )
        closure = history[-1]
        serialized_history = [asdict(item) for item in history]
        if case["input"].get("attempt") == "SELECT_CLOSED_MAPPING_FOR_LATER_OBSERVATION":
            try:
                selected = mapper.select(case["input"]["candidates"], history)
                actual = {
                    "accepted": True, "error": "ACCEPT", "mapping_id": selected["mapping_id"],
                    "reason": case["input"]["reason"],
                    "permanent": closure.permanent,
                    "reopen_permitted": closure.reopen_permitted,
                    "history_size": len(history), "coherence_eligible": True,
                    "closure_executed": True, "history": serialized_history,
                }
            except ValueError as exc:
                actual = {
                    "accepted": False, "error": str(exc), "mapping_id": closure.mapping_id,
                    "reason": closure.reason, "permanent": closure.permanent,
                    "reopen_permitted": closure.reopen_permitted,
                    "history_size": len(history), "coherence_eligible": False,
                    "closure_executed": True, "history": serialized_history,
                }
        else:
            try:
                mapper.reopen(case["input"]["mapping_id"], history)
            except ValueError as exc:
                reopen_error = str(exc)
            actual = {
                "accepted": True, "error": "ACCEPT", "mapping_id": closure.mapping_id,
                "reason": closure.reason, "permanent": closure.permanent,
                "reopen_permitted": closure.reopen_permitted,
                "history_size": len(history), "reopen_error": reopen_error,
                "closure_executed": True, "history": serialized_history,
            }
    elif handler == "accept_candidate":
        actual = CoherenceController().accept_candidate(case["input"])
    elif handler == "evaluate_release":
        release_input = case["input"]
        if release_mapping_close_bound is not None:
            mapping_id = (
                release_input["proof_bound_mapping_ids"][0]
                if release_mapping_close_bound else "MAP:" + "f" * 64
            )
            history = ClockMapper().close(str(mapping_id), "SLEEP_RESUME")
            release_input = {
                **release_input,
                "proof_bound_mappings_open_unclosed_valid_at_release": (
                    bypass_release_mapping_guard or not any(
                        closure.mapping_id in case["input"]["proof_bound_mapping_ids"]
                        for closure in history
                    )
                ),
            }
            actual = CoherenceController().evaluate_release(release_input)
            actual["__operation_metadata"] = {
                "mapping_close_executed": True, "closed_mapping_id": mapping_id,
                "history": [asdict(item) for item in history],
            }
        else:
            actual = CoherenceController().evaluate_release(release_input)
    else:
        raise ValueError("E_CLOCK_NO_EXECUTABLE_ADAPTER")
    if handler in {"accept_candidate", "evaluate_release"} and "schema_record" in case["input"]:
        try:
            validate_artifact(
                case["input"]["schema_record"], "clock-coherence-records.schema.json",
                bootstrap_only=True, vendor=RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6",
            )
        except ValidationError:
            actual.update(
                schema_valid=False,
                schema_error=(
                    "REJECT_SCHEMA" if handler == "accept_candidate"
                    else "REJECT_RELEASE_TRANSITION"
                ),
            )
        else:
            actual.update(schema_valid=True, schema_error=None)
    return _source_age(dict(actual))


def _typescript(
    case: dict[str, Any], runtime: Path, *, mutate_closed_state: bool = False,
    release_mapping_close_bound: bool | None = None,
    bypass_release_mapping_guard: bool = False,
    executable_artifacts: dict[str, dict[str, str]],
) -> dict[str, Any]:
    # Expected fields and IDs never cross the evaluator boundary.
    payload = {
        "handler": case["handler"], "input": case["input"],
        "mutate_closed_state": mutate_closed_state,
        "release_mapping_close_bound": release_mapping_close_bound,
        "bypass_release_mapping_guard": bypass_release_mapping_guard,
    }
    if case["handler"] in {"raw", "stored"}:
        payload.update({key: case[key] for key in ("raw", "stored", "guardrails")})
    module = runtime / "extension/.test-build/src/contracts/clock-vectors.js"
    node = which("node")
    if not node or not module.is_file():
        raise FileNotFoundError("E_CLOCK_TYPESCRIPT_PREREQUISITE:compile tsconfig.test.json")
    before = _verify_typescript_executable(runtime, executable_artifacts)
    completed = run(  # noqa: S603 -- fixed JS bridge; data passed as JSON, no shell
        [node, "-e", _NODE, json.dumps(_json_for_node(payload)), str(module),
         str(runtime / "vendor/hybrid-discovery-v6.3.6/schemas"),
         str(runtime / "vendor/hybrid-discovery-v6.3.6/registries/canonical-hash-domains.v1.json"),
         str(runtime / "extension/.test-build/src/contracts/clock-coherence.js")],
        capture_output=True, text=True, check=True, timeout=15,
    )
    after = _verify_typescript_executable(runtime, executable_artifacts)
    if before != after:
        raise RuntimeError("E_CLOCK_TYPESCRIPT_EXECUTABLE_CHANGED")
    actual = _source_age(json.loads(completed.stdout))
    actual["__typescript_execution_binding"] = {"before": before, "after": after}
    return actual


def _verify_typescript_executable(
    runtime: Path, artifacts: dict[str, dict[str, str]],
) -> dict[str, str]:
    if set(artifacts) != set(_TYPESCRIPT_MODULES):
        raise ValueError("E_CLOCK_TYPESCRIPT_EXECUTABLE_GRAPH")
    observed: dict[str, str] = {}
    for relative, reference in artifacts.items():
        generated = runtime / "extension/.test-build/src" / relative
        retained = Path(reference["path"])
        if not generated.is_file() or not retained.is_file():
            raise FileNotFoundError("E_CLOCK_TYPESCRIPT_EXECUTABLE_MODULE:" + relative)
        generated_hash = hashlib.sha256(generated.read_bytes()).hexdigest()
        retained_hash = hashlib.sha256(retained.read_bytes()).hexdigest()
        if generated_hash != retained_hash or retained_hash != reference["sha256"]:
            raise ValueError("E_CLOCK_TYPESCRIPT_EXECUTABLE_MISMATCH:" + relative)
        observed[relative] = generated_hash
    return observed


def _retain_typescript_executable(
    runtime: Path, evidence: Path,
) -> dict[str, dict[str, str]]:
    artifacts: dict[str, dict[str, str]] = {}
    for relative in _TYPESCRIPT_MODULES:
        source = runtime / "extension/.test-build/src" / relative
        if not source.is_file():
            raise FileNotFoundError("E_CLOCK_TYPESCRIPT_PREREQUISITE:compile tsconfig.test.json")
        target = evidence / "typescript-executable" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        with target.open("xb") as stream:
            stream.write(content)
        artifacts[relative] = {
            "path": str(target.resolve()),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    return artifacts


def _json_for_node(value: object) -> object:
    if type(value) is int and not -(2**53 - 1) <= value <= 2**53 - 1:
        return {"$bigint": str(value)}
    if isinstance(value, dict):
        return {key: _json_for_node(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_for_node(item) for item in value]
    return value


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


def _transition_schema_record(value: dict[str, Any], *, release: bool) -> dict[str, Any]:
    def artifact(prefix: str, digit: str) -> str:
        return f"{prefix}:{digit * 64}"

    return {
        "record_type": "CoherenceTransition", "schema_version": "1",
        "content_hash": "0" * 64,
        "coherence_transition_id": artifact("TRANSITION", "1"),
        "fixture_id": artifact("FIXTURE", "2"),
        "from_state": "NEW_EPOCH_PENDING" if release else "WAITING_FOR_RESNAPSHOT",
        "to_state": "NEW_EPOCH_OPEN" if release else "NEW_EPOCH_PENDING",
        "predecessor_epoch_id": artifact("EPOCH", "3"),
        "candidate_epoch_id": artifact("EPOCH", "4"),
        "shock_observation_id": artifact("SHOCK", "5"),
        "input_freshness_vector_id": artifact("FRESHNESS", "6"),
        "resnapshot_proof_id": artifact("PROOF", "7"),
        "candidate_epoch_relation": "DISTINCT_SUCCESSOR",
        "proof_status_at_transition": value["proof_status"],
        "proof_verified": value["proof_verified"],
        "freshness_binding_verified": value.get("freshness_binding_verified", True),
        "shock_binding_verified": value.get("shock_binding_verified", True),
        "mapping_bindings_verified": value.get("mapping_bindings_verified", True),
        "continuity_bindings_verified": value.get("continuity_bindings_verified", True),
        "predecessor_permanently_closed": value["predecessor_permanently_closed"],
        "release_predicate_at_transition": value.get("release_predicate", "SATISFIED"),
        **({
            "proof_bound_mappings_open_unclosed_valid_at_release": value[
                "proof_bound_mappings_open_unclosed_valid_at_release"
            ],
            "freshness_bindings_valid_at_release": value["freshness_bindings_valid_at_release"],
            "continuity_bindings_valid_at_release": value[
                "continuity_bindings_valid_at_release"
            ],
        } if release else {}),
        "transition_reason": (
            "RELEASE_PREDICATE_SATISFIED" if release else "RESNAPSHOT_CANDIDATE_ACCEPTED"
        ),
        "transitioned_at": {
            "clock_domain_id": "11111111-1111-4111-8111-111111111111",
            "boot_id": "22222222-2222-4222-8222-222222222222",
            "unit": "MICROSECOND", "monotonic_value": "1", "resolution_us": "1",
            "owner": "BACKEND_PROCESS",
        },
        "immutable": True,
    }


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
    if handler == "verify_clock_observation":
        positive = vectors["canonical_hash_positive_vector"]
        record = copy.deepcopy(positive["record"])
        if section == "canonical_hash_negative_vector":
            del record["content_hash"]
        case["input"] = {"artifact_type": positive["artifact_type"], "record": record}
        case["expected"] = {
            "accepted": section == "canonical_hash_positive_vector",
            "error": vector["expected"],
            "schema_valid": section == "canonical_hash_positive_vector",
            "computed_hash": (
                positive["expected_sha256"]
                if section == "canonical_hash_positive_vector" else None
            ),
        }
        return case
    if handler == "compute_drift":
        case["input"] = {key: vector[key] for key in (
            "relative_drift_ppm", "source_anchor_us", "x",
        )}
        case["expected"] = {"accepted": True, "error": "ACCEPT",
                            "drift_us": vector["expected_drift_us"]}
        return case
    if handler == "validate_midpoint":
        case["input"] = {key: vector[key] for key in (
            "offset_lower_us", "offset_upper_us", "base_uncertainty_us",
            "offset_midpoint_us",
        )}
        case["expected"] = {"accepted": str(vector["expected"]).startswith("ACCEPT"),
                            "error": vector["expected"]}
        return case
    if handler == "select_mapping":
        case["input"] = {"candidates": vector["candidates"]}
        case["expected"] = {
            "accepted": True, "error": "ACCEPT",
            "mapping_id": vector["expected_mapping_id"],
        }
        return case
    if handler == "close_mapping":
        mapping_id = "MAP:" + "c" * 64
        case["input"] = {
            "mapping_id": mapping_id, "reason": vector["reason"],
            **({"attempt": vector["attempt"], "candidates": [{
                "mapping_id": mapping_id, "width_us": 1, "valid_from_us": 1,
            }]} if "attempt" in vector else {}),
        }
        closure = {
            "mapping_id": mapping_id, "reason": vector["reason"],
            "permanent": vector.get("permanent", True), "reopen_permitted": False,
        }
        common = {
            **closure, "history_size": 1, "closure_executed": True,
            "history": [closure],
        }
        case["expected"] = (
            {"accepted": False, "error": vector["expected_error"], **common,
             "coherence_eligible": vector["coherence_eligible"]}
            if "attempt" in vector else
            {"accepted": True, "error": "ACCEPT", **common,
             "reopen_error": vector["reopen_attempt_error"]}
        )
        return case
    if handler == "accept_candidate":
        case["input"] = {
            "controller_state": "WAITING_FOR_RESNAPSHOT",
            "proof_status": vector.get("proof_status_at_transition", vector.get("proof_status")),
            "proof_verified": vector["proof_verified"],
            "release_predicate": vector["release_predicate"],
            "predecessor_permanently_closed": True,
            "candidate_distinct_from_predecessor": True,
            "freshness_binding_verified": vector.get("freshness_binding_verified", False),
            "shock_binding_verified": vector.get("shock_binding_verified", False),
            "mapping_bindings_verified": vector.get("mapping_bindings_verified", False),
            "continuity_bindings_verified": vector.get("continuity_bindings_verified", False),
        }
        case["expected"] = {
            "accepted": False, "error": "E_RESNAPSHOT_CANDIDATE_BINDING",
            "state": vector["expected_state"],
        }
        if "JSON" in vector["surface"]:
            case["input"]["schema_record"] = _transition_schema_record(case["input"], release=False)
            case["expected"].update(schema_valid=False, schema_error="REJECT_SCHEMA")
        case["sql_surface"] = "SQL" in vector["surface"]
        return case
    if handler == "evaluate_release":
        positive = vectors["release_positive_vector"]
        case["input"] = {
            **{key: value for key, value in positive.items() if key not in {
                "id", "expected_transition", "expected_predecessor_state",
                "expected_successor_distinct",
            }},
            "controller_state": "NEW_EPOCH_PENDING",
            "predecessor_epoch_id": "EPOCH:" + "1" * 64,
            "candidate_epoch_id": "EPOCH:" + "2" * 64,
            "proof_verified": True,
            "candidate_created": True,
            "candidate_distinct_from_predecessor": True,
            "predecessor_permanently_closed": True,
            "proof_bindings_valid": True,
            "proof_bound_mapping_ids": ["MAP:" + digit * 64 for digit in "123"],
        }
        if section == "release_negative_vectors":
            failed = vector.get("failed_predicate")
            if isinstance(failed, str):
                case["input"][failed] = (
                    vector.get("value", vector["proof_status"])
                    if failed == "proof_status" else vector.get("value", False)
                )
            for key in ("proof_status", "blocker"):
                if key in vector:
                    case["input"][key] = vector[key]
            attempt = vector.get("attempt")
            if attempt == "REOPEN_CLOSED_PREDECESSOR_EPOCH":
                case["input"]["predecessor_reopen_requested"] = True
            elif attempt == "NEW_EPOCH_PENDING_TO_NEW_EPOCH_OPEN_WITH_CANDIDATE_NOT_CREATED":
                case["input"].update(candidate_created=False, candidate_epoch_id=None)
            elif attempt == "CONTROLLER_RELEASE_RETAINS_PREDECESSOR_AS_CURRENT_EPOCH":
                case["input"]["candidate_epoch_id"] = case["input"]["predecessor_epoch_id"]
            elif attempt == "CREATE_NON_GENESIS_EPOCH_WITH_PREDECESSOR_PERMANENTLY_CLOSED_FALSE":
                case["input"]["predecessor_permanently_closed"] = False
            elif attempt == (
                "RELEASE_WITH_OBSERVED_PROOF_NOT_BOUND_TO_CANDIDATE_FRESHNESS_"
                "SHOCK_MAPPINGS_AND_CONTINUITY"
            ):
                case["input"]["proof_bindings_valid"] = False
            case["expected"] = {
                "accepted": False, "error": vector["expected_error"],
                "state": vector["expected_state"],
            }
            if vector.get("surface") == "JSON_SCHEMA_AND_SQL":
                case["input"]["schema_record"] = _transition_schema_record(
                    case["input"], release=True,
                )
                case["expected"].update(
                    schema_valid=False, schema_error=vector["expected_schema"],
                )
                case["sql_surface"] = True
        else:
            case["expected"] = {
                "accepted": True, "error": "ACCEPT", "state": "NEW_EPOCH_OPEN",
                "predecessor_state": positive["expected_predecessor_state"],
                "successor_distinct": positive["expected_successor_distinct"],
            }
        return case
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
    row = {**context, "case_id": case["case_id"], "family": case["family"],
           "source_section": case["section"], "evaluator_refs": case["evaluator_refs"],
           "input": case["input"], "expected": case["expected"],
           "input_sha256": _hash(case["input"]), "expected_sha256": _hash(case["expected"]),
           **fields}
    if not fields["executed"] and fields["execution_kind"] != "QUALIFICATION_MUTATION":
        return row
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "actual.json"
    with artifact.open("xb") as stream:
        stream.write(_bytes(actual))
    return {**row,
            "actual": actual, "actual_artifact": {"path": str(artifact.resolve()),
                                                   "sha256": _hash(actual)}}


def _write_artifact(directory: Path, name: str, value: object) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with path.open("xb") as stream:
        stream.write(_bytes(value))
    return {"path": str(path.resolve()), "sha256": _hash(value)}


def _midpoint_sql_observation(value: dict[str, Any]) -> dict[str, Any]:
    ddl = RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6/sql/discovery-store-v1.sql"
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(ddl.read_text())
        connection.execute(
            "INSERT INTO run_meta VALUES (?,1,'OPEN',?,?,?,0,NULL)",
            ("11111111-1111-4111-8111-111111111111", "test-only:clock",
             "0" * 64, "1" * 64),
        )
        fields = (
            "MAP:" + "2" * 64, "11111111-1111-4111-8111-111111111111",
            "source", "source-boot", "EXTENSION_SERVICE_WORKER",
            "target", "target-boot", "BACKEND_PROCESS", "MICROSECOND", 8, 0,
            value["offset_lower_us"], value["offset_upper_us"],
            value["offset_midpoint_us"], value["base_uncertainty_us"],
            0, 100, 0, 1, "OPEN", 0,
        )
        connection.execute("""INSERT INTO clock_mappings (
            clock_mapping_id, run_id, source_clock_domain_id, source_boot_id, source_owner,
            target_clock_domain_id, target_boot_id, target_owner, unit, sample_count,
            source_anchor_us, offset_lower_us, offset_upper_us, offset_midpoint_us,
            base_uncertainty_us, network_rtt_us, relative_drift_ppm,
            valid_from_source_us, valid_until_source_us, mapping_status, created_at_us
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", fields)
    except sqlite3.IntegrityError as exc:
        message = str(exc)
        error = ("REJECT_OVERFLOW_GUARD"
                 if "9223372036854775807" in message else "REJECT_CHECK_CONSTRAINT")
        accepted = False
    else:
        message = ""
        accepted = True
        error = ("ACCEPT_OVERFLOW_SAFE"
                 if value["offset_upper_us"] == 2**63 - 1 else "ACCEPT")
    finally:
        connection.close()
    return {"accepted": accepted, "error": error, "sqlite_error": message or None,
            "ddl_sha256": hashlib.sha256(ddl.read_bytes()).hexdigest()}


def _insert_mapping(connection: sqlite3.Connection, mapping_id: str, run_id: str) -> None:
    connection.execute(
        "INSERT INTO clock_mappings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mapping_id, run_id, mapping_id, "source-boot", "EXTENSION_SERVICE_WORKER",
         "target", "target-boot", "BACKEND_PROCESS", "MICROSECOND", 8, 0,
         0, 2, 1, 1, 0, 100, 0, 10, "OPEN", 0),
    )


def _coherence_sql_observation(
    *, proof_status: str | None = None, release_mapping_close: bool = False,
) -> dict[str, Any]:
    """Execute only governed candidate/release SQL negatives against the vendored DDL."""
    if (proof_status not in {"UNKNOWN", "NOT_OBSERVED"}) == (not release_mapping_close):
        raise ValueError("E_CLOCK_SQL_SURFACE")
    ddl = RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6/sql/discovery-store-v1.sql"
    connection = sqlite3.connect(":memory:")
    run_id, fixture = "run", "fixture"
    predecessor, candidate = "epoch-0", "epoch-1"
    controller, shock, freshness, proof = "controller", "shock", "freshness", "proof"
    mapping_ids = ("mapping-football", "mapping-operator", "mapping-book")
    candidate_accepted = mapping_closed = False
    try:
        connection.executescript(ddl.read_text())
        connection.execute(
            "INSERT INTO run_meta VALUES (?,1,'OPEN',?,?,?,0,NULL)",
            (run_id, "test-only:clock", "0" * 64, "1" * 64),
        )
        if release_mapping_close:
            connection.execute(
                "INSERT INTO stream_generations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("generation-0", run_id, "browser", "producer", "stream", 0, None,
                 "ACTIVE", 0, None, None),
            )
        connection.execute(
            "INSERT INTO coherence_epochs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (predecessor, run_id, fixture, 0, None, "CLOSED", None, None, 0, 0),
        )
        connection.execute(
            "INSERT INTO shock_observations VALUES (?,?,?,?,?,?,?,?)",
            (shock, run_id, fixture,
             "SEQUENCE_GAP" if release_mapping_close else "GOAL",
             1, 2, "2" * 64, 2),
        )
        connection.execute(
            "INSERT INTO input_freshness_vectors VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (freshness, run_id, fixture, "FRESH", "FRESH", "FRESH",
             "NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK", "NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK",
             "NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK", "NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK",
             "3" * 64, 3),
        )
        connection.execute(
            "INSERT INTO coherence_epochs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (candidate, run_id, fixture, 1, predecessor, "OPEN", freshness, proof, 3, 1),
        )
        if not release_mapping_close:
            connection.execute(
                "INSERT INTO coherence_controllers VALUES (?,?,?,?,?,?,?,?,?,?)",
                (controller, run_id, fixture, "WAITING_FOR_RESNAPSHOT", predecessor,
                 None, predecessor, shock, 0, 3),
            )
            connection.execute(
                "INSERT INTO authoritative_resnapshot_proofs VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (proof, run_id, fixture, predecessor, None, shock,
                 proof_status, None, None, None, None, None, None, None, None,
                 0, 0, 0, "NOT_SATISFIED", "4" * 64, 4),
            )
            connection.execute(
                "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("candidate-negative", controller, fixture, "WAITING_FOR_RESNAPSHOT",
                 "NEW_EPOCH_PENDING", predecessor, candidate, shock, freshness, proof, 1,
                 "RESNAPSHOT_CANDIDATE_ACCEPTED", 4),
            )
        else:
            connection.execute(
                "INSERT INTO coherence_controllers VALUES (?,?,?,?,?,?,?,?,?,?)",
                (controller, run_id, fixture, "OPEN", predecessor, None, None, None, 0, 0),
            )
            connection.execute(
                "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("close-shock", controller, fixture, "OPEN", "SHOCKED_CLOSED", predecessor,
                 None, shock, None, None, 1, "SHOCK_ATOMIC_CLOSE", 2),
            )
            connection.execute(
                "UPDATE coherence_controllers SET controller_state='SHOCKED_CLOSED', "
                "active_shock_observation_id=?, controller_revision=1, updated_at_us=2 "
                "WHERE coherence_controller_id=?", (shock, controller),
            )
            connection.execute(
                "INSERT INTO gap_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("gap", run_id, "browser", "producer", "stream", 0, 1, 1, 1, 2,
                 "MISSING_SEQUENCE", "RESNAPSHOT_NEW_GENERATION", 0, 2),
            )
            connection.execute(
                "INSERT INTO gap_epoch_bindings VALUES (?,?,?,?,?,?,?,?)",
                ("gap-binding", "gap", predecessor, controller, shock, "close-shock",
                 "AFFECTED_EPOCH_PERMANENTLY_CLOSED", 2),
            )
            connection.execute(
                "UPDATE stream_generations SET generation_state='CLOSED', closed_at_us=2, "
                "close_reason='MISSING_SEQUENCE' WHERE generation_id='generation-0'"
            )
            connection.execute(
                "INSERT INTO generation_transitions VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("generation-transition", "gap", run_id, "browser", "producer", "stream",
                 0, 1, "GAP", 2),
            )
            connection.execute(
                "INSERT INTO stream_generations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("generation-1", run_id, "browser", "producer", "stream", 1, 0, "ACTIVE",
                 3, None, None),
            )
            connection.execute(
                "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("close-recorded", controller, fixture, "SHOCKED_CLOSED",
                 "WAITING_FOR_RESNAPSHOT", predecessor, None, shock, None, None, 1,
                 "CLOSE_RECORDED", 3),
            )
            connection.execute(
                "UPDATE coherence_controllers SET controller_state='WAITING_FOR_RESNAPSHOT', "
                "controller_revision=2, updated_at_us=3 WHERE coherence_controller_id=?",
                (controller,),
            )
            connection.execute(
                "INSERT INTO raw_commits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("raw", run_id, "browser", "producer", "stream", 1, 1, "observation",
                 "5" * 64, "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c",
                 "7" * 64, 1, "APPLIED", 1),
            )
            connection.execute(
                "INSERT INTO application_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("application", "raw", run_id, "browser", "producer", "stream", 1, 1,
                 "5" * 64, "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c",
                 "APPLIED", 1),
            )
            connection.execute(
                "INSERT INTO derived_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("revision", "application", "raw", run_id, "browser", "producer", "stream",
                 1, 1, 1, None, "8" * 64, 1),
            )
            connection.execute(
                "INSERT INTO reducer_cursors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("cursor", "revision", run_id, "browser", "producer", "stream", 1, 1,
                 "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c",
                 "7" * 64, 1, "5" * 64, 1),
            )
            for mapping_id in mapping_ids:
                _insert_mapping(connection, mapping_id, run_id)
            connection.execute(
                "INSERT INTO authoritative_resnapshot_proofs VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (proof, run_id, fixture, predecessor, candidate, shock, "OBSERVED",
                 "capability", freshness, *mapping_ids, "9" * 64, "cursor", "a" * 64,
                 1, 1, 1, "SATISFIED", "b" * 64, 4),
            )
            connection.execute(
                "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("candidate-accepted", controller, fixture, "WAITING_FOR_RESNAPSHOT",
                 "NEW_EPOCH_PENDING", predecessor, candidate, shock, freshness, proof, 1,
                 "RESNAPSHOT_CANDIDATE_ACCEPTED", 4),
            )
            candidate_accepted = True
            connection.execute(
                "UPDATE coherence_controllers SET controller_state='NEW_EPOCH_PENDING', "
                "candidate_epoch_id=?, predecessor_epoch_id=?, controller_revision=3, "
                "updated_at_us=4 WHERE coherence_controller_id=?",
                (candidate, predecessor, controller),
            )
            connection.execute(
                "INSERT INTO clock_mapping_closures VALUES (?,?,?,?,?,?,?,?,?)",
                ("mapping-close", mapping_ids[0], "SLEEP_RESUME", "source", "source-boot",
                 5, 1, 0, 5),
            )
            mapping_closed = True
            connection.execute(
                "INSERT INTO coherence_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("release-negative", controller, fixture, "NEW_EPOCH_PENDING",
                 "NEW_EPOCH_OPEN", predecessor, candidate, shock, freshness, proof, 1,
                 "RELEASE_PREDICATE_SATISFIED", 5),
            )
    except sqlite3.IntegrityError as exc:
        message = str(exc)
    else:
        message = ""
    finally:
        connection.close()
    expected = (
        "E_RELEASE_BINDING" if release_mapping_close else "E_RESNAPSHOT_CANDIDATE_BINDING"
    )
    return {
        "accepted": False, "error": expected if expected in message else "E_SQL_UNEXPECTED",
        "sqlite_error": message or None,
        "candidate_acceptance_executed": candidate_accepted,
        "mapping_close_executed": mapping_closed,
        "ddl_sha256": hashlib.sha256(ddl.read_bytes()).hexdigest(),
    }


def _execute(case: dict[str, Any], runtime: Path, directory: Path,
             context: dict[str, Any], *, corrupt_both: bool = False,
             mutate_closed_state: bool = False,
             release_mapping_close_bound: bool | None = None,
             bypass_release_mapping_guard: bool = False) -> dict[str, Any]:
    actual: dict[str, Any] = {}
    status, error, executed = "NOT_IMPLEMENTED", "E_CLOCK_NO_EXECUTABLE_ADAPTER", False
    drift: bool | None = None
    comparison: dict[str, Any] = {"matched": False, "diff": {}}
    exits: dict[str, Any] = {"python": None, "typescript": None}
    evaluator_artifacts: dict[str, dict[str, str]] = {}
    operation_metadata: dict[str, dict[str, Any]] = {}
    operation_metadata_artifacts: dict[str, dict[str, str]] = {}
    typescript_execution_binding: dict[str, Any] | None = None
    sql_observation: dict[str, Any] | None = None
    try:
        if case["handler"] in {
            "raw", "stored", "verify_clock_observation", "compute_drift", "validate_midpoint",
            "select_mapping", "close_mapping", "accept_candidate", "evaluate_release",
        }:
            if not which("node") or not (
                runtime / "extension/.test-build/src/contracts/clock-vectors.js"
            ).is_file():
                raise FileNotFoundError("E_CLOCK_TYPESCRIPT_PREREQUISITE")
            executed = True
            actual["python"] = _python(
                case, mutate_closed_state=mutate_closed_state,
                release_mapping_close_bound=release_mapping_close_bound,
                bypass_release_mapping_guard=bypass_release_mapping_guard,
            )
            exits["python"] = 0
            actual["typescript"] = _typescript(
                case, runtime, mutate_closed_state=mutate_closed_state,
                release_mapping_close_bound=release_mapping_close_bound,
                bypass_release_mapping_guard=bypass_release_mapping_guard,
                executable_artifacts=context["typescript_executable_artifacts"],
            )
            exits["typescript"] = 0
            typescript_execution_binding = actual["typescript"].pop(
                "__typescript_execution_binding", None,
            )
            for language in ("python", "typescript"):
                metadata = actual[language].pop("__operation_metadata", None)
                if metadata is not None:
                    operation_metadata[language] = metadata
            if corrupt_both:
                for language in ("python", "typescript"):
                    actual[language]["network_rtt_us"] = 0
            diffs = {language: _diff(value, case["expected"])
                     for language, value in actual.items()}
            if case.get("oracle_conflict"):
                diffs["independent_arithmetic"] = case["oracle_conflict"]
            drift = _bytes(actual["python"]) != _bytes(actual["typescript"])
            comparison = {"matched": not any(diffs.values()), "diff": diffs}
            evaluator_artifacts = {
                language: _write_artifact(directory, f"{language}.json", value)
                for language, value in actual.items()
            }
            operation_metadata_artifacts = {
                language: _write_artifact(directory, f"{language}-operation.json", value)
                for language, value in operation_metadata.items()
            }
            sql_observation = None
            if case["handler"] == "validate_midpoint":
                sql_observation = _midpoint_sql_observation(case["input"])
                sql_diff = _diff(
                    {key: sql_observation[key] for key in ("accepted", "error")},
                    case["expected"],
                )
                comparison["diff"]["sqlite"] = sql_diff
                comparison["matched"] = comparison["matched"] and not sql_diff
            elif case.get("sql_surface"):
                sql_observation = _coherence_sql_observation(
                    proof_status=(
                        str(case["input"]["proof_status"])
                        if case["handler"] == "accept_candidate" else None
                    ),
                    release_mapping_close=case["handler"] == "evaluate_release",
                )
                expected_sql_error = (
                    "E_RESNAPSHOT_CANDIDATE_BINDING"
                    if case["handler"] == "accept_candidate" else "E_RELEASE_BINDING"
                )
                sql_diff = {} if sql_observation["error"] == expected_sql_error else {
                    "error": {"expected": expected_sql_error, "actual": sql_observation["error"]}
                }
                comparison["diff"]["sqlite"] = sql_diff
                comparison["matched"] = comparison["matched"] and not sql_diff
            status = "PASS" if comparison["matched"] and not drift else "FAIL"
            error, executed = actual["python"]["error"], True
    except FileNotFoundError as exc:
        status = "FAIL" if executed else "BLOCKED_ENVIRONMENT"
        error = str(exc)
    except TimeoutExpired as exc:
        status, error = "FAIL", str(exc)
    except CalledProcessError as exc:
        exits["typescript"] = exc.returncode
        status, error = "FAIL", str(exc.stderr)
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        status, error = "FAIL", str(exc)
    executed = executed or status == "FAIL"
    actual["execution_error"] = error if status == "FAIL" else None
    prerequisite = ({"name": "compiled TypeScript clock evaluator and Node",
                     "available": False} if status == "BLOCKED_ENVIRONMENT" else None)
    fields = ({"comparison": comparison, "cross_language_drift": drift, "command_exit": exits,
               "evaluator_artifacts": evaluator_artifacts,
               **({"typescript_execution_binding": typescript_execution_binding,
                   "typescript_execution_binding_artifact": _write_artifact(
                       directory, "typescript-execution.json",
                       typescript_execution_binding,
                   )} if typescript_execution_binding is not None else {}),
               **({"operation_metadata": operation_metadata,
                   "operation_metadata_artifacts": operation_metadata_artifacts}
                  if operation_metadata else {}),
               **({"sql_observation": sql_observation,
                   "sql_observation_artifact": _write_artifact(
                       directory, "sqlite.json", sql_observation,
                   )} if sql_observation is not None else {})}
              if executed else {"implementation_marker": error}
              if status == "NOT_IMPLEMENTED" else {"prerequisite": prerequisite})
    return _record(case, actual, directory, context, status=status, executed=executed,
                   launch_attempted=executed, observed_error=error,
                   execution_kind="OFFLINE_SHARED_CLOCK_EVALUATOR", **fields)


def verify_record(
    row: dict[str, Any], *, _current_binding: dict[str, Any] | None = None,
    artifacts: RetainedArtifactIO | None = None,
) -> bool:
    def retained(reference: dict[str, Any]) -> bytes:
        path = str(reference["path"])
        return (
            artifacts.read_bytes(
                path, recorded_boundary=artifacts.recorded_boundary(path)
            )
            if artifacts is not None
            else Path(path).read_bytes()
        )

    try:
        if _current_binding is None:
            from tools.verify_repair_evidence import capture_binding

            _current_binding = capture_binding()
        if row["evidence_binding"] != _current_binding:
            return False
        if row.get("execution_kind") != "QUALIFICATION_MUTATION":
            from tools.verify_repair_evidence import validate_case_status

            validate_case_status(row)
        hashes_match = bool(row["input_sha256"] == _hash(row["input"])
                            and row["expected_sha256"] == _hash(row["expected"]))
        if not row["executed"] and row.get("execution_kind") != "QUALIFICATION_MUTATION":
            return hashes_match
        artifact = row["actual_artifact"]
        digest = hashlib.sha256(retained(artifact)).hexdigest()
        evaluator_artifacts = row.get("evaluator_artifacts", {})
        evaluator_match = (
            row.get("execution_kind") == "QUALIFICATION_MUTATION"
            or set(evaluator_artifacts) == {"python", "typescript"}
        ) and all(
            hashlib.sha256(retained(reference)).hexdigest()
            == reference["sha256"] == _hash(row["actual"][language])
            for language, reference in evaluator_artifacts.items()
        )
        executable_artifacts = row["typescript_executable_artifacts"]
        evidence = Path(row["evidence_directory"]).resolve()
        executable_match = set(executable_artifacts) == set(_TYPESCRIPT_MODULES) and all(
            Path(reference["path"]).resolve().is_relative_to(
                evidence / "typescript-executable"
            )
            and hashlib.sha256(retained(reference)).hexdigest()
            == reference["sha256"]
            for reference in executable_artifacts.values()
        )
        from tools.verify_repair_evidence import (
            _compiled_typescript_module_hashes,
            _typescript_compile_binding,
        )

        executable_match = executable_match and (
            {name: reference["sha256"] for name, reference in executable_artifacts.items()}
            == _compiled_typescript_module_hashes(
                _typescript_compile_binding(_current_binding), "clock"
            )
        )
        execution_binding = row.get("typescript_execution_binding")
        execution_reference = row.get("typescript_execution_binding_artifact")
        execution_match = row.get("execution_kind") == "QUALIFICATION_MUTATION" or (
            execution_binding is not None
            and execution_reference is not None
            and execution_binding["before"] == execution_binding["after"]
            == {key: value["sha256"] for key, value in executable_artifacts.items()}
            and hashlib.sha256(retained(execution_reference)).hexdigest()
            == execution_reference["sha256"] == _hash(execution_binding)
        )
        sql_reference = row.get("sql_observation_artifact")
        sql_match = sql_reference is None or (
            hashlib.sha256(retained(sql_reference)).hexdigest()
            == sql_reference["sha256"] == _hash(row["sql_observation"])
        )
        operation_metadata = row.get("operation_metadata", {})
        operation_artifacts = row.get("operation_metadata_artifacts", {})
        operation_match = (
            set(operation_metadata) == set(operation_artifacts)
            and all(
            hashlib.sha256(retained(reference)).hexdigest()
            == reference["sha256"] == _hash(operation_metadata[language])
            for language, reference in operation_artifacts.items()
            )
        )
        return bool(digest == artifact["sha256"]
                and artifact["sha256"] == _hash(row["actual"])
                and hashes_match
                and evaluator_match and executable_match and execution_match
                and sql_match and operation_match
                and all(verify_record(
                            row["actual"][key],
                            _current_binding=_current_binding,
                            artifacts=artifacts,
                        )
                        for key in ("control", "trial")
                        if key in row["actual"]))
    except (OSError, KeyError, TypeError, ValueError):
        return False


def summarize(required_ids: list[str], records: list[dict[str, Any]]) -> dict[str, Any]:
    from tools.verify_repair_evidence import aggregate_repair_evidence, capture_binding

    counts = Counter(row["case_id"] for row in records)
    exact = len(required_ids) == len(set(required_ids)) and counts == Counter(required_ids)
    current_binding = capture_binding()
    valid = [
        row for row in records if verify_record(row, _current_binding=current_binding)
    ]
    passed = [row for row in valid if row["status"] == "PASS" and row["executed"]
              and row["comparison"]["matched"] and row["cross_language_drift"] is False
              and all(not _diff(row["actual"][lang], row["expected"])
                      for lang in ("python", "typescript"))]
    failures = (not exact or len(valid) != len(records)
                or any(row["status"] == "FAIL" for row in records)
                or sum(row["status"] == "PASS" for row in records) != len(passed))
    status = "FAIL" if failures else "PASS" if len(passed) == len(required_ids) else "HOLD"
    if aggregate_repair_evidence(required_ids, records)["result"] == "FAIL":
        status = "FAIL"
    return {"result": status,
            "covered_vector_count": len({row["case_id"] for row in passed}),
            "executed_vector_count": sum(row["executed"] for row in valid),
            "skipped_vectors": sum(not row["executed"] for row in records),
            "cross_language_drift": sum(row.get("cross_language_drift") is True for row in valid),
            "required_id_set_complete": exact}


def _mutations(
    cases: list[dict[str, Any]], runtime: Path, directory: Path,
    context: dict[str, Any], *, bypass_release_mapping_guard: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    golden = next(c for c in cases if c["section"] == "golden_mapping")
    negative = next(c for c in cases if c["case_id"] == "MAP-NEG-01-TARGET-ORDER")
    hash_case = next(c for c in cases if c["case_id"].startswith("CLOCK-HASH-POS"))
    drift_case = next(c for c in cases if c["case_id"] == "DRIFT-02-ONE-SECOND")
    midpoint_case = next(c for c in cases if c["case_id"] == "MIDPOINT-POS-GOLDEN")
    close_case = next(c for c in cases if c["case_id"] == "CLOSE-NEG-USE-AFTER-CLOSE")
    candidate_case = next(c for c in cases if c["case_id"].startswith("CANDIDATE-"))
    release_case = next(c for c in cases if c["case_id"] == "RELEASE-POS-01")
    selection_case = next(c for c in cases if c["case_id"] == "SELECT-01-NARROWEST")
    for name in _MUTATION_NAMES:
        workspace = Path(mkdtemp(prefix=name + "-", dir=directory))
        original = (negative if name in {"wrong_expected_error", "inverse_eligibility"}
                    else hash_case if name == "hash_field_removal"
                    else drift_case if name == "drift_input_change"
                    else midpoint_case if name == "midpoint_corruption" else golden)
        if name == "post_close_selection":
            original = close_case
        elif name == "selection_candidate_order":
            original = selection_case
        elif name == "candidate_proof_corruption":
            original = copy.deepcopy(candidate_case)
            original.pop("sql_surface", None)
            original["input"].pop("schema_record", None)
            original["input"].update(
                proof_status="OBSERVED", proof_verified=True, release_predicate="SATISFIED",
                predecessor_permanently_closed=True, candidate_distinct_from_predecessor=True,
                freshness_binding_verified=True, shock_binding_verified=True,
                mapping_bindings_verified=True, continuity_bindings_verified=True,
            )
            original["expected"] = {
                "accepted": True, "error": "ACCEPT", "state": "NEW_EPOCH_PENDING",
            }
        elif name == "release_mapping_close":
            original = copy.deepcopy(release_case)
        control = _execute(
            copy.deepcopy(original), runtime, workspace / "control", context,
            release_mapping_close_bound=(False if name == "release_mapping_close" else None),
        )
        case = copy.deepcopy(original)
        if name == "wrong_expected_error":
            case["expected"]["error"] = "E_MUTATED_EXPECTATION"
        elif name == "inverse_eligibility":
            case["expected"]["accepted"] = not case["expected"]["accepted"]
        elif name == "raw_timestamp":
            case["raw"]["t4"] += 1
        elif name == "hash_field_removal":
            del case["input"]["record"]["content_hash"]
        elif name == "drift_input_change":
            case["input"]["x"] += 1
        elif name == "midpoint_corruption":
            case["input"]["offset_midpoint_us"] += 1
        elif name == "selection_candidate_order":
            first, second = case["input"]["candidates"]
            first["width_us"], second["width_us"] = second["width_us"], first["width_us"]
        elif name == "candidate_proof_corruption":
            case["input"]["shock_binding_verified"] = False
        trial = _execute(case, runtime, workspace / "trial", context,
                         corrupt_both=name == "same_wrong_result",
                         mutate_closed_state=name == "post_close_selection",
                         release_mapping_close_bound=(
                             True if name == "release_mapping_close" else None
                         ),
                         bypass_release_mapping_guard=(
                             bypass_release_mapping_guard
                             if name == "release_mapping_close" else False
                         ))
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
    from tools.verify_repair_evidence import capture_binding

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
    executable_artifacts = _retain_typescript_executable(runtime, evidence)
    git = which("git")
    if not git:
        raise FileNotFoundError("E_CLOCK_GIT_PREREQUISITE")
    revision = run(  # noqa: S603 -- read-only fixed argv
        [git, "rev-parse", "HEAD"], cwd=RUNTIME_ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout.strip()
    files = [Path(__file__), RUNTIME_ROOT / "src/moj_discovery/clock_vectors.py",
             RUNTIME_ROOT / "src/moj_discovery/canonical.py",
             RUNTIME_ROOT / "src/moj_discovery/schema_registry.py",
             RUNTIME_ROOT / "src/moj_discovery/clock.py",
             RUNTIME_ROOT / "src/moj_discovery/coherence.py",
             runtime / "extension/src/contracts/clock-vectors.ts",
             runtime / "extension/src/canonical.ts",
             runtime / "extension/src/schema-registry.ts",
             pack / _VECTOR_PATH, pack / _COVERAGE_PATH,
             pack / "sql/discovery-store-v1.sql",
             pack / "schemas/clock-coherence-records.schema.json",
             pack / "registries/canonical-hash-domains.v1.json"]
    context = {"evidence_binding": capture_binding(),
               "evidence_directory": str(evidence.resolve()),
               "typescript_executable_artifacts": executable_artifacts,
               "environment": {"python": platform.python_version(),
                               "platform": platform.platform(), "node": which("node")},
               "code": {"revision": revision, "sha256": {
                   str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in files if p.is_file()}},
               "registry_version": coverage["schema_version"]}
    records = [_execute(case, runtime, evidence / case["case_id"], context) for case in cases]
    mutations = _mutations(cases, runtime, evidence, context)
    summary = summarize(ids, records)
    executed_mutations = [r for r in mutations if r["executed"]]
    evidence_errors = [{"case_id": r["case_id"], "error": "E_CLOCK_MUTATION_EVIDENCE"}
                       for r in mutations if not verify_record(
                           r, _current_binding=context["evidence_binding"],
                       )]
    mutation_ids = [row["case_id"] for row in mutations]
    mutation_exact = Counter(mutation_ids) == Counter(_MUTATION_NAMES)
    # Lost execution evidence makes detection unknown; it cannot erase an execution.
    survivors = (None if evidence_errors
                 else sum(not row["detected"] for row in executed_mutations))
    if evidence_errors or not mutation_exact:
        summary["result"] = "FAIL"
    elif survivors or len(executed_mutations) != len(mutations):
        summary["result"] = "FAIL" if survivors or summary["result"] == "FAIL" else "HOLD"
    report = {**summary, "registry_version": coverage["schema_version"],
              "registry_source_sha256": coverage["source_sha256"],
              "required_vector_ids": ids, "records": records, "mutation_records": mutations,
              "mutation_attempts": len(mutations), "mutation_evidence_errors": evidence_errors,
              "mutation_verified_executions": sum(
                  verify_record(r, _current_binding=context["evidence_binding"])
                  for r in executed_mutations
              ),
              "mutation_executions": len(executed_mutations), "mutation_survivors": survivors,
              "mutation_id_set_complete": mutation_exact,
              "evidence_directory": str(evidence.resolve())}
    with (evidence / "qualification.json").open("xb") as stream:
        stream.write(_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute the offline clock qualification")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_clock_vector_qualification(
        RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6",
        RUNTIME_ROOT,
        evidence_dir=args.evidence_dir,
    )
    print(json.dumps({
        "qualification": str((args.evidence_dir / "qualification.json").resolve()),
        "result": report["result"],
        "covered_vector_count": report["covered_vector_count"],
        "mutation_executions": report["mutation_executions"],
    }, sort_keys=True))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
