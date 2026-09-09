"""Pure lane-A preflight. It cannot validate future LV approvals or activate live access."""

import math
import re
from collections.abc import Mapping
from typing import Any


def check_live_readiness(
    config: Mapping[str, Any], evidence: Mapping[str, Any], secret_presence: Mapping[str, bool]
) -> dict[str, Any]:
    if (
        not isinstance(config, Mapping)
        or not isinstance(evidence, Mapping)
        or not isinstance(secret_presence, Mapping)
    ):
        raise ValueError("E_LIVE_CONFIG_TYPE")
    if any(not isinstance(value, Mapping) for value in evidence.values()) or any(
        type(value) is not bool for value in secret_presence.values()
    ):
        raise ValueError("E_LIVE_EVIDENCE_TYPE")
    expected = {
        "schema_version",
        "mode",
        "enabled",
        "provider",
        "operator",
        "runtime",
        "gates",
        "model_enabled",
        "paper_enabled",
        "money_enabled",
        "cashout_submission_enabled",
    }
    if (
        set(config) != expected
        or config["schema_version"] != "bh-live-readonly-config/v1"
        or config["mode"] != "LIVE_READ_ONLY"
        or type(config["enabled"]) is not bool
        or any(
            config[name] is not False
            for name in [
                "model_enabled",
                "paper_enabled",
                "money_enabled",
                "cashout_submission_enabled",
            ]
        )
    ):
        raise ValueError("E_LIVE_CONFIG_SCOPE")
    provider, operator, runtime, gates = (
        config[name] for name in ["provider", "operator", "runtime", "gates"]
    )
    shapes = [
        (
            provider,
            {
                "id",
                "base_url",
                "api_key_env",
                "fixture_ids",
                "poll_fixture_seconds",
                "poll_events_seconds",
                "max_requests_per_run",
                "max_requests_per_minute",
            },
        ),
        (
            operator,
            {
                "capture_profile_path",
                "profile_evidence_hash",
                "user_session_present",
                "allowed_fixture_bindings",
            },
        ),
        (
            runtime,
            {"host", "port", "max_matches", "max_run_minutes", "platform_qualification_path"},
        ),
        (
            gates,
            {
                "offline_result_path",
                "security_review_path",
                "provider_feasibility_path",
                "live_run_authorization_path",
            },
        ),
    ]
    if any(not isinstance(value, dict) or set(value) != keys for value, keys in shapes):
        raise ValueError("E_LIVE_CONFIG_FIELDS")
    if (
        provider["id"] != "API_FOOTBALL_V3"
        or provider["base_url"] != "https://v3.football.api-sports.io"
        or not isinstance(provider["api_key_env"], str)
        or not re.fullmatch("[A-Z][A-Z0-9_]{0,63}", provider["api_key_env"])
        or runtime["host"] != "127.0.0.1"
        or type(runtime["port"]) is not int
        or runtime["port"] != 8765
    ):
        raise ValueError("E_LIVE_CONFIG_BINDING")
    bounds = [
        (runtime["max_matches"], 1, 1),
        (runtime["max_run_minutes"], 1, 120),
        (provider["poll_fixture_seconds"], 30, 3600),
        (provider["poll_events_seconds"], 30, 3600),
        (provider["max_requests_per_run"], 1, 500),
        (provider["max_requests_per_minute"], 1, 8),
    ]
    if any(type(value) is not int or not low <= value <= high for value, low, high in bounds):
        raise ValueError("E_LIVE_CONFIG_LIMIT")
    fixtures = provider["fixture_ids"]
    if (
        not isinstance(fixtures, list)
        or len(fixtures) > runtime["max_matches"]
        or any(type(value) is not int or value <= 0 for value in fixtures)
        or type(operator["user_session_present"]) is not bool
        or not isinstance(operator["allowed_fixture_bindings"], list)
    ):
        raise ValueError("E_LIVE_CONFIG_FIXTURE")
    paths = [
        operator["capture_profile_path"],
        runtime["platform_qualification_path"],
        *gates.values(),
    ]
    if any(
        value is not None and (not isinstance(value, str) or not value or len(value) > 4096)
        for value in paths
    ):
        raise ValueError("E_LIVE_CONFIG_PATH")
    digest = operator["profile_evidence_hash"]
    if digest is not None and (
        not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest)
    ):
        raise ValueError("E_LIVE_CONFIG_HASH")
    estimate = 1 + sum(
        math.ceil(runtime["max_run_minutes"] * 60 / provider[field])
        for field in ["poll_fixture_seconds", "poll_events_seconds"]
    )
    minute_estimate = 1 + sum(
        math.ceil(60 / provider[field]) for field in ["poll_fixture_seconds", "poll_events_seconds"]
    )
    within_budget = (
        estimate <= provider["max_requests_per_run"]
        and minute_estimate <= provider["max_requests_per_minute"]
    )
    checks = {
        "offline_gate": "REQUIRES_OFFLINE_GATE_VERIFICATION"
        if "offline_gate" in evidence
        else "PENDING_OFFLINE_GATE",
        "provider_key": "ENV_NAME_PRESENT_UNVALIDATED"
        if secret_presence.get(provider["api_key_env"]) is True
        else "PENDING_KEY",
        "fixture_selection": "SELECTED_UNVALIDATED" if fixtures else "PENDING_FIXTURE",
        "operator_session": "PENDING_MANUAL_OPERATOR_SESSION"
        if not operator["user_session_present"]
        else "SESSION_CLAIM_REQUIRES_LV_REVIEW",
        "operator_fixture_binding": "PENDING_FIXTURE_BINDING"
        if not operator["allowed_fixture_bindings"]
        else "BINDING_REQUIRES_LV_REVIEW",
        "quota_budget": "PENDING_OBSERVED_QUOTA"
        if within_budget
        else "INSUFFICIENT_CONFIGURED_BUDGET",
    }
    for name in [
        "capture_profile",
        "provider_feasibility",
        "platform_qualification",
        "security_review",
        "live_run_authorization",
    ]:
        checks[name] = (
            "PENDING_REAL_INPUTS" if name not in evidence else "REQUIRES_LV_EVIDENCE_REVIEW"
        )
        if evidence.get(name, {}).get("source_kind") == "SYNTHETIC_TEST":
            checks[name] = "SYNTHETIC_NOT_LIVE_EVIDENCE"
    return {
        "LIVE_PREFLIGHT_IMPLEMENTED": "YES",
        "LIVE_READ_ONLY_READY": "PENDING_REAL_INPUTS_AND_LIVE_REVIEW",
        "MONEY_READY": "NO",
        "production_authority": "NONE",
        "status": "PENDING_REAL_INPUTS",
        "evaluation_scope": "SYNTHETIC_PREFLIGHT_ONLY",
        "checks": checks,
        "estimated_requests": estimate,
        "estimated_requests_first_minute": minute_estimate,
        "missing_inputs": [name for name, value in checks.items() if value != "PASS"],
    }
