from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .universal_denial import UniversalDenialEngine

VENDOR = Path("vendor/hybrid-discovery-v6.3.6")

E0_VECTOR = "e0-evidence-v1.json"
D0_VECTOR = "d0-evidence-v1.json"

_E0_SCENARIOS = tuple(f"E0-S{index:02d}" for index in range(1, 25))
_E0_REPORTS = frozenset(
    {
        "catalog-capability-report.json",
        "global-operator-state-report.json",
        "operator-identity-report.json",
        "participant-orientation-report.json",
        "transport-semantics-report.json",
        "quote-display-parity-report.json",
        "browser-lifecycle-report.json",
        "clock-timestamp-report.json",
        "gaps-and-loss-report.json",
        "loopback-topology-report.json",
        "betslip-observation-report.json",
        "position-observation-report.json",
        "cashout-observation-report.json",
        "capacity-report.json",
        "credential-redaction-report.json",
    }
)
_D0_REPORTS = frozenset(
    {
        "football-provider-capability-report.json",
        "football-latency-report.json",
        "football-correction-report.json",
        "football-identity-report.json",
    }
)
_SCOPE_CATEGORIES = frozenset(
    {
        "coverage",
        "semantics",
        "identity_confidence",
        "missingness",
        "timing",
        "replayability",
        "schema_stability",
        "capacity",
        "quota",
        "licensing",
        "cost",
    }
)
_D0_MODEL_FIELDS = frozenset({"features", "predictions", "probabilities", "model"})
_RANK_ONE_ERRORS = frozenset(
    {
        "E_ENCODING",
        "E_DUPLICATE_NAME",
        "E_NON_NFC",
        "E_SHAPE",
        "E_OPEN_OBJECT_ESCAPE",
        "E_D0_RESULT_FIELD",
        "E_D0_PERFORMANCE_FIELD",
        "E_FORBIDDEN_NAME",
        "E_FORBIDDEN_VALUE",
        "E_FORBIDDEN_COMMAND",
        "E_FORBIDDEN_AUTHORITY",
        "E_CREDENTIAL_ENTROPY",
    }
)


class EvidenceSemanticContractError(AssertionError):
    pass


@dataclass(frozen=True)
class EvidenceFailure:
    error_code: str
    precedence_rank: int


class EvidenceSemanticEvaluator:
    """Derive E0/D0 vector failures from candidate bytes and closed record semantics."""

    def __init__(self, vendor: Path = VENDOR) -> None:
        self._scanner = UniversalDenialEngine(vendor)

    def evaluate(
        self,
        vector_name: str,
        candidate: Mapping[str, object],
        *,
        schema_valid: bool,
        require_failure: bool = True,
    ) -> EvidenceFailure | None:
        if vector_name not in {E0_VECTOR, D0_VECTOR}:
            raise EvidenceSemanticContractError("E_EVIDENCE_VECTOR_NAME")
        record = _object(candidate.get("record"))
        schema_ref = candidate.get("record_schema_ref")
        if not isinstance(schema_ref, str):
            raise EvidenceSemanticContractError("E_EVIDENCE_SCHEMA_REF")
        raw = json.dumps(
            record,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        universal = self._scanner.scan(raw, schema_ref)
        if universal.error_code in _RANK_ONE_ERRORS:
            return EvidenceFailure(universal.error_code, 1)

        if not schema_valid:
            error = (
                _e0_schema_error(record)
                if vector_name == E0_VECTOR
                else _d0_schema_error(record)
            )
            if error is not None:
                return EvidenceFailure(error, 10)
            if universal.error_code in {"E_UNKNOWN_NAME", "E_UNKNOWN_SCHEMA"}:
                return EvidenceFailure(universal.error_code, 1)
            if require_failure:
                raise EvidenceSemanticContractError("E_EVIDENCE_SCHEMA_FAILURE_UNCLASSIFIED")
            return None

        error = (
            _e0_semantic_error(record)
            if vector_name == E0_VECTOR
            else _d0_semantic_error(record)
        )
        if error is not None:
            return EvidenceFailure(error, 20)
        if universal.disposition != "ACCEPTED":
            if require_failure:
                raise EvidenceSemanticContractError("E_EVIDENCE_UNIVERSAL_FAILURE_UNCLASSIFIED")
            return None
        if require_failure:
            raise EvidenceSemanticContractError("E_EVIDENCE_FAILURE_NOT_DERIVED")
        return None


def _e0_schema_error(record: Mapping[str, object]) -> str | None:
    record_kind = record.get("record_kind")
    if record_kind == "E0_SCENARIO_RESULT":
        return _e0_scenario_schema_error(record)

    observation_kind = record.get("observation_kind")
    facts = _optional_object(record.get("facts"))
    if observation_kind == "DOM_VERIFICATION" and "context" not in record:
        return "E_DOCUMENT_CONTEXT_REQUIRED"
    if observation_kind == "LIFECYCLE" and facts is not None:
        if facts.get("stale_evidence_disposition") == "RETAINED":
            return "E_STALE_EVIDENCE_NOT_INVALIDATED"
        if facts.get("automatic_resume") is True:
            return "E_AUTOMATIC_RESUME_FORBIDDEN"
    if observation_kind == "GAP" and facts is not None:
        if "reducer_cursor_ref" not in facts:
            return "E_GAP_CURSOR_REFERENCE"
        if "generation_transition_ref" not in facts:
            return "E_GAP_TRANSITION_REFERENCE"
        if "closed_epoch_ref" not in facts:
            return "E_GAP_CLOSED_EPOCH_REFERENCE"

    if _looks_like_e0_bundle(record):
        scenario_ids = record.get("scenario_ids")
        if not isinstance(scenario_ids, list) or tuple(scenario_ids) != _E0_SCENARIOS:
            return "E_SCENARIO_SET"

    if record_kind == "E0_REPORT":
        report_name = record.get("report_name")
        if report_name not in _E0_REPORTS:
            return "E_REPORT_NAME_UNKNOWN"
        projection = _optional_object(record.get("scope0_projection"))
        if projection is not None and not set(projection).issubset(_SCOPE_CATEGORIES):
            return "E_SCOPE0_CATEGORY"
        sufficiency = _optional_object(record.get("sufficiency"))
        if (
            report_name == "catalog-capability-report.json"
            and sufficiency is not None
            and sufficiency.get("classification") == "FULL_CATALOG"
            and not _catalog_full(record, sufficiency)
        ):
            return "E_CATALOG_FULL_SUFFICIENCY"
        if (
            report_name == "global-operator-state-report.json"
            and sufficiency is not None
            and not _global_classification_exact(sufficiency)
        ):
            return "E_GLOBAL_CLASSIFICATION"
    return None


def _e0_scenario_schema_error(record: Mapping[str, object]) -> str | None:
    facts = _optional_object(record.get("facts"))
    if facts is None:
        return None
    status = record.get("status")
    positive_refs = record.get("positive_fact_refs")
    if status == "NOT_OBSERVED" and (
        isinstance(positive_refs, list) and bool(positive_refs)
        or facts.get("fact_state") == "OBSERVED"
    ):
        return "E_NOT_OBSERVED_POSITIVE_FACT"
    if status == "COMPLETE" and facts.get("fact_state") != "OBSERVED":
        return "E_COMPLETE_REQUIRES_OBSERVED_FACTS"
    if facts.get("automatic_resume") is True:
        return "E_AUTOMATIC_RESUME_FORBIDDEN"
    if facts.get("active_request_issued") is True:
        return "E_ACTIVE_REQUEST_FORBIDDEN"
    if facts.get("tool_caused_action") is True:
        return "E_TOOL_CAUSED_MONETARY_ACTION"
    provenance = _optional_object(facts.get("provenance"))
    if provenance is not None and provenance.get("tool_caused_action") is True:
        return "E_TOOL_CAUSED_MONETARY_ACTION"
    if facts.get("generated_load") is True:
        return "E_GENERATED_OPERATOR_LOAD"
    if facts.get("traffic_source") == "SYNTHETIC_OPERATOR_TRAFFIC":
        return "E_NON_NATURAL_OPERATOR_TRAFFIC"
    scenario_id = record.get("scenario_id")
    if scenario_id == "E0-S19" and "operator_acceptance_ref" not in facts:
        return "E_OPERATOR_ACCEPTANCE_REFERENCE"
    if scenario_id == "E0-S23" and "correction_disposition" not in facts:
        return "E_CORRECTION_DISPOSITION"
    return None


def _d0_schema_error(record: Mapping[str, object]) -> str | None:
    observation = _optional_object(record.get("observation"))
    if observation is not None and set(observation) & _D0_MODEL_FIELDS:
        return "E_D0_MODEL_FIELD"
    if record.get("schema_version") == "provider-call-receipt/v1":
        if record.get("method") != "GET":
            return "E_PROVIDER_METHOD"
        if record.get("body_mode") != "NONE":
            return "E_PROVIDER_BODY"
    if (
        record.get("schema_version") == "provider-correction-lineage/v1"
        and record.get("append_only") is not True
    ):
        return "E_LINEAGE_MUTABLE"
    if record.get("record_kind") == "D0_REPORT" and record.get("report_name") not in _D0_REPORTS:
        return "E_REPORT_NAME_UNKNOWN"
    return None


def _e0_semantic_error(record: Mapping[str, object]) -> str | None:
    if record.get("record_kind") == "E0_SCENARIO_RESULT":
        facts = _optional_object(record.get("facts"))
        if facts is not None and record.get("scenario_id") == "E0-S16":
            if facts.get("prior_browser_boot_id") == facts.get("new_browser_boot_id"):
                return "E_S16_BOOT_NOT_ROTATED"
            if facts.get("prior_browser_run_id") == facts.get("new_browser_run_id"):
                return "E_S16_RUN_NOT_ROTATED"
        if facts is not None and record.get("scenario_id") == "E0-S24":
            p99 = _optional_object(facts.get("p99"))
            sample_count = _decimal_integer(facts.get("sample_count"))
            if (
                p99 is not None
                and p99.get("availability") == "AVAILABLE"
                and (sample_count is None or sample_count < 1000)
            ):
                return "E_P99_SAMPLE_COUNT"
        if (
            facts is not None
            and record.get("status") in {"COMPLETE", "PARTIAL"}
            and facts.get("fact_state") == "OBSERVED"
            and not _reference_sets_equal(
                record.get("positive_fact_refs"), facts.get("evidence_refs")
            )
        ):
            return "E_SCENARIO_FACT_REFERENCE_MATCH"

    if record.get("record_kind") == "E0_REPORT":
        report_name = record.get("report_name")
        sufficiency = _optional_object(record.get("sufficiency"))
        if sufficiency is None:
            return None
        if report_name == "catalog-capability-report.json":
            runs = sufficiency.get("runs")
            if isinstance(runs, list) and _has_duplicate_run_reference(runs):
                return "E_CATALOG_DUPLICATE_RUN_REF"
        if report_name == "quote-display-parity-report.json" and not _quote_threshold_exact(
            sufficiency
        ):
            return "E_QUOTE_SUFFICIENCY"
        if report_name == "global-operator-state-report.json" and not _global_classification_exact(
            sufficiency
        ):
            return "E_GLOBAL_CLASSIFICATION"
    return None


def _d0_semantic_error(record: Mapping[str, object]) -> str | None:
    if record.get("schema_version") != "provider-correction-lineage/v1":
        return None
    lineage_id = record.get("lineage_id")
    for field in ("supersedes_lineage_id", "reverses_lineage_id"):
        linked_id = record.get(field)
        if linked_id != "NONE" and linked_id == lineage_id:
            return "E_LINEAGE_CYCLE"
    return None


def _catalog_full(record: Mapping[str, object], sufficiency: Mapping[str, object]) -> bool:
    runs = sufficiency.get("runs")
    if not isinstance(runs, list) or len(runs) < 2 or _has_duplicate_run_reference(runs):
        return False
    expected_checkpoints = ("CATALOG_LOAD", "AFTER_NATURAL_UPDATE", "RUN_CLOSE")
    for run_value in runs:
        run = _optional_object(run_value)
        if run is None or run.get("bounded_run") is not True:
            return False
        if run.get("natural_operator_traffic") is not True:
            return False
        if run.get("one_detail_tab_per_fixture_used") is not False:
            return False
        checkpoints = run.get("checkpoints")
        if not isinstance(checkpoints, list):
            return False
        checkpoint_ids: list[object] = []
        for item in checkpoints:
            checkpoint = _optional_object(item)
            checkpoint_ids.append(checkpoint.get("checkpoint_id") if checkpoint else None)
        if tuple(checkpoint_ids) != expected_checkpoints:
            return False
        for checkpoint_value in checkpoints:
            checkpoint = _optional_object(checkpoint_value)
            if checkpoint is None:
                return False
            if _decimal_integer(checkpoint.get("visible_fixture_denominator")) != _decimal_integer(
                checkpoint.get("reconciled_fixture_numerator")
            ):
                return False
            if _decimal_integer(checkpoint.get("unexplained_gap_count")) != 0:
                return False
    summary = _optional_object(record.get("report_summary"))
    return (
        _decimal_integer(sufficiency.get("unexplained_gap_count")) == 0
        and summary is not None
        and _decimal_integer(summary.get("unexplained_gap_count")) == 0
    )


def _has_duplicate_run_reference(runs: Sequence[object]) -> bool:
    identities: list[tuple[object, ...]] = []
    for run_value in runs:
        run = _optional_object(run_value)
        reference = _optional_object(run.get("run_ref")) if run is not None else None
        if reference is None:
            continue
        identities.append(_reference_key(reference))
    return len(identities) != len(set(identities))


def _quote_threshold_exact(sufficiency: Mapping[str, object]) -> bool:
    counts = (
        (_decimal_integer(sufficiency.get("matched_revision_count")), 30),
        (_decimal_integer(sufficiency.get("distinct_fixture_count")), 3),
        (_decimal_integer(sufficiency.get("distinct_run_count")), 2),
    )
    threshold_met = all(value is not None and value >= minimum for value, minimum in counts)
    dispositions_met = (
        sufficiency.get("price_transformation_disposition") == "THRESHOLD_MET"
        and sufficiency.get("tick_inference_disposition") == "THRESHOLD_MET"
    )
    return threshold_met is dispositions_met


def _global_classification_exact(sufficiency: Mapping[str, object]) -> bool:
    classification = sufficiency.get("classification")
    observed = _decimal_integer(sufficiency.get("observed_global_state_class_count"))
    required = _decimal_integer(sufficiency.get("required_global_state_class_count"))
    unknown = _decimal_integer(sufficiency.get("unknown_global_state_class_count"))
    if None in {observed, required, unknown}:
        return False
    full = observed == required and unknown == 0
    partial = cast_int(observed) > 0 and not full
    unsupported = observed == 0
    return (
        classification == "FULL_CATALOG"
        and full
        or classification == "PARTIAL_CATALOG"
        and partial
        or classification == "UNSUPPORTED"
        and unsupported
    )


def _reference_sets_equal(left: object, right: object) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    left_refs = [_optional_object(value) for value in left]
    right_refs = [_optional_object(value) for value in right]
    if any(value is None for value in (*left_refs, *right_refs)):
        return False
    return {_reference_key(value) for value in left_refs if value is not None} == {
        _reference_key(value) for value in right_refs if value is not None
    }


def _reference_key(reference: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(
        reference.get(field)
        for field in ("schema_id", "schema_version", "artifact_type", "artifact_id", "content_hash")
    )


def _looks_like_e0_bundle(record: Mapping[str, object]) -> bool:
    return "scenario_ids" in record and "report_names" in record and "schema_version" not in record


def _decimal_integer(value: object) -> int | None:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        return None
    if len(value) > 1 and value.startswith("0"):
        return None
    return int(value)


def cast_int(value: int | None) -> int:
    if value is None:
        raise EvidenceSemanticContractError("E_DECIMAL_REQUIRED")
    return value


def _object(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise EvidenceSemanticContractError("E_EVIDENCE_RECORD_OBJECT")
    return value


def _optional_object(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, dict) else None
