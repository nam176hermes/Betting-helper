"""Durable attempt reservations with one process owner; this is not run authorization."""

import fcntl
import math
import os
import re
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

from ..live_contracts import CONTRACTS

PURPOSES = frozenset({"STATUS", "COVERAGE", "LOOKUP", "BUNDLE", "EVENTS_FALLBACK"})
OUTCOMES = frozenset(
    {
        "SUCCESS",
        "AUTH_FAILED",
        "HTTP_429",
        "HTTP_5XX",
        "TIMEOUT",
        "REDIRECT",
        "TRANSPORT_ERROR",
        "SCHEMA_ERROR",
        "PROVIDER_ERROR",
        "UNKNOWN",
    }
)
QUOTA_ERRORS = frozenset({"QUOTA_INVALID", "QUOTA_INCONSISTENT"})
HEADER_NAMES = (
    "x-ratelimit-requests-limit",
    "x-ratelimit-requests-remaining",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
)


@dataclass(frozen=True)
class Denied:
    code: str


@dataclass(frozen=True)
class Reservation:
    attempt_id: str
    scope_id: str
    purpose: str
    reserved_at_utc: str


def _quota_headers(headers: Mapping[str, str]) -> tuple[int | None, ...]:
    selected: dict[str, str] = {}
    for key, value in headers.items():
        name = key.lower()
        if name in HEADER_NAMES:
            if (
                name in selected
                or type(value) is not str
                or not re.fullmatch(r"[0-9]{1,10}", value)
            ):
                raise ValueError("E_QUOTA_HEADERS")
            selected[name] = value
    if not selected:
        return (None, None, None, None)
    if set(selected) != set(HEADER_NAMES):
        raise ValueError("E_QUOTA_HEADERS")
    limit, remaining, minute_limit, minute_remaining = (int(selected[n]) for n in HEADER_NAMES)
    if not (
        0 < limit <= 2**31 - 1
        and 0 <= remaining <= limit
        and 0 < minute_limit <= 2**31 - 1
        and 0 <= minute_remaining <= minute_limit
    ):
        raise ValueError("E_QUOTA_HEADERS")
    return limit, remaining, minute_limit, minute_remaining


class QuotaLedger:
    def __init__(
        self,
        path: Path,
        *,
        scope_id: str,
        daily_cap: int = 6000,
        session_cap: int = 600,
        minute_cap: int = 6,
        allow_status_bootstrap: bool = False,
    ):
        if (
            str(UUID(scope_id)) != scope_id
            or type(allow_status_bootstrap) is not bool
            or any(
                type(v) is not int or not 1 <= v <= maximum
                for v, maximum in [(daily_cap, 6000), (session_cap, 600), (minute_cap, 6)]
            )
        ):
            raise ValueError("E_QUOTA_CONFIG")
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("E_QUOTA_PATH")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.stat().st_mode & 0o077:
            raise ValueError("E_QUOTA_PATH")
        self._lock_fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._lock_fd)
            raise ValueError("E_QUOTA_POLLER_LOCK") from None
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            if path.stat().st_mode & 0o077:
                raise ValueError("E_QUOTA_PATH")
            self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            ddl = (CONTRACTS / "quota-store.sql").read_text()
            if not self.db.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchone():
                self.db.executescript(ddl)
            for pragma in (
                "journal_mode=DELETE",
                "synchronous=FULL",
                "foreign_keys=ON",
                "trusted_schema=OFF",
                "busy_timeout=5000",
            ):
                self.db.execute("PRAGMA " + pragma)
            with sqlite3.connect(":memory:") as expected:
                expected.executescript(ddl)
                query = "SELECT type,name,sql FROM sqlite_schema ORDER BY type,name"
                if [tuple(row) for row in self.db.execute(query)] != expected.execute(
                    query
                ).fetchall():
                    raise ValueError("E_QUOTA_SCHEMA")
            if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("E_QUOTA_DATABASE")
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            os.close(self._lock_fd)
            raise
        self.scope_id = scope_id
        self.daily_cap, self.session_cap, self.minute_cap = daily_cap, session_cap, minute_cap
        self.allow_status_bootstrap = allow_status_bootstrap
        self.boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        self._pending: Reservation | None = None
        self._mutex = threading.RLock()
        self._pid = os.getpid()
        self._closed = False

    def __enter__(self) -> "QuotaLedger":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        with self._mutex:
            if not self._closed:
                self.db.close()
                os.close(self._lock_fd)
                self._closed = True

    def _owner(self) -> None:
        if self._closed or os.getpid() != self._pid:
            raise ValueError("E_QUOTA_OWNER")

    def count_attempts(self, scope_id: str | None = None) -> int:
        with self._mutex:
            self._owner()
            return int(
                self.db.execute(
                    "SELECT count(*) FROM quota_reservations WHERE scope_id=?",
                    (scope_id or self.scope_id,),
                ).fetchone()[0]
            )

    def _latest_quota(self) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self.db.execute(
                "SELECT r.rowid AS ordinal,r.*,o.* FROM quota_reservations r JOIN quota_outcomes o "
                "USING(attempt_id) WHERE o.observed_daily_limit IS NOT NULL "
                "ORDER BY r.rowid DESC LIMIT 1"
            ).fetchone(),
        )

    def _provider_guard(self, purpose: str, day: str, mono_us: int) -> Denied | None:
        known = self._latest_quota()
        latest = self.db.execute(
            "SELECT r.scope_id,o.result_code FROM quota_reservations r JOIN quota_outcomes o "
            "USING(attempt_id) ORDER BY r.rowid DESC LIMIT 1"
        ).fetchone()
        if (
            latest
            and latest["scope_id"] == self.scope_id
            and latest["result_code"] == "AUTH_FAILED"
        ):
            return Denied("AUTH_FAILED")
        if known is None or known["utc_day"] != day or known["boot_id"] != self.boot_id:
            used = self.db.execute(
                "SELECT count(*) FROM quota_reservations WHERE scope_id=? AND purpose='STATUS' "
                "AND utc_day=?",
                (self.scope_id, day),
            ).fetchone()[0]
            if purpose == "STATUS" and self.allow_status_bootstrap and used == 0:
                return None
            return Denied("QUOTA_UNKNOWN" if known is None else "QUOTA_RECONCILIATION_REQUIRED")
        if latest and latest["result_code"] in QUOTA_ERRORS and purpose != "STATUS":
            return Denied("QUOTA_RECONCILIATION_REQUIRED")
        debt = self.db.execute(
            "SELECT count(*) FROM quota_reservations WHERE rowid>?", (known["ordinal"],)
        ).fetchone()[0]
        floor = (known["observed_daily_limit"] + 4) // 5
        if known["observed_daily_remaining"] - debt <= floor:
            return Denied("PROVIDER_DAILY_RESERVE")
        observed_mono = known["reserved_mono_us"] + int(
            (
                datetime.fromisoformat(known["observed_at_utc"])
                - datetime.fromisoformat(known["reserved_at_utc"])
            ).total_seconds()
            * 1_000_000
        )
        rolling = self.db.execute(
            "SELECT count(*) FROM quota_reservations WHERE boot_id=? AND reserved_mono_us>?",
            (self.boot_id, mono_us - 60_000_000),
        ).fetchone()[0]
        if rolling >= known["observed_minute_limit"]:
            return Denied("PROVIDER_MINUTE_BUDGET")
        if mono_us - observed_mono < 60_000_000 and known["observed_minute_remaining"] - debt <= 0:
            return Denied("PROVIDER_MINUTE_BUDGET")
        return None

    def reserve_attempt(
        self, scope_id: str, purpose: str, now_utc: datetime, now_mono: float
    ) -> Reservation | Denied:
        with self._mutex:
            self._owner()
            if (
                scope_id != self.scope_id
                or purpose not in PURPOSES
                or now_utc.tzinfo is None
                or now_utc.utcoffset() != UTC.utcoffset(now_utc)
                or type(now_mono) not in {int, float}
                or not math.isfinite(now_mono)
                or not 0 <= now_mono <= (2**63 - 1) / 1_000_000
            ):
                raise ValueError("E_QUOTA_REQUEST")
            if self._pending is not None:
                return Denied("IN_FLIGHT")
            day, utc = now_utc.date().isoformat(), now_utc.isoformat()
            mono = int(now_mono * 1_000_000)
            self.db.execute("BEGIN IMMEDIATE")
            try:
                last = self.db.execute(
                    "SELECT * FROM quota_reservations ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                deny = None
                if last and (
                    now_utc < datetime.fromisoformat(last["reserved_at_utc"])
                    or (last["boot_id"] == self.boot_id and mono < last["reserved_mono_us"])
                ):
                    deny = Denied("CLOCK_ROLLBACK")
                elif self.count_attempts() >= self.session_cap:
                    deny = Denied("SESSION_BUDGET")
                elif (
                    self.db.execute(
                        "SELECT count(*) FROM quota_reservations WHERE utc_day=?", (day,)
                    ).fetchone()[0]
                    >= self.daily_cap
                ):
                    deny = Denied("DAILY_BUDGET")
                elif (
                    last
                    and last["boot_id"] != self.boot_id
                    and (now_utc - datetime.fromisoformat(last["reserved_at_utc"])).total_seconds()
                    < 60
                ):
                    deny = Denied("CLOCK_RECONCILIATION_REQUIRED")
                elif (
                    last
                    and last["boot_id"] == self.boot_id
                    and mono - last["reserved_mono_us"] < 10_000_000
                ):
                    deny = Denied("MINIMUM_GAP")
                elif (
                    self.db.execute(
                        "SELECT count(*) FROM quota_reservations "
                        "WHERE boot_id=? AND reserved_mono_us>?",
                        (self.boot_id, mono - 60_000_000),
                    ).fetchone()[0]
                    >= self.minute_cap
                ):
                    deny = Denied("MINUTE_BUDGET")
                else:
                    deny = self._provider_guard(purpose, day, mono)
                if deny:
                    self.db.execute("ROLLBACK")
                    return deny
                attempt = Reservation(str(uuid4()), scope_id, purpose, utc)
                self.db.execute(
                    "INSERT INTO quota_reservations VALUES(?,?,?,?,?,?,?,?)",
                    (
                        attempt.attempt_id,
                        "api-football-primary",
                        scope_id,
                        purpose,
                        day,
                        utc,
                        self.boot_id,
                        mono,
                    ),
                )
                self.db.execute("COMMIT")
                self._pending = attempt
                self._pending_native_start = time.monotonic()
                return attempt
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def finalize_attempt(
        self, reservation_id: str, outcome: str, headers: Mapping[str, str]
    ) -> None:
        with self._mutex:
            self._owner()
            pending = self._pending
            if pending is None or pending.attempt_id != reservation_id or outcome not in OUTCOMES:
                raise ValueError("E_QUOTA_FINALIZE")
            result = outcome
            try:
                limit, remaining, minute_limit, minute_remaining = _quota_headers(headers)
            except (ValueError, TypeError, AttributeError):
                limit = remaining = minute_limit = minute_remaining = None
                result = "QUOTA_INVALID"
            old = self._latest_quota()
            if (
                old
                and limit is not None
                and old["utc_day"] == pending.reserved_at_utc[:10]
                and pending.purpose != "STATUS"
            ):
                if (
                    limit != old["observed_daily_limit"]
                    or remaining > old["observed_daily_remaining"]
                ):
                    limit = remaining = minute_limit = minute_remaining = None
                    result = "QUOTA_INCONSISTENT"
                else:
                    debt = self.db.execute(
                        "SELECT count(*) FROM quota_reservations WHERE rowid>?",
                        (old["ordinal"],),
                    ).fetchone()[0]
                    remaining = min(remaining, max(0, old["observed_daily_remaining"] - debt))
            if outcome == "AUTH_FAILED":
                result = outcome
            observed = (
                datetime.fromisoformat(pending.reserved_at_utc)
                + timedelta(seconds=time.monotonic() - self._pending_native_start)
            ).isoformat()
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "INSERT INTO quota_outcomes VALUES(?,?,?,?,?,?,?)",
                    (
                        reservation_id,
                        result,
                        limit,
                        remaining,
                        minute_limit,
                        minute_remaining,
                        observed,
                    ),
                )
                self.db.execute("COMMIT")
                self._pending = None
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
