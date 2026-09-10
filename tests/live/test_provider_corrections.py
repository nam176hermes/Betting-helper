import copy
from typing import Any

from moj_discovery.providers.football_normalizer import compare_event_sets
from tests.live.test_provider_normalization import normalize, stamp


def event(detail: Any = "Normal Goal", kind: Any = "Goal", player: Any = 501) -> Any:
    return {
        "time": {"elapsed": 10, "extra": None},
        "team": {"id": 201},
        "player": {"id": player},
        "assist": {"id": None},
        "type": kind,
        "detail": detail,
    }


def test_reorder_preserves_multiset_and_duplicate_multiplicity(
    synthetic_provider_response: Any,
) -> None:
    row = synthetic_provider_response["response"][0]
    a, b = event(), event("Yellow Card", "Card", 502)
    row["events"] = [a, b, a]
    first = normalize(synthetic_provider_response).states[101]
    row["events"] = [a, a, b]
    second = normalize(synthetic_provider_response, stamp(previous_states={101: first})).states[101]
    change = compare_event_sets(first["events"], second["events"])
    assert change.kind == "UNCHANGED"
    assert change.old_hash == change.new_hash
    assert len(second["events"]) == 3
    assert first["content_revision"] == second["content_revision"]


def test_removed_or_changed_goal_is_correction(synthetic_provider_response: Any) -> None:
    row = synthetic_provider_response["response"][0]
    row["events"] = [event(), event("Yellow Card", "Card")]
    first = normalize(synthetic_provider_response).states[101]
    for events in [
        [event("Yellow Card", "Card")],
        [event("Own Goal"), event("Yellow Card", "Card")],
    ]:
        row["events"] = events
        result = normalize(synthetic_provider_response, stamp(previous_states={101: first}))
        second = result.states[101]
        assert compare_event_sets(first["events"], second["events"]).kind == "CORRECTION"
        assert second["content_revision"] == "2"
        assert result.event_changes[101].kind == "CORRECTION"


def test_unknown_detail_and_ambiguous_reds_stay_unknown(synthetic_provider_response: Any) -> None:
    row = synthetic_provider_response["response"][0]
    cases = [
        [event("Future Card", "Card")],
        [event("Red Card", "Card", None)],
        [event("Red Card", "Card"), event("Red Card", "Card")],
        [event("Red Card", "Card"), event("Second Yellow card", "Card")],
    ]
    for events in cases:
        row["events"] = copy.deepcopy(events)
        state = normalize(synthetic_provider_response).states[101]
        assert state["red_card_state"] == "UNKNOWN"
    row["events"] = [event("Red Card", "Card")]
    assert normalize(synthetic_provider_response).states[101]["red_card_state"] == "KNOWN"


def test_missing_actor_preserves_event_and_unknown_red(synthetic_provider_response: Any) -> None:
    missing = event("Red Card", "Card")
    missing["player"] = None
    missing["assist"] = None
    synthetic_provider_response["response"][0]["events"] = [missing]
    state = normalize(synthetic_provider_response).states[101]
    assert state["red_card_state"] == "UNKNOWN"
    assert state["events_status"] == "OBSERVED"
    assert state["events"][0]["player_id"] is None
