"""One local read-only run owner. Real admission is verified by the PB-16 gate."""

import asyncio
import copy
import hashlib
import importlib
import io
import json
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

import rfc8785

from .live_config import LiveConfig, private_path
from .live_contracts import event_hash, schema_validate, validate_live_record
from .live_receiver import LiveReceiver, serve_live_receiver
from .live_state import request_reference
from .live_store import MAX_BYTES, LiveStore
from .live_wire import PairingAuthority
from .operator_profile import ExtractionProfile, activate_profile
from .provider_protocol import ProviderScope
from .providers.api_football import ApiFootballClient, ProviderError
from .providers.bundle_poller import ProviderBundlePoller
from .providers.quota import QuotaLedger
from .secrets_local import SecretValue
from .workspace_projection import WorkspaceState, project_watchlist


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RunAdmission:
    root: Path
    run_id: str
    config_sha256: str
    source_tree_sha256: str
    extension_origin: str
    deadline_mono: float
    bindings: tuple[dict[str, Any], ...]
    profile: ExtractionProfile
    capture_streams: dict[str, dict[str, Any]]
    source_kind: str = "MOCK"
    provider_receipt: object = field(default=None, repr=False)
    security_evidence: object = field(default=None, repr=False)


@dataclass(frozen=True)
class LiveRunResult:
    run_id: str
    status: str
    reason: str
    request_attempts: int
    real_http_attempts: int
    run_directory: str
    authenticated: bool = False
    model_enabled: bool = False
    money_ready: bool = False


class MockProviderTransport:
    """Explicit synthetic input only; this transport has no network operation."""

    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = deque(copy.deepcopy(responses))
        self.paths: list[str] = []

    def open(self, request: Any, timeout: float) -> Any:
        if not self.responses:
            raise ProviderError("MOCK_INPUT_EXHAUSTED")
        self.paths.append(request.full_url)
        body = self.responses.popleft()

        class Reply(io.BytesIO):
            status = 200
            headers = {
                "x-ratelimit-requests-limit": "7500",
                "x-ratelimit-requests-remaining": "7499",
                "x-ratelimit-limit": "300",
                "x-ratelimit-remaining": "299",
            }

            def geturl(self) -> str:
                return str(request.full_url)

        return Reply(json.dumps(body).encode())


def verify_run_admission(config: LiveConfig, admitted: RunAdmission, now: float) -> None:
    try:
        if type(config) is not LiveConfig or type(admitted) is not RunAdmission:
            raise ValueError()
        cfg = config.public
        schema_validate(cfg, "config")
        if (
            str(UUID(admitted.run_id)) != admitted.run_id
            or config.sha256 != admitted.config_sha256
            or not re.fullmatch(r"[0-9a-f]{64}", admitted.source_tree_sha256)
            or not re.fullmatch(r"chrome-extension://[a-p]{32}", admitted.extension_origin)
            or not now < admitted.deadline_mono <= now + cfg["runtime"]["max_run_minutes"] * 60
            or not 1 <= len(admitted.bindings) <= cfg["runtime"]["max_matches"]
            or sorted(b["provider_fixture_id"] for b in admitted.bindings)
            != list(config.fixture_ids)
            or sorted(b["binding_id"] for b in admitted.bindings)
            != sorted(cfg["operator"]["allowed_fixture_bindings"])
            or admitted.source_kind not in {"MOCK", "OBSERVED_REAL"}
            or cfg["provider"]["events_fallback_enabled"]
            or cfg["provider"]["events_fallback_fixture_ids"]
        ):
            raise ValueError()
        profile = activate_profile(
            admitted.profile, "SYNTHETIC_TEST" if admitted.source_kind == "MOCK" else "OPERATOR"
        )
        for binding in admitted.bindings:
            validate_live_record(binding, "FixtureBinding")
            if (
                binding["league_id"] != cfg["provider"]["league_id"]
                or binding["season"] != cfg["provider"]["season"]
                or binding["operator_fixture_id"] not in profile["permitted_fixture_ids"]
                or binding["operator_match_url"]
                not in {profile["origin"] + p for p in profile["exact_paths"]}
                or binding["operator_fixture_id"] not in admitted.profile.observed_markets
            ):
                raise ValueError()
        scopes = list(admitted.capture_streams.values())
        if len(scopes) != len(admitted.bindings):
            raise ValueError()
        for scope in scopes:
            observed = admitted.profile.observed_markets[scope["operator_fixture_id"]]
            expected = {
                m["horizon"]: {"market_id": m["market_id"], "selections": m["selections"]}
                for m in observed
            }
            if (
                scope["profile_hash"] != admitted.profile.profile_hash
                or scope["markets"] != expected
            ):
                raise ValueError()
        if admitted.source_kind == "OBSERVED_REAL":
            if not config.enabled:
                raise ValueError()
            importlib.import_module("moj_discovery.live_preflight_batched").verify_run_admission(
                config, admitted
            )
    except Exception:
        raise ValueError("E_LIVE_RUN_ADMISSION") from None


class LiveService:
    def __init__(
        self,
        config: LiveConfig,
        secret: SecretValue,
        admitted: RunAdmission,
        *,
        mock_transport: MockProviderTransport | None = None,
        now_mono: Callable[[], float] = time.monotonic,
        now_utc: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ):
        verify_run_admission(config, admitted, now_mono())
        if type(secret) is not SecretValue or (
            (admitted.source_kind == "MOCK") != (type(mock_transport) is MockProviderTransport)
        ):
            raise ValueError("E_LIVE_RUN_ADMISSION_TRANSPORT")
        if admitted.source_kind == "OBSERVED_REAL" and (
            now_mono is not time.monotonic or now_utc is not _utc_now or sleep is not time.sleep
        ):
            raise ValueError("E_LIVE_RUN_ADMISSION_CLOCK")
        self.config, self.admitted = config, admitted
        self._mono, self._utc = now_mono, now_utc
        self._lock = threading.RLock()
        self._tick_lock = asyncio.Lock()
        self._resources = ExitStack()
        self.receiver: LiveReceiver | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._selected = {b["binding_id"] for b in admitted.bindings}
        self._watchlist_revision = 1
        self._started = False
        self._bootstrapped = False
        self._closed = False
        self._reason: str | None = None
        self._last_clock = now_mono()
        self._last_display_tick = -float("inf")
        cfg = config.public
        self.directory = private_path(cfg["runtime"]["run_output_dir"], root=admitted.root)
        # New run namespace only. Restart preserves the previous journal and needs fresh admission.
        if self.directory.exists():
            raise ValueError("E_LIVE_RUN_RESTART_REQUIRES_ADMISSION")
        self.directory.mkdir(mode=0o700, parents=True)
        self._started_utc = self._utc().isoformat().replace("+00:00", "Z")
        self._started_mono = self._mono()
        self._manual_checks: list[dict[str, Any]] = []
        try:
            from .live_intent import RunIntentReceipt

            receipt = (
                cast(RunIntentReceipt, admitted.provider_receipt)
                if admitted.source_kind == "OBSERVED_REAL"
                else None
            )
            self._artifact(
                "intent.json",
                {
                    "intent": receipt.intent.public if receipt is not None else None,
                    "original_json": receipt.intent.original_json if receipt is not None else None,
                    "intent_sha256": receipt.intent.sha256 if receipt is not None else None,
                    "consumed_at_utc": receipt.consumed_at_utc if receipt is not None else None,
                    "confirmation_kind": receipt.confirmation_kind
                    if receipt is not None
                    else "MOCK",
                },
            )
            self._artifact(
                "config-public.json",
                {
                    "value": cfg,
                    "original_json": config.original_json,
                    "original_sha256": config.sha256,
                    "canonical_sha256": hashlib.sha256(rfc8785.dumps(cfg)).hexdigest(),
                },
            )
            self._artifact(
                "source-bindings.json",
                {
                    "run_id": admitted.run_id,
                    "source_kind": admitted.source_kind,
                    "source_tree_sha256": admitted.source_tree_sha256,
                    "profile": admitted.profile.public,
                    "profile_sha256": admitted.profile.profile_hash,
                    "bindings": list(admitted.bindings),
                    "evidence_refs": cast(Any, admitted.security_evidence).evidence.paths
                    if receipt is not None
                    else {},
                },
            )
            self._artifact("manual-ft-checks.jsonl", [], lines=True)
            self.store = self._resources.enter_context(
                LiveStore(
                    self.directory / "live.sqlite3",
                    run_id=admitted.run_id,
                    source_tree_hash=admitted.source_tree_sha256,
                    config_hash=config.sha256,
                    started_utc=self._started_utc,
                    max_matches=cfg["runtime"]["max_matches"],
                    # Reserve room for bounded run metadata, request outcomes and SQLite journal.
                    max_bytes=MAX_BYTES - 16 * 1024 * 1024,
                )
            )
            for binding in admitted.bindings:
                self._append(
                    "BindingChange",
                    {"before_revision": None, "after": binding, "reason": "USER_VERIFIED_BINDING"},
                )
                self.control(
                    binding["binding_id"],
                    "PROFILE_ADMITTED",
                    hashes=[admitted.profile.profile_hash],
                )
            self.pairing = PairingAuthority(admitted.run_id, admitted.deadline_mono)
            context = dict(
                run_id=admitted.run_id,
                allowed_extension_origin=admitted.extension_origin,
                deadline_mono=admitted.deadline_mono,
                source_kind=admitted.source_kind,
                capture_streams=copy.deepcopy(admitted.capture_streams),
            )
            if admitted.source_kind == "OBSERVED_REAL":
                context["authority"] = admitted.security_evidence
            # Validate receiver scope before creating any provider transport.
            LiveReceiver(context, self.store, self.pairing)
            self._receiver_context = context
            provider = cfg["provider"]
            ledger_path = (
                self.directory / "mock-quota.sqlite3"
                if admitted.source_kind == "MOCK"
                else private_path(
                    ".local/part-b/quota/api-football-primary.sqlite3", root=admitted.root
                )
            )
            self.quota = self._resources.enter_context(
                QuotaLedger(
                    ledger_path,
                    scope_id=admitted.run_id,
                    daily_cap=provider["daily_soft_cap"],
                    session_cap=provider["max_requests_per_run"],
                    minute_cap=provider["max_requests_per_minute"],
                    allow_status_bootstrap=True,
                )
            )
            scope = ProviderScope(
                admitted.run_id,
                config.fixture_ids,
                provider["league_id"],
                provider["season"],
                admitted.deadline_mono,
                source_kind=admitted.source_kind,
                stage="LIVE_READ_ONLY",
                max_attempts=provider["max_requests_per_run"],
                config_sha256=config.sha256,
                source_tree_sha256=admitted.source_tree_sha256,
                receipt=admitted.provider_receipt,
            )
            self.client = self._resources.enter_context(
                ApiFootballClient(
                    secret,
                    self.quota,
                    scope,
                    opener=mock_transport,
                    now_mono=now_mono,
                    now_utc=now_utc,
                    sleep=sleep,
                    before_attempt=self._before_attempt,
                )
            )
            self.poller = ProviderBundlePoller(self.client, now_mono=now_mono, now_utc=now_utc)
            self.poller.set_watchlist(config.fixture_ids, self._watchlist_revision)
        except BaseException:
            self._resources.close()
            raise

    def _artifact(self, name: str, value: Any, *, lines: bool = False) -> None:
        raw = (
            b"".join(rfc8785.dumps(row) + b"\n" for row in value)
            if lines
            else rfc8785.dumps(value) + b"\n"
        )
        if len(raw) > 1024 * 1024:
            raise ValueError("E_LIVE_RUN_ARTIFACT_CAP")
        fd = os.open(
            self.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())

    def record_manual_ft_check(self, fixture_id: int, prices: tuple[str, str, str]) -> None:
        """Record an explicit terminal comparison against a current, committed FT book."""
        from .secrets_local import controlling_tty

        with controlling_tty(), self._lock:
            if self._closed or self._reason or len(self._manual_checks) >= 30:
                raise ValueError("E_LIVE_MANUAL_CHECK_STOPPED")
            binding = next(
                b for b in self.admitted.bindings if b["provider_fixture_id"] == fixture_id
            )
            view = self.view(binding["binding_id"])
            book = view["books"]["FT"]
            stamp = self._utc()
            if (
                type(fixture_id) is not int
                or view["market_states"]["FT"]["status"] != "CURRENT_DISPLAY_ONLY"
                or tuple(book["selections"][s]["decimal_odds"] for s in ("HOME", "DRAW", "AWAY"))
                != prices
                or not 0
                <= (stamp - datetime.fromisoformat(book["observed_at_utc"])).total_seconds()
                <= 30
                or any(
                    r["binding_id"] == binding["binding_id"]
                    and (
                        r["capture_event_hash"] == view["book_meta"]["FT"]["event_hash"]
                        or (stamp - datetime.fromisoformat(r["checked_at_utc"])).total_seconds()
                        < 30
                    )
                    for r in self._manual_checks
                )
            ):
                raise ValueError("E_LIVE_MANUAL_CHECK_NOT_CURRENT_OR_DISTINCT")
            row = {
                "confirmation_kind": "LOCAL_TTY_USER_CHECK",
                "source_kind": self.admitted.source_kind,
                "run_id": self.admitted.run_id,
                "binding_id": binding["binding_id"],
                "capture_event_hash": view["book_meta"]["FT"]["event_hash"],
                "checked_at_utc": stamp.isoformat(),
                "selections": book["selections"],
                "market_id": book["market_id"],
            }
            fd = os.open(
                self.directory / "manual-ft-checks.jsonl", os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
            )
            with os.fdopen(fd, "wb") as output:
                output.write(rfc8785.dumps(row) + b"\n")
                output.flush()
                os.fsync(output.fileno())
            self._manual_checks.append(row)

    def _append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            source = "PROVIDER" if kind == "ProviderState" else "CONTROL"
            stream = str(uuid5(UUID(self.admitted.run_id), "BH-LIVE-SERVICE/" + source))
            seq, previous = self.store.cursor(stream)
            now = str(int(self._mono() * 1000000))
            value = copy.deepcopy(payload)
            if kind == "ProviderState":
                # Timestamp actual admission to this backend pipeline under its ordering lock.
                value["received_mono_us"] = now
            event = dict(
                protocol="BH_LIVE_READONLY_V1",
                run_id=self.admitted.run_id,
                source_kind=source,
                stream_id=stream,
                generation="0",
                sequence=str(seq + 1),
                observation_id=str(uuid4()),
                observed_at_utc=self._utc().isoformat().replace("+00:00", "Z"),
                received_mono_us=now,
                previous_hash=previous,
                content_hash="0" * 64,
                payload_type=kind,
                payload=value,
            )
            event["content_hash"] = event_hash(event)
            self.store.append(event)
            return event

    def control(
        self,
        binding_id: str,
        reason: str,
        state: str = "WAITING_FOR_DATA",
        *,
        hashes: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            view = self.store.read_projection(binding_id)
            return self._append(
                "HealthChange",
                dict(
                    binding_id=binding_id,
                    reason=reason,
                    state=state,
                    epoch=str(view["epoch"]),
                    evidence_hashes=hashes or [],
                ),
            )

    def _before_attempt(self, purpose: str, request_id: str) -> None:
        with self._lock:
            if (
                self._reason is not None
                or self._mono() >= self.admitted.deadline_mono
                or self._profile_expired()
            ):
                raise ValueError("E_LIVE_RUN_STOPPED")
            if purpose == "BUNDLE":
                for binding in self._selected:
                    self.control(
                        binding, "PROVIDER_REQUEST_STARTED", hashes=[request_reference(request_id)]
                    )

    def view(self, binding_id: str) -> dict[str, Any]:
        return self.store.read_projection(binding_id)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        if self._closed or len(self._subscribers) >= 8:
            raise ValueError("E_LIVE_SUBSCRIPTION_CAP")
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        queue.put_nowait(self.snapshot())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def snapshot(self) -> dict[str, Any]:
        views = []
        for binding in self.admitted.bindings:
            view, revision = self.store.read_projection_version(binding["binding_id"])
            views.append({**view, "projection_revision": revision})
        state: WorkspaceState = {
            "run_id": self.admitted.run_id,
            "views": views,
            "selected": sorted(self._selected),
            "max_matches": self.config.public["runtime"]["max_matches"],
            "source_kind": self.admitted.source_kind,
            "quota": self.quota.display_remaining(self._utc(), self._mono()),
            "provider_connection": "STOPPED"
            if self._reason
            else (
                "PAUSED" if not self._selected else "CONNECTED" if self._bootstrapped else "WAITING"
            ),
            "capture_connection": "CONNECTED"
            if self.receiver and self.receiver.connected("CAPTURE_PRODUCER")
            else "DISCONNECTED",
        }
        return {
            **state,
            "workspace": project_watchlist(state),
            "attempts": self.quota.count_attempts(),
            "model_enabled": False,
            "money_ready": False,
        }

    def wire_projection(
        self, binding_id: str, health: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        snapshot = self.snapshot()
        view = next(v for v in snapshot["views"] if v["binding"]["binding_id"] == binding_id)
        match = next(
            v for v in snapshot["workspace"]["matches"] if v["binding"]["binding_id"] == binding_id
        )
        stream, scope = next(
            (k, v)
            for k, v in self.admitted.capture_streams.items()
            if v["binding_id"] == binding_id
        )
        profile = self.admitted.profile.public
        return dict(
            **match,
            run_id=self.admitted.run_id,
            capture_scope={
                "stream_id": stream,
                "generation": scope["generation"],
                "exact_url": view["binding"]["operator_match_url"],
                "profile_status": self.admitted.profile.status,
                "profile_hash": self.admitted.profile.profile_hash,
                "document_epoch": scope["document_epoch"],
                "selectors": profile["selectors"],
                "price_parser": profile["price_parser"],
                "markets": self.admitted.profile.observed_markets[
                    view["binding"]["operator_fixture_id"]
                ],
                "expires_at": profile["expires_at"]
                or (
                    self._utc()
                    + timedelta(seconds=max(0, self.admitted.deadline_mono - self._mono()))
                )
                .isoformat()
                .replace("+00:00", "Z"),
                "max_duration_seconds": max(
                    1, min(7200, int(self.admitted.deadline_mono - self._mono()))
                ),
            },
            health=health
            or {
                "binding_id": binding_id,
                "reason": "DISPLAY_PROJECTION",
                "state": view["status"],
                "epoch": str(view["epoch"]),
                "evidence_hashes": [],
            },
            model_status="MODEL_NOT_QUALIFIED",
            money_ready=False,
        )

    async def publish(self) -> None:
        snapshot = self.snapshot()
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(copy.deepcopy(snapshot))
        if self.receiver:
            for binding in self.admitted.bindings:
                await self.receiver.publish(self.wire_projection(binding["binding_id"]))

    async def request_capture(self, binding_id: str) -> str | None:
        if binding_id not in self._selected or self._reason is not None:
            return None
        view = self.view(binding_id)
        if view["hold"] is not None:
            return None
        challenge = hashlib.sha256(uuid4().bytes).hexdigest()
        health = self.control(binding_id, "CAPTURE_REQUEST_STARTED", hashes=[challenge])["payload"]
        if self.receiver:
            await self.receiver.publish(
                self.wire_projection(binding_id, health), role="CAPTURE_PRODUCER"
            )
        return challenge

    async def capture_received(self, event: dict[str, Any]) -> None:
        with self._lock:
            book = event["payload"]
            meta = self.view(book["binding_id"])["book_meta"].get(book["horizon"])
            if meta and meta["event_hash"] == event["content_hash"] and meta["receipt_us"] is None:
                self.control(book["binding_id"], "CAPTURE_RECEIVED", hashes=[event["content_hash"]])

    async def source_changed(self, binding_id: str | None, reason: str) -> None:
        if reason == "USER_STOP" and binding_id in self._selected:
            self._selected.remove(binding_id)
            self._watchlist_revision += 1
            self.poller.set_watchlist(
                [
                    b["provider_fixture_id"]
                    for b in self.admitted.bindings
                    if b["binding_id"] in self._selected
                ],
                self._watchlist_revision,
            )
        if reason in {"PAIRING_RENEWED", "CAPTURE_REJECTED"}:
            for selected in self._selected if binding_id is None else [binding_id]:
                await self.request_capture(selected)
        await self.publish()

    async def on_ui(self, command: str, binding_id: str | None) -> None:
        if command == "STOP_SESSION":
            self._reason = "USER_STOP"
            self.poller.stop("USER_STOP")
            for binding in self.admitted.bindings:
                self.control(binding["binding_id"], "USER_STOP", "STOPPED")
        elif command in {"WATCHLIST_ADD", "WATCHLIST_REMOVE"}:
            if binding_id not in {b["binding_id"] for b in self.admitted.bindings}:
                raise ValueError("E_LIVE_UI_SCOPE")
            assert binding_id is not None
            if command == "WATCHLIST_ADD" and binding_id not in self._selected:
                self.control(binding_id, "USER_RESUME")
                self._selected.add(binding_id)
                await self.request_capture(binding_id)
            elif command == "WATCHLIST_REMOVE" and binding_id in self._selected:
                self._selected.remove(binding_id)
                self.control(binding_id, "USER_PAUSE", "PAUSED")
            self._watchlist_revision += 1
            ids = [
                b["provider_fixture_id"]
                for b in self.admitted.bindings
                if b["binding_id"] in self._selected
            ]
            self.poller.set_watchlist(ids, self._watchlist_revision)
        elif command == "REFRESH":
            self.poller.request_refresh()
        elif command != "SELECT_ACTIVE" or binding_id not in {
            b["binding_id"] for b in self.admitted.bindings
        }:
            raise ValueError("E_LIVE_UI_SCOPE")
        await self.publish()

    async def start(self) -> None:
        if self._started or self._closed:
            raise ValueError("E_LIVE_SERVICE_OWNER")
        self.receiver = await serve_live_receiver(self._receiver_context, self.store, self.pairing)
        self.receiver.on_ui = self.on_ui
        self.receiver.on_capture = self.capture_received
        self.receiver.on_change = self.source_changed
        self._started = True

    async def _io(self, operation: Callable[[], Any]) -> Any:
        task = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Drain our bounded request before closing its ledger/journal.
            await task
            raise

    def _profile_expired(self) -> bool:
        expires = self.admitted.profile.public["expires_at"]
        return expires is not None and self._utc() >= datetime.fromisoformat(expires)

    async def tick(self) -> None:
        if not self._started or self._closed:
            raise ValueError("E_LIVE_SERVICE_OWNER")
        if self._tick_lock.locked():
            return
        async with self._tick_lock:
            now = self._mono()
            if now < self._last_clock:
                self._reason = "SECURITY_HOLD"
            elif now >= self.admitted.deadline_mono:
                self._reason = "RUN_DEADLINE"
            elif self._profile_expired():
                self._reason = "SECURITY_HOLD"
                for binding in self.admitted.bindings:
                    self.control(binding["binding_id"], "PROFILE_EXPIRED", "PROFILE_EXPIRED")
            self._last_clock = max(now, self._last_clock)
            if self._reason is not None:
                if now >= self._last_clock:
                    for binding in self.admitted.bindings:
                        self.control(binding["binding_id"], "RUN_HALTED", "STOPPED")
                    await self.publish()
                return
            if now - self._last_display_tick >= 5:
                self._last_display_tick = now
                for binding in self.admitted.bindings:
                    self.control(binding["binding_id"], "CLOCK_TICK")
            if not self._selected:
                await self.publish()
                return
            if not self._bootstrapped:
                try:
                    status = await self._io(self.client.get_status)
                    if not status.active or status.daily_remaining is None:
                        raise ValueError("E_LIVE_ACCOUNT")
                    self._bootstrapped = True
                except Exception:
                    self._reason = self._reason or "SECURITY_HOLD"
                    for binding in self._selected:
                        self.control(binding, "PROVIDER_START_FAILED", "PAUSED")
                    await self.publish()
                    return
            outcome = await self._io(lambda: self.poller.tick(self._mono()))
            if self._reason is not None:
                return
            if outcome.projection:
                for state in outcome.projection.states.values():
                    self._append("ProviderState", state)
                    binding_id = next(
                        b["binding_id"]
                        for b in self.admitted.bindings
                        if b["provider_fixture_id"] == state["fixture_id"]
                    )
                    delay = 15 if state["period"] in {"H1", "H2"} else 60
                    if (
                        state["period"] == "PREGAME"
                        and (
                            datetime.fromisoformat(state["kickoff_utc"]) - self._utc()
                        ).total_seconds()
                        < 600
                    ):
                        delay = 30
                    self.control(binding_id, "SCHEDULE_" + str(delay))
                    await self.request_capture(binding_id)
            if outcome.status in {"PAUSED", "STOPPED"}:
                self._reason = "SOURCE_STOPPED"
                for binding in self._selected:
                    self.control(binding, "PROVIDER_STOPPED", "PAUSED")
            elif outcome.status == "STALE" or outcome.wake_gap:
                for binding in self._selected:
                    self.control(binding, "PROVIDER_DISCONNECTED", "STALE_PROVIDER")
            await self.publish()

    async def close(self, reason: str = "USER_STOP") -> LiveRunResult:
        if self._closed:
            raise ValueError("E_LIVE_SERVICE_CLOSED")
        self._reason = self._reason or reason
        self.poller.stop("SHUTDOWN")
        if self.receiver:
            await self.receiver.close()
        async with self._tick_lock:
            try:
                if self._mono() >= self._last_clock:
                    for binding in self.admitted.bindings:
                        self.control(binding["binding_id"], "USER_STOP", "STOPPED")
                    await self.publish()
                closed_utc = self._utc().isoformat().replace("+00:00", "Z")
                self.store.close_run(closed_utc, self._reason)
                count = self.quota.count_attempts()
                rows = self.quota.db.execute(
                    "SELECT r.attempt_id,r.purpose,r.reserved_at_utc,"
                    "r.reserved_mono_us,o.result_code "
                    "FROM quota_reservations r LEFT JOIN quota_outcomes o USING(attempt_id) "
                    "WHERE r.scope_id=? ORDER BY r.reserved_mono_us,r.attempt_id",
                    (self.admitted.run_id,),
                ).fetchall()
                requests = [
                    dict(
                        zip(
                            (
                                "attempt_id",
                                "purpose",
                                "reserved_at_utc",
                                "reserved_mono_us",
                                "outcome",
                            ),
                            row,
                            strict=True,
                        )
                    )
                    for row in rows
                ]
                self._artifact("requests.jsonl", requests, lines=True)
                self._artifact(
                    "result.json",
                    {
                        "schema_version": "part-b-recorded-run/v1",
                        "run_id": self.admitted.run_id,
                        "source_kind": self.admitted.source_kind,
                        "status": "STOPPED",
                        "reason": self._reason,
                        "started_at_utc": self._started_utc,
                        "closed_at_utc": closed_utc,
                        "duration_us": max(0, int((self._mono() - self._started_mono) * 1000000)),
                        "reserved_attempts": count,
                        "http_attempts": self.client.http_attempts,
                        "real_http_attempts": self.client.http_attempts
                        if self.admitted.source_kind == "OBSERVED_REAL"
                        else 0,
                        "authenticated": self._bootstrapped,
                        "model_enabled": False,
                        "money_ready": False,
                    },
                )
                with (self.directory / "provider-attempts.json").open("x") as output:
                    json.dump(
                        {
                            "source_kind": self.admitted.source_kind,
                            "reserved_attempts": count,
                            "http_attempts": self.client.http_attempts,
                            "attempts": self.client.request_log,
                        },
                        output,
                        indent=2,
                    )
                    output.flush()
                    os.fsync(output.fileno())
                return LiveRunResult(
                    self.admitted.run_id,
                    "STOPPED",
                    self._reason,
                    count,
                    self.client.http_attempts
                    if self.admitted.source_kind == "OBSERVED_REAL"
                    else 0,
                    str(self.directory),
                    authenticated=self._bootstrapped,
                )
            finally:
                self._closed = True
                self._resources.close()


async def _run(
    service: LiveService, on_ready: Callable[[LiveService], Callable[[], None] | None] | None = None
) -> LiveRunResult:
    cleanup: Callable[[], None] | None = None
    try:
        await service.start()
        if on_ready is not None:
            cleanup = on_ready(service)
        while service._reason is None:
            await service.tick()
            await asyncio.sleep(1)
    except Exception:
        service._reason = service._reason or "SECURITY_HOLD"
    finally:
        try:
            if cleanup is not None:
                cleanup()
        finally:
            result = await service.close()
    return result


def run_live_service(
    config: LiveConfig,
    secret: SecretValue,
    admitted: RunAdmission,
    *,
    on_ready: Callable[[LiveService], Callable[[], None] | None] | None = None,
) -> LiveRunResult:
    # No secret lookup occurs here. Only the no-echo user-terminal launcher may obtain it.
    return asyncio.run(_run(LiveService(config, secret, admitted), on_ready))
