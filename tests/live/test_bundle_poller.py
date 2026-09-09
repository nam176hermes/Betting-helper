import copy
import threading
from datetime import timedelta
from uuid import uuid4

import pytest

from moj_discovery.provider_protocol import ProviderScope
from moj_discovery.providers.api_football import ProviderError, ProviderResponse
from moj_discovery.providers.bundle_poller import ProviderBundlePoller


class FixtureHTTP:
    def __init__(self, clock, template, ids=(101,), statuses=None):
        self.clock = clock
        self.scope = ProviderScope(
            str(uuid4()), ids, 999, 2026, 7200, stage="LIVE_READ_ONLY", max_attempts=600
        )
        self.template = template
        self.statuses = statuses or {}
        self.calls = []
        self.error = None
        self.delay = 0
        self.in_flight = 0
        self.maximum_in_flight = 0
        self.before_reply = None

    def get_fixture_bundle(self, ids):
        self.calls.append((self.clock.mono, tuple(ids)))
        self.in_flight += 1
        self.maximum_in_flight = max(self.maximum_in_flight, self.in_flight)
        try:
            if self.before_reply:
                self.before_reply()
            self.clock.advance(self.delay)
            if self.error:
                raise ProviderError(self.error)
            rows = []
            for fixture_id in ids:
                status = self.statuses.get(fixture_id, "1H")
                if status == "MISSING":
                    continue
                row = copy.deepcopy(self.template["response"][0])
                row["fixture"]["id"] = fixture_id
                row["fixture"]["status"]["short"] = status
                rows.append(row)
            return ProviderResponse(str(uuid4()), "MOCK", "BUNDLE", tuple(rows))
        finally:
            self.in_flight -= 1


def scheduler(clock, template, ids=(101,), statuses=None):
    http = FixtureHTTP(clock, template, ids, statuses)
    poller = ProviderBundlePoller(http, now_mono=lambda: clock.mono, now_utc=lambda: clock.utc)
    poller.set_watchlist(ids, 1)
    return poller, http


def test_adaptive_union_and_panel_reopen(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response, (101, 103), {103: "HT"})
    assert poller.tick(0).status == "UPDATED"
    for _second in range(1, 61):
        fake_clock.advance(1)
        poller.set_watchlist([103, 101, 101], 1)
        poller.request_refresh()
        poller.tick(fake_clock.mono)
    assert http.calls == [(n, (101, 103)) for n in [0, 15, 30, 45, 60]]
    http.statuses[101] = "HT"
    fake_clock.advance(15)
    assert poller.tick(75).next_due_mono == 135


@pytest.mark.parametrize("before,period", [(900, 60), (600, 60), (599, 30), (0, 30)])
def test_pregame_deadline(fake_clock, synthetic_provider_response, before, period):
    fake_clock.utc -= timedelta(seconds=before)
    poller, _ = scheduler(fake_clock, synthetic_provider_response, statuses={101: "NS"})
    assert poller.tick(0).next_due_mono == period


def test_terminal_checks_are_anchored_and_stop(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response, statuses={101: "FT"})
    for second in range(181):
        fake_clock.advance(second - fake_clock.mono)
        poller.tick(fake_clock.mono)
    assert [time for time, _ in http.calls] == [0, 30, 120]
    assert poller.tick(180).stopped_ids == {101: "TERMINAL_CONFIRMED"}


def test_terminal_joins_existing_batch_without_early_confirmation(
    fake_clock, synthetic_provider_response
):
    poller, http = scheduler(fake_clock, synthetic_provider_response, (101, 103), {103: "FT"})
    for second in range(151):
        fake_clock.advance(second - fake_clock.mono)
        poller.tick(fake_clock.mono)
    assert all(103 in ids for time, ids in http.calls if time <= 120)
    assert all(ids == (101,) for time, ids in http.calls if time > 120)


@pytest.mark.parametrize(
    "status", ["PST", "CANC", "ABD", "AWD", "WO", "ET", "BT", "P", "AET", "PEN"]
)
def test_unsupported_period_stops_without_settlement(
    fake_clock, synthetic_provider_response, status
):
    poller, http = scheduler(fake_clock, synthetic_provider_response, statuses={101: status})
    result = poller.tick(0)
    assert result.projection.states[101]["period"] == "OUT_OF_SCOPE"
    fake_clock.advance(600)
    assert poller.tick(600).status == "STOPPED"
    assert len(http.calls) == 1


def test_unknown_period_is_bounded(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response, statuses={101: "LIVE"})
    for second in range(601):
        fake_clock.advance(second - fake_clock.mono)
        poller.tick(fake_clock.mono)
    assert len(http.calls) == 5
    assert poller.tick(600).stopped_ids == {101: "UNKNOWN_PERIOD_TIMEOUT"}


def test_slow_io_and_sleep_never_catch_up(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response)
    http.delay = 21
    assert poller.tick(0).next_due_mono == 36
    assert poller.tick(21).status == "WAIT"
    fake_clock.advance(300)
    result = poller.tick(fake_clock.mono)
    assert result.wake_gap is True and len(http.calls) == 2
    assert poller.tick(fake_clock.mono).status == "WAIT"


def test_inflight_request_has_one_owner(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response)
    started, release = threading.Event(), threading.Event()

    def blocked():
        started.set()
        assert release.wait(3)

    http.before_reply = blocked
    worker = threading.Thread(target=lambda: poller.tick(0))
    worker.start()
    try:
        assert started.wait(3)
        assert poller.tick(0).reason == "IN_FLIGHT"
        poller.stop("USER_STOP")
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert http.maximum_in_flight == 1
    assert poller.tick(0).status == "STOPPED"


@pytest.mark.parametrize("code", ["SESSION_BUDGET", "QUOTA_UNKNOWN", "AUTH_FAILED", "SECRET_ECHO"])
def test_budget_and_safety_failures_hold_last_data(fake_clock, synthetic_provider_response, code):
    poller, http = scheduler(fake_clock, synthetic_provider_response)
    first = poller.tick(0).projection.states[101]
    http.error = code
    fake_clock.advance(15)
    assert poller.tick(15).status == "PAUSED"
    assert poller.last_states[101] == first
    fake_clock.advance(60)
    assert poller.tick(75).status == "PAUSED"
    assert len(http.calls) == 2


def test_failed_cycles_open_circuit_then_require_restart(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response)
    http.error = "HTTP_429"
    assert poller.tick(0).status == "STALE"
    fake_clock.advance(59)
    assert poller.tick(59).status == "WAIT"
    fake_clock.advance(1)
    assert poller.tick(60).status == "STALE"
    fake_clock.advance(60)
    assert poller.tick(120).status == "PAUSED"
    fake_clock.advance(600)
    assert poller.tick(720).status == "PAUSED"
    assert len(http.calls) == 3


def test_missing_member_does_not_erase_or_activate_fallback(
    fake_clock, synthetic_provider_response
):
    poller, http = scheduler(fake_clock, synthetic_provider_response, (101, 103))
    first = poller.tick(0).projection.states[103]
    http.statuses[103] = "MISSING"
    fake_clock.advance(15)
    result = poller.tick(15)
    assert result.stale_ids == (103,)
    assert poller.last_states[103] == first
    assert not http.scope.events_fixture_ids


def test_watchlist_revisions_and_authority_are_bounded(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response, (101, 103))
    poller.tick(0)
    for ids, rev in [([999], 2), ([True], 2), ([101], 1), ([101], 0)]:
        with pytest.raises(ValueError):
            poller.set_watchlist(ids, rev)
    poller.set_watchlist([101], 2)
    fake_clock.advance(15)
    poller.tick(15)
    assert http.calls[-1][1] == (101,)
    with pytest.raises(ValueError):
        poller.set_watchlist([101, 103], 1)


def test_deadline_and_clock_rollback_fail_closed(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response)
    poller.tick(0)
    fake_clock.advance(20)
    poller.tick(20)
    fake_clock.advance(-1)
    assert poller.tick(19).reason == "CLOCK_ERROR"
    other, http2 = scheduler(fake_clock, synthetic_provider_response)
    fake_clock.advance(7200 - fake_clock.mono)
    assert other.tick(7200).reason == "RUN_DEADLINE"
    assert not http2.calls


def test_sleep_past_ft_checks_is_not_catchup_or_confirmed(fake_clock, synthetic_provider_response):
    poller, http = scheduler(fake_clock, synthetic_provider_response, statuses={101: "FT"})
    poller.tick(0)
    fake_clock.advance(600)
    result = poller.tick(600)
    assert result.stopped_ids == {101: "TERMINAL_CONFIRMATION_MISSED"}
    fake_clock.advance(10)
    assert poller.tick(610).status == "STOPPED"
    assert len(http.calls) == 2


def test_real_client_retries_feed_shared_circuit(tmp_path, fake_clock, synthetic_provider_response):
    from test_api_football import STATUS, Reply, make_client

    replies = (
        [Reply(STATUS)]
        + [Reply({}, status=429, headers={"Retry-After": "75"}) for _ in range(3)]
        + [Reply(synthetic_provider_response)]
    )
    client, quota, http = make_client(tmp_path, fake_clock, replies)
    with quota, client:
        client.get_status()
        poller = ProviderBundlePoller(
            client, now_mono=lambda: fake_clock.mono, now_utc=lambda: fake_clock.utc
        )
        poller.set_watchlist([101], 1)
        assert poller.tick(0).status == "STALE"
        assert fake_clock.mono == 160
        fake_clock.advance(60)
        assert poller.tick(220).status == "WAIT"
        fake_clock.advance(15)
        assert poller.tick(235).status == "UPDATED"
        assert len(http.calls) == quota.count_attempts() == 5
