import re
from collections.abc import Mapping

_TRANSITIONS = {
    ("OPEN", "SHOCK_ATOMIC_CLOSE"): "SHOCKED_CLOSED",
    ("NEW_EPOCH_OPEN", "SHOCK_ATOMIC_CLOSE"): "SHOCKED_CLOSED",
    ("SHOCKED_CLOSED", "CLOSE_RECORDED"): "WAITING_FOR_RESNAPSHOT",
    ("WAITING_FOR_RESNAPSHOT", "RESNAPSHOT_CANDIDATE_ACCEPTED"): "NEW_EPOCH_PENDING",
    ("NEW_EPOCH_PENDING", "RELEASE_PREDICATE_SATISFIED"): "NEW_EPOCH_OPEN",
    ("NEW_EPOCH_PENDING", "NEW_SHOCK_CLOSED_CANDIDATE"): "WAITING_FOR_RESNAPSHOT",
}


def _rejected(error: str, state: str) -> dict[str, object]:
    return {"accepted": False, "error": error, "state": state}


def _valid_artifact_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Z][A-Z0-9_]*:[0-9a-f]{64}", value) is not None
    )


class CoherenceController:
    def transition(self, state: str, reason: str) -> str:
        try:
            return _TRANSITIONS[state, reason]
        except KeyError as exc:
            raise ValueError("E_INVALID_COHERENCE_TRANSITION") from exc

    def accept_candidate(self, value: Mapping[str, object]) -> dict[str, object]:
        required = (
            value.get("controller_state") == "WAITING_FOR_RESNAPSHOT",
            value.get("proof_status") == "OBSERVED",
            value.get("proof_verified") is True,
            value.get("release_predicate") == "SATISFIED",
            value.get("predecessor_permanently_closed") is True,
            value.get("candidate_distinct_from_predecessor") is True,
            value.get("freshness_binding_verified") is True,
            value.get("shock_binding_verified") is True,
            value.get("mapping_bindings_verified") is True,
            value.get("continuity_bindings_verified") is True,
        )
        if not all(required):
            return _rejected("E_RESNAPSHOT_CANDIDATE_BINDING", "WAITING_FOR_RESNAPSHOT")
        return {"accepted": True, "error": "ACCEPT", "state": "NEW_EPOCH_PENDING"}

    def evaluate_release(self, value: Mapping[str, object]) -> dict[str, object]:
        if value.get("predecessor_reopen_requested") is True:
            return _rejected("E_PREDECESSOR_EPOCH_IMMUTABLE", "CLOSED_FOREVER")
        if value.get("controller_state") != "NEW_EPOCH_PENDING":
            return _rejected("E_INVALID_COHERENCE_TRANSITION", "NEW_EPOCH_PENDING")
        predecessor_id = value.get("predecessor_epoch_id")
        candidate_id = value.get("candidate_epoch_id")
        if (
            value.get("candidate_created") is not True
            or not _valid_artifact_id(predecessor_id)
            or not _valid_artifact_id(candidate_id)
        ):
            return _rejected("E_RELEASE_BINDING", "NEW_EPOCH_PENDING")
        if candidate_id == predecessor_id:
            return _rejected("E_INVALID_COHERENCE_TRANSITION", "NEW_EPOCH_PENDING")
        if value.get("predecessor_permanently_closed") is not True:
            return _rejected("E_NON_GENESIS_PREDECESSOR_NOT_CLOSED", "WAITING_FOR_RESNAPSHOT")
        if value.get("predecessor_closed") is not True:
            return _rejected("E_PREDECESSOR_NOT_CLOSED", "WAITING_FOR_RESNAPSHOT")
        if value.get("signed_accepted_capability_evidence") is not True:
            return _rejected("E_CAPABILITY_EVIDENCE_NOT_ACCEPTED", "WAITING_FOR_RESNAPSHOT")
        if value.get("proof_status") == "NOT_OBSERVED":
            return _rejected("E_RESNAPSHOT_NOT_OBSERVED", "WAITING_FOR_RESNAPSHOT")
        if value.get("proof_status") != "OBSERVED" or value.get("proof_verified") is not True:
            return _rejected("E_RESNAPSHOT_UNKNOWN", "WAITING_FOR_RESNAPSHOT")
        if value.get("snapshot_semantics") != "FULL_AUTHORITATIVE_SNAPSHOT":
            return _rejected("E_RESNAPSHOT_NOT_OBSERVED", "WAITING_FOR_RESNAPSHOT")
        checks = (
            (value.get("football_state") == "FRESH", "E_FOOTBALL_STATE_NOT_FRESH"),
            (value.get("operator_state") == "FRESH", "E_OPERATOR_STATE_NOT_FRESH"),
            (value.get("market_book") == "FRESH_COMPLETE_OPEN", "E_MARKET_BOOK_NOT_COMPLETE_OPEN"),
            (value.get("conservative_lower_bounds_strictly_after_shock_upper") is True,
             "E_NOT_STRICTLY_POST_SHOCK"),
            (value.get("proof_bound_mappings_open_unclosed_valid_at_release") is True,
             "E_MAPPING_CLOSED"),
            (value.get("mappings_valid") is True, "E_MAPPING_CLOSED"),
            (value.get("identities_orientation_generations_agree") is True,
             "E_IDENTITY_OR_GENERATION_MISMATCH"),
            (value.get("cursor_ranges_contiguous") is True, "E_CURSOR_NOT_CONTIGUOUS"),
        )
        for passed, error in checks:
            if not passed:
                return _rejected(error, "NEW_EPOCH_PENDING")
        blocker_absent = value.get(
            "gap_conflict_schema_lifecycle_mapping_or_later_shock_absent"
        )
        if blocker_absent is not True:
            if value.get("blocker") == "LATER_OR_INTERSECTING_SHOCK":
                return _rejected("E_CANDIDATE_CLOSED_BY_NEW_SHOCK", "WAITING_FOR_RESNAPSHOT")
            return _rejected("E_RELEASE_BLOCKED", "NEW_EPOCH_PENDING")
        if value.get("score_period_suspension_and_shock_fields_agree") is not True:
            return _rejected("E_STATE_FIELDS_DISAGREE", "NEW_EPOCH_PENDING")
        if (
            value.get("freshness_bindings_valid_at_release") is not True
            or value.get("continuity_bindings_valid_at_release") is not True
            or value.get("proof_bindings_valid") is not True
        ):
            return _rejected("E_RELEASE_BINDING", "NEW_EPOCH_PENDING")
        return {
            "accepted": True,
            "error": "ACCEPT",
            "state": "NEW_EPOCH_OPEN",
            "predecessor_state": "CLOSED_FOREVER",
            "successor_distinct": True,
        }
