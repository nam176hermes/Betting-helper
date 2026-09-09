from dataclasses import replace

import pytest
from test_bundle_poller import FixtureHTTP, scheduler

from moj_discovery.providers.bundle_poller import ProviderBundlePoller
from moj_discovery.providers.poll_budget import PollSegment, estimate_requests


@pytest.mark.parametrize("count", [1, 3, 5])
def test_two_hour_concurrent_union_is_480(fake_clock, synthetic_provider_response, count):
    ids = tuple(range(101, 101 + count))
    poller, http = scheduler(fake_clock, synthetic_provider_response, ids)
    for second in range(7200):
        fake_clock.advance(second - fake_clock.mono)
        poller.tick(float(second))
    assert len(http.calls) == 480
    assert http.maximum_in_flight == 1
    assert all(observed == ids for _, observed in http.calls)


def test_staggered_union_counts_active_windows(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response, (101, 103))
    poller.set_watchlist([101], 2)
    for second in range(180):
        fake_clock.advance(second - fake_clock.mono)
        if second == 60:
            poller.set_watchlist([101, 103], 3)
        if second == 120:
            poller.set_watchlist([103], 4)
        poller.tick(float(second))
    assert len(http.calls) == 12
    assert (
        len(http.calls)
        == estimate_requests(
            [PollSegment(0, 120, 15), PollSegment(60, 180, 15)], setup=0, confirmations=0
        ).periodic
    )


def test_fallback_insufficient_budget_rejected_before_io(fake_clock, synthetic_provider_response):
    http = FixtureHTTP(fake_clock, synthetic_provider_response, (101, 102, 103, 104, 105))
    http.scope = replace(http.scope, events_fixture_ids=http.scope.fixture_ids)
    with pytest.raises(ValueError, match="FALLBACK_BUDGET"):
        ProviderBundlePoller(http, now_mono=lambda: fake_clock.mono, now_utc=lambda: fake_clock.utc)
    assert not http.calls
