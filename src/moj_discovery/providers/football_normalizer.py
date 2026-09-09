"""Pure football projection: source observations and semantic changes stay distinct."""

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import rfc8785

from ..live_contracts import MAX_INTEGER, validate_live_record
from .api_football import ProviderResponse

PERIODS = {
    "NS": "PREGAME",
    "1H": "H1",
    "HT": "HALFTIME",
    "2H": "H2",
    "FT": "FINISHED",
    "SUSP": "BLOCKED",
    "INT": "BLOCKED",
    **dict.fromkeys(
        ("ET", "BT", "P", "AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"), "OUT_OF_SCOPE"
    ),
}
TYPES = {"goal": "GOAL", "card": "CARD", "subst": "SUBSTITUTION", "var": "VAR"}
DETAILS = {
    "normal goal": "NORMAL_GOAL",
    "own goal": "OWN_GOAL",
    "penalty": "PENALTY",
    "missed penalty": "MISSED_PENALTY",
    "yellow card": "YELLOW_CARD",
    "red card": "RED_CARD",
    "second yellow card": "SECOND_YELLOW",
    "goal cancelled": "GOAL_CANCELLED",
    "penalty cancelled": "PENALTY_CANCELLED",
}
OBSERVATION_FIELDS = frozenset(
    {
        "observed_at_utc",
        "received_mono_us",
        "clock_domain_id",
        "request_id",
        "batch_observation_id",
        "content_revision",
    }
)


@dataclass(frozen=True)
class ObservationStamp:
    observed_at_utc: datetime
    received_mono_us: int
    clock_domain_id: str
    batch_observation_id: str
    league_id: int
    season: int
    previous_states: Mapping[int, dict[str, Any]] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class EventRevision:
    kind: str
    old_hash: str
    new_hash: str


@dataclass(frozen=True)
class BundleProjection:
    states: dict[int, dict[str, Any]]
    missing_ids: tuple[int, ...]
    rejected: dict[int, str]
    event_changes: dict[int, EventRevision]
    batch_observation_id: str
    source_kind: str


def _event_bytes(events: Sequence[dict[str, Any]]) -> list[bytes]:
    return sorted(rfc8785.dumps(event) for event in events)


def compare_event_sets(
    old: Sequence[dict[str, Any]], new: Sequence[dict[str, Any]]
) -> EventRevision:
    before, after = _event_bytes(old), _event_bytes(new)
    before_hash = hashlib.sha256(
        b"BH-LIVE-READONLY/Events/v1\0[" + b",".join(before) + b"]"
    ).hexdigest()
    after_hash = hashlib.sha256(
        b"BH-LIVE-READONLY/Events/v1\0[" + b",".join(after) + b"]"
    ).hexdigest()
    kind = (
        "UNCHANGED"
        if before == after
        else ("CORRECTION" if Counter(before) - Counter(after) else "EVENT_SET_CHANGED")
    )
    return EventRevision(kind, before_hash, after_hash)


def semantic_hash(state: dict[str, Any]) -> str:
    payload = {k: v for k, v in state.items() if k not in OBSERVATION_FIELDS}
    return hashlib.sha256(
        b"BH-LIVE-READONLY/ProviderSemantic/v1\0" + rfc8785.dumps(payload)
    ).hexdigest()


def _integer(value: object, minimum: int = 0, maximum: int = 2**53 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("INVALID_FIXTURE")
    return value


def _nullable(value: object, minimum: int = 0) -> int | None:
    return None if value is None else _integer(value, minimum)


def _score(value: object, flags: set[str]) -> dict[str, int] | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError("INVALID_FIXTURE")
    home, away = value.get("home"), value.get("away")
    for score in (home, away):
        if score is not None:
            _integer(score, 0, 100)
    if home is None or away is None:
        if home is not None or away is not None:
            flags.add("PARTIAL_SCORE")
        return None
    return {"home": home, "away": away}


def _availability(value: object) -> str:
    if value is None:
        return "MISSING"
    if type(value) is not list:
        return "MALFORMED"
    return "PRESENT" if value else "EMPTY"


def _actor_id(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError("INVALID_EVENT")
    return _nullable(value.get("id"), 1)


def _events(
    value: object, participants: set[int]
) -> tuple[list[dict[str, Any]], str, set[str], str]:
    if value is None:
        return [], "UNKNOWN_SECTION", {"EVENTS_UNKNOWN"}, "UNKNOWN"
    try:
        if type(value) is not list or len(value) > 2000:
            raise ValueError()
        normalized = []
        flags: set[str] = set()
        for event in value:
            source_time = event["time"]
            kind = TYPES.get(event["type"].casefold(), "OTHER")
            detail = DETAILS.get(event["detail"].casefold(), "OTHER")
            if kind == "OTHER" or detail == "OTHER":
                flags.add("UNKNOWN_EVENT_DETAIL")
            team = _actor_id(event.get("team"))
            if team is not None and team not in participants:
                raise ValueError()
            normalized.append(
                {
                    "elapsed_minute": _nullable(source_time.get("elapsed")),
                    "extra_minute": _nullable(source_time.get("extra")),
                    "team_id": team,
                    "player_id": _actor_id(event.get("player")),
                    "assist_id": _actor_id(event.get("assist")),
                    "type": kind,
                    "detail": detail,
                }
            )
        normalized.sort(key=rfc8785.dumps)
        dismissals = [
            e
            for e in normalized
            if e["type"] == "CARD" and e["detail"] in {"RED_CARD", "SECOND_YELLOW"}
        ]
        players = [(e["team_id"], e["player_id"]) for e in dismissals]
        red = "KNOWN"
        if (
            flags
            or any(team is None or player is None for team, player in players)
            or len(set(players)) != len(players)
        ):
            red = "UNKNOWN"
            flags.add("RED_CARD_STATE_UNKNOWN")
        return normalized, "OBSERVED" if normalized else "OBSERVED_EMPTY", flags, red
    except (KeyError, TypeError, ValueError, AttributeError):
        return [], "MALFORMED", {"EVENTS_MALFORMED"}, "UNKNOWN"


def _fixture(
    raw: dict[str, Any], response: ProviderResponse, stamp: ObservationStamp
) -> dict[str, Any]:
    fixture, league = raw["fixture"], raw["league"]
    fixture_id = _integer(fixture["id"], 1)
    if (
        _integer(league["id"], 1) != stamp.league_id
        or _integer(league["season"], 2000, 2100) != stamp.season
    ):
        raise ValueError("INVALID_FIXTURE")
    kickoff = datetime.fromisoformat(fixture["date"])
    if kickoff.tzinfo is None or _integer(fixture["timestamp"], 1) != int(kickoff.timestamp()):
        raise ValueError("INVALID_FIXTURE")
    kickoff_text = kickoff.astimezone(UTC).isoformat().replace("+00:00", "Z")
    home, away = raw["teams"]["home"], raw["teams"]["away"]
    home_id, away_id = _integer(home["id"], 1), _integer(away["id"], 1)
    previous = stamp.previous_states.get(fixture_id)
    if previous is not None:
        previous = validate_live_record(previous, "ProviderState")
        if (
            previous["fixture_id"] != fixture_id
            or previous["home_id"] != home_id
            or previous["away_id"] != away_id
            or previous["kickoff_utc"] != kickoff_text
        ):
            raise ValueError("IDENTITY_MISMATCH")
    status = fixture["status"]
    period = PERIODS.get(status["short"], "UNKNOWN")
    elapsed, extra = _nullable(status.get("elapsed")), _nullable(status.get("extra"))
    flags = {"SYNTHETIC"} if response.source_kind == "MOCK" else set()
    if period in {"UNKNOWN", "OUT_OF_SCOPE", "BLOCKED"}:
        flags.add(
            {
                "UNKNOWN": "UNKNOWN_PERIOD",
                "OUT_OF_SCOPE": "NORMAL_TIME_INELIGIBLE",
                "BLOCKED": "SOURCE_BLOCKED",
            }[period]
        )
    events, events_status, event_flags, red = _events(raw.get("events"), {home_id, away_id})
    flags.update(event_flags)
    availability = {
        name: _availability(raw.get(name))
        for name in ("events", "lineups", "statistics", "players")
    }
    if events_status == "MALFORMED":
        availability["events"] = "MALFORMED"
    score = _score(raw.get("goals"), flags)
    scores = raw.get("score") or {}
    halftime, fulltime = (
        _score(scores.get("halftime"), flags),
        _score(scores.get("fulltime"), flags),
    )
    if (
        score is not None
        and events_status in {"OBSERVED", "OBSERVED_EMPTY"}
        and all(e["type"] != "VAR" and e["detail"] not in {"OWN_GOAL", "OTHER"} for e in events)
    ):
        goals = Counter(
            e["team_id"]
            for e in events
            if e["type"] == "GOAL" and e["detail"] in {"NORMAL_GOAL", "PENALTY"}
        )
        if goals[home_id] != score["home"] or goals[away_id] != score["away"]:
            flags.add("SCORE_EVENT_DISAGREEMENT")
    state = {
        "fixture_id": fixture_id,
        "observed_at_utc": stamp.observed_at_utc.isoformat().replace("+00:00", "Z"),
        "received_mono_us": str(stamp.received_mono_us),
        "clock_domain_id": stamp.clock_domain_id,
        "request_id": response.request_id,
        "batch_observation_id": stamp.batch_observation_id,
        "content_revision": "1",
        "status_code": status["short"],
        "period": period,
        "elapsed_minute": elapsed,
        "extra_minute": extra,
        "clock_precision": "MINUTE" if elapsed is not None else "UNKNOWN",
        "kickoff_utc": kickoff_text,
        "home_id": home_id,
        "away_id": away_id,
        "home_name": home["name"],
        "away_name": away["name"],
        "score_current": score,
        "score_ht": halftime,
        "score_ft": fulltime,
        "events": events,
        "events_status": events_status,
        "section_availability": availability,
        "red_card_state": red,
        "provider_updated_at": None,
        "quality_flags": sorted(flags),
    }
    if previous is not None:
        revision = int(previous["content_revision"]) + (
            semantic_hash(previous) != semantic_hash(state)
        )
        state["content_revision"] = str(revision)
    return validate_live_record(state, "ProviderState")


def normalize_bundle(
    response: ProviderResponse, selected: Sequence[int], observation: ObservationStamp
) -> BundleProjection:
    if (
        response.purpose != "BUNDLE"
        or response.source_kind not in {"MOCK", "OBSERVED_REAL"}
        or not 1 <= len(selected) <= 5
        or len(set(selected)) != len(selected)
        or any(type(i) is not int or i <= 0 for i in selected)
        or observation.observed_at_utc.tzinfo is None
        or observation.observed_at_utc.utcoffset() != UTC.utcoffset(observation.observed_at_utc)
    ):
        raise ValueError("E_BUNDLE_SCOPE")
    _integer(observation.received_mono_us, 0, MAX_INTEGER)
    _integer(observation.league_id, 1)
    _integer(observation.season, 2000, 2100)
    for identifier in (
        observation.clock_domain_id,
        observation.batch_observation_id,
        response.request_id,
    ):
        UUID(identifier)
    seen: set[int] = set()
    states, rejected, changes = {}, {}, {}
    for raw in response.rows:
        fixture_id = _integer(raw.get("fixture", {}).get("id"), 1)
        if fixture_id not in selected or fixture_id in seen:
            raise ValueError("E_BUNDLE_SCOPE")
        seen.add(fixture_id)
        try:
            state = _fixture(raw, response, observation)
            states[fixture_id] = state
            previous = observation.previous_states.get(fixture_id)
            if (
                previous
                and previous["events_status"] in {"OBSERVED", "OBSERVED_EMPTY"}
                and state["events_status"] in {"OBSERVED", "OBSERVED_EMPTY"}
            ):
                changes[fixture_id] = compare_event_sets(previous["events"], state["events"])
        except Exception as error:
            rejected[fixture_id] = (
                "IDENTITY_MISMATCH" if str(error) == "IDENTITY_MISMATCH" else "INVALID_FIXTURE"
            )
    return BundleProjection(
        states,
        tuple(sorted(set(selected) - seen)),
        rejected,
        changes,
        observation.batch_observation_id,
        response.source_kind,
    )
