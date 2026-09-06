import { strict as assert } from "node:assert";
import { readFileSync, readdirSync } from "node:fs";
import type { AnySchemaObject } from "ajv";
import type { CanonicalRegistry } from "../../src/canonical.js";
import {
  computeDrift,
  closeClockMapping,
  evaluateClockMappingVector,
  reopenClockMapping,
  selectClockMapping,
  validateMidpoint,
  verifyClockObservation,
} from "../../src/contracts/clock-vectors.js";

const vendor = "vendor/hybrid-discovery-v6.3.6";
interface ClockPrimitiveVectors {
  canonical_hash_positive_vector: { artifact_type: string; record: Record<string, unknown> };
  drift_vectors: {
    relative_drift_ppm: number;
    source_anchor_us: number;
    x: number;
    expected_drift_us: number;
  }[];
  midpoint_constraint_vectors: {
    id: string;
    expected: string;
    offset_lower_us: number;
    offset_upper_us: number;
    base_uncertainty_us: number;
    offset_midpoint_us: number;
  }[];
  mapping_selection_vectors: {
    id: string;
    candidates: { mapping_id: string; width_us: number; valid_from_us: number }[];
    expected_mapping_id: string;
  }[];
  closure_vectors: {
    id: string;
    reason: string;
    permanent?: boolean;
    reopen_attempt_error?: string;
    expected_error?: string;
  }[];
}
const vectors = JSON.parse(
  readFileSync(`${vendor}/docs/vectors/inherited/clock-coherence-v6.2.json`, "utf8"),
) as unknown as ClockPrimitiveVectors;
const schemas = readdirSync(`${vendor}/schemas`).filter((name) => name.endsWith(".json")).map(
  (name) => JSON.parse(readFileSync(`${vendor}/schemas/${name}`, "utf8")) as AnySchemaObject,
);
const registry = JSON.parse(readFileSync(`${vendor}/registries/canonical-hash-domains.v1.json`, "utf8")) as CanonicalRegistry;

export const clockVectorQualificationSuite = (): void => {
  const vector = {
    source: { clock_domain_id: "source", boot_id: "boot-source", owner: "EXTENSION_SERVICE_WORKER", unit: "MICROSECOND", resolution_us: 10 },
    target: { clock_domain_id: "target", boot_id: "boot-target", owner: "BACKEND_PROCESS", unit: "MICROSECOND", resolution_us: 20 },
    t1: 1_000_000, t2: 1_005_200, t3: 1_005_400, t4: 1_000_600,
  };
  const guardrails = {
    max_network_rtt_us: 250_000, max_base_uncertainty_us: 125_000,
    minimum_valid_samples: 8, max_mapping_segment_age_us: 30_000_000,
    wall_step_tolerance_us: 1_000_000,
  };
  assert.deepEqual(evaluateClockMappingVector(vector, guardrails), {
    accepted: true, error: "ACCEPT", raw_lower_us: 4800, raw_upper_us: 5200,
    network_rtt_us: 400, padding_us: 30, offset_interval_us: [4770, 5230],
    offset_midpoint_us: 5000, base_uncertainty_us: 230,
  });
  assert.equal(
    evaluateClockMappingVector({ ...vector, t3: 1_005_199 }, guardrails).error,
    "E_NEGATIVE_TARGET_ORDER",
  );
};

clockVectorQualificationSuite();

const positive = vectors.canonical_hash_positive_vector;
assert.deepEqual(await verifyClockObservation(positive.artifact_type, positive.record, schemas, registry), {
  accepted: true,
  error: "SCHEMA_VALID_AND_RECOMPUTED_HASH_MATCH",
  schema_valid: true,
  computed_hash: "2b63679a94fd4c6d217c3f23f811f77314e82b46baef7902a95e4146efbcee41",
});
const missingHash = structuredClone(positive.record);
delete missingHash.content_hash;
assert.deepEqual(await verifyClockObservation(positive.artifact_type, missingHash, schemas, registry), {
  accepted: false,
  error: "SCHEMA_INVALID_BEFORE_CANONICAL_HASH",
  schema_valid: false,
  computed_hash: null,
});

for (const vector of vectors.drift_vectors) {
  assert.equal(
    computeDrift(vector.relative_drift_ppm, vector.source_anchor_us, vector.x),
    BigInt(vector.expected_drift_us),
  );
}
for (const vector of vectors.midpoint_constraint_vectors) {
  const { id: _id, expected, ...input } = vector;
  const exactInput = _id.includes("MAX-BOUNDARY") ? {
    ...input,
    offset_lower_us: 9223372036854525807n,
    offset_upper_us: 9223372036854775807n,
    offset_midpoint_us: 9223372036854650807n,
  } : _id.includes("OVERFLOW") ? {
    ...input,
    offset_lower_us: 9223372036854525808n,
    offset_upper_us: 9223372036854775807n,
    offset_midpoint_us: 9223372036854650808n,
  } : input;
  assert.equal(validateMidpoint(exactInput).error, expected);
}

for (const vector of vectors.mapping_selection_vectors) {
  assert.equal(selectClockMapping(vector.candidates).mapping_id, vector.expected_mapping_id);
}

const mappingId = `MAP:${"c".repeat(64)}`;
for (const vector of vectors.closure_vectors.slice(0, 10)) {
  const history = closeClockMapping(mappingId, vector.reason);
  assert.deepEqual(history, [{
    mapping_id: mappingId,
    reason: vector.reason,
    permanent: vector.permanent,
    reopen_permitted: false,
  }]);
  assert.ok(Object.isFrozen(history));
  assert.ok(Object.isFrozen(history[0]));
  assert.throws(() => reopenClockMapping(mappingId, history), {
    message: vector.reopen_attempt_error,
  });
}

const firstHistory = closeClockMapping(mappingId, "SLEEP_RESUME");
const secondHistory = closeClockMapping(`MAP:${"d".repeat(64)}`, "RUN_CLOSED", firstHistory);
assert.equal(firstHistory.length, 1);
assert.deepEqual(secondHistory.slice(0, 1), firstHistory);
assert.equal(secondHistory.length, 2);
assert.throws(
  () => selectClockMapping([{ mapping_id: mappingId, width_us: 1, valid_from_us: 1 }], firstHistory),
  { message: vectors.closure_vectors[10]?.expected_error },
);
