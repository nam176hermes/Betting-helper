"""Pure four-timestamp mapping evaluator with frozen first-failure precedence."""
from __future__ import annotations


def _result(
    error: str,
    *,
    raw_lower: int = 0,
    raw_upper: int = 0,
    rtt: int = 0,
    padding: int = 0,
    lower: int = 0,
    upper: int = 0,
) -> dict[str, object]:
    midpoint = (lower + upper) // 2
    return {
        "accepted": error == "ACCEPT",
        "error": error,
        "raw_lower_us": raw_lower,
        "raw_upper_us": raw_upper,
        "network_rtt_us": rtt,
        "padding_us": padding,
        "offset_interval_us": [lower, upper],
        "offset_midpoint_us": midpoint,
        "base_uncertainty_us": (upper - lower) // 2,
    }


def evaluate_clock_mapping_vector(
    vector: dict[str, object], guardrails: dict[str, object]
) -> dict[str, object]:
    source = vector["source"]
    target = vector["target"]
    t1, t2, t3, t4 = (int(vector[key]) for key in ("t1", "t2", "t3", "t4"))
    if t3 < t2:
        return _result("E_NEGATIVE_TARGET_ORDER")
    if t4 < t1:
        return _result("E_NEGATIVE_SOURCE_ORDER")
    raw_lower, raw_upper = t3 - t4, t2 - t1
    rtt = int(vector.get("network_rtt_us", (t4 - t1) - (t3 - t2)))
    padding = int(source["resolution_us"]) + int(target["resolution_us"])
    lower = int(vector.get("offset_lower_us", raw_lower - padding))
    upper = int(vector.get("offset_upper_us", raw_upper + padding))
    if rtt < 0:
        return _result("E_NEGATIVE_NETWORK_RTT", raw_lower=raw_lower, raw_upper=raw_upper, rtt=rtt, padding=padding, lower=lower, upper=upper)
    if vector.get("t4_clock_domain_id", source["clock_domain_id"]) != source["clock_domain_id"]:
        return _result("E_SOURCE_DOMAIN_MISMATCH")
    if vector.get("t3_clock_domain_id", target["clock_domain_id"]) != target["clock_domain_id"]:
        return _result("E_TARGET_DOMAIN_MISMATCH")
    if vector.get("t4_boot_id", source["boot_id"]) != source["boot_id"]:
        return _result("E_BOOT_MISMATCH")
    if vector.get("t3_unit", target["unit"]) != "MICROSECOND":
        return _result("E_UNIT_NOT_MICROSECOND")
    if vector.get("t2_owner", target["owner"]) != target["owner"]:
        return _result("E_TIMESTAMP_OWNER_MISMATCH")
    if lower > upper:
        return _result("E_INVERTED_OFFSET_INTERVAL", lower=lower, upper=upper)
    if rtt > int(guardrails["max_network_rtt_us"]):
        return _result("E_MAX_NETWORK_RTT_EXCEEDED")
    uncertainty = int(vector.get("base_uncertainty_us", (upper - lower) // 2))
    if uncertainty > int(guardrails["max_base_uncertainty_us"]):
        return _result("E_MAX_BASE_UNCERTAINTY_EXCEEDED")
    if int(vector.get("valid_sample_count", guardrails["minimum_valid_samples"])) < int(guardrails["minimum_valid_samples"]):
        return _result("E_MINIMUM_VALID_SAMPLES")
    if int(vector.get("mapping_segment_age_us", 0)) > int(guardrails["max_mapping_segment_age_us"]):
        return _result("E_MAX_MAPPING_SEGMENT_AGE")
    if abs(int(vector.get("wall_step_us", 0))) > int(guardrails["wall_step_tolerance_us"]):
        return _result("E_WALL_STEP_TOLERANCE")
    intervals = vector.get("eligible_target_intervals")
    if isinstance(intervals, list):
        left = max(int(interval[0]) for interval in intervals)
        right = min(int(interval[1]) for interval in intervals)
        if left > right:
            return _result("E_INCONSISTENT_MAPPING")
    if vector.get("source_owner", source["owner"]) == "CDP_BROWSER" and not vector.get("proven_mapping", True):
        return _result("SOURCE_AGE_UNKNOWN")
    return _result(
        "ACCEPT",
        raw_lower=raw_lower,
        raw_upper=raw_upper,
        rtt=rtt,
        padding=padding,
        lower=lower,
        upper=upper,
    )
