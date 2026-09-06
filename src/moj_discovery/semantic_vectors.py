from collections.abc import Mapping
from datetime import datetime, timedelta

SCOPE_CATEGORIES = frozenset(
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
SCOPE_POLICY_ENTRIES = frozenset(
    {
        (
            "scope0-input:e0-catalog-coverage",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "catalog-capability-report.json",
            "/scope0_projection/coverage",
            "coverage",
        ),
        (
            "scope0-input:e0-catalog-missingness",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "catalog-capability-report.json",
            "/scope0_projection/missingness",
            "missingness",
        ),
        (
            "scope0-input:e0-global-semantics",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "global-operator-state-report.json",
            "/scope0_projection/semantics",
            "semantics",
        ),
        (
            "scope0-input:e0-identity-confidence",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "operator-identity-report.json",
            "/scope0_projection/identity_confidence",
            "identity_confidence",
        ),
        (
            "scope0-input:e0-orientation-semantics",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "participant-orientation-report.json",
            "/scope0_projection/semantics",
            "semantics",
        ),
        (
            "scope0-input:e0-transport-semantics",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "transport-semantics-report.json",
            "/scope0_projection/semantics",
            "semantics",
        ),
        (
            "scope0-input:e0-transport-schema-stability",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "transport-semantics-report.json",
            "/scope0_projection/schema_stability",
            "schema_stability",
        ),
        (
            "scope0-input:e0-quote-semantics",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "quote-display-parity-report.json",
            "/scope0_projection/semantics",
            "semantics",
        ),
        (
            "scope0-input:e0-browser-replayability",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "browser-lifecycle-report.json",
            "/scope0_projection/replayability",
            "replayability",
        ),
        (
            "scope0-input:e0-clock-timing",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "clock-timestamp-report.json",
            "/scope0_projection/timing",
            "timing",
        ),
        (
            "scope0-input:e0-gap-missingness",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "gaps-and-loss-report.json",
            "/scope0_projection/missingness",
            "missingness",
        ),
        (
            "scope0-input:e0-gap-replayability",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "gaps-and-loss-report.json",
            "/scope0_projection/replayability",
            "replayability",
        ),
        (
            "scope0-input:e0-loopback-capacity",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "loopback-topology-report.json",
            "/scope0_projection/capacity",
            "capacity",
        ),
        (
            "scope0-input:e0-loopback-replayability",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "loopback-topology-report.json",
            "/scope0_projection/replayability",
            "replayability",
        ),
        (
            "scope0-input:e0-natural-capacity",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "capacity-report.json",
            "/scope0_projection/capacity",
            "capacity",
        ),
        (
            "scope0-input:e0-natural-timing",
            "urn:hybrid-discovery:v6.2:e0-evidence:v1",
            "e0-report/v1",
            "capacity-report.json",
            "/scope0_projection/timing",
            "timing",
        ),
        (
            "scope0-input:d0-provider-coverage",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-provider-capability-report.json",
            "/scope0_projection/coverage",
            "coverage",
        ),
        (
            "scope0-input:d0-provider-schema-stability",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-provider-capability-report.json",
            "/scope0_projection/schema_stability",
            "schema_stability",
        ),
        (
            "scope0-input:d0-provider-quota",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-provider-capability-report.json",
            "/scope0_projection/quota",
            "quota",
        ),
        (
            "scope0-input:d0-provider-licensing",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-provider-capability-report.json",
            "/scope0_projection/licensing",
            "licensing",
        ),
        (
            "scope0-input:d0-provider-cost",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-provider-capability-report.json",
            "/scope0_projection/cost",
            "cost",
        ),
        (
            "scope0-input:d0-latency-timing",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-latency-report.json",
            "/scope0_projection/timing",
            "timing",
        ),
        (
            "scope0-input:d0-latency-missingness",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-latency-report.json",
            "/scope0_projection/missingness",
            "missingness",
        ),
        (
            "scope0-input:d0-latency-capacity",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-latency-report.json",
            "/scope0_projection/capacity",
            "capacity",
        ),
        (
            "scope0-input:d0-correction-replayability",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-correction-report.json",
            "/scope0_projection/replayability",
            "replayability",
        ),
        (
            "scope0-input:d0-identity-confidence",
            "urn:hybrid-discovery:v6.2:d0-evidence:v1",
            "d0-report/v1",
            "football-identity-report.json",
            "/scope0_projection/identity_confidence",
            "identity_confidence",
        ),
    }
)
SCOPE_EXCLUDED_SOURCE_CLASSES = frozenset(
    {
        "RAW_OBSERVATION",
        "SCENARIO_BODY",
        "BETSLIP",
        "POSITION",
        "CASHOUT",
        "REDACTION_MATCH",
        "RESULT_DATA",
        "MODEL_METRICS",
        "MARKET_METRICS",
        "FINANCIAL_METRICS",
        "CHAMPION_DATA",
        "PRODUCTION_AUTHORITY",
    }
)
PERFORMANCE_DENIAL_CODES = frozenset(
    {
        "RESULT_DATA",
        "MODEL_METRICS",
        "CALIBRATION_METRICS",
        "MARKET_METRICS",
        "FINANCIAL_METRICS",
        "RANKING_DATA",
        "CHAMPION_DATA",
        "PRODUCTION_AUTHORITY",
    }
)
REQUIRED_DECISIONS = (
    "OPERATOR_CATALOG_WDL_COVERAGE",
    "OPERATOR_GLOBAL_STATE_COVERAGE",
    "OPERATOR_TRANSPORT_TARGET_INVENTORY",
    "OPERATOR_SEQUENCE_RESUME_SEMANTICS",
    "OPERATOR_IDENTIFIER_STABILITY",
    "OPERATOR_IDENTIFIER_LIFECYCLE",
    "OPERATOR_WDL_ORIENTATION",
    "OPERATOR_PRICE_TRANSFORMATION_ATOMICITY",
    "OPERATOR_TIMESTAMP_SEMANTICS",
    "BROWSER_LIFECYCLE_CONTINUITY",
    "LOOPBACK_TOPOLOGY",
    "NATURAL_CAPACITY",
    "BODY_CLASS_SAFETY",
    "CASHOUT_OBSERVABILITY",
    "BETSLIP_POSITION_SEMANTICS",
    "PARTIAL_CASHOUT_SIDE_EFFECT_FREEDOM",
    "PROVIDER_FEASIBILITY",
    "POST_SHOCK_RESNAPSHOT_RECOGNITION",
)
DISCOVERY_CONSUMERS = frozenset(
    {
        "G0_DISCOVERY_EVIDENCE_REVIEW",
        "SCOPE0_INPUT_VIEW_BUILDER",
        "SCOPE0_SCOPE_FREEZER",
        "V7_DESIGN_HANDOFF",
        "FUTURE_FORMAL_SCANNER",
        "FUTURE_OPERATOR_STATE_REDUCER",
        "FUTURE_COHERENCE_CONTROLLER",
        "FUTURE_PROVIDER_FEASIBILITY_SELECTOR",
    }
)
READINESS_INPUTS = (
    "REPO0_BASELINE_VALID",
    "SAFE_TO_IMPLEMENT_R0",
    "SAFE_TO_IMPLEMENT_F0A",
    "SAFE_TO_IMPLEMENT_SEC0",
    "SAFE_TO_IMPLEMENT_E0",
    "SAFE_TO_IMPLEMENT_D0",
    "SAFE_TO_FREEZE_SCOPE0",
)


def _object(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return value


def _array(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _strings(value: object) -> list[str]:
    values = _array(value)
    assert all(isinstance(item, str) for item in values)
    return [str(item) for item in values]


def _timestamp(value: object) -> datetime:
    assert isinstance(value, str)
    return datetime.fromisoformat(value.upper().replace("Z", "+00:00"))


def validate_scope_policy(policy: Mapping[str, object]) -> None:
    assert policy["schema_version"] == "scope0-input-policy/v1"
    assert policy["wildcard_pointers_permitted"] is False
    assert policy["production_authority"] == "NONE"
    assert frozenset(_strings(policy["allowed_categories"])) == SCOPE_CATEGORIES
    assert frozenset(_strings(policy["excluded_source_classes"])) == SCOPE_EXCLUDED_SOURCE_CLASSES
    entries = _array(policy["entries"])
    observed = frozenset(
        (
            str(entry["entry_id"]),
            str(entry["schema_id"]),
            str(entry["schema_version"]),
            str(entry["artifact_name"]),
            str(entry["json_pointer"]),
            str(entry["category"]),
        )
        for entry_value in entries
        for entry in (_object(entry_value),)
    )
    assert len(entries) == len(observed) == 26
    assert observed == SCOPE_POLICY_ENTRIES
    assert all("*" not in entry[4] for entry in observed)


def validate_required_decision_registry(registry: Mapping[str, object]) -> None:
    assert registry["schema_version"] == "required-discovery-decisions/v1"
    assert registry["decision_count"] == len(REQUIRED_DECISIONS)
    assert registry["additional_decisions_permitted"] is False
    assert registry["production_authority"] == "NONE"
    decisions = [_object(item) for item in _array(registry["decisions"])]
    assert tuple(str(item["decision_id"]) for item in decisions) == REQUIRED_DECISIONS
    assert [item["order"] for item in decisions] == list(range(1, 19))
    assert all(item["unresolved_default"] == "UNKNOWN" for item in decisions)


def validate_consumer_registry(registry: Mapping[str, object]) -> None:
    assert registry["schema_version"] == "discovery-capability-consumers/v1"
    assert registry["production_authority"] == "NONE"
    consumers = [_object(item) for item in _array(registry["consumers"])]
    assert len(consumers) == len(DISCOVERY_CONSUMERS)
    assert frozenset(str(item["consumer_id"]) for item in consumers) == DISCOVERY_CONSUMERS


def semantic_vector_error(
    vector_name: str,
    base_case: Mapping[str, object],
    candidate_case: Mapping[str, object],
    *,
    scope_policy: Mapping[str, object] | None = None,
) -> str | None:
    record = _object(candidate_case["record"])
    base_record = _object(base_case["record"])
    if vector_name == "scope-semantic-v1.json":
        assert scope_policy is not None
        return _scope_error(record, base_record, scope_policy)
    assert vector_name == "review-semantic-v1.json"
    if record.get("schema_version") == "discovery-capability/v1":
        return _capability_error(record)
    return _review_error(record)


def _production_error(record: Mapping[str, object]) -> str | None:
    production = record.get("production_authority")
    if isinstance(production, dict):
        production = production.get("AUTHORIZED_PRODUCTION_PHASES")
    if production is None:
        production = record.get("AUTHORIZED_PRODUCTION_PHASES")
    return None if production == "NONE" else "E_PRODUCTION_AUTHORITY"


def _scope_error(
    record: Mapping[str, object],
    base: Mapping[str, object],
    policy: Mapping[str, object],
) -> str | None:
    if "stored_approval_hash" in record:
        return _scope_integrity_error(record, base)
    production_error = _production_error(record)
    if production_error is not None:
        return production_error
    kind = record.get("record_kind")
    if kind == "FROZEN_INITIAL_SCOPE_APPROVAL":
        return _frozen_scope_error(record, base, policy)
    if kind == "NO_FEASIBLE_SCOPE":
        return _no_feasible_scope_error(record)
    if kind == "SCOPE_REVOCATION":
        return _scope_revocation_error(record, base)
    return "E_SCOPE_RECORD_KIND"


def _frozen_scope_error(
    record: Mapping[str, object],
    base: Mapping[str, object],
    policy: Mapping[str, object],
) -> str | None:
    if record.get("authority") != "V7_DESIGN_ONLY":
        return "E_SCOPE_AUTHORITY"
    forecast_scope = _object(record["forecast_bundle_scope"])
    if record.get("competition_id") != forecast_scope.get("competition_id"):
        return "E_SCOPE_COMPETITION_MISMATCH"
    horizons = frozenset(_strings(record["supported_horizons"]))
    bands = _object(record["evaluation_bands"])
    if horizons != frozenset(str(key) for key in bands):
        return "E_SCOPE_HORIZON_BAND_KEYS"
    band_error = _band_error(bands, _strings(forecast_scope["eligible_fixture_states"]))
    if band_error is not None:
        return band_error
    partition_error = _partition_error(_object(record["temporal_partitions"]))
    if partition_error is not None:
        return partition_error
    if not (
        _timestamp(record["valid_from"])
        <= _timestamp(record["review_by"])
        <= _timestamp(record["valid_from"]) + timedelta(seconds=2_592_000)
    ):
        return "E_SCOPE_REVIEW_BOUNDARY"
    admission_error = _admission_error(record, base, policy)
    if admission_error is not None:
        return admission_error
    denial = _object(record["performance_input_denial"])
    if (
        denial.get("policy_enforced") is not True
        or denial.get("audit_confirmed") is not True
        or frozenset(_strings(denial["denied_category_codes"])) != PERFORMANCE_DENIAL_CODES
    ):
        return "E_SCOPE_PERFORMANCE_DENIAL"
    lineage = _object(record["contamination_lineage"])
    if lineage.get("replay_disposition") != "MATCHED":
        return "E_SCOPE_LEDGER_REPLAY"
    if (
        lineage.get("contamination_status") != "CLEAN"
        or lineage.get("test_access_events") != "0"
        or lineage.get("forward_access_events") != "0"
    ):
        return "E_SCOPE_CONTAMINATION"
    if lineage.get("access_ledger_schema_version") != "scope-input-audit/v1":
        return "E_SCOPE_SCHEMA_VERSION"
    ledger_ref = _object(lineage["access_ledger_ref"])
    if (
        ledger_ref.get("schema_id") != "urn:hybrid-discovery:v6.2:meta-records:v1"
        or ledger_ref.get("schema_version") != "scope-input-audit/v1"
        or ledger_ref.get("artifact_type") != "SCOPE_INPUT_AUDIT"
    ):
        return "E_SCOPE_SCHEMA_VERSION"
    if ledger_ref.get("content_hash") != lineage.get("access_ledger_hash"):
        return "E_SCOPE_EVIDENCE_HASH"
    return None


def _band_error(evaluation_bands: Mapping[str, object], eligible_states: list[str]) -> str | None:
    allowed_states = frozenset(eligible_states)
    phase_order = {
        "PRE_MATCH": 0,
        "FIRST_HALF": 1,
        "HALFTIME": 2,
        "SECOND_HALF": 3,
        "EXTRA_TIME": 4,
    }
    admission_by_state = {
        "PRE_MATCH": "ADMITTED_PRE_MATCH",
        "FIRST_HALF": "ADMITTED_FIRST_HALF",
        "HALFTIME": "ADMITTED_HALFTIME",
        "SECOND_HALF": "ADMITTED_SECOND_HALF",
        "EXTRA_TIME": "ADMITTED_EXTRA_TIME",
    }
    for horizon, band_values in evaluation_bands.items():
        live_intervals: list[tuple[int, int]] = []
        chronology: list[tuple[int, int]] = []
        for value in _array(band_values):
            band = _object(value)
            phase = str(band.get("fixture_phase"))
            if horizon == "H1" and phase not in {"PRE_MATCH", "FIRST_HALF"}:
                return "E_SCOPE_H1_PHASE"
            if phase not in allowed_states or band.get("admission_code") != admission_by_state.get(
                phase
            ):
                return "E_SCOPE_BAND_STATE"
            is_live = phase in {"FIRST_HALF", "SECOND_HALF", "EXTRA_TIME"}
            has_minute = "start_minute" in band or "end_minute" in band
            if not is_live and has_minute:
                return "E_SCOPE_NONLIVE_MINUTE"
            if not is_live:
                chronology.append((phase_order[phase], -1))
                continue
            try:
                start = int(str(band["start_minute"]))
                end = int(str(band["end_minute"]))
            except (KeyError, ValueError):
                return "E_SCOPE_MINUTE_RANGE"
            if start < 0 or start > 180 or end < 0 or end > 180:
                return "E_SCOPE_MINUTE_RANGE"
            if start >= end:
                return "E_SCOPE_MINUTE_ORDER"
            live_intervals.append((start, end))
            chronology.append((phase_order[phase], start))
        if chronology != sorted(chronology):
            return "E_SCOPE_BAND_ORDER"
        ordered_intervals = sorted(live_intervals)
        for index, interval in enumerate(ordered_intervals):
            if index and interval[0] < ordered_intervals[index - 1][1]:
                return "E_SCOPE_BAND_OVERLAP"
    return None


def _partition_error(partitions: Mapping[str, object]) -> str | None:
    windows = {
        name: _object(partitions[name]) for name in ("TRAIN", "VALIDATION", "TEST", "FORWARD")
    }
    for name in ("TEST", "FORWARD"):
        window = windows[name]
        if window.get("pre_freeze_access_state") != "NEVER_ACCESSED":
            return f"E_SCOPE_{name}_TOUCHED"
        if window.get("pre_freeze_access_event_count") != "0":
            return f"E_SCOPE_{name}_TOUCHED"
    bounds = {
        name: (_timestamp(window["start"]), _timestamp(window["end"]))
        for name, window in windows.items()
    }
    if any(start >= end for start, end in bounds.values()):
        return "E_SCOPE_PARTITION_EMPTY"
    if bounds["TRAIN"][1] > bounds["VALIDATION"][0]:
        return "E_SCOPE_PARTITION_OVERLAP"
    if bounds["VALIDATION"][1] > bounds["TEST"][0]:
        return "E_SCOPE_PARTITION_ORDER"
    if bounds["TEST"][1] > bounds["FORWARD"][0]:
        return "E_SCOPE_PARTITION_OVERLAP"
    starts = [bounds[name][0] for name in ("TRAIN", "VALIDATION", "TEST", "FORWARD")]
    if starts != sorted(starts):
        return "E_SCOPE_PARTITION_ORDER"
    return None


def _admission_error(
    record: Mapping[str, object],
    base: Mapping[str, object],
    policy: Mapping[str, object],
) -> str | None:
    binding_expectations = {
        "scope_input_view_binding": (
            "urn:hybrid-discovery:v6.2:meta-records:v1",
            "scope-input-view/v1",
        ),
        "scope_input_audit_binding": (
            "urn:hybrid-discovery:v6.2:meta-records:v1",
            "scope-input-audit/v1",
        ),
        "scope_input_policy_binding": (
            "urn:hybrid-discovery:v6.2:scope0-input-policy:v1",
            "scope0-input-policy/v1",
        ),
    }
    for field, expected in binding_expectations.items():
        binding = _object(record[field])
        if (binding.get("schema_id"), binding.get("schema_version")) != expected:
            return "E_SCOPE_SCHEMA_VERSION"
        base_binding = _object(base[field])
        if binding.get("content_hash") != base_binding.get("content_hash"):
            return "E_SCOPE_EVIDENCE_HASH"
    policy_entries = {
        str(entry["entry_id"]): entry
        for value in _array(policy["entries"])
        for entry in (_object(value),)
    }
    base_hashes = {
        str(item["policy_entry_id"]): item.get("projected_value_hash")
        for value in _array(base["admitted_inputs"])
        for item in (_object(value),)
    }
    seen: set[str] = set()
    for value in _array(record["admitted_inputs"]):
        admitted = _object(value)
        pointer = str(admitted.get("json_pointer"))
        if "*" in pointer:
            return "E_SCOPE_POLICY_POINTER"
        entry_id = str(admitted.get("policy_entry_id"))
        if entry_id in seen or entry_id not in policy_entries:
            return "E_SCOPE_POLICY_ADMISSION"
        seen.add(entry_id)
        entry = policy_entries[entry_id]
        if admitted.get("category") != entry.get("category"):
            return "E_SCOPE_POLICY_CATEGORY"
        if pointer != entry.get("json_pointer"):
            return "E_SCOPE_POLICY_POINTER"
        source_ref = _object(admitted["source_ref"])
        expected_artifact_type = (
            "E0_REPORT" if entry.get("schema_version") == "e0-report/v1" else "D0_REPORT"
        )
        if source_ref.get("schema_version") != entry.get("schema_version"):
            return "E_SCOPE_SCHEMA_VERSION"
        if (
            source_ref.get("schema_id") != entry.get("schema_id")
            or source_ref.get("artifact_type") != expected_artifact_type
        ):
            return "E_SCOPE_POLICY_ADMISSION"
        base_item = next(
            (
                item
                for value in _array(base["admitted_inputs"])
                for item in (_object(value),)
                if item.get("policy_entry_id") == entry_id
            ),
            None,
        )
        if base_item is not None and source_ref != _object(base_item["source_ref"]):
            return "E_SCOPE_EVIDENCE_HASH"
        expected_hash = base_hashes.get(entry_id)
        if expected_hash is not None and admitted.get("projected_value_hash") != expected_hash:
            return "E_SCOPE_EVIDENCE_HASH"
    return None


def _no_feasible_scope_error(record: Mapping[str, object]) -> str | None:
    if record.get("authority") != "NONE":
        return "E_SCOPE_AUTHORITY"
    positive_fields = {
        "competition_id",
        "forecast_bundle_scope",
        "supported_horizons",
        "evaluation_bands",
        "temporal_partitions",
        "admitted_inputs",
    }
    if positive_fields.intersection(record):
        return "E_NO_FEASIBLE_POSITIVE_SCOPE"
    return None


def _scope_revocation_error(record: Mapping[str, object], base: Mapping[str, object]) -> str | None:
    if record.get("terminal") is not True or record.get("reopening_permitted") is not False:
        return "E_REVOCATION_TERMINAL"
    if record.get("approval_hash") != base.get("approval_hash"):
        return "E_REVOCATION_APPROVAL_HASH"
    if record.get("revocation_sequence") != base.get("revocation_sequence"):
        return "E_REVOCATION_SEQUENCE"
    if record.get("previous_revocation_hash") != base.get("previous_revocation_hash"):
        return "E_REVOCATION_PREVIOUS_HASH"
    return None


def _scope_integrity_error(record: Mapping[str, object], base: Mapping[str, object]) -> str | None:
    if record.get("stored_approval_hash") != record.get("recomputed_approval_hash"):
        return "E_APPROVAL_IMMUTABILITY"
    if record.get("stored_approval_hash") != record.get("revocation_approval_hash"):
        return "E_REVOCATION_APPROVAL_HASH"
    if record.get("revocation_sequence") != base.get("revocation_sequence"):
        return "E_REVOCATION_SEQUENCE"
    if record.get("previous_revocation_hash") != base.get("previous_revocation_hash"):
        return "E_REVOCATION_PREVIOUS_HASH"
    if record.get("terminal") is not True:
        return "E_REVOCATION_TERMINAL"
    return None


def _review_error(record: Mapping[str, object]) -> str | None:
    production_error = _production_error(record)
    if production_error is not None:
        return production_error
    findings = [_object(item) for item in _array(record["findings"])]
    if record.get("review_outcome") in {"HELD", "REJECTED"} and not findings:
        return "E_REVIEW_FINDINGS_EMPTY"
    finding_ids = [str(item.get("finding_id")) for item in findings]
    if len(finding_ids) != len(set(finding_ids)):
        return "E_FINDING_ID_DUPLICATE"
    for finding in findings:
        if finding.get("blocking") is True and any(
            record.get(verdict) != "NO" for verdict in _strings(finding["affected_verdicts"])
        ):
            return "E_BLOCKER_VERDICT"
    if record.get("READY_TO_IMPLEMENT_DISCOVERY_PACK") == "YES" and any(
        record.get(verdict) != "YES" for verdict in READINESS_INPUTS
    ):
        return "E_READY_CONTRADICTION"
    decisions = [_object(item) for item in _array(record["required_discovery_decisions"])]
    decision_ids = tuple(str(item.get("decision_id")) for item in decisions)
    if decision_ids != REQUIRED_DECISIONS or len(decision_ids) != len(set(decision_ids)):
        return "E_REQUIRED_DECISION_SET"
    for decision in decisions:
        consumers = frozenset(_strings(decision["authorized_consumers"]))
        if not consumers.issubset(DISCOVERY_CONSUMERS):
            return "E_CONSUMER_UNKNOWN"
        disposition = decision.get("disposition")
        evidence = _array(decision["evidence_refs"])
        limitations = _strings(decision["limitation_codes"])
        if disposition == "SUPPORTED" and not evidence:
            return "E_SUPPORTED_EVIDENCE_REQUIRED"
        if disposition == "PARTIAL" and (not evidence or not limitations):
            return "E_PARTIAL_SEMANTICS"
        if disposition in {
            "UNSUPPORTED",
            "UNKNOWN",
            "NOT_OBSERVED",
            "INCONCLUSIVE",
            "SAFETY_STOP",
        }:
            if consumers:
                if disposition == "UNKNOWN":
                    return "E_UNKNOWN_AUTHORIZES_CONSUMER"
                return f"E_{disposition}_AUTHORIZES_CONSUMER"
            if not limitations:
                return f"E_{disposition}_LIMITATION"
    return None


def _capability_error(record: Mapping[str, object]) -> str | None:
    production_error = _production_error(record)
    if production_error is not None:
        return production_error
    evaluated = frozenset(_strings(record["evaluated_consumers"]))
    authorized = frozenset(_strings(record["authorized_consumers"]))
    blocked = frozenset(_strings(record["blocked_consumers"]))
    if not (evaluated | authorized | blocked).issubset(DISCOVERY_CONSUMERS):
        return "E_CONSUMER_UNKNOWN"
    verdict = str(record.get("verdict"))
    evidence = _array(record["evidence_refs"])
    limitations = _strings(record["limitation_codes"])
    unknowns = _strings(record["unknown_codes"])
    confidence = record.get("confidence")
    context_closed = _object(record["tested_context"]).get("context_status") == "CLOSED"
    if verdict == "SUPPORTED":
        if not evidence:
            return "E_SUPPORTED_EVIDENCE_REQUIRED"
        if confidence not in {"OBSERVED", "INFERRED"}:
            return "E_SUPPORTED_CONFIDENCE"
        if unknowns:
            return "E_SUPPORTED_UNKNOWN"
        if not authorized:
            return "E_SUPPORTED_CONSUMER_SCOPE"
        if not context_closed:
            return "E_SUPPORTED_SEMANTICS"
    elif verdict == "PARTIAL":
        if not limitations:
            return "E_PARTIAL_LIMITATION"
        if not evidence:
            return "E_PARTIAL_SEMANTICS"
        if not blocked:
            return "E_PARTIAL_BLOCKED_CONSUMER"
        if not authorized:
            return "E_PARTIAL_AUTHORIZED_CONSUMER"
        if confidence not in {"OBSERVED", "INFERRED"}:
            return "E_PARTIAL_CONFIDENCE"
        if not context_closed:
            return "E_PARTIAL_SEMANTICS"
    elif verdict == "UNSUPPORTED":
        if authorized:
            return "E_UNSUPPORTED_AUTHORIZES"
        if not limitations:
            return "E_UNSUPPORTED_LIMITATION"
        if unknowns:
            return "E_UNSUPPORTED_UNKNOWN"
        if not evidence or not context_closed:
            return "E_UNSUPPORTED_SEMANTICS"
    elif verdict == "UNKNOWN":
        if authorized:
            return "E_UNKNOWN_AUTHORIZES"
        if confidence not in {"UNKNOWN", "NOT_OBSERVED"}:
            return "E_UNKNOWN_SEMANTICS"
        if not limitations or not unknowns:
            return "E_UNKNOWN_SEMANTICS"
    elif verdict == "INDETERMINATE":
        if authorized:
            return "E_INDETERMINATE_AUTHORIZES"
        if confidence not in {"CONFLICT", "INTEGRITY_FAILURE", "INSUFFICIENT_SAMPLE"}:
            return "E_INDETERMINATE_CONFIDENCE"
        if not evidence or not limitations:
            return "E_INDETERMINATE_SEMANTICS"
    else:
        return "E_CAPABILITY_VERDICT"
    if authorized.intersection(blocked):
        return "E_CONSUMER_PARTITION_OVERLAP"
    if evaluated != DISCOVERY_CONSUMERS or authorized | blocked != evaluated:
        return "E_CONSUMER_PARTITION_INCOMPLETE"
    if verdict in {"UNSUPPORTED", "UNKNOWN", "INDETERMINATE"} and blocked != evaluated:
        return f"E_{verdict}_SEMANTICS"
    return None
