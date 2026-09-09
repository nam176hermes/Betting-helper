"""Fixed API-Football GET client. All calls share one reservation ledger and owner."""

import copy
import re
import ssl
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

from ..canonical import parse_strict_json
from ..provider_protocol import ProviderScope, verify_call_authorization, verify_probe_protocol
from ..secrets_local import SecretValue
from .quota import HEADER_NAMES, Denied, QuotaLedger

BASE = "https://v3.football.api-sports.io"
MAX_BODY = 8 * 1024 * 1024


class ProviderError(ValueError):
    def __init__(self, code: str, retry_after: float | None = None):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def build_fixed_opener() -> OpenerDirector:
    context = ssl.create_default_context()
    context.set_alpn_protocols(["http/1.1"])
    return build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))


def retry_after_seconds(value: str | None, now: datetime) -> float:
    try:
        if value is None or len(value) > 128:
            return 60
        if re.fullmatch(r"[0-9]{1,10}", value):
            return float(value)
        stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is None:
            return 60
        return max(0, (stamp - now).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 60


@dataclass(frozen=True)
class SafeStatus:
    plan: str
    active: bool
    expires_on: str | None
    daily_limit: int | None
    daily_remaining: int | None


@dataclass(frozen=True)
class ProviderResponse:
    request_id: str
    source_kind: str
    purpose: str
    rows: tuple[dict[str, Any], ...] = field(repr=False)
    missing_ids: tuple[int, ...] = ()
    attempts: int = 1


def _positive_id(value: object) -> int:
    if type(value) is not int or not 0 < value <= 2**53 - 1:
        raise ProviderError("PARAMETER_ERROR")
    return value


def _select(value: object, keys: Sequence[str]) -> dict[str, Any]:
    if type(value) is not dict:
        return {}
    return {key: copy.deepcopy(value[key]) for key in keys if key in value}


def _fixture_fields(raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "fixture": _select(raw.get("fixture"), ("id", "date", "timestamp")),
        "league": _select(raw.get("league"), ("id", "season")),
        "teams": {},
        "goals": _select(raw.get("goals"), ("home", "away")),
        "score": {},
    }
    result["fixture"]["status"] = _select(
        raw.get("fixture", {}).get("status"), ("short", "elapsed", "extra")
    )
    for side in ("home", "away"):
        result["teams"][side] = _select(
            _select(raw.get("teams"), (side,)).get(side), ("id", "name")
        )
    for period in ("halftime", "fulltime"):
        result["score"][period] = _select(
            _select(raw.get("score"), (period,)).get(period), ("home", "away")
        )
    for section in ("events", "lineups", "statistics", "players"):
        value = raw.get(section)
        if section != "events":
            result[section] = (
                ([] if not value else [{}])
                if isinstance(value, list)
                else (None if value is None else {"invalid": True})
            )
        elif isinstance(value, list):
            if len(value) > 2000 or any(type(row) is not dict for row in value):
                result[section] = {"invalid": True}
                continue
            events = []
            for row in value:
                event = _select(row, ("type", "detail"))
                event["time"] = _select(row.get("time"), ("elapsed", "extra"))
                for actor in ("team", "player", "assist"):
                    event[actor] = _select(row.get(actor), ("id",))
                events.append(event)
            result[section] = events
        else:
            result[section] = None if value is None else {"invalid": True}
    return result


class ApiFootballClient:
    def __init__(
        self,
        secret: SecretValue,
        quota: QuotaLedger,
        scope: ProviderScope,
        *,
        opener: Any = None,
        now_mono: Callable[[], float] = time.monotonic,
        now_utc: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ):
        try:
            verify_probe_protocol(scope)
            verify_call_authorization(scope, now_mono=now_mono())
            if (
                quota.scope_id != scope.scope_id
                or type(secret) is not SecretValue
                or (opener is None and scope.source_kind != "OBSERVED_REAL")
                or (opener is not None and scope.source_kind != "MOCK")
            ):
                raise ValueError()
        except Exception:
            raise ProviderError("REAL_AUTHORITY_REQUIRED") from None
        self.scope, self.quota = scope, quota
        self._secret: SecretValue | None = secret
        self._real = opener is None
        self._opener = build_fixed_opener() if opener is None else opener
        self._mono, self._utc, self._sleep = now_mono, now_utc, sleep
        self._lock = threading.Lock()
        self._next_start = now_mono()
        self._stopped: str | None = None
        self._blocked_purposes: dict[str, str] = {}
        self._coverage_cache: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}
        self._lookup_cache: dict[str, tuple[float, ProviderResponse]] = {}
        self.request_log: list[dict[str, Any]] = []

    def __enter__(self) -> "ApiFootballClient":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._secret = None
        self._stopped = "STOPPED"

    def _admit(self, purpose: str) -> None:
        if self._stopped:
            raise ProviderError(self._stopped)
        if purpose in self._blocked_purposes:
            raise ProviderError(self._blocked_purposes[purpose])
        try:
            verify_call_authorization(self.scope, purpose=purpose, now_mono=self._mono())
        except Exception:
            raise ProviderError("RUN_DEADLINE_OR_AUTHORITY") from None
        if self.quota.count_attempts() >= self.scope.max_attempts:
            raise ProviderError("SESSION_BUDGET")

    def _read(self, response: Any, request: Request, timeout: float) -> bytes:
        if response.geturl() != request.full_url:
            raise ProviderError("REDIRECT")
        encoding = response.headers.get("Content-Encoding", "identity")
        if encoding.lower() not in {"identity", ""}:
            raise ProviderError("SCHEMA_ERROR")
        length = response.headers.get("Content-Length")
        if length is not None and (
            not re.fullmatch(r"[0-9]{1,10}", length) or int(length) > MAX_BODY
        ):
            raise ProviderError("RESPONSE_TOO_LARGE")
        deadline = min(self.scope.deadline_mono, self._mono() + timeout)
        chunks, size = [], 0
        while True:
            if self._real and response.fp is None:
                break
            remaining = deadline - self._mono()
            if remaining <= 0:
                raise ProviderError("TIMEOUT")
            if self._real:
                # Pinned Python 3.12 HTTPResponse socket; fail closed if the shape changes.
                response.fp.raw._sock.settimeout(min(10, remaining))
            chunk = response.read1(min(65536, MAX_BODY + 1 - size))
            size += len(chunk)
            if size > MAX_BODY:
                raise ProviderError("RESPONSE_TOO_LARGE")
            if not chunk:
                break
            chunks.append(chunk)
        if length is not None and size != int(length):
            raise ProviderError("SCHEMA_ERROR")
        return b"".join(chunks)

    def _decode(self, raw: bytes, purpose: str, ids: tuple[int, ...]) -> dict[str, Any]:
        try:
            body = parse_strict_json(raw)
            if type(body) is not dict:
                raise ProviderError("SCHEMA_ERROR")
            errors = body.get("errors")
            if errors not in ({}, []):
                if isinstance(errors, dict) and set(errors) & {"token", "access", "authentication"}:
                    raise ProviderError("AUTH_FAILED")
                raise ProviderError(
                    "PROVIDER_ERROR" if isinstance(errors, (dict, list)) else "SCHEMA_ERROR"
                )
            assert self._secret is not None
            key = self._secret.reveal_for_header()
            # Reject credential echoes before any projection or retention. No secret hash is made.
            encoded_key = quote(key, safe="")

            def has_echo(value: object) -> bool:
                if isinstance(value, str):
                    return key in value or encoded_key in value
                if isinstance(value, dict):
                    return any(has_echo(k) or has_echo(v) for k, v in value.items())
                if isinstance(value, list):
                    return any(has_echo(v) for v in value)
                return False

            if has_echo(body):
                raise ProviderError("SECRET_ECHO")
            paging = body.get("paging")
            if (
                type(paging) is not dict
                or type(paging.get("current")) is not int
                or type(paging.get("total")) is not int
                or paging["current"] != 1
                or paging["total"] != 1
            ):
                raise ProviderError("SCHEMA_ERROR")
            rows = body.get("response")
            if purpose == "STATUS":
                if (
                    type(rows) is not dict
                    or type(body.get("results")) is not int
                    or body["results"] != 1
                ):
                    raise ProviderError("SCHEMA_ERROR")
            elif (
                type(rows) is not list
                or type(body.get("results")) is not int
                or body["results"] != len(rows)
                or any(type(row) is not dict for row in rows)
            ):
                raise ProviderError("SCHEMA_ERROR")
            if purpose in {"BUNDLE", "LOOKUP"}:
                returned = [_positive_id(row.get("fixture", {}).get("id")) for row in rows]
                if len(returned) != len(set(returned)) or (
                    purpose == "BUNDLE" and not set(returned) <= set(ids)
                ):
                    raise ProviderError("SCHEMA_ERROR")
            return body
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("SCHEMA_ERROR") from None

    def _request(
        self, purpose: str, path: str, ids: tuple[int, ...] = ()
    ) -> tuple[dict[str, Any], str, int]:
        allowed = {
            "STATUS": "/status",
            "COVERAGE": f"/leagues?id={self.scope.league_id}&season={self.scope.season}",
            "BUNDLE": "/fixtures?ids=" + "-".join(map(str, ids)),
            "LOOKUP": (
                f"/fixtures?league={self.scope.league_id}&season={self.scope.season}"
                f"&date={self.scope.lookup_date}"
            ),
        }
        if purpose == "EVENTS_FALLBACK":
            if path not in {f"/fixtures/events?fixture={i}" for i in self.scope.events_fixture_ids}:
                raise ProviderError("FALLBACK_DISABLED")
        elif purpose not in allowed or path != allowed[purpose]:
            raise ProviderError("PARAMETER_ERROR")
        if purpose == "BUNDLE" and (not ids or not set(ids) <= set(self.scope.fixture_ids)):
            raise ProviderError("PARAMETER_ERROR")
        if not self._lock.acquire(blocking=False):
            raise ProviderError("IN_FLIGHT")
        try:
            for index in range(3):
                self._admit(purpose)
                delay = max(0, self._next_start - self._mono())
                if delay >= self.scope.deadline_mono - self._mono():
                    raise ProviderError("RUN_DEADLINE_OR_AUTHORITY")
                if delay:
                    self._sleep(delay)
                self._admit(purpose)
                reservation = self.quota.reserve_attempt(
                    self.scope.scope_id, purpose, self._utc(), self._mono()
                )
                if isinstance(reservation, Denied):
                    raise ProviderError(reservation.code)
                headers: dict[str, str] = {}
                response = None
                body = None
                failure: ProviderError | None = None
                started = self._mono()
                self._next_start = started + 10
                try:
                    assert self._secret is not None
                    request = Request(  # noqa: S310 -- exact purpose/path allowlist above, fixed HTTPS host
                        BASE + path,
                        method="GET",
                        headers={
                            "x-apisports-key": self._secret.reveal_for_header(),
                            "Accept": "application/json",
                            "Accept-Encoding": "identity",
                        },
                    )
                    timeout = min(10, self.scope.deadline_mono - started)
                    try:
                        response = self._opener.open(request, timeout=timeout)
                    except HTTPError as error:
                        response = error
                    headers = {
                        str(k).lower(): str(v)
                        for k, v in response.headers.items()
                        if str(k).lower() in (*HEADER_NAMES, "retry-after")
                    }
                    status = response.code if isinstance(response, HTTPError) else response.status
                    if status in {401, 403}:
                        raise ProviderError("AUTH_FAILED")
                    if 300 <= status < 400:
                        raise ProviderError("REDIRECT")
                    if status == 429:
                        raise ProviderError(
                            "HTTP_429", retry_after_seconds(headers.get("retry-after"), self._utc())
                        )
                    if status == 499 or 500 <= status <= 599:
                        raise ProviderError("HTTP_5XX", 2 if index == 0 else 4)
                    if status != 200:
                        raise ProviderError("PARAMETER_ERROR")
                    body = self._decode(self._read(response, request, timeout), purpose, ids)
                except ProviderError as error:
                    failure = error
                except TimeoutError:
                    failure = ProviderError("TIMEOUT", 2 if index == 0 else 4)
                except URLError:
                    failure = ProviderError("TRANSPORT_ERROR")
                except KeyboardInterrupt:
                    failure = ProviderError("USER_STOP")
                except Exception:
                    failure = ProviderError("TRANSPORT_ERROR")
                finally:
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            failure = failure or ProviderError("TRANSPORT_ERROR")
                    outcome = "SUCCESS" if failure is None else failure.code
                    ledger_outcome = (
                        outcome
                        if outcome
                        in {
                            "SUCCESS",
                            "AUTH_FAILED",
                            "HTTP_429",
                            "HTTP_5XX",
                            "TIMEOUT",
                            "REDIRECT",
                            "TRANSPORT_ERROR",
                            "SCHEMA_ERROR",
                            "PROVIDER_ERROR",
                        }
                        else ("UNKNOWN" if outcome == "USER_STOP" else "SCHEMA_ERROR")
                    )
                    self.quota.finalize_attempt(
                        reservation.attempt_id,
                        ledger_outcome,
                        {k: v for k, v in headers.items() if k in HEADER_NAMES},
                    )
                    self.request_log.append(
                        {
                            "attempt_id": reservation.attempt_id,
                            "purpose": purpose,
                            "outcome": outcome,
                            "source_kind": self.scope.source_kind,
                        }
                    )
                if failure is None:
                    assert body is not None
                    return body, reservation.attempt_id, index + 1
                if failure.code in {"AUTH_FAILED", "SECRET_ECHO", "REDIRECT"}:
                    self._stopped = failure.code
                if failure.code == "USER_STOP":
                    raise KeyboardInterrupt from None
                if failure.code == "HTTP_429":
                    self._next_start = max(
                        self._next_start, self._mono() + (failure.retry_after or 60)
                    )
                if failure.code not in {"HTTP_429", "HTTP_5XX", "TIMEOUT"} or index == 2:
                    if failure.code in {
                        "SCHEMA_ERROR",
                        "PARAMETER_ERROR",
                        "PROVIDER_ERROR",
                        "RESPONSE_TOO_LARGE",
                    }:
                        self._blocked_purposes[purpose] = failure.code
                    raise failure from None
                retry_delay = failure.retry_after
                if retry_delay is None:
                    retry_delay = 2 if index == 0 else 4
                self._next_start = max(self._next_start, self._mono() + retry_delay)
            raise ProviderError("PROVIDER_UNAVAILABLE")
        finally:
            self._lock.release()

    def get_status(self) -> SafeStatus:
        body, _, _ = self._request("STATUS", "/status")
        try:
            response = body["response"]
            subscription, requests = response.get("subscription", {}), response.get("requests", {})
            plan = subscription.get("plan", "UNKNOWN").upper()
            if plan not in {"FREE", "PRO", "ULTRA", "MEGA"}:
                plan = "UNKNOWN"
            active = subscription.get("active") is True
            expires = subscription.get("end")
            if type(expires) is not str or date.fromisoformat(expires).isoformat() != expires:
                expires = None
            limit, used = requests.get("limit_day"), requests.get("current")
            if (
                type(limit) is not int
                or type(used) is not int
                or not 0 <= used <= limit <= 2**31 - 1
            ):
                limit, remaining = None, None
            else:
                remaining = limit - used
            return SafeStatus(plan, active, expires, limit, remaining)
        except Exception:
            raise ProviderError("SCHEMA_ERROR") from None

    def get_fixture_bundle(self, ids: Sequence[int]) -> ProviderResponse:
        ordered = tuple(sorted({_positive_id(i) for i in ids}))
        if not 1 <= len(ordered) <= 20 or not set(ordered) <= set(self.scope.fixture_ids):
            raise ProviderError("PARAMETER_ERROR")
        body, request_id, attempts = self._request(
            "BUNDLE", "/fixtures?ids=" + "-".join(map(str, ordered)), ordered
        )
        try:
            rows = tuple(_fixture_fields(row) for row in body["response"])
            missing = tuple(sorted(set(ordered) - {row["fixture"]["id"] for row in rows}))
            return ProviderResponse(
                request_id, self.scope.source_kind, "BUNDLE", rows, missing, attempts
            )
        except Exception:
            raise ProviderError("SCHEMA_ERROR") from None

    def get_coverage(self, league_id: int, season: int) -> dict[str, Any]:
        self._admit("COVERAGE")
        if (
            type(league_id) is not int
            or league_id != self.scope.league_id
            or type(season) is not int
            or season != self.scope.season
        ):
            raise ProviderError("PARAMETER_ERROR")
        key = (league_id, season)
        cached = self._coverage_cache.get(key)
        if cached and self._mono() < cached[0]:
            return copy.deepcopy(cached[1])
        body, _, _ = self._request("COVERAGE", f"/leagues?id={league_id}&season={season}")
        try:
            matching = [row for row in body["response"] if row["league"]["id"] == league_id]
            if len(matching) != 1:
                raise ValueError()
            seasons = [s for s in matching[0]["seasons"] if s["year"] == season]
            if len(seasons) != 1:
                raise ValueError()
            coverage = seasons[0]["coverage"]["fixtures"]
            result = {
                "league_id": league_id,
                "season": season,
                "coverage": {
                    name: coverage.get(name) if type(coverage.get(name)) is bool else None
                    for name in ("events", "lineups", "statistics_fixtures", "statistics_players")
                },
            }
            self._coverage_cache[key] = (self._mono() + 86400, result)
            return copy.deepcopy(result)
        except Exception:
            raise ProviderError("SCHEMA_ERROR") from None

    def get_events(self, fixture_id: int) -> ProviderResponse:
        _positive_id(fixture_id)
        if fixture_id not in self.scope.events_fixture_ids:
            raise ProviderError("FALLBACK_DISABLED")
        body, request_id, attempts = self._request(
            "EVENTS_FALLBACK", f"/fixtures/events?fixture={fixture_id}"
        )
        projected = _fixture_fields({"fixture": {}, "events": body["response"]})["events"]
        return ProviderResponse(
            request_id, self.scope.source_kind, "EVENTS_FALLBACK", tuple(projected), (), attempts
        )

    def get_fixtures_for_date(self, league_id: int, season: int, date: str) -> ProviderResponse:
        self._admit("LOOKUP")
        if (
            type(league_id) is not int
            or league_id != self.scope.league_id
            or type(season) is not int
            or season != self.scope.season
            or type(date) is not str
            or date != self.scope.lookup_date
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
        ):
            raise ProviderError("LOOKUP_NOT_AUTHORIZED")
        cached = self._lookup_cache.get(date)
        if cached and self._mono() < cached[0]:
            return copy.deepcopy(cached[1])
        body, request_id, attempts = self._request(
            "LOOKUP", f"/fixtures?league={league_id}&season={season}&date={date}"
        )
        rows = tuple(_fixture_fields(row) for row in body["response"])
        result = ProviderResponse(request_id, self.scope.source_kind, "LOOKUP", rows, (), attempts)
        self._lookup_cache[date] = (self._mono() + 60, result)
        return result
