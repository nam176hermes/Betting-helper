import type { AnySchemaObject } from "ajv";
import {
  canonicalContentHash,
  verifyCanonicalContentHash,
  type CanonicalRegistry,
} from "../canonical.js";
import { validateArtifact } from "../schema-registry.js";

type Integer = bigint | number;
type ClockEndpoint = { clock_domain_id: string; boot_id: string; owner: string; unit: string; resolution_us: Integer };
type EndpointMetadata = Partial<Record<`${"t1" | "t2" | "t3" | "t4"}_${"clock_domain_id" | "boot_id" | "owner" | "unit"}`, string>>;
export type RawClockInput = EndpointMetadata & {
  source: ClockEndpoint; target: ClockEndpoint;
  t1: Integer; t2: Integer; t3: Integer; t4: Integer;
  valid_sample_count?: Integer; mapping_segment_age_us?: Integer; wall_step_us?: Integer;
  eligible_target_intervals?: [Integer, Integer][]; proven_mapping?: boolean;
};
export type ClockGuardrails = {
  max_network_rtt_us: Integer; max_base_uncertainty_us: Integer;
  minimum_valid_samples: Integer; max_mapping_segment_age_us: Integer; wall_step_tolerance_us: Integer;
};
export type ClockEvaluation = {
  accepted: boolean; error: string;
  raw_lower_us: bigint; raw_upper_us: bigint; network_rtt_us: bigint; padding_us: bigint;
  offset_interval_us: [bigint, bigint]; offset_midpoint_us: bigint; base_uncertainty_us: bigint;
};
type MappingInput = Record<string, unknown>;
const identityFields = ["clock_domain_id", "boot_id", "unit", "owner"] as const;
const timestamps = ["t1", "t2", "t3", "t4"] as const;
const endpointFields = timestamps.flatMap(t => identityFields.map(field => `${t}_${field}`));
const rawFields = new Set(["source", "target", ...timestamps, ...endpointFields, "valid_sample_count", "mapping_segment_age_us", "wall_step_us", "eligible_target_intervals", "proven_mapping"]);
const storedFields = new Set(["accepted", "error", "raw_lower_us", "raw_upper_us", "network_rtt_us", "padding_us", "offset_interval_us", "offset_midpoint_us", "base_uncertainty_us", "offset_lower_us", "offset_upper_us"]);
const limitFields = ["max_network_rtt_us", "max_base_uncertainty_us", "minimum_valid_samples", "max_mapping_segment_age_us", "wall_step_tolerance_us"] as const;
const isInteger = (n: unknown): n is Integer => typeof n === "bigint" || (typeof n === "number" && Number.isSafeInteger(n));
const isIntegerPair = (value: unknown): value is [Integer, Integer] => Array.isArray(value) && value.length === 2 && Object.hasOwn(value, 0) && Object.hasOwn(value, 1) && isInteger(value[0]) && isInteger(value[1]);
const isRecord = (value: unknown): value is MappingInput => typeof value === "object" && value !== null && !Array.isArray(value);
const nonempty = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const int64Max = 2n ** 63n - 1n;
const int64Min = -(2n ** 63n);

export type ClockPrimitiveEvaluation = { accepted: boolean; error: string };
export type ClockObservationEvaluation = ClockPrimitiveEvaluation & {
  schema_valid: boolean;
  computed_hash: string | null;
};

export type MappingCandidate = {
  mapping_id: string;
  width_us: Integer;
  valid_from_us: Integer;
};
export type MappingClosure = Readonly<{
  mapping_id: string;
  reason: string;
  permanent: true;
  reopen_permitted: false;
}>;
const closureReasons = new Set([
  "DOMAIN_BOOT_CHANGED", "MONOTONIC_REGRESSION", "WALL_CLOCK_STEP", "SLEEP_RESUME",
  "MAX_DURATION", "RTT_EXCEEDED", "UNCERTAINTY_EXCEEDED", "INCONSISTENT_MAPPING",
  "LIFECYCLE_INVALIDATED", "RUN_CLOSED",
]);

export const selectClockMapping = (
  candidates: readonly MappingCandidate[],
  history: readonly MappingClosure[] = [],
): MappingCandidate => {
  const closed = new Set(history.map((closure) => closure.mapping_id));
  const eligible = candidates.filter((candidate) => !closed.has(candidate.mapping_id));
  for (const candidate of eligible) {
    if (!nonempty(candidate.mapping_id) || !isInteger(candidate.width_us) || BigInt(candidate.width_us) < 0n ||
        !isInteger(candidate.valid_from_us) || BigInt(candidate.valid_from_us) < 0n) {
      throw new Error("E_INVALID_MAPPING_CANDIDATE");
    }
  }
  if (!eligible.length) throw new Error("E_NO_VALID_MAPPING");
  return eligible.reduce((best, candidate) => {
    const width = BigInt(candidate.width_us), bestWidth = BigInt(best.width_us);
    const validFrom = BigInt(candidate.valid_from_us), bestValidFrom = BigInt(best.valid_from_us);
    return width < bestWidth ||
      (width === bestWidth && (validFrom > bestValidFrom ||
        (validFrom === bestValidFrom && candidate.mapping_id < best.mapping_id))) ? candidate : best;
  });
};

export const closeClockMapping = (
  mappingId: string,
  reason: string,
  history: readonly MappingClosure[] = [],
): readonly MappingClosure[] => {
  if (!nonempty(mappingId) || !closureReasons.has(reason)) throw new Error("E_INVALID_MAPPING_CLOSURE");
  if (history.some((closure) => closure.mapping_id === mappingId)) {
    throw new Error("E_MAPPING_PERMANENTLY_CLOSED");
  }
  const closure = Object.freeze({
    mapping_id: mappingId, reason, permanent: true as const, reopen_permitted: false as const,
  });
  return Object.freeze([...history, closure]);
};

export const reopenClockMapping = (
  mappingId: string,
  history: readonly MappingClosure[],
): never => {
  if (history.some((closure) => closure.mapping_id === mappingId)) {
    throw new Error("E_MAPPING_PERMANENTLY_CLOSED");
  }
  throw new Error("E_NO_VALID_MAPPING");
};

export const verifyClockObservation = async (
  artifactType: string,
  record: MappingInput,
  schemas: readonly AnySchemaObject[],
  registry: CanonicalRegistry,
): Promise<ClockObservationEvaluation> => {
  if (!Object.hasOwn(record, "content_hash")) {
    return { accepted: false, error: "SCHEMA_INVALID_BEFORE_CANONICAL_HASH", schema_valid: false, computed_hash: null };
  }
  try {
    validateArtifact(record, "https://hybrid-discovery.local/schemas/v6.2/clock-coherence-records.schema.json", schemas);
  } catch {
    return { accepted: false, error: "SCHEMA_INVALID", schema_valid: false, computed_hash: null };
  }
  const computedHash = await canonicalContentHash(artifactType, record, registry);
  try {
    await verifyCanonicalContentHash(artifactType, record, String(record.content_hash), registry);
  } catch (error) {
    return { accepted: false, error: error instanceof Error ? error.message : String(error), schema_valid: true, computed_hash: computedHash };
  }
  return { accepted: true, error: "SCHEMA_VALID_AND_RECOMPUTED_HASH_MATCH", schema_valid: true, computed_hash: computedHash };
};

export const computeDrift = (
  relativeDriftPpm: Integer,
  sourceAnchorUs: Integer,
  x: Integer,
): bigint => {
  if (![relativeDriftPpm, sourceAnchorUs, x].every(isInteger)) throw new Error("E_INVALID_DRIFT_INPUT");
  const ppm = BigInt(relativeDriftPpm), anchor = BigInt(sourceAnchorUs), point = BigInt(x);
  if (ppm < 0n || anchor < 0n || point < 0n) throw new Error("E_INVALID_DRIFT_INPUT");
  const distance = point >= anchor ? point - anchor : anchor - point;
  return (ppm * distance + 999_999n) / 1_000_000n;
};

export const validateMidpoint = (value: MappingInput): ClockPrimitiveEvaluation => {
  const fields = ["offset_lower_us", "offset_upper_us", "base_uncertainty_us", "offset_midpoint_us"] as const;
  if (Object.keys(value).length !== fields.length || fields.some((field) => !isInteger(value[field]))) {
    return { accepted: false, error: "REJECT_CHECK_CONSTRAINT" };
  }
  const lower = BigInt(value.offset_lower_us as Integer);
  const upper = BigInt(value.offset_upper_us as Integer);
  const uncertainty = BigInt(value.base_uncertainty_us as Integer);
  const midpoint = BigInt(value.offset_midpoint_us as Integer);
  if ([lower, upper, midpoint].some((number) => number < int64Min || number > int64Max)) {
    return { accepted: false, error: "REJECT_OVERFLOW_GUARD" };
  }
  if (uncertainty < 0n || uncertainty > 125_000n || lower > int64Max - uncertainty * 2n) {
    return { accepted: false, error: "REJECT_OVERFLOW_GUARD" };
  }
  if (lower > midpoint || midpoint > upper || upper !== lower + uncertainty * 2n || midpoint !== lower + uncertainty) {
    return { accepted: false, error: "REJECT_CHECK_CONSTRAINT" };
  }
  return { accepted: true, error: upper === int64Max ? "ACCEPT_OVERFLOW_SAFE" : "ACCEPT" };
};

const result = (error: string, rawLower = 0n, rawUpper = 0n, rtt = 0n, padding = 0n, lower = 0n, upper = 0n): ClockEvaluation => {
  const sum = lower + upper;
  const midpoint = sum / 2n - (sum < 0n && sum % 2n !== 0n ? 1n : 0n);
  const left = midpoint - lower, right = upper - midpoint;
  return {
    accepted: error === "ACCEPT", error, raw_lower_us: rawLower, raw_upper_us: rawUpper,
    network_rtt_us: rtt, padding_us: padding, offset_interval_us: [lower, upper],
    offset_midpoint_us: midpoint, base_uncertainty_us: left > right ? left : right,
  };
};
const reject = (actual: ClockEvaluation, error: string): ClockEvaluation => ({ ...actual, accepted: false, error });

const validInput = (raw: unknown, guards: unknown): boolean => {
  if (!isRecord(raw) || !isRecord(guards)) return false;
  if (Object.keys(raw).some(k => !rawFields.has(k))) return false;
  if (timestamps.some(t => !isInteger(raw[t]))) return false;
  for (const endpoint of [raw.source, raw.target]) {
    if (!isRecord(endpoint) || Object.keys(endpoint).length !== 5 || identityFields.some(k => !nonempty(endpoint[k]))) return false;
    if (!isInteger(endpoint.resolution_us) || BigInt(endpoint.resolution_us) < 0n) return false;
  }
  for (const [key, value] of Object.entries(raw)) {
    if (endpointFields.includes(key) && !nonempty(value)) return false;
    if (["valid_sample_count", "mapping_segment_age_us", "wall_step_us"].includes(key) &&
        (!isInteger(value) || (key !== "wall_step_us" && BigInt(value) < 0n))) return false;
  }
  if (limitFields.some(k => !isInteger(guards[k]) || BigInt(guards[k]) < 0n)) return false;
  if ("proven_mapping" in raw && typeof raw.proven_mapping !== "boolean") return false;
  if ("eligible_target_intervals" in raw) {
    const intervals = raw.eligible_target_intervals;
    if (!Array.isArray(intervals) || !intervals.length) return false;
    for (const interval of intervals) if (!isIntegerPair(interval)) return false;
  }
  return true;
};

/** Arithmetic depends only on validated raw evidence. All outputs stay exact BigInts. */
export const deriveClockMapping = (raw: RawClockInput, guards: ClockGuardrails): ClockEvaluation => {
  if (!validInput(raw, guards)) return result("E_INVALID_RAW_CLOCK_INPUT");
  const { source, target } = raw;
  const t1 = BigInt(raw.t1), t2 = BigInt(raw.t2), t3 = BigInt(raw.t3), t4 = BigInt(raw.t4);
  if (t3 < t2) return result("E_NEGATIVE_TARGET_ORDER");
  if (t4 < t1) return result("E_NEGATIVE_SOURCE_ORDER");
  const rawLower = t3 - t4, rawUpper = t2 - t1;
  const rtt = (t4 - t1) - (t3 - t2);
  const padding = BigInt(source.resolution_us) + BigInt(target.resolution_us);
  const actual = result("ACCEPT", rawLower, rawUpper, rtt, padding, rawLower - padding, rawUpper + padding);
  if (rtt < 0n) return reject(actual, "E_NEGATIVE_NETWORK_RTT");
  const endpoints = [["t1", source], ["t4", source], ["t2", target], ["t3", target]] as const;
  if (["t1", "t4"].some(t => (raw[`${t}_clock_domain_id` as keyof EndpointMetadata] ?? source.clock_domain_id) !== source.clock_domain_id)) return reject(actual, "E_SOURCE_DOMAIN_MISMATCH");
  if (["t2", "t3"].some(t => (raw[`${t}_clock_domain_id` as keyof EndpointMetadata] ?? target.clock_domain_id) !== target.clock_domain_id)) return reject(actual, "E_TARGET_DOMAIN_MISMATCH");
  if (endpoints.some(([t, e]) => (raw[`${t}_boot_id`] ?? e.boot_id) !== e.boot_id)) return reject(actual, "E_BOOT_MISMATCH");
  if (endpoints.some(([t, e]) => e.unit !== "MICROSECOND" || (raw[`${t}_unit`] ?? e.unit) !== "MICROSECOND")) return reject(actual, "E_UNIT_NOT_MICROSECOND");
  if (endpoints.some(([t, e]) => (raw[`${t}_owner`] ?? e.owner) !== e.owner)) return reject(actual, "E_TIMESTAMP_OWNER_MISMATCH");
  if (rtt > BigInt(guards.max_network_rtt_us)) return reject(actual, "E_MAX_NETWORK_RTT_EXCEEDED");
  if (actual.base_uncertainty_us > BigInt(guards.max_base_uncertainty_us)) return reject(actual, "E_MAX_BASE_UNCERTAINTY_EXCEEDED");
  if (BigInt(raw.valid_sample_count ?? guards.minimum_valid_samples) < BigInt(guards.minimum_valid_samples)) return reject(actual, "E_MINIMUM_VALID_SAMPLES");
  if (BigInt(raw.mapping_segment_age_us ?? 0) > BigInt(guards.max_mapping_segment_age_us)) return reject(actual, "E_MAX_MAPPING_SEGMENT_AGE");
  const wallStep = BigInt(raw.wall_step_us ?? 0);
  if ((wallStep < 0n ? -wallStep : wallStep) > BigInt(guards.wall_step_tolerance_us)) return reject(actual, "E_WALL_STEP_TOLERANCE");
  const intervals = raw.eligible_target_intervals;
  const first = intervals?.[0];
  if (intervals && first) {
    let lower = BigInt(first[0]), upper = BigInt(first[1]);
    for (const interval of intervals) {
      const left = BigInt(interval[0]), right = BigInt(interval[1]);
      if (left > lower) lower = left;
      if (right < upper) upper = right;
    }
    if (lower > upper) return reject(actual, "E_INCONSISTENT_MAPPING");
  }
  if (raw.proven_mapping === false || (source.owner === "CDP_BROWSER" && raw.proven_mapping !== true)) return reject(actual, "SOURCE_AGE_UNKNOWN");
  return actual;
};

/** MAP-NEG-09/10/11 are stored interval/RTT/radius corruption, never raw overrides. */
export const validateStoredMapping = (stored: MappingInput, raw: RawClockInput, guards: ClockGuardrails): ClockEvaluation => {
  const actual = deriveClockMapping(raw, guards);
  if (!actual.accepted) return actual;
  if (!Object.keys(stored).length || Object.keys(stored).some(k => !storedFields.has(k))) return reject(actual, "E_STORED_MAPPING_MISMATCH");
  const expected: MappingInput = { ...actual, offset_lower_us: actual.offset_interval_us[0], offset_upper_us: actual.offset_interval_us[1] };
  const normalized: MappingInput = {};
  for (const [key, value] of Object.entries(stored)) {
    if (key === "offset_interval_us") {
      if (!isIntegerPair(value)) return reject(actual, "E_STORED_MAPPING_MISMATCH");
      normalized[key] = value.map(v => BigInt(v));
    } else if (typeof expected[key] === "bigint") {
      if (!isInteger(value)) return reject(actual, "E_STORED_MAPPING_MISMATCH");
      normalized[key] = BigInt(value);
    } else {
      if (typeof value !== typeof expected[key]) return reject(actual, "E_STORED_MAPPING_MISMATCH");
      normalized[key] = value;
    }
  }
  const lower = (normalized.offset_lower_us as bigint | undefined) ?? actual.offset_interval_us[0];
  const upper = (normalized.offset_upper_us as bigint | undefined) ?? actual.offset_interval_us[1];
  const interval = (normalized.offset_interval_us as [bigint, bigint] | undefined) ?? [lower, upper];
  if (lower > upper || interval[0] > interval[1]) return reject(actual, "E_INVERTED_OFFSET_INTERVAL");
  if (((normalized.network_rtt_us as bigint | undefined) ?? 0n) > BigInt(guards.max_network_rtt_us)) return reject(actual, "E_MAX_NETWORK_RTT_EXCEEDED");
  if (((normalized.base_uncertainty_us as bigint | undefined) ?? 0n) > BigInt(guards.max_base_uncertainty_us)) return reject(actual, "E_MAX_BASE_UNCERTAINTY_EXCEEDED");
  for (const [key, value] of Object.entries(normalized)) {
    const correct = expected[key];
    if (Array.isArray(value) && Array.isArray(correct) ? value.some((v, i) => v !== correct[i]) : value !== correct) return reject(actual, "E_STORED_MAPPING_MISMATCH");
  }
  return actual;
};

/** Verification-only legacy adapter; golden/MAP-NEG-01..08/12..16 are RAW_SAMPLE.
 * MAP-NEG-09..11 are SERIALIZED_MAPPING_VALIDATION. ID/expected metadata is inert.
 * Only this adapter serializes exact BigInts as safe numbers or decimal strings.
 */
export const evaluateClockMappingVector = (vector: MappingInput, guardrails: MappingInput): MappingInput => {
  const stored: MappingInput = {}, raw: MappingInput = {};
  for (const [key, value] of Object.entries(vector)) {
    if (storedFields.has(key)) stored[key] = value;
    else if (!["id", "expected", "source_owner"].includes(key)) raw[key] = value;
  }
  if ("source_owner" in vector && isRecord(raw.source)) raw.source = { ...raw.source, owner: vector.source_owner };
  const sample = raw as RawClockInput, guards = guardrails as ClockGuardrails;
  const actual = Object.keys(stored).length ? validateStoredMapping(stored, sample, guards) : deriveClockMapping(sample, guards);
  const serialize = (n: bigint): number | string => n >= BigInt(Number.MIN_SAFE_INTEGER) && n <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(n) : n.toString();
  return Object.fromEntries(Object.entries(actual).map(([k, v]) => [k, typeof v === "bigint" ? serialize(v) : Array.isArray(v) ? v.map(serialize) : v]));
};
