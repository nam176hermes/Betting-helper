"""One bounded backend scheduler for the selected fixture union."""

import copy
import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..provider_protocol import verify_probe_protocol
from .api_football import ApiFootballClient, ProviderError, ProviderResponse
from .football_normalizer import BundleProjection, ObservationStamp, normalize_bundle
from .poll_budget import PollSegment, estimate_requests

TRANSIENT = frozenset(
    {"HTTP_429", "HTTP_5XX", "TIMEOUT", "TRANSPORT_ERROR", "PROVIDER_UNAVAILABLE"}
)
STOP_REASONS = frozenset({"USER_STOP", "RUN_DEADLINE", "SHUTDOWN", "SCOPE_REVOKED"})


@dataclass(frozen=True)
class PollOutcome:
    status: str
    reason: str
    next_due_mono: float | None
    projection: BundleProjection | None = None
    stale_ids: tuple[int, ...] = ()
    stopped_ids: dict[int, str] = field(default_factory=dict)
    wake_gap: bool = False
    fallback: ProviderResponse | None = None


class ProviderBundlePoller:
    def __init__(
        self,
        client: ApiFootballClient,
        *,
        now_mono: Callable[[], float] = time.monotonic,
        now_utc: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        verify_probe_protocol(client.scope)
        self.client = client
        self._mono, self._utc = now_mono, now_utc
        duration = math.ceil(client.scope.deadline_mono - now_mono())
        if not 0 < duration <= (300 if client.scope.stage == "PROVIDER_PROBE" else 7200):
            raise ValueError("E_POLLER_DEADLINE")
        self._floor = 30 if client.scope.stage == "PROVIDER_PROBE" else 15
        fallback = len(client.scope.events_fixture_ids) * math.ceil(duration / 60)
        if (
            fallback
            and estimate_requests(
                [PollSegment(0, duration, self._floor)], fallback_calls=fallback
            ).with_reserve
            > client.scope.max_attempts
        ):
            raise ValueError("E_FALLBACK_BUDGET")
        self.clock_domain_id = str(uuid4())
        self._ids: tuple[int, ...] = ()
        self._revision = 0
        self._states: dict[int, dict[str, Any]] = {}
        self._due: dict[int, float] = {}
        self._terminal: dict[int, tuple[float, int]] = {}
        self._unknown: dict[int, float] = {}
        self._stopped: dict[int, str] = {}
        self._stale: set[int] = set()
        self._fallback_due = dict.fromkeys(client.scope.events_fixture_ids, now_mono() + 10)
        self._fallback_count = 0
        self._not_before = now_mono()
        self._last_tick = now_mono()
        self._failures = 0
        self._pause: str | None = None
        self._stop_reason: str | None = None
        self._state_lock = threading.RLock()
        self._request_lock = threading.Lock()

    @property
    def last_states(self) -> dict[int, dict[str, Any]]:
        with self._state_lock:
            return copy.deepcopy(self._states)

    def set_watchlist(self, ids: Sequence[int], scope_revision: int) -> None:
        with self._state_lock:
            if (
                len(ids) > 20
                or any(type(i) is not int or i <= 0 for i in ids)
                or not set(ids) <= set(self.client.scope.fixture_ids)
                or type(scope_revision) is not int
                or not self._revision <= scope_revision <= 2**63 - 1
            ):
                raise ValueError("E_WATCHLIST_SCOPE")
            selected = tuple(sorted(set(ids)))
            if scope_revision == self._revision:
                if selected != self._ids:
                    raise ValueError("E_WATCHLIST_REVISION")
                return
            now = self._mono()
            for fixture_id in selected:
                if fixture_id not in self._ids:
                    self._due[fixture_id] = now
            self._ids, self._revision = selected, scope_revision

    def request_refresh(self) -> None:
        # A refresh subscribes to the next shared due request; it cannot reset deadlines.
        return None

    def stop(self, reason: str) -> None:
        if reason not in STOP_REASONS:
            raise ValueError("E_STOP_REASON")
        with self._state_lock:
            self._stop_reason = reason

    def _active(self) -> tuple[int, ...]:
        return tuple(i for i in self._ids if i not in self._stopped)

    def _next(self) -> float | None:
        active = self._active()
        if self._pause or self._stop_reason or not active:
            return None
        deadlines = [self._due[i] for i in active]
        deadlines += [due for i, due in self._fallback_due.items() if i in active]
        return max(self._not_before, min(deadlines))

    def _outcome(
        self,
        status: str,
        reason: str = "NONE",
        *,
        projection: BundleProjection | None = None,
        wake_gap: bool = False,
        fallback: ProviderResponse | None = None,
    ) -> PollOutcome:
        return PollOutcome(
            status,
            reason,
            self._next(),
            projection,
            tuple(sorted(self._stale.intersection(self._ids))),
            dict(self._stopped),
            wake_gap,
            fallback,
        )

    def _schedule(self, fixture_id: int, state: dict[str, Any], now: float) -> None:
        period = state["period"]
        if period != "UNKNOWN":
            self._unknown.pop(fixture_id, None)
        if period != "FINISHED":
            self._terminal.pop(fixture_id, None)
        if period == "OUT_OF_SCOPE":
            self._stopped[fixture_id] = "OUT_OF_SCOPE_NORMAL_TIME"
        elif period == "FINISHED":
            first, count = self._terminal.get(fixture_id, (now, 0))
            if fixture_id in self._terminal and count == 0 and now >= first + 120:
                self._stopped[fixture_id] = "TERMINAL_CONFIRMATION_MISSED"
                return
            if fixture_id in self._terminal and now >= first + (30 if count == 0 else 120):
                count += 1
            self._terminal[fixture_id] = first, count
            if count == 2:
                self._stopped[fixture_id] = "TERMINAL_CONFIRMED"
            else:
                self._due[fixture_id] = max(now + 10, first + (30 if count == 0 else 120))
        else:
            interval = 60
            if period in {"H1", "H2"}:
                interval = self._floor
            elif period == "PREGAME":
                kickoff = datetime.fromisoformat(state["kickoff_utc"])
                interval = 60 if (kickoff - self._utc()).total_seconds() >= 600 else 30
            elif period == "UNKNOWN":
                self._unknown.setdefault(fixture_id, now)
            self._due[fixture_id] = now + interval

    def tick(self, now_mono: float) -> PollOutcome:
        if not self._request_lock.acquire(blocking=False):
            with self._state_lock:
                return self._outcome("WAIT", "IN_FLIGHT")
        try:
            return self._tick(now_mono)
        finally:
            self._request_lock.release()

    def _tick(self, now: float) -> PollOutcome:
        with self._state_lock:
            if not math.isfinite(now) or now < self._last_tick or abs(now - self._mono()) > 1:
                self._pause = "CLOCK_ERROR"
            wake = now - self._last_tick > 90
            self._last_tick = now
            if now >= self.client.scope.deadline_mono:
                self._stop_reason = "RUN_DEADLINE"
            if self._stop_reason:
                return self._outcome("STOPPED", self._stop_reason)
            if self._pause:
                return self._outcome("PAUSED", self._pause)
            for i, first in self._unknown.items():
                if now - first >= 300:
                    self._stopped[i] = "UNKNOWN_PERIOD_TIMEOUT"
            active = self._active()
            if not active:
                return self._outcome("STOPPED", "NO_ACTIVE_FIXTURES")
            if wake:
                self._stale.update(active)
            due = self._next()
            if due is None or now < due:
                return self._outcome("WAIT", wake_gap=wake)
            fallback_id = None
            if now < min(self._due[i] for i in active):
                fallback_id = next(
                    (i for i in active if self._fallback_due.get(i, math.inf) <= now), None
                )
            previous = copy.deepcopy(self._states)
        try:
            if fallback_id is not None:
                if self.client.scope.stage == "PROVIDER_PROBE" and self._fallback_count >= 2:
                    raise ProviderError("FALLBACK_PROBE_LIMIT")
                response = self.client.get_events(fallback_id)
                projection = None
            else:
                response = self.client.get_fixture_bundle(active)
                projection = normalize_bundle(
                    response,
                    active,
                    ObservationStamp(
                        self._utc(),
                        int(self._mono() * 1_000_000),
                        self.clock_domain_id,
                        str(uuid4()),
                        self.client.scope.league_id,
                        self.client.scope.season,
                        previous,
                    ),
                )
        except Exception as error:
            with self._state_lock:
                self._stale.update(active)
                delay = 60.0
                if type(error) is ProviderError and error.code == "HTTP_429":
                    delay = max(delay, error.retry_after or 60)
                self._not_before = self._mono() + delay
                code = (
                    error.code if type(error) is ProviderError else "INVALID_PROVIDER_OBSERVATION"
                )
                self._failures += 1
                if code not in TRANSIENT or self._failures >= 3:
                    # Only finite client codes from this boundary reach the visible projection.
                    self._pause = "PROVIDER_RESTART_REQUIRED" if code in TRANSIENT else code
                return self._outcome(
                    "PAUSED" if self._pause else "STALE",
                    self._pause or "CIRCUIT_OPEN",
                    wake_gap=wake,
                )
        with self._state_lock:
            completed = self._mono()
            self._not_before = completed + 10
            self._failures = 0
            if fallback_id is not None:
                self._fallback_count += 1
                self._fallback_due[fallback_id] = completed + 60
                return self._outcome(
                    "UPDATED", "FALLBACK_OBSERVATION", fallback=response, wake_gap=wake
                )
            assert projection is not None
            for i in projection.missing_ids:
                self._stale.add(i)
                self._due[i] = completed + 60
            for i, reason in projection.rejected.items():
                self._stale.add(i)
                self._stopped[i] = reason
            for i, state in projection.states.items():
                self._states[i] = state
                self._stale.discard(i)
                self._schedule(i, state, completed)
            return self._outcome("UPDATED", projection=projection, wake_gap=wake)
