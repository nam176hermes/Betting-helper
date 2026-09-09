"""Request-count arithmetic, not provider billing or a source-latency guarantee."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal


@dataclass(frozen=True)
class PollSegment:
    start_seconds: int
    end_seconds: int
    interval_seconds: int


@dataclass(frozen=True)
class BudgetEstimate:
    periodic: int
    overhead: int
    fallback: int
    calls: int
    with_reserve: int


def estimate_requests(
    segments: Sequence[PollSegment],
    setup: int = 3,
    confirmations: int = 2,
    fallback_calls: int = 0,
    reserve_fraction: Decimal = Decimal("0.20"),
) -> BudgetEstimate:
    if any(type(v) is not int or v < 0 for v in (setup, confirmations, fallback_calls)):
        raise ValueError("E_BUDGET_COUNT")
    if (
        not isinstance(reserve_fraction, Decimal)
        or not reserve_fraction.is_finite()
        or not 0 <= reserve_fraction <= 1
    ):
        raise ValueError("E_BUDGET_RESERVE")
    for s in segments:
        if (
            any(type(v) is not int for v in (s.start_seconds, s.end_seconds, s.interval_seconds))
            or not 0 <= s.start_seconds <= s.end_seconds
            or s.interval_seconds <= 0
        ):
            raise ValueError("E_BUDGET_INTERVAL")
    boundaries = sorted({v for s in segments for v in (s.start_seconds, s.end_seconds)})
    merged: list[PollSegment] = []
    # ponytail: quadratic in plan segments (a handful per fixture); sweep-line if plans grow.
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        active = [
            s.interval_seconds
            for s in segments
            if s.start_seconds <= start and s.end_seconds >= end
        ]
        if not active:
            continue
        interval = min(active)
        if merged and merged[-1].end_seconds == start and merged[-1].interval_seconds == interval:
            merged[-1] = PollSegment(merged[-1].start_seconds, end, interval)
        else:
            merged.append(PollSegment(start, end, interval))
    periodic = sum(
        (s.end_seconds - s.start_seconds + s.interval_seconds - 1) // s.interval_seconds
        for s in merged
    )
    calls = periodic + setup + confirmations + fallback_calls
    with_reserve = int(
        (Decimal(calls) * (1 + reserve_fraction)).to_integral_value(rounding=ROUND_CEILING)
    )
    return BudgetEstimate(periodic, setup + confirmations, fallback_calls, calls, with_reserve)
