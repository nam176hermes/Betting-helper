"""Exact raw clock arithmetic and separate stored assertions; vector adapter is test-only."""
from __future__ import annotations

from collections.abc import Mapping
from typing import NotRequired, TypedDict, cast


class ClockEndpoint(TypedDict):
    clock_domain_id: str
    boot_id: str
    owner: str
    unit: str
    resolution_us: int


class RawClockInput(TypedDict):
    source: ClockEndpoint
    target: ClockEndpoint
    t1: int
    t2: int
    t3: int
    t4: int
    valid_sample_count: NotRequired[int]
    mapping_segment_age_us: NotRequired[int]
    wall_step_us: NotRequired[int]
    eligible_target_intervals: NotRequired[list[list[int]]]
    proven_mapping: NotRequired[bool]


class ClockGuardrails(TypedDict):
    max_network_rtt_us: int
    max_base_uncertainty_us: int
    minimum_valid_samples: int
    max_mapping_segment_age_us: int
    wall_step_tolerance_us: int


class ClockEvaluation(TypedDict):
    accepted: bool
    error: str
    raw_lower_us: int
    raw_upper_us: int
    network_rtt_us: int
    padding_us: int
    offset_interval_us: list[int]
    offset_midpoint_us: int
    base_uncertainty_us: int


_IDENTITY_FIELDS = ("clock_domain_id", "boot_id", "unit", "owner")
_TIMESTAMPS = ("t1", "t2", "t3", "t4")
_ENDPOINT_OVERRIDES = {f"{t}_{field}" for t in _TIMESTAMPS for field in _IDENTITY_FIELDS}
_RAW_FIELDS = set(RawClockInput.__annotations__) | _ENDPOINT_OVERRIDES
_STORED_FIELDS = set(ClockEvaluation.__annotations__) | {"offset_lower_us", "offset_upper_us"}


def _result(
    error: str, raw_lower: int = 0, raw_upper: int = 0, rtt: int = 0,
    padding: int = 0, lower: int = 0, upper: int = 0,
) -> ClockEvaluation:
    midpoint = (lower + upper) // 2
    return {
        "accepted": error == "ACCEPT", "error": error,
        "raw_lower_us": raw_lower, "raw_upper_us": raw_upper,
        "network_rtt_us": rtt, "padding_us": padding,
        "offset_interval_us": [lower, upper], "offset_midpoint_us": midpoint,
        "base_uncertainty_us": max(midpoint - lower, upper - midpoint),
    }


def _reject(actual: ClockEvaluation, error: str) -> ClockEvaluation:
    return {**actual, "accepted": False, "error": error}


def _valid_input(raw: Mapping[str, object], guardrails: Mapping[str, object]) -> bool:
    if not isinstance(raw, Mapping) or not isinstance(guardrails, Mapping):
        return False
    if set(raw) - _RAW_FIELDS:
        return False
    for key in _TIMESTAMPS:
        if type(raw.get(key)) is not int:
            return False
    for side in ("source", "target"):
        endpoint = raw.get(side)
        if not isinstance(endpoint, dict) or set(endpoint) != set(ClockEndpoint.__annotations__):
            return False
        if any(not isinstance(endpoint[k], str) or not endpoint[k] for k in _IDENTITY_FIELDS):
            return False
        if type(endpoint["resolution_us"]) is not int or endpoint["resolution_us"] < 0:
            return False
    for key in _ENDPOINT_OVERRIDES & raw.keys():
        if not isinstance(raw[key], str) or not raw[key]:
            return False
    for key in ClockGuardrails.__annotations__:
        value = guardrails.get(key)
        if type(value) is not int or value < 0:
            return False
    for key in ("valid_sample_count", "mapping_segment_age_us", "wall_step_us"):
        if key in raw and (type(raw[key]) is not int or (
            key != "wall_step_us" and cast(int, raw[key]) < 0
        )):
            return False
    if "proven_mapping" in raw and type(raw["proven_mapping"]) is not bool:
        return False
    if "eligible_target_intervals" in raw:
        intervals = raw["eligible_target_intervals"]
        if not isinstance(intervals, list) or not intervals:
            return False
        for interval in intervals:
            if (not isinstance(interval, list) or len(interval) != 2
                    or any(type(item) is not int for item in interval)):
                return False
    return True


def derive_clock_mapping(
    raw: RawClockInput | Mapping[str, object], guardrails: ClockGuardrails | Mapping[str, object],
) -> ClockEvaluation:
    """Derive from validated raw evidence only; never accept expected or derived fields."""
    if not _valid_input(raw, guardrails):
        return _result("E_INVALID_RAW_CLOCK_INPUT")
    sample, limits = cast(RawClockInput, raw), cast(ClockGuardrails, guardrails)
    source, target = sample["source"], sample["target"]
    t1, t2, t3, t4 = (sample["t1"], sample["t2"], sample["t3"], sample["t4"])
    if t3 < t2:
        return _result("E_NEGATIVE_TARGET_ORDER")
    if t4 < t1:
        return _result("E_NEGATIVE_SOURCE_ORDER")
    raw_lower, raw_upper = t3 - t4, t2 - t1
    rtt = (t4 - t1) - (t3 - t2)
    padding = source["resolution_us"] + target["resolution_us"]
    actual = _result("ACCEPT", raw_lower, raw_upper, rtt, padding,
                     raw_lower - padding, raw_upper + padding)
    if rtt < 0:
        return _reject(actual, "E_NEGATIVE_NETWORK_RTT")
    endpoints = (("t1", source), ("t4", source), ("t2", target), ("t3", target))
    for times, endpoint, error in (
        (("t1", "t4"), source, "E_SOURCE_DOMAIN_MISMATCH"),
        (("t2", "t3"), target, "E_TARGET_DOMAIN_MISMATCH"),
    ):
        if any(raw.get(f"{t}_clock_domain_id", endpoint["clock_domain_id"])
               != endpoint["clock_domain_id"] for t in times):
            return _reject(actual, error)
    if any(raw.get(f"{t}_boot_id", e["boot_id"]) != e["boot_id"] for t, e in endpoints):
        return _reject(actual, "E_BOOT_MISMATCH")
    if any(e["unit"] != "MICROSECOND" or raw.get(f"{t}_unit", e["unit"]) != "MICROSECOND"
           for t, e in endpoints):
        return _reject(actual, "E_UNIT_NOT_MICROSECOND")
    if any(raw.get(f"{t}_owner", e["owner"]) != e["owner"] for t, e in endpoints):
        return _reject(actual, "E_TIMESTAMP_OWNER_MISMATCH")
    if rtt > limits["max_network_rtt_us"]:
        return _reject(actual, "E_MAX_NETWORK_RTT_EXCEEDED")
    if actual["base_uncertainty_us"] > limits["max_base_uncertainty_us"]:
        return _reject(actual, "E_MAX_BASE_UNCERTAINTY_EXCEEDED")
    if sample.get("valid_sample_count", limits["minimum_valid_samples"]) < limits[
        "minimum_valid_samples"
    ]:
        return _reject(actual, "E_MINIMUM_VALID_SAMPLES")
    if sample.get("mapping_segment_age_us", 0) > limits["max_mapping_segment_age_us"]:
        return _reject(actual, "E_MAX_MAPPING_SEGMENT_AGE")
    if abs(sample.get("wall_step_us", 0)) > limits["wall_step_tolerance_us"]:
        return _reject(actual, "E_WALL_STEP_TOLERANCE")
    intervals = sample.get("eligible_target_intervals")
    if intervals and max(i[0] for i in intervals) > min(i[1] for i in intervals):
        return _reject(actual, "E_INCONSISTENT_MAPPING")
    if sample.get("proven_mapping") is False or (
        source["owner"] == "CDP_BROWSER" and sample.get("proven_mapping") is not True
    ):
        return _reject(actual, "SOURCE_AGE_UNKNOWN")
    return actual


def validate_stored_mapping(
    stored: Mapping[str, object], raw: RawClockInput | Mapping[str, object],
    guardrails: ClockGuardrails | Mapping[str, object],
) -> ClockEvaluation:
    """Check supplied stored assertions against raw recomputation, retaining raw diagnostics.

    MAP-NEG-09/10/11 are SERIALIZED_MAPPING_VALIDATION: their frozen errors describe
    invalid stored intervals/RTT/radius. Other numeric mismatches reject as corruption.
    Raw sample rejection always prevents a stored value from making it eligible.
    """
    actual = derive_clock_mapping(raw, guardrails)
    if not actual["accepted"]:
        return actual
    if not stored or set(stored) - _STORED_FIELDS:
        return _reject(actual, "E_STORED_MAPPING_MISMATCH")
    expected: dict[str, object] = dict(actual)
    expected.update(offset_lower_us=actual["offset_interval_us"][0],
                    offset_upper_us=actual["offset_interval_us"][1])
    for key, value in stored.items():
        if key == "offset_interval_us":
            if (not isinstance(value, list) or len(value) != 2
                    or any(type(item) is not int for item in value)):
                return _reject(actual, "E_STORED_MAPPING_MISMATCH")
        elif type(value) is not type(expected[key]):
            return _reject(actual, "E_STORED_MAPPING_MISMATCH")
    lower = cast(int, stored.get("offset_lower_us", actual["offset_interval_us"][0]))
    upper = cast(int, stored.get("offset_upper_us", actual["offset_interval_us"][1]))
    interval = cast(list[int], stored.get("offset_interval_us", [lower, upper]))
    if lower > upper or interval[0] > interval[1]:
        return _reject(actual, "E_INVERTED_OFFSET_INTERVAL")
    limits = cast(ClockGuardrails, guardrails)
    if cast(int, stored.get("network_rtt_us", 0)) > limits["max_network_rtt_us"]:
        return _reject(actual, "E_MAX_NETWORK_RTT_EXCEEDED")
    if cast(int, stored.get("base_uncertainty_us", 0)) > limits["max_base_uncertainty_us"]:
        return _reject(actual, "E_MAX_BASE_UNCERTAINTY_EXCEEDED")
    if any(value != expected[key] for key, value in stored.items()):
        return _reject(actual, "E_STORED_MAPPING_MISMATCH")
    return actual


def evaluate_clock_mapping_vector(
    vector: Mapping[str, object], guardrails: Mapping[str, object],
) -> ClockEvaluation:
    """Verification-only legacy adapter. IDs/expected metadata never affect computation.

    Golden and MAP-NEG-01..08/12..16 use RAW_SAMPLE; MAP-NEG-09..11 use the
    separate stored validator. The source_owner alias belongs only to legacy fixtures.
    """
    stored = {k: v for k, v in vector.items() if k in _STORED_FIELDS}
    raw = {k: v for k, v in vector.items()
           if k not in _STORED_FIELDS | {"id", "expected", "source_owner"}}
    if "source_owner" in vector and isinstance(raw.get("source"), dict):
        raw["source"] = {**cast(dict[str, object], raw["source"]), "owner": vector["source_owner"]}
    return (validate_stored_mapping(stored, raw, guardrails) if stored
            else derive_clock_mapping(raw, guardrails))
