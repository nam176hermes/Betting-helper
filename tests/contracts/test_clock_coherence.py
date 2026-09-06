import json
from pathlib import Path

import pytest

from moj_discovery.clock import ClockMapper
from moj_discovery.coherence import CoherenceController
from moj_discovery.vendor import plan_root

ROOT = Path(__file__).parents[2]
VECTORS = json.loads(
    (plan_root(ROOT) / "docs/vectors/inherited/clock-coherence-v6.2.json").read_text()
)
MAPPING_ID = "MAP:" + "c" * 64


def _release_input() -> dict[str, object]:
    return {
        **{key: value for key, value in VECTORS["release_positive_vector"].items()
           if key not in {"id", "expected_transition", "expected_predecessor_state",
                          "expected_successor_distinct"}},
        "controller_state": "NEW_EPOCH_PENDING",
        "predecessor_epoch_id": "EPOCH:predecessor",
        "candidate_epoch_id": "EPOCH:candidate",
        "proof_verified": True,
        "candidate_created": True,
        "candidate_distinct_from_predecessor": True,
        "predecessor_permanently_closed": True,
        "proof_bindings_valid": True,
    }


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


def test_governed_coherence_state_path_and_pending_shock() -> None:
    controller = CoherenceController()
    state = "OPEN"
    for reason, expected in (
        ("SHOCK_ATOMIC_CLOSE", "SHOCKED_CLOSED"),
        ("CLOSE_RECORDED", "WAITING_FOR_RESNAPSHOT"),
        ("RESNAPSHOT_CANDIDATE_ACCEPTED", "NEW_EPOCH_PENDING"),
        ("RELEASE_PREDICATE_SATISFIED", "NEW_EPOCH_OPEN"),
    ):
        state = controller.transition(state, reason)
        assert state == expected
    assert controller.transition("NEW_EPOCH_PENDING", "NEW_SHOCK_CLOSED_CANDIDATE") == (
        "WAITING_FOR_RESNAPSHOT"
    )


@pytest.mark.parametrize(
    "vector", VECTORS["candidate_acceptance_negative_vectors"], ids=lambda item: item["id"]
)
def test_candidate_gate_rejects_each_governed_negative(vector: dict[str, object]) -> None:
    candidate = {
        "controller_state": "WAITING_FOR_RESNAPSHOT",
        "proof_status": vector.get("proof_status_at_transition", vector.get("proof_status")),
        "proof_verified": vector["proof_verified"],
        "release_predicate": vector["release_predicate"],
        "predecessor_permanently_closed": True,
        "candidate_distinct_from_predecessor": True,
        "freshness_binding_verified": vector.get("freshness_binding_verified", False),
        "shock_binding_verified": vector.get("shock_binding_verified", False),
        "mapping_bindings_verified": vector.get("mapping_bindings_verified", False),
        "continuity_bindings_verified": vector.get("continuity_bindings_verified", False),
    }
    assert CoherenceController().accept_candidate(candidate) == {
        "accepted": False,
        "error": "E_RESNAPSHOT_CANDIDATE_BINDING",
        "state": vector["expected_state"],
    }


def test_release_positive_and_all_frozen_negative_results() -> None:
    controller = CoherenceController()
    assert controller.evaluate_release(_release_input()) == {
        "accepted": True,
        "error": "ACCEPT",
        "state": "NEW_EPOCH_OPEN",
        "predecessor_state": "CLOSED_FOREVER",
        "successor_distinct": True,
    }
    for vector in VECTORS["release_negative_vectors"]:
        value = _release_input()
        if "proof_status" in vector:
            value["proof_status"] = vector["proof_status"]
        if "blocker" in vector:
            value["blocker"] = vector["blocker"]
        if "failed_predicate" in vector:
            predicate = str(vector["failed_predicate"])
            value[predicate] = (
                vector.get("value", vector["proof_status"])
                if predicate == "proof_status"
                else vector.get("value", False)
            )
        attempt = vector.get("attempt")
        if attempt == "REOPEN_CLOSED_PREDECESSOR_EPOCH":
            value["predecessor_reopen_requested"] = True
        elif attempt == "NEW_EPOCH_PENDING_TO_NEW_EPOCH_OPEN_WITH_CANDIDATE_NOT_CREATED":
            value["candidate_created"] = False
            value["candidate_epoch_id"] = None
        elif attempt == "CONTROLLER_RELEASE_RETAINS_PREDECESSOR_AS_CURRENT_EPOCH":
            value["candidate_epoch_id"] = value["predecessor_epoch_id"]
        elif attempt == "CREATE_NON_GENESIS_EPOCH_WITH_PREDECESSOR_PERMANENTLY_CLOSED_FALSE":
            value["predecessor_permanently_closed"] = False
        elif attempt == (
            "RELEASE_WITH_OBSERVED_PROOF_NOT_BOUND_TO_CANDIDATE_FRESHNESS_"
            "SHOCK_MAPPINGS_AND_CONTINUITY"
        ):
            value["proof_bindings_valid"] = False
        result = controller.evaluate_release(value)
        assert result["accepted"] is False
        assert result["error"] == vector["expected_error"]
        assert result["state"] == vector["expected_state"]
