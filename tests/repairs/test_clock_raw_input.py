"""BH-R06: raw arithmetic and stored assertions are independent trust boundaries."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

import pytest

from moj_discovery import clock_vectors as clock

GUARDS: clock.ClockGuardrails = {
    "max_network_rtt_us": 250_000, "max_base_uncertainty_us": 125_000,
    "minimum_valid_samples": 8, "max_mapping_segment_age_us": 30_000_000,
    "wall_step_tolerance_us": 1_000_000,
}
GOLDEN: clock.RawClockInput = {
    "source": {"clock_domain_id": "source", "boot_id": "source-boot",
               "unit": "MICROSECOND", "owner": "EXTENSION", "resolution_us": 10},
    "target": {"clock_domain_id": "target", "boot_id": "target-boot",
               "unit": "MICROSECOND", "owner": "BACKEND", "resolution_us": 20},
    "t1": 1_000_000, "t2": 1_005_200, "t3": 1_005_300, "t4": 1_000_500,
}
BYPASS = {**GOLDEN, "source": {**GOLDEN["source"], "resolution_us": 1},
          "target": {**GOLDEN["target"], "resolution_us": 1},
          "t1": 0, "t2": 500100, "t3": 500200, "t4": 1000000}
OVERRIDES = {"network_rtt_us": 1, "offset_lower_us": 100,
             "offset_upper_us": 101, "base_uncertainty_us": 0}


def test_audited_bypass_is_not_eligible_even_through_compatibility_adapter() -> None:
    result = clock.evaluate_clock_mapping_vector({**BYPASS, **OVERRIDES}, GUARDS)
    assert result["accepted"] is False
    assert result["error"] == "E_MAX_NETWORK_RTT_EXCEEDED"
    assert result["network_rtt_us"] == 999900
    assert result["offset_interval_us"] == [-499802, 500102]
    assert clock.derive_clock_mapping(BYPASS, GUARDS) == result


def test_exact_golden_arithmetic() -> None:
    assert clock.derive_clock_mapping(GOLDEN, GUARDS) == {
        "accepted": True, "error": "ACCEPT", "raw_lower_us": 4800,
        "raw_upper_us": 5200, "network_rtt_us": 400, "padding_us": 30,
        "offset_interval_us": [4770, 5230], "offset_midpoint_us": 5000,
        "base_uncertainty_us": 230,
    }


@pytest.mark.parametrize("field", [*OVERRIDES, "expected", "accepted", "error",
                                  "offset_interval_us", "offset_midpoint_us",
                                  "raw_lower_us", "raw_upper_us", "padding_us"])
def test_raw_boundary_rejects_assertion_fields(field: str) -> None:
    assert clock.derive_clock_mapping({**GOLDEN, field: 0}, GUARDS)["error"] == (
        "E_INVALID_RAW_CLOCK_INPUT"
    )


def test_stored_values_are_checked_without_overriding_raw_result() -> None:
    derived = clock.derive_clock_mapping(GOLDEN, GUARDS)
    assert clock.validate_stored_mapping(derived, GOLDEN, GUARDS) == derived
    for field, value in [("network_rtt_us", 1), ("offset_midpoint_us", 5001),
                         ("base_uncertainty_us", 0), ("padding_us", 0),
                         ("offset_interval_us", [100, 101])]:
        result = clock.validate_stored_mapping({field: value}, GOLDEN, GUARDS)
        assert result["error"] == "E_STORED_MAPPING_MISMATCH", field
        assert result["network_rtt_us"] == 400
        assert result["offset_interval_us"] == [4770, 5230]
    assert clock.validate_stored_mapping(OVERRIDES, BYPASS, GUARDS)["error"] == (
        "E_MAX_NETWORK_RTT_EXCEEDED"
    )


@pytest.mark.parametrize(("stored", "error"), [
    ({"offset_lower_us": 5230, "offset_upper_us": 4770}, "E_INVERTED_OFFSET_INTERVAL"),
    ({"network_rtt_us": 250001}, "E_MAX_NETWORK_RTT_EXCEEDED"),
    ({"base_uncertainty_us": 125001}, "E_MAX_BASE_UNCERTAINTY_EXCEEDED"),
    ({"network_rtt_us": True}, "E_STORED_MAPPING_MISMATCH"),
    ({"offset_interval_us": [1]}, "E_STORED_MAPPING_MISMATCH"),
    ({"expected": {"accepted": True}}, "E_STORED_MAPPING_MISMATCH"),
    ({}, "E_STORED_MAPPING_MISMATCH"),
])
def test_stored_corruption_family(stored: dict[str, object], error: str) -> None:
    actual = clock.validate_stored_mapping(stored, GOLDEN, GUARDS)
    assert actual["error"] == error
    assert actual["accepted"] is False
    assert actual["network_rtt_us"] == 400
    assert actual["offset_interval_us"] == [4770, 5230]


def test_expected_metadata_cannot_change_adapter_result() -> None:
    assert clock.evaluate_clock_mapping_vector(
        {**GOLDEN, "id": "ARBITRARY", "expected": {"accepted": False, "network_rtt_us": 0}},
        GUARDS,
    ) == clock.derive_clock_mapping(GOLDEN, GUARDS)


@pytest.mark.parametrize("shift", [0, -10000, 2**60, -(2**60)])
def test_odd_width_fraction_oracle_and_large_integers(shift: int) -> None:
    # Independent endpoint oracle: 401us RTT + 60us padding has width 461.
    raw = {**GOLDEN, "t2": 1005200 + shift, "t3": 1005300 + shift, "t4": 1000501}
    result = clock.derive_clock_mapping(raw, GUARDS)
    lower, upper = 4769 + shift, 5230 + shift
    center = Fraction(lower + upper, 2)
    radius = Fraction(upper - lower, 2)
    assert result["accepted"] is True
    assert result["network_rtt_us"] == 401
    assert result["offset_interval_us"] == [lower, upper]
    assert result["offset_midpoint_us"] == center.numerator // center.denominator
    assert result["base_uncertainty_us"] == 231
    assert Fraction(231) >= radius + abs(center - result["offset_midpoint_us"])


@pytest.mark.parametrize(("mutation", "error"), [
    ({"t3": 0, "t4": 0, "t3_unit": "SECOND"}, "E_NEGATIVE_TARGET_ORDER"),
    ({"t4": 0, "t4_boot_id": "bad"}, "E_NEGATIVE_SOURCE_ORDER"),
    ({"t3": 2000000, "t4_clock_domain_id": "bad"}, "E_NEGATIVE_NETWORK_RTT"),
    ({"t4_clock_domain_id": "bad", "t3_unit": "SECOND"}, "E_SOURCE_DOMAIN_MISMATCH"),
    ({"t3_clock_domain_id": "bad", "t4_boot_id": "bad"}, "E_TARGET_DOMAIN_MISMATCH"),
    ({"t3_boot_id": "bad", "t3_unit": "SECOND"}, "E_BOOT_MISMATCH"),
    ({"t1_unit": "SECOND", "t2_owner": "bad"}, "E_UNIT_NOT_MICROSECOND"),
    ({"t4_owner": "bad"}, "E_TIMESTAMP_OWNER_MISMATCH"),
])
def test_exact_first_error(mutation: dict[str, object], error: str) -> None:
    assert clock.derive_clock_mapping({**GOLDEN, **mutation}, GUARDS)["error"] == error


def test_unknown_source_age_and_nested_validation() -> None:
    raw = deepcopy(GOLDEN)
    raw["source"]["owner"] = "CDP_BROWSER"
    for extra in ({}, {"proven_mapping": False}):
        result = clock.derive_clock_mapping({**raw, **extra}, GUARDS)
        assert result["error"] == "SOURCE_AGE_UNKNOWN"
        assert result["accepted"] is False
    for source in ({**GOLDEN["source"], "unit": "SECOND"},
                   {**GOLDEN["source"], "boot_id": ""}):
        assert clock.derive_clock_mapping({**GOLDEN, "source": source}, GUARDS)["accepted"] is False


@pytest.mark.parametrize("value", [True, 1.5, "1000000", None])
def test_invalid_timestamp_type_is_rejected(value: object) -> None:
    assert clock.derive_clock_mapping({**GOLDEN, "t1": value}, GUARDS)["error"] == (
        "E_INVALID_RAW_CLOCK_INPUT"
    )


def test_invalid_resolution_and_guardrail_are_rejected() -> None:
    assert clock.derive_clock_mapping(
        {**GOLDEN, "source": {**GOLDEN["source"], "resolution_us": -1}}, GUARDS,
    )["error"] == "E_INVALID_RAW_CLOCK_INPUT"
    assert clock.derive_clock_mapping(GOLDEN, {**GUARDS, "max_network_rtt_us": -1})[
        "error"
    ] == "E_INVALID_RAW_CLOCK_INPUT"
