import copy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from moj_discovery.providers.api_football import ProviderResponse
from moj_discovery.providers.football_normalizer import ObservationStamp, normalize_bundle


def stamp(**kwargs: Any) -> Any:
    return ObservationStamp(
        datetime(2026, 9, 9, 18, 10, tzinfo=UTC),
        1_000_000,
        str(uuid4()),
        str(uuid4()),
        999,
        2026,
        **kwargs,
    )


def bundle(raw: Any) -> Any:
    return ProviderResponse(str(uuid4()), "MOCK", "BUNDLE", tuple(raw["response"]))


def normalize(raw: Any, observation: Any = None, selected: Any = (101,)) -> Any:
    return normalize_bundle(bundle(raw), selected, observation or stamp())


def test_scoped_snapshot_preserves_nulls_and_source_time(synthetic_provider_response: Any) -> None:
    result = normalize(synthetic_provider_response, selected=(101, 103))
    state = result.states[101]
    assert state["score_current"] == {"home": 0, "away": 0}
    assert state["score_ht"] is None and state["score_ft"] is None
    assert state["provider_updated_at"] is None
    assert state["kickoff_utc"] == "2026-09-09T18:00:00Z"
    assert state["elapsed_minute"] == 10 and state["clock_precision"] == "MINUTE"
    assert state["events_status"] == "OBSERVED_EMPTY"
    assert result.missing_ids == (103,)
    assert "SYNTHETIC" in state["quality_flags"]


@pytest.mark.parametrize("value", [None, {"home": None, "away": None}, {"home": 0, "away": None}])
def test_null_score_is_not_zero(synthetic_provider_response: Any, value: Any) -> None:
    synthetic_provider_response["response"][0]["goals"] = value
    assert normalize(synthetic_provider_response).states[101]["score_current"] is None


@pytest.mark.parametrize(
    "status,period",
    [
        ("NS", "PREGAME"),
        ("1H", "H1"),
        ("HT", "HALFTIME"),
        ("2H", "H2"),
        ("FT", "FINISHED"),
        ("SUSP", "BLOCKED"),
        ("INT", "BLOCKED"),
        ("ET", "OUT_OF_SCOPE"),
        ("PEN", "OUT_OF_SCOPE"),
        ("ABD", "OUT_OF_SCOPE"),
        ("TBD", "UNKNOWN"),
        ("FUTURE", "UNKNOWN"),
    ],
)
def test_status_never_inferred_from_elapsed(
    synthetic_provider_response: Any, status: Any, period: Any
) -> None:
    row = synthetic_provider_response["response"][0]
    row["fixture"]["status"] = {"short": status, "elapsed": None, "extra": None}
    state = normalize(synthetic_provider_response).states[101]
    assert state["period"] == period
    assert state["clock_precision"] == "UNKNOWN"
    assert state["elapsed_minute"] is None


@pytest.mark.parametrize(
    "field,value",
    [("events", None), ("events", "malformed"), ("statistics", [{"PRIVATE": "DISCARDED"}])],
)
def test_missing_sections_and_discarded_details(
    synthetic_provider_response: Any, field: Any, value: Any
) -> None:
    row = synthetic_provider_response["response"][0]
    row[field] = value
    state = normalize(synthetic_provider_response).states[101]
    if field == "events":
        assert state["events_status"] == ("UNKNOWN_SECTION" if value is None else "MALFORMED")
        assert state["red_card_state"] == "UNKNOWN"
    else:
        assert state["section_availability"]["statistics"] == "PRESENT"
        assert "PRIVATE" not in repr(state)


@pytest.mark.parametrize(
    "mutation", ["score_bool", "score_large", "same_team", "league", "season", "kickoff"]
)
def test_bad_fixture_cannot_corrupt_sibling(
    synthetic_provider_response: Any, mutation: Any
) -> None:
    bad = copy.deepcopy(synthetic_provider_response["response"][0])
    bad["fixture"]["id"] = 103
    if mutation == "score_bool":
        bad["goals"]["home"] = True
    if mutation == "score_large":
        bad["goals"]["away"] = 101
    if mutation == "same_team":
        bad["teams"]["away"]["id"] = 201
    if mutation == "league":
        bad["league"]["id"] = 888
    if mutation == "season":
        bad["league"]["season"] = 2025
    if mutation == "kickoff":
        bad["fixture"]["timestamp"] += 60
    synthetic_provider_response["response"].append(bad)
    result = normalize(synthetic_provider_response, selected=(101, 103))
    assert set(result.states) == {101}
    assert result.rejected[103] == "INVALID_FIXTURE"


def test_observation_receipt_and_semantic_revision_are_separate(
    synthetic_provider_response: Any,
) -> None:
    initial_stamp = stamp()
    first = normalize(synthetic_provider_response, initial_stamp).states[101]
    next_stamp = replace(
        initial_stamp,
        received_mono_us=2_000_000,
        batch_observation_id=str(uuid4()),
        previous_states={101: first},
    )
    second = normalize(synthetic_provider_response, next_stamp).states[101]
    assert second["content_revision"] == first["content_revision"] == "1"
    assert second["received_mono_us"] != first["received_mono_us"]
    assert second["request_id"] != first["request_id"]
    assert second["batch_observation_id"] != first["batch_observation_id"]
    synthetic_provider_response["response"][0]["goals"]["home"] = 1
    third = normalize(synthetic_provider_response, next_stamp).states[101]
    assert third["content_revision"] == "2"


def test_identity_change_requires_binding_review(synthetic_provider_response: Any) -> None:
    first = normalize(synthetic_provider_response).states[101]
    synthetic_provider_response["response"][0]["teams"]["home"]["id"] = 555
    result = normalize(synthetic_provider_response, stamp(previous_states={101: first}))
    assert 101 not in result.states
    assert result.rejected[101] == "IDENTITY_MISMATCH"


def test_http_projection_flows_to_normalizer(
    tmp_path: Any, fake_clock: Any, synthetic_provider_response: Any
) -> None:
    from tests.live.test_api_football import STATUS, Reply, make_client

    synthetic_provider_response["response"][0]["lineups"] = []
    client, quota, _ = make_client(
        tmp_path, fake_clock, [Reply(STATUS), Reply(synthetic_provider_response)]
    )
    with quota, client:
        client.get_status()
        response = client.get_fixture_bundle([101, 103])
        result = normalize_bundle(response, [101, 103], stamp())
    assert result.missing_ids == (103,)
    assert result.states[101]["events_status"] == "OBSERVED_EMPTY"
    assert result.states[101]["section_availability"]["lineups"] == "EMPTY"
