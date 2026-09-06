import json
from pathlib import Path

import pytest

from moj_discovery.clock import ClockMapper
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
VECTORS = json.loads(
    (plan_root(ROOT) / "docs/vectors/inherited/clock-coherence-v6.2.json").read_text()
)
MAPPING_ID = "MAP:" + "c" * 64


def test_selects_each_governed_mapping_by_frozen_precedence() -> None:
    mapper = ClockMapper()
    for vector in VECTORS["mapping_selection_vectors"]:
        assert mapper.select(vector["candidates"])["mapping_id"] == vector["expected_mapping_id"]


def test_each_governed_closure_reason_is_permanent_and_retained_in_history() -> None:
    mapper = ClockMapper()
    for vector in VECTORS["closure_vectors"][:10]:
        history = mapper.close(MAPPING_ID, vector["reason"])
        closure = history[-1]
        assert closure.mapping_id == MAPPING_ID
        assert closure.reason == vector["reason"]
        assert closure.permanent is vector["permanent"]
        assert closure.reopen_permitted is False
        assert history == (closure,)
        with pytest.raises(ValueError, match=vector["reopen_attempt_error"]):
            mapper.reopen(MAPPING_ID, history)


def test_close_returns_new_history_without_mutating_existing_closures() -> None:
    mapper = ClockMapper()
    first = mapper.close(MAPPING_ID, "SLEEP_RESUME")
    second = mapper.close("MAP:" + "d" * 64, "RUN_CLOSED", first)
    assert first == second[:1]
    assert len(first) == 1
    assert len(second) == 2


def test_closed_mapping_cannot_be_selected_for_later_observation() -> None:
    mapper = ClockMapper()
    candidate = {"mapping_id": MAPPING_ID, "width_us": 1, "valid_from_us": 1}
    history = mapper.close(MAPPING_ID, "SLEEP_RESUME")
    with pytest.raises(ValueError, match="E_NO_VALID_MAPPING"):
        mapper.select([candidate], history)
