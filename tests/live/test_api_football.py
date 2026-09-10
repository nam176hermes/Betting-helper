import copy
import io
import json
from typing import Any
from uuid import uuid4

import pytest

from moj_discovery.provider_protocol import ProviderScope
from moj_discovery.providers.api_football import ApiFootballClient, ProviderError
from moj_discovery.providers.quota import QuotaLedger
from moj_discovery.secrets_local import SecretValue

QUOTA = {
    "x-ratelimit-requests-limit": "7500",
    "x-ratelimit-requests-remaining": "7499",
    "x-ratelimit-limit": "300",
    "x-ratelimit-remaining": "299",
}
STATUS = {
    "errors": [],
    "results": 1,
    "paging": {"current": 1, "total": 1},
    "response": {
        "account": {"email": "PRIVATE_NOT_RETAINED"},
        "subscription": {"plan": "Pro", "active": True, "end": "2026-12-31"},
        "requests": {"current": 1, "limit_day": 7500},
    },
}


class Reply(io.BytesIO):
    def __init__(self, body: Any, status: Any = 200, headers: Any = None, url: Any = None) -> None:
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())
        self.status = status
        self.headers = {**QUOTA, **(headers or {})}
        self.url = url

    def geturl(self) -> Any:
        return self.url


class MockHTTP:
    def __init__(self, replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[Any] = []

    def open(self, request: Any, timeout: Any) -> Any:
        self.calls.append((request, timeout))
        result = self.replies.pop(0)
        if isinstance(result, BaseException):
            raise result
        if result.url is None:
            result.url = request.full_url
        return result


def make_client(tmp_path: Any, clock: Any, replies: Any, **scope_values: Any) -> Any:
    scope = ProviderScope(str(uuid4()), (101, 103), 999, 2026, clock.mono + 300, **scope_values)
    quota = QuotaLedger(
        tmp_path / "quota.sqlite3",
        scope_id=scope.scope_id,
        session_cap=20,
        allow_status_bootstrap=True,
    )
    http = MockHTTP(replies)
    client = ApiFootballClient(
        SecretValue("TEST_ONLY_HTTP_KEY"),
        quota,
        scope,
        opener=http,
        now_mono=lambda: clock.mono,
        now_utc=lambda: clock.utc,
        sleep=clock.advance,
    )
    return client, quota, http


def test_status_projection_and_sorted_bundle(
    tmp_path: Any, fake_clock: Any, synthetic_provider_response: Any
) -> None:
    client, q, http = make_client(
        tmp_path, fake_clock, [Reply(STATUS), Reply(synthetic_provider_response)]
    )
    with q, client:
        status = client.get_status()
        assert status.plan == "PRO"
        assert "PRIVATE_NOT_RETAINED" not in repr(status)
        response = client.get_fixture_bundle([103, 101, 103])
        request, timeout = http.calls[-1]
        assert request.full_url == "https://v3.football.api-sports.io/fixtures?ids=101-103"
        assert request.get_header("X-apisports-key") == "TEST_ONLY_HTTP_KEY"
        assert request.get_header("Accept-encoding") == "identity"
        assert request.get_method() == "GET" and timeout <= 10
        assert response.missing_ids == (103,)
        assert response.source_kind == "MOCK"
        assert q.count_attempts() == 2


@pytest.mark.parametrize("change", ["unexpected", "duplicate", "bool", "pages", "errors"])
def test_bad_bundle_rejects(
    tmp_path: Any, fake_clock: Any, synthetic_provider_response: Any, change: Any
) -> None:
    bad = copy.deepcopy(synthetic_provider_response)
    if change == "unexpected":
        bad["response"][0]["fixture"]["id"] = 500
    if change == "bool":
        bad["response"][0]["fixture"]["id"] = True
    if change == "duplicate":
        bad["response"] *= 2
        bad["results"] = 2
    if change == "pages":
        bad["paging"]["total"] = 2
    if change == "errors":
        bad["errors"] = {"parameters": "PRIVATE_ERROR_TEXT"}
    client, q, _ = make_client(tmp_path, fake_clock, [Reply(STATUS), Reply(bad)])
    with q, client:
        client.get_status()
        with pytest.raises(ProviderError) as error:
            client.get_fixture_bundle([101, 103])
        assert "PRIVATE_ERROR_TEXT" not in str(error.value)
        assert q.count_attempts() == 2


def test_auth_failure_zero_retries(tmp_path: Any, fake_clock: Any) -> None:
    client, q, http = make_client(tmp_path, fake_clock, [Reply({}, status=401)])
    with q, client:
        for _ in range(2):
            with pytest.raises(ProviderError, match="AUTH_FAILED"):
                client.get_status()
        assert len(http.calls) == q.count_attempts() == 1


def test_http200_auth_body_stops(tmp_path: Any, fake_clock: Any) -> None:
    client, q, http = make_client(
        tmp_path, fake_clock, [Reply({**STATUS, "errors": {"token": "TEST_ONLY_HTTP_KEY"}})]
    )
    with q, client:
        with pytest.raises(ProviderError):
            client.get_status()
        assert len(http.calls) == 1


def test_timeout_retries_all_reserved(
    tmp_path: Any, fake_clock: Any, synthetic_provider_response: Any
) -> None:
    client, q, http = make_client(
        tmp_path,
        fake_clock,
        [Reply(STATUS), TimeoutError(), Reply({}, status=500), Reply(synthetic_provider_response)],
    )
    with q, client:
        client.get_status()
        result = client.get_fixture_bundle([101])
        assert result.attempts == 3
        assert len(http.calls) == q.count_attempts() == 4
        assert fake_clock.mono >= 30


def test_429_retry_after_honored(
    tmp_path: Any, fake_clock: Any, synthetic_provider_response: Any
) -> None:
    client, q, http = make_client(
        tmp_path,
        fake_clock,
        [
            Reply(STATUS),
            Reply({}, status=429, headers={"Retry-After": "75"}),
            Reply(synthetic_provider_response),
        ],
    )
    with q, client:
        client.get_status()
        client.get_fixture_bundle([101])
        assert fake_clock.mono >= 85
        assert len(http.calls) == q.count_attempts() == 3


def test_fallback_and_lookup_default_off(tmp_path: Any, fake_clock: Any) -> None:
    client, q, http = make_client(tmp_path, fake_clock, [])
    with q, client:
        with pytest.raises(ProviderError):
            client.get_events(101)
        with pytest.raises(ProviderError):
            client.get_fixtures_for_date(999, 2026, "2026-09-09")
        assert http.calls == [] and q.count_attempts() == 0


def test_scope_invalid_ids_never_reach_io(tmp_path: Any, fake_clock: Any) -> None:
    client, q, http = make_client(tmp_path, fake_clock, [])
    with q, client:
        for ids in [[], [True], [1.0], [0], [500], list(range(1, 22))]:
            with pytest.raises(ProviderError):
                client.get_fixture_bundle(ids)
        assert http.calls == [] and q.count_attempts() == 0


def test_coverage_and_bounded_lookup_cache(
    tmp_path: Any, fake_clock: Any, synthetic_provider_response: Any
) -> None:
    coverage = {
        "errors": {},
        "results": 1,
        "paging": {"current": 1, "total": 1},
        "response": [
            {
                "league": {"id": 999},
                "seasons": [
                    {"year": 2026, "coverage": {"fixtures": {"events": True, "lineups": False}}}
                ],
            }
        ],
    }
    client, q, http = make_client(
        tmp_path,
        fake_clock,
        [Reply(STATUS), Reply(coverage), Reply(synthetic_provider_response)],
        lookup_date="2026-09-09",
    )
    with q, client:
        client.get_status()
        first = client.get_coverage(999, 2026)
        assert first["coverage"]["events"] is True
        assert first["coverage"]["statistics_fixtures"] is None
        assert client.get_coverage(999, 2026) == first
        result = client.get_fixtures_for_date(999, 2026, "2026-09-09")
        assert client.get_fixtures_for_date(999, 2026, "2026-09-09") == result
        assert len(http.calls) == q.count_attempts() == 3


def test_explicit_mock_event_comparison(tmp_path: Any, fake_clock: Any) -> None:
    events = {
        "errors": [],
        "results": 1,
        "paging": {"current": 1, "total": 1},
        "response": [
            {
                "time": {"elapsed": 10, "extra": None},
                "type": "Goal",
                "detail": "Normal Goal",
                "team": {"id": 201},
                "player": {"id": 555, "name": "PRIVATE_NOT_RETAINED"},
                "assist": {"id": None},
            }
        ],
    }
    client, q, http = make_client(
        tmp_path, fake_clock, [Reply(STATUS), Reply(events)], events_fixture_ids=(101,)
    )
    with q, client:
        client.get_status()
        result = client.get_events(101)
        assert result.rows[0]["player"] == {"id": 555}
        assert "PRIVATE_NOT_RETAINED" not in repr(result.rows)
        assert len(http.calls) == 2


def test_schema_failure_stops_request_family(tmp_path: Any, fake_clock: Any) -> None:
    client, q, http = make_client(tmp_path, fake_clock, [Reply(STATUS), Reply({})])
    with q, client:
        client.get_status()
        for _ in range(2):
            with pytest.raises(ProviderError):
                client.get_fixture_bundle([101])
        assert len(http.calls) == 2
