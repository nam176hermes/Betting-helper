"""Closed display projections. Observed records stay separate from receipt ages."""

import copy
from typing import Any, TypedDict
from uuid import UUID

from .live_contracts import validate_live_record


class WorkspaceState(TypedDict):
    run_id: str | None
    views: list[dict[str, Any]]
    selected: list[str]
    max_matches: int
    source_kind: str
    quota: dict[str, int | None]
    provider_connection: str
    capture_connection: str


WorkspaceView = dict[str, Any]
STATES = {
    "WAITING_FOR_DATA",
    "CURRENT_DISPLAY_ONLY",
    "SOURCE_TIME_UNKNOWN",
    "STALE_PROVIDER",
    "STALE_MARKET",
    "STATE_CONFLICT",
    "MARKET_SUSPENDED",
    "PROFILE_EXPIRED",
    "OUT_OF_SCOPE",
    "STOPPED",
    "PAUSED",
    "GAP",
    "CONTEXT_UNVERIFIED",
}


def _age(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ValueError("E_WORKSPACE_AGE")
    return value


def project_watchlist(state: WorkspaceState) -> WorkspaceView:
    try:
        if (state["run_id"] is not None and str(UUID(state["run_id"])) != state["run_id"]) or (
            type(state["max_matches"]) is not int
            or state["max_matches"] not in {1, 3, 5}
            or len(state["views"]) > state["max_matches"]
            or len(set(state["selected"])) != len(state["selected"])
            or state["source_kind"] not in {"MOCK", "OBSERVED_REAL"}
            or state["provider_connection"] not in {"WAITING", "CONNECTED", "PAUSED", "STOPPED"}
            or state["capture_connection"] not in {"CONNECTED", "DISCONNECTED"}
        ):
            raise ValueError()
        if state["run_id"] is None and state["views"]:
            raise ValueError()
        quota = state["quota"]
        caps = {
            "session_remaining": 600,
            "daily_remaining": 6000,
            "minute_remaining": 6,
            "provider_remaining": 2**31 - 1,
        }
        if set(quota) != set(caps):
            raise ValueError()
        for key, cap in caps.items():
            value = quota[key]
            if value is None and key == "provider_remaining":
                continue
            if type(value) is not int or not 0 <= value <= cap:
                raise ValueError()
        matches: list[dict[str, Any]] = []
        for view in state["views"]:
            binding = validate_live_record(view["binding"], "FixtureBinding")
            provider = (
                None
                if view["provider"] is None
                else validate_live_record(view["provider"], "ProviderState")
            )
            if provider is not None and any(
                provider[field] != binding[key]
                for field, key in (
                    ("fixture_id", "provider_fixture_id"),
                    ("home_id", "home_id"),
                    ("away_id", "away_id"),
                    ("kickoff_utc", "kickoff_utc"),
                )
            ):
                raise ValueError()
            if (
                view["status"] not in STATES
                or view["model_enabled"] is not False
                or view["money_ready"] is not False
            ):
                raise ValueError()
            books = []
            markets = {}
            for horizon, raw in view["books"].items():
                book = validate_live_record(raw, "MarketBook")
                if (
                    book["binding_id"] != binding["binding_id"]
                    or book["binding_revision"] != binding["revision"]
                    or book["horizon"] != horizon
                ):
                    raise ValueError()
                if ("SYNTHETIC" in book["quality_flags"]) != (state["source_kind"] == "MOCK"):
                    raise ValueError()
                status = view["market_states"][horizon]
                if status["status"] not in STATES:
                    raise ValueError()
                markets[horizon] = {
                    "status": status["status"],
                    "receipt_age_us": _age(status["receipt_age_us"]),
                    "content_age_us": _age(status["content_age_us"]),
                    "source_age_us": None,
                }
                books.append(book)
            if (
                type(view["projection_revision"]) is not int
                or not 0 <= view["projection_revision"] <= 2**63 - 1
            ):
                raise ValueError()
            score = view["h2_score"]
            if score is not None and (
                type(score) is not dict
                or set(score) != {"home", "away"}
                or any(type(v) is not int or not 0 <= v <= 100 for v in score.values())
            ):
                raise ValueError()
            matches.append(
                {
                    "binding": binding,
                    "provider_state": provider,
                    "books": books,
                    "revision": str(view["projection_revision"]),
                    "display": {
                        "source_kind": state["source_kind"],
                        "status": view["status"],
                        "selected": binding["binding_id"] in state["selected"],
                        "max_matches": state["max_matches"],
                        "provider_receipt_age_us": _age(view["provider_receipt_age_us"]),
                        "provider_content_age_us": _age(view["provider_content_age_us"]),
                        "source_age_us": None,
                        "markets": markets,
                        "h2_score": copy.deepcopy(view["h2_score"]),
                        "quota": copy.deepcopy(quota),
                        "provider_connection": state["provider_connection"],
                        "capture_connection": state["capture_connection"],
                    },
                }
            )
        ids = [row["binding"]["binding_id"] for row in matches]
        if len(set(ids)) != len(ids) or not set(state["selected"]) <= set(ids):
            raise ValueError()
        return {
            "run_id": state["run_id"],
            "matches": matches,
            "source_time_status": "UNKNOWN",
            "model_status": "MODEL_NOT_QUALIFIED",
            "money_ready": False,
        }
    except Exception:
        raise ValueError("E_WORKSPACE_PROJECTION") from None
