import { strict as assert } from "node:assert";
import { evaluateClockMappingVector } from "../../src/contracts/clock-vectors.js";

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
