import { strict as assert } from "node:assert";
import { test } from "node:test";
import * as clock from "../../src/contracts/clock-vectors.js";

const guards = {
  max_network_rtt_us: 250_000, max_base_uncertainty_us: 125_000,
  minimum_valid_samples: 8, max_mapping_segment_age_us: 30_000_000,
  wall_step_tolerance_us: 1_000_000,
};
const golden = {
  source: { clock_domain_id: "source", boot_id: "source-boot", unit: "MICROSECOND", owner: "EXTENSION", resolution_us: 10 },
  target: { clock_domain_id: "target", boot_id: "target-boot", unit: "MICROSECOND", owner: "BACKEND", resolution_us: 20 },
  t1: 1000000, t2: 1005200, t3: 1005300, t4: 1000500,
};
const bypass = { ...golden, source: { ...golden.source, resolution_us: 1 }, target: { ...golden.target, resolution_us: 1 }, t1: 0, t2: 500100, t3: 500200, t4: 1000000 };
const overrides = { network_rtt_us: 1, offset_lower_us: 100, offset_upper_us: 101, base_uncertainty_us: 0 };

void test("audited high-RTT bypass cannot become eligible through compatibility adapter", () => {
  const actual = clock.evaluateClockMappingVector({ ...bypass, ...overrides }, guards);
  assert.equal(actual.accepted, false);
  assert.equal(actual.error, "E_MAX_NETWORK_RTT_EXCEEDED");
  assert.equal(actual.network_rtt_us, 999900);
  assert.deepEqual(actual.offset_interval_us, [-499802, 500102]);
  assert.equal(clock.deriveClockMapping(bypass, guards).network_rtt_us, 999900n);
});

void test("golden arithmetic uses exact BigInt outputs", () => {
  assert.deepEqual(clock.deriveClockMapping(golden, guards), {
    accepted: true, error: "ACCEPT", raw_lower_us: 4800n, raw_upper_us: 5200n,
    network_rtt_us: 400n, padding_us: 30n, offset_interval_us: [4770n, 5230n],
    offset_midpoint_us: 5000n, base_uncertainty_us: 230n,
  });
});

void test("raw input rejects all derived and expected fields", () => {
  for (const key of [...Object.keys(overrides), "expected", "accepted", "error", "offset_interval_us", "offset_midpoint_us", "raw_lower_us", "raw_upper_us", "padding_us"]) {
    assert.equal(clock.deriveClockMapping({ ...golden, [key]: 0 }, guards).error, "E_INVALID_RAW_CLOCK_INPUT", key);
  }
});

void test("stored assertions cannot replace raw arithmetic", () => {
  const actual = clock.deriveClockMapping(golden, guards);
  assert.deepEqual(clock.validateStoredMapping(actual, golden, guards), actual);
  for (const stored of [{ network_rtt_us: 1 }, { offset_midpoint_us: 5001 }, { base_uncertainty_us: 0 }, { padding_us: 0 }, { offset_interval_us: [100, 101] }]) {
    const rejected = clock.validateStoredMapping(stored, golden, guards);
    assert.equal(rejected.error, "E_STORED_MAPPING_MISMATCH");
    assert.equal(rejected.network_rtt_us, 400n);
    assert.deepEqual(rejected.offset_interval_us, [4770n, 5230n]);
  }
  assert.equal(clock.validateStoredMapping(overrides, bypass, guards).error, "E_MAX_NETWORK_RTT_EXCEEDED");
});

void test("stored corruption retains inherited rejection codes and exact raw diagnostics", () => {
  const cases: [Record<string, unknown>, string][] = [
    [{ offset_lower_us: 5230, offset_upper_us: 4770 }, "E_INVERTED_OFFSET_INTERVAL"],
    [{ network_rtt_us: 250001 }, "E_MAX_NETWORK_RTT_EXCEEDED"],
    [{ base_uncertainty_us: 125001 }, "E_MAX_BASE_UNCERTAINTY_EXCEEDED"],
    [{ network_rtt_us: true }, "E_STORED_MAPPING_MISMATCH"],
    [{ offset_interval_us: [1] }, "E_STORED_MAPPING_MISMATCH"],
    [{ expected: { accepted: true } }, "E_STORED_MAPPING_MISMATCH"],
    [{}, "E_STORED_MAPPING_MISMATCH"],
  ];
  for (const [stored, error] of cases) {
    const actual = clock.validateStoredMapping(stored, golden, guards);
    assert.equal(actual.error, error);
    assert.equal(actual.accepted, false);
    assert.equal(actual.network_rtt_us, 400n);
    assert.deepEqual(actual.offset_interval_us, [4770n, 5230n]);
  }
});

void test("adapter metadata is inert", () => {
  assert.deepEqual(clock.evaluateClockMappingVector({ ...golden, id: "ARBITRARY", expected: { accepted: false, network_rtt_us: 0 } }, guards), clock.evaluateClockMappingVector(golden, guards));
});

void test("odd-width intervals enclose both endpoints including beyond 2^53", () => {
  for (const shift of [0n, -10000n, 2n ** 60n, -(2n ** 60n)]) {
    const actual = clock.deriveClockMapping({ ...golden, t2: 1005200n + shift, t3: 1005300n + shift, t4: 1000501n }, guards);
    assert.equal(actual.accepted, true);
    assert.equal(actual.network_rtt_us, 401n);
    assert.deepEqual(actual.offset_interval_us, [4769n + shift, 5230n + shift]);
    assert.equal(actual.offset_midpoint_us, 4999n + shift);
    assert.equal(actual.base_uncertainty_us, 231n);
    assert.ok(actual.offset_midpoint_us - actual.base_uncertainty_us <= 4769n + shift);
    assert.ok(actual.offset_midpoint_us + actual.base_uncertainty_us >= 5230n + shift);
  }
});

void test("first failure follows frozen ordering and checks every endpoint identity", () => {
  const cases = [
    [{ t3: 0, t4: 0, t3_unit: "SECOND" }, "E_NEGATIVE_TARGET_ORDER"],
    [{ t4: 0, t4_boot_id: "bad" }, "E_NEGATIVE_SOURCE_ORDER"],
    [{ t3: 2000000, t4_clock_domain_id: "bad" }, "E_NEGATIVE_NETWORK_RTT"],
    [{ t4_clock_domain_id: "bad", t3_unit: "SECOND" }, "E_SOURCE_DOMAIN_MISMATCH"],
    [{ t3_clock_domain_id: "bad", t4_boot_id: "bad" }, "E_TARGET_DOMAIN_MISMATCH"],
    [{ t3_boot_id: "bad", t3_unit: "SECOND" }, "E_BOOT_MISMATCH"],
    [{ t1_unit: "SECOND", t2_owner: "bad" }, "E_UNIT_NOT_MICROSECOND"],
    [{ t4_owner: "bad" }, "E_TIMESTAMP_OWNER_MISMATCH"],
  ] as const;
  for (const [mutation, error] of cases) assert.equal(clock.deriveClockMapping({ ...golden, ...mutation }, guards).error, error);
});

void test("unmapped CDP source age stays unknown without an affirmative proof", () => {
  const raw = { ...golden, source: { ...golden.source, owner: "CDP_BROWSER" } };
  for (const extra of [{}, { proven_mapping: false }]) {
    const actual = clock.deriveClockMapping({ ...raw, ...extra }, guards);
    assert.equal(actual.error, "SOURCE_AGE_UNKNOWN");
    assert.equal(actual.accepted, false);
  }
  assert.equal(clock.deriveClockMapping({ ...raw, source: { ...raw.source, unit: "SECOND" } }, guards).error, "E_UNIT_NOT_MICROSECOND");
});

void test("unsafe numbers, non-integers, malformed identities and negative limits reject", () => {
  for (const t1 of [Number.MAX_SAFE_INTEGER + 1, 1.5, NaN, Infinity]) {
    assert.equal(clock.deriveClockMapping({ ...golden, t1 }, guards).error, "E_INVALID_RAW_CLOCK_INPUT");
  }
  assert.equal(clock.deriveClockMapping({ ...golden, source: { ...golden.source, boot_id: "" } }, guards).accepted, false);
  assert.equal(clock.deriveClockMapping({ ...golden, source: { ...golden.source, resolution_us: -1 } }, guards).error, "E_INVALID_RAW_CLOCK_INPUT");
  assert.equal(clock.deriveClockMapping(golden, { ...guards, max_network_rtt_us: -1 }).error, "E_INVALID_RAW_CLOCK_INPUT");
});
