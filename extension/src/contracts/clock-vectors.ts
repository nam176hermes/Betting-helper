type MappingInput = Record<string, unknown>;
type Evaluation = {
  accepted: boolean;
  error: string;
  raw_lower_us: number;
  raw_upper_us: number;
  network_rtt_us: number;
  padding_us: number;
  offset_interval_us: [number, number];
  offset_midpoint_us: number;
  base_uncertainty_us: number;
};

const value = (record: MappingInput, key: string): MappingInput => record[key] as MappingInput;
const number = (record: MappingInput, key: string): number => record[key] as number;

const result = (
  error: string,
  rawLower = 0,
  rawUpper = 0,
  rtt = 0,
  padding = 0,
  lower = 0,
  upper = 0,
): Evaluation => ({
  accepted: error === "ACCEPT",
  error,
  raw_lower_us: rawLower,
  raw_upper_us: rawUpper,
  network_rtt_us: rtt,
  padding_us: padding,
  offset_interval_us: [lower, upper],
  offset_midpoint_us: Math.trunc((lower + upper) / 2),
  base_uncertainty_us: Math.trunc((upper - lower) / 2),
});

export const evaluateClockMappingVector = (
  vector: MappingInput,
  guardrails: MappingInput,
): Evaluation => {
  const source = value(vector, "source");
  const target = value(vector, "target");
  const t1 = number(vector, "t1");
  const t2 = number(vector, "t2");
  const t3 = number(vector, "t3");
  const t4 = number(vector, "t4");
  if (t3 < t2) return result("E_NEGATIVE_TARGET_ORDER");
  if (t4 < t1) return result("E_NEGATIVE_SOURCE_ORDER");
  const rawLower = t3 - t4;
  const rawUpper = t2 - t1;
  const rtt = (vector.network_rtt_us as number | undefined) ?? ((t4 - t1) - (t3 - t2));
  const padding = number(source, "resolution_us") + number(target, "resolution_us");
  const lower = (vector.offset_lower_us as number | undefined) ?? rawLower - padding;
  const upper = (vector.offset_upper_us as number | undefined) ?? rawUpper + padding;
  if (rtt < 0) return result("E_NEGATIVE_NETWORK_RTT", rawLower, rawUpper, rtt, padding, lower, upper);
  if ((vector.t4_clock_domain_id ?? source.clock_domain_id) !== source.clock_domain_id) return result("E_SOURCE_DOMAIN_MISMATCH");
  if ((vector.t3_clock_domain_id ?? target.clock_domain_id) !== target.clock_domain_id) return result("E_TARGET_DOMAIN_MISMATCH");
  if ((vector.t4_boot_id ?? source.boot_id) !== source.boot_id) return result("E_BOOT_MISMATCH");
  if ((vector.t3_unit ?? target.unit) !== "MICROSECOND") return result("E_UNIT_NOT_MICROSECOND");
  if ((vector.t2_owner ?? target.owner) !== target.owner) return result("E_TIMESTAMP_OWNER_MISMATCH");
  if (lower > upper) return result("E_INVERTED_OFFSET_INTERVAL", 0, 0, 0, 0, lower, upper);
  if (rtt > number(guardrails, "max_network_rtt_us")) return result("E_MAX_NETWORK_RTT_EXCEEDED");
  const uncertainty = (vector.base_uncertainty_us as number | undefined) ?? Math.trunc((upper - lower) / 2);
  if (uncertainty > number(guardrails, "max_base_uncertainty_us")) return result("E_MAX_BASE_UNCERTAINTY_EXCEEDED");
  if (((vector.valid_sample_count as number | undefined) ?? number(guardrails, "minimum_valid_samples")) < number(guardrails, "minimum_valid_samples")) return result("E_MINIMUM_VALID_SAMPLES");
  if (((vector.mapping_segment_age_us as number | undefined) ?? 0) > number(guardrails, "max_mapping_segment_age_us")) return result("E_MAX_MAPPING_SEGMENT_AGE");
  if (Math.abs((vector.wall_step_us as number | undefined) ?? 0) > number(guardrails, "wall_step_tolerance_us")) return result("E_WALL_STEP_TOLERANCE");
  const intervals = vector.eligible_target_intervals as [number, number][] | undefined;
  if (intervals && Math.max(...intervals.map(item => item[0])) > Math.min(...intervals.map(item => item[1]))) return result("E_INCONSISTENT_MAPPING");
  if ((vector.source_owner ?? source.owner) === "CDP_BROWSER" && vector.proven_mapping === false) return result("SOURCE_AGE_UNKNOWN");
  return result("ACCEPT", rawLower, rawUpper, rtt, padding, lower, upper);
};
