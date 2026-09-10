"""Pure display projection. Receive order is replay order, never source chronology.

Only backend-generated HealthChange records carry receipt/request clocks. A
CAPTURE_REQUEST_STARTED challenge is sent through the existing PROJECTION health
record; the fixed producer derives its observation ID before starting DOM reads.
CAPTURE_RECEIVED links the actual committed operator event to backend receipt time.
Producer-supplied monotonic values are never compared to backend monotonic values.
"""

import copy
import hashlib
from typing import Any
from uuid import UUID, uuid5

import rfc8785

from .live_contracts import MAX_INTEGER, event_hash, validate_live_record
from .providers.football_normalizer import semantic_hash

CHALLENGE_NAMESPACE = UUID("8aa7e474-6a01-4ae9-91d8-d4770a55b3e4")
BOOK_RECEIPT_FIELDS = frozenset(
    {"capture_revision", "observed_at_utc", "browser_mono_us", "clock_domain_id"}
)
BLOCKS = {"STOPPED", "PAUSED", "PROFILE_EXPIRED", "OUT_OF_SCOPE"}
TIMED_CONTROLS = {
    "CLOCK_TICK",
    "PROFILE_ADMITTED",
    "PROVIDER_REQUEST_STARTED",
    "CAPTURE_REQUEST_STARTED",
    "CAPTURE_RECEIVED",
    "SCHEDULE_15",
    "SCHEDULE_30",
    "SCHEDULE_60",
    "USER_RESUME",
}


def request_reference(request_id: str) -> str:
    UUID(request_id)
    return hashlib.sha256(b"BH-LIVE-READONLY/Request/v1\0" + request_id.encode()).hexdigest()


def capture_observation_id(challenge_hash: str, horizon: str) -> str:
    if (
        len(challenge_hash) != 64
        or any(c not in "0123456789abcdef" for c in challenge_hash)
        or horizon not in {"H1", "H2", "FT"}
    ):
        raise ValueError("E_LIVE_CAPTURE_CHALLENGE")
    return str(uuid5(CHALLENGE_NAMESPACE, challenge_hash + ":" + horizon))


def h2_score(ht: tuple[int, int] | None, current: tuple[int, int] | None) -> tuple[int, int] | None:
    if ht is None or current is None:
        return None
    if (
        len(ht) != 2
        or len(current) != 2
        or any(type(v) is not int or not 0 <= v <= 100 for v in (*ht, *current))
        or any(a > b for a, b in zip(ht, current, strict=True))
    ):
        return None
    return current[0] - ht[0], current[1] - ht[1]


def _observations(previous: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    """Preserve source records independently before deriving display eligibility."""
    kind, payload = event["payload_type"], event["payload"]
    view = copy.deepcopy(previous)
    if kind == "BindingChange":
        binding = validate_live_record(payload["after"], "FixtureBinding")
        before = None if view is None else view["binding"]["revision"]
        if payload["before_revision"] != before or int(binding["revision"]) != (
            1 if before is None else int(before) + 1
        ):
            raise ValueError("E_LIVE_BINDING_REVISION")
        view = {
            "binding_id": binding["binding_id"],
            "binding": binding,
            "provider": None,
            "books": {},
            "health": None,
            "model_enabled": False,
            "money_ready": False,
        }
    elif view is None:
        raise ValueError("E_LIVE_BINDING_REQUIRED")
    elif kind == "ProviderState":
        binding = view["binding"]
        if any(
            payload[k] != binding[b]
            for k, b in (
                ("fixture_id", "provider_fixture_id"),
                ("home_id", "home_id"),
                ("away_id", "away_id"),
                ("kickoff_utc", "kickoff_utc"),
            )
        ):
            raise ValueError("E_LIVE_BINDING_MISMATCH")
        prior = view["provider"]
        expected_revision = (
            1
            if prior is None
            else int(prior["content_revision"]) + (semantic_hash(prior) != semantic_hash(payload))
        )
        if int(payload["content_revision"]) != expected_revision:
            raise ValueError("E_LIVE_PROVIDER_REVISION")
        view["provider"] = payload
    elif kind == "MarketBook":
        if (
            payload["binding_revision"] != view["binding"]["revision"]
            or payload["operator_fixture_id"] != view["binding"]["operator_fixture_id"]
        ):
            raise ValueError("E_LIVE_BINDING_MISMATCH")
        prior = view["books"].get(payload["horizon"])
        if prior is not None and int(payload["capture_revision"]) <= int(prior["capture_revision"]):
            raise ValueError("E_LIVE_CAPTURE_REVISION")
        view["books"][payload["horizon"]] = payload
    elif kind == "HealthChange":
        view["health"] = payload
    else:
        raise ValueError("E_LIVE_STORE_KIND")
    assert view is not None
    view["last_observation_id"] = event["observation_id"]
    view["observed_at_utc"] = event["observed_at_utc"]
    view["received_mono_us"] = event["received_mono_us"]
    return view


def _invalidate(view: dict[str, Any], reason: str, event: dict[str, Any]) -> None:
    view["epoch"] += 1
    if view["epoch"] > MAX_INTEGER:
        raise ValueError("E_LIVE_EPOCH_RANGE")
    view["invalidation"] = {"reason": reason, "evidence_hash": event["content_hash"]}
    view["provider_epoch"] = None
    view["requests"] = {}
    view["capture_requests"] = {}
    for meta in view["book_meta"].values():
        meta["epoch"] = None


def _advance(view: dict[str, Any], value: int) -> None:
    if value < view["backend_now_us"]:
        raise ValueError("E_LIVE_BACKEND_CLOCK")
    view["backend_now_us"] = value


def _book_semantic(book: dict[str, Any]) -> str:
    return hashlib.sha256(
        rfc8785.dumps({k: v for k, v in book.items() if k not in BOOK_RECEIPT_FIELDS})
    ).hexdigest()


def _event_context(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        **{
            k: provider[k]
            for k in ("score_current", "score_ht", "period", "red_card_state", "events_status")
        },
        "events": [e for e in provider["events"] if e["type"] in {"GOAL", "CARD", "VAR"}],
    }


def _health(view: dict[str, Any], event: dict[str, Any]) -> None:
    payload = event["payload"]
    reason, evidence = payload["reason"], payload["evidence_hashes"]
    if reason in TIMED_CONTROLS:
        _advance(view, int(event["received_mono_us"]))
    if reason == "PROFILE_ADMITTED":
        if len(evidence) != 1 or view["hold"] in {"STOPPED", "PROFILE_EXPIRED"}:
            raise ValueError("E_LIVE_PROFILE_ADMISSION")
        if view["profile_hash"] != evidence[0]:
            _invalidate(view, reason, event)
        view["profile_hash"] = evidence[0]
    elif reason in {"PROVIDER_REQUEST_STARTED", "CAPTURE_REQUEST_STARTED"}:
        if len(evidence) != 1 or int(payload["epoch"]) != view["epoch"] or view["hold"] in BLOCKS:
            raise ValueError("E_LIVE_REQUEST_EPOCH")
        pending = (
            view["requests"] if reason == "PROVIDER_REQUEST_STARTED" else view["capture_requests"]
        )
        refs = (
            [evidence[0]]
            if reason == "PROVIDER_REQUEST_STARTED"
            else [capture_observation_id(evidence[0], h) for h in ("H1", "H2", "FT")]
        )
        if any(ref in pending for ref in refs):
            raise ValueError("E_LIVE_REQUEST_CAP")
        # One current request per source/fixture. Superseded late observations
        # remain visible but cannot satisfy this new request's freshness gate.
        pending.clear()
        for ref in refs:
            pending[ref] = {"epoch": view["epoch"], "started_us": view["backend_now_us"]}
    elif reason == "CAPTURE_RECEIVED":
        if len(evidence) != 1:
            raise ValueError("E_LIVE_CAPTURE_RECEIPT")
        matches = [m for m in view["book_meta"].values() if m["event_hash"] == evidence[0]]
        if len(matches) != 1 or matches[0]["receipt_us"] is not None:
            raise ValueError("E_LIVE_CAPTURE_RECEIPT")
        meta = matches[0]
        meta["receipt_us"] = view["backend_now_us"]
        if meta["semantic_changed"]:
            meta["changed_us"] = view["backend_now_us"]
    elif reason.startswith("SCHEDULE_") and reason in TIMED_CONTROLS:
        view["scheduled_interval_seconds"] = int(reason.removeprefix("SCHEDULE_"))
    elif reason == "CLOCK_TICK":
        pass
    elif reason == "USER_RESUME":
        if view["hold"] in {"STOPPED", "PROFILE_EXPIRED", "OUT_OF_SCOPE"}:
            raise ValueError("E_LIVE_RESUME_REQUIRES_ADMISSION")
        view["hold"] = None
        _invalidate(view, reason, event)
    else:
        _invalidate(view, reason, event)
        if payload["state"] in BLOCKS:
            view["hold"] = payload["state"]


def _display(view: dict[str, Any]) -> None:
    provider, now = view["provider"], view["backend_now_us"]
    provider_age = (
        None if view["provider_receipt_us"] is None else now - view["provider_receipt_us"]
    )
    view["provider_receipt_age_us"] = provider_age
    view["provider_content_age_us"] = (
        None if view["provider_changed_us"] is None else now - view["provider_changed_us"]
    )
    view["source_age"] = None
    view["source_time_status"] = "UNKNOWN"
    view["market_states"] = {}
    view["h2_score"] = None
    if provider is not None and view["halftime_baseline"] is not None:
        ht = view["halftime_baseline"]
        if provider["score_ht"] == ht and provider["score_current"] is not None:
            result = h2_score(
                (ht["home"], ht["away"]),
                (provider["score_current"]["home"], provider["score_current"]["away"]),
            )
            if result is not None:
                view["h2_score"] = {"home": result[0], "away": result[1]}
    for horizon, book in view["books"].items():
        meta = view["book_meta"][horizon]
        market_age = None if meta["receipt_us"] is None else now - meta["receipt_us"]
        state = "CURRENT_DISPLAY_ONLY"
        if view["hold"] is not None:
            state = view["hold"]
        elif view["binding"]["orientation_status"] != "VERIFIED":
            state = "CONTEXT_UNVERIFIED"
        elif view["profile_hash"] != book["profile_hash"]:
            state = "PROFILE_EXPIRED" if view["profile_hash"] is not None else "WAITING_FOR_DATA"
        elif provider is None:
            state = "WAITING_FOR_DATA"
        elif provider["period"] in {"OUT_OF_SCOPE", "BLOCKED", "UNKNOWN", "FINISHED"}:
            state = "OUT_OF_SCOPE"
        elif book["market_status"] != "OPEN":
            state = "MARKET_SUSPENDED"
        elif (
            book["settlement_basis"] != "NORMAL_TIME_INCLUDING_STOPPAGE"
            or (horizon == "H1" and provider["period"] != "H1")
            or (horizon == "H2" and provider["period"] != "H2")
        ):
            state = "OUT_OF_SCOPE"
        elif (
            book["operator_score"] is not None
            and provider["score_current"] is not None
            and book["operator_score"] != provider["score_current"]
        ) or (
            book["operator_period"] not in {None, "UNKNOWN"}
            and book["operator_period"] != provider["period"]
        ):
            state = "STATE_CONFLICT"
        elif (
            book["operator_score"] is None
            or provider["score_current"] is None
            or book["operator_period"] in {None, "UNKNOWN"}
            or (horizon == "H2" and view["h2_score"] is None)
            or book["capture_evidence_tier"] != "DISPLAY_COHERENT"
        ):
            state = "CONTEXT_UNVERIFIED"
        elif (
            provider_age is None
            or provider_age > max(45, 2 * view["scheduled_interval_seconds"] + 5) * 1000000
        ):
            state = "STALE_PROVIDER"
        elif market_age is None or market_age > 35000000:
            state = "STALE_MARKET"
        elif view["provider_epoch"] != view["epoch"] or meta["epoch"] != view["epoch"]:
            state = "WAITING_FOR_DATA"
        view["market_states"][horizon] = {
            "status": state,
            "market_eligible": state == "CURRENT_DISPLAY_ONLY",
            "receipt_age_us": market_age,
            "content_age_us": None if meta["changed_us"] is None else now - meta["changed_us"],
            "source_age": None,
        }
    view["market_eligible"] = any(m["market_eligible"] for m in view["market_states"].values())
    view["status"] = view["hold"] or (
        "CURRENT_DISPLAY_ONLY" if view["market_eligible"] else "WAITING_FOR_DATA"
    )
    view["model_enabled"] = False
    view["money_ready"] = False


def reduce_live_event(current: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    event = validate_live_record(event, "LiveEvent")
    if event_hash(event) != event["content_hash"]:
        raise ValueError("E_LIVE_EVENT_HASH")
    kind, payload = event["payload_type"], event["payload"]
    expected_source = {
        "BindingChange": "CONTROL",
        "HealthChange": "CONTROL",
        "ProviderState": "PROVIDER",
        "MarketBook": "OPERATOR",
    }[kind]
    if event["source_kind"] != expected_source:
        raise ValueError("E_LIVE_SOURCE_ROLE")
    if current is not None:
        binding = current["binding"]
        event_binding = payload.get("binding_id")
        if (event_binding is not None and event_binding != binding["binding_id"]) or (
            kind == "ProviderState" and payload["fixture_id"] != binding["provider_fixture_id"]
        ):
            raise ValueError("E_LIVE_BINDING_MISMATCH")
        if kind == "BindingChange" and payload["after"]["binding_id"] != binding["binding_id"]:
            raise ValueError("E_LIVE_BINDING_MISMATCH")
    view = _observations(current, event)
    if kind == "BindingChange":
        view.update(
            epoch=0 if current is None else current["epoch"] + 1,
            invalidation={"reason": "BINDING_CHANGE", "evidence_hash": event["content_hash"]},
            backend_now_us=0 if current is None else current["backend_now_us"],
            provider_receipt_us=None,
            provider_changed_us=None,
            provider_epoch=None,
            provider_clock_domain=None,
            requests={},
            capture_requests={},
            book_meta={},
            halftime_baseline=None,
            profile_hash=None,
            hold=None,
            scheduled_interval_seconds=15,
        )
    elif kind == "HealthChange":
        _health(view, event)
    elif kind == "ProviderState":
        assert current is not None
        previous = current["provider"]
        if view["provider_clock_domain"] not in {None, payload["clock_domain_id"]}:
            _invalidate(view, "BACKEND_CLOCK_CHANGED", event)
            view["hold"] = "PAUSED"
        else:
            _advance(view, int(payload["received_mono_us"]))
            view["provider_clock_domain"] = payload["clock_domain_id"]
            request = view["requests"].pop(request_reference(payload["request_id"]), None)
            if previous is not None and _event_context(previous) != _event_context(payload):
                _invalidate(view, "PROVIDER_CONTEXT_CHANGED", event)
            view["provider_receipt_us"] = view["backend_now_us"]
            if previous is None or semantic_hash(previous) != semantic_hash(payload):
                view["provider_changed_us"] = view["backend_now_us"]
            if request is not None and request["epoch"] == view["epoch"]:
                view["provider_epoch"] = view["epoch"]
            if (
                payload["period"] == "HALFTIME"
                and payload["score_ht"] is not None
                and payload["score_ht"] == payload["score_current"]
            ):
                view["halftime_baseline"] = copy.deepcopy(payload["score_ht"])
    elif kind == "MarketBook":
        assert current is not None
        previous = current["books"].get(payload["horizon"])
        request = view["capture_requests"].pop(event["observation_id"], None)
        if previous is not None and any(
            previous[k] != payload[k]
            for k in ("operator_score", "operator_period", "document_epoch", "profile_hash")
        ):
            _invalidate(view, "OPERATOR_CONTEXT_CHANGED", event)
        elif payload["market_status"] != "OPEN" and (
            previous is None or previous["market_status"] == "OPEN"
        ):
            _invalidate(view, "MARKET_SUSPENDED", event)
        previous_meta = current["book_meta"].get(payload["horizon"])
        view["book_meta"][payload["horizon"]] = {
            "event_hash": event["content_hash"],
            "receipt_us": None,
            "epoch": request["epoch"]
            if request is not None and request["epoch"] == view["epoch"]
            else None,
            "semantic_changed": previous is None
            or _book_semantic(previous) != _book_semantic(payload),
            "changed_us": None if previous_meta is None else previous_meta["changed_us"],
        }
    _display(view)
    return view
