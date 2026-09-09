import json
import socket
from pathlib import Path
from unittest.mock import patch

from moj_discovery.live_preflight import check_live_readiness


def test_missing_inputs_stay_pending_without_network() -> None:
    config = json.loads(Path("config/live.example.json").read_text())
    with patch.object(socket, "socket", side_effect=AssertionError("network")) as direct:
        result = check_live_readiness(config, {}, {})
    assert direct.call_count == 0
    assert result["LIVE_READ_ONLY_READY"] == "PENDING_REAL_INPUTS_AND_LIVE_REVIEW"
    assert result["checks"]["provider_key"] == "PENDING_KEY"
    assert result["checks"]["capture_profile"] == "PENDING_REAL_INPUTS"
    assert result["MONEY_READY"] == "NO"


def test_synthetic_evidence_cannot_satisfy_live_requirements() -> None:
    config = json.loads(Path("config/live.example.json").read_text())
    result = check_live_readiness(
        config,
        {
            "capture_profile": {"source_kind": "SYNTHETIC_TEST"},
            "security_review": {"source_kind": "SYNTHETIC_TEST"},
        },
        {"API_FOOTBALL_KEY": True},
    )
    assert result["checks"]["capture_profile"] == "SYNTHETIC_NOT_LIVE_EVIDENCE"
    assert result["checks"]["security_review"] == "SYNTHETIC_NOT_LIVE_EVIDENCE"
    assert result["LIVE_READ_ONLY_READY"] == "PENDING_REAL_INPUTS_AND_LIVE_REVIEW"


def test_scope_and_budget_validation() -> None:
    import pytest

    config = json.loads(Path("config/live.example.json").read_text())
    config["money_enabled"] = True
    with pytest.raises(ValueError, match="E_LIVE_CONFIG_SCOPE"):
        check_live_readiness(config, {}, {})
    config["money_enabled"] = False
    config["provider"]["max_requests_per_minute"] = 1
    assert (
        check_live_readiness(config, {}, {})["checks"]["quota_budget"]
        == "INSUFFICIENT_CONFIGURED_BUDGET"
    )
    config["provider"]["poll_events_seconds"] = True
    with pytest.raises(ValueError, match="E_LIVE_CONFIG_LIMIT"):
        check_live_readiness(config, {}, {})


def test_serialized_pass_flag_is_not_offline_proof() -> None:
    config = json.loads(Path("config/live.example.json").read_text())
    result = check_live_readiness(
        config, {"offline_gate": {"verified": True, "OFFLINE_SLICE_PASS": "YES"}}, {}
    )
    assert result["checks"]["offline_gate"] != "PASS"
