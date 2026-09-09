from decimal import Decimal
from uuid import uuid4

import pytest

from moj_discovery.providers.poll_budget import PollSegment, estimate_requests
from moj_discovery.providers.quota import Denied, QuotaLedger

HEADERS = {
    "x-ratelimit-requests-limit": "7500",
    "x-ratelimit-requests-remaining": "7499",
    "x-ratelimit-limit": "300",
    "x-ratelimit-remaining": "299",
}


def test_budget_oracle_concurrent_sequential_and_fallback():
    for n in [1, 3, 5]:
        b = estimate_requests([PollSegment(0, 7200, 15)] * n, 3, 2, 0, Decimal("0.20"))
        assert (b.periodic, b.calls, b.with_reserve) == (480, 485, 582)
    b = estimate_requests(
        [PollSegment(i * 7200, (i + 1) * 7200, 15) for i in range(5)], 15, 10, 0, Decimal("0.20")
    )
    assert b.calls == 2425
    assert estimate_requests([PollSegment(0, 7200, 15)], 3, 2, 600, Decimal("0.20")).calls == 1085
    assert (
        estimate_requests(
            [PollSegment(0, 600, 60), PollSegment(600, 6600, 15), PollSegment(6600, 7500, 60)],
            3,
            2,
            0,
            Decimal("0.20"),
        ).calls
        == 430
    )


def test_union_and_half_open():
    assert estimate_requests([PollSegment(0, 15, 15)], 0, 0, 0, Decimal(0)).calls == 1
    assert (
        estimate_requests(
            [PollSegment(0, 60, 15), PollSegment(1, 61, 15)], 0, 0, 0, Decimal(0)
        ).calls
        == 5
    )
    assert estimate_requests([PollSegment(0, 0, 15)], 0, 0, 0, Decimal(0)).calls == 0


@pytest.mark.parametrize(
    "segment",
    [
        PollSegment(0, -1, 15),
        PollSegment(0, 1, 0),
        PollSegment(True, 20, 15),
        PollSegment(0, 20, 1.5),
    ],
)
def test_invalid_interval(segment):
    with pytest.raises(ValueError):
        estimate_requests([segment], 0, 0, 0, Decimal("0.20"))


@pytest.mark.parametrize("reserve", ["NaN", "Infinity", "-0.1", "1.1"])
def test_invalid_reserve(reserve):
    with pytest.raises(ValueError):
        estimate_requests([], 0, 0, 0, Decimal(reserve))


def ledger(tmp_path, **kwargs):
    return QuotaLedger(
        tmp_path / "quota.sqlite3", scope_id=str(uuid4()), allow_status_bootstrap=True, **kwargs
    )


def reserve(q, clock, purpose="BUNDLE"):
    return q.reserve_attempt(q.scope_id, purpose, clock.utc, clock.mono)


def bootstrap(q, clock):
    attempt = reserve(q, clock, "STATUS")
    assert not isinstance(attempt, Denied)
    q.finalize_attempt(attempt.attempt_id, "SUCCESS", HEADERS)
    clock.advance(10)


def test_bootstrap_and_missing_quota_are_fail_closed(tmp_path, fake_clock):
    with ledger(tmp_path) as q:
        assert reserve(q, fake_clock).code == "QUOTA_UNKNOWN"
        a = reserve(q, fake_clock, "STATUS")
        assert not isinstance(a, Denied)
        assert reserve(q, fake_clock).code == "IN_FLIGHT"
        q.finalize_attempt(a.attempt_id, "TIMEOUT", {})
        fake_clock.advance(10)
        assert reserve(q, fake_clock).code == "QUOTA_UNKNOWN"
        assert isinstance(reserve(q, fake_clock, "STATUS"), Denied)
        assert q.count_attempts() == 1


def test_every_failed_attempt_and_session_cap(tmp_path, fake_clock):
    with ledger(tmp_path, session_cap=4) as q:
        bootstrap(q, fake_clock)
        for outcome in ["HTTP_5XX", "HTTP_429", "TIMEOUT"]:
            a = reserve(q, fake_clock)
            assert not isinstance(a, Denied)
            q.finalize_attempt(a.attempt_id, outcome, {})
            fake_clock.advance(10)
        assert reserve(q, fake_clock).code == "SESSION_BUDGET"
        assert q.count_attempts() == 4
        assert q.db.execute("SELECT count(*) FROM quota_reservations").fetchone()[0] == 4


def test_gap_and_sliding_minute(tmp_path, fake_clock):
    with ledger(tmp_path, minute_cap=3) as q:
        bootstrap(q, fake_clock)
        for _ in range(2):
            a = reserve(q, fake_clock)
            q.finalize_attempt(a.attempt_id, "SUCCESS", {})
            assert reserve(q, fake_clock).code == "MINIMUM_GAP"
            fake_clock.advance(10)
        assert reserve(q, fake_clock).code == "MINUTE_BUDGET"
        fake_clock.advance(30)
        assert not isinstance(reserve(q, fake_clock), Denied)


def test_provider_reserve_is_fixed_share_not_compounded(tmp_path, fake_clock):
    with ledger(tmp_path) as q:
        a = reserve(q, fake_clock, "STATUS")
        q.finalize_attempt(
            a.attempt_id,
            "SUCCESS",
            {
                "X-RateLimit-Requests-Limit": "100",
                "X-RateLimit-Requests-Remaining": "22",
                "x-ratelimit-limit": "10",
                "x-ratelimit-remaining": "9",
            },
        )
        for _ in range(2):
            fake_clock.advance(10)
            a = reserve(q, fake_clock)
            assert not isinstance(a, Denied)
            q.finalize_attempt(a.attempt_id, "SUCCESS", {})
        fake_clock.advance(10)
        assert reserve(q, fake_clock).code == "PROVIDER_DAILY_RESERVE"


def test_day_rollover_requires_provider_reconciliation(tmp_path, fake_clock):
    with ledger(tmp_path) as q:
        bootstrap(q, fake_clock)
        fake_clock.advance(86400)
        assert reserve(q, fake_clock).code == "QUOTA_RECONCILIATION_REQUIRED"
        a = reserve(q, fake_clock, "STATUS")
        q.finalize_attempt(a.attempt_id, "SUCCESS", HEADERS)
        fake_clock.advance(10)
        assert not isinstance(reserve(q, fake_clock), Denied)


def test_wall_clock_rollback_no_new_allowance(tmp_path, fake_clock):
    from datetime import timedelta

    with ledger(tmp_path) as q:
        bootstrap(q, fake_clock)
        fake_clock.utc -= timedelta(hours=2)
        assert reserve(q, fake_clock).code == "CLOCK_ROLLBACK"


@pytest.mark.parametrize(
    "headers",
    [
        {"x-ratelimit-requests-limit": "7500"},
        {**HEADERS, "x-ratelimit-requests-remaining": "secret_bad_number"},
        {**HEADERS, "x-ratelimit-requests-remaining": "8000"},
    ],
)
def test_invalid_quota_headers_block_polling(tmp_path, fake_clock, headers):
    with ledger(tmp_path) as q:
        a = reserve(q, fake_clock, "STATUS")
        q.finalize_attempt(a.attempt_id, "SUCCESS", headers)
        fake_clock.advance(10)
        assert isinstance(reserve(q, fake_clock), Denied)


def test_unexplained_remaining_increase_requires_status(tmp_path, fake_clock):
    with ledger(tmp_path) as q:
        bootstrap(q, fake_clock)
        a = reserve(q, fake_clock)
        q.finalize_attempt(
            a.attempt_id, "SUCCESS", {**HEADERS, "x-ratelimit-requests-remaining": "7500"}
        )
        fake_clock.advance(10)
        assert reserve(q, fake_clock).code == "QUOTA_RECONCILIATION_REQUIRED"


def test_provider_minute_limit_remains_distinct_from_daily(tmp_path, fake_clock):
    with ledger(tmp_path) as q:
        a = reserve(q, fake_clock, "STATUS")
        q.finalize_attempt(
            a.attempt_id,
            "SUCCESS",
            {**HEADERS, "x-ratelimit-limit": "1", "x-ratelimit-remaining": "1"},
        )
        fake_clock.advance(10)
        assert reserve(q, fake_clock).code == "PROVIDER_MINUTE_BUDGET"
        fake_clock.advance(51)
        assert not isinstance(reserve(q, fake_clock), Denied)


def test_auth_failure_never_becomes_quota_retry(tmp_path, fake_clock):
    with ledger(tmp_path) as q:
        a = reserve(q, fake_clock, "STATUS")
        q.finalize_attempt(
            a.attempt_id, "AUTH_FAILED", {"x-ratelimit-requests-limit": "TEST_ONLY_INVALID"}
        )
        fake_clock.advance(60)
        assert reserve(q, fake_clock, "STATUS").code == "AUTH_FAILED"
