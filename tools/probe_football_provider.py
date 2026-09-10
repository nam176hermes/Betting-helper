"""Bounded direct-provider probe dispatched only by the user-terminal key launcher."""

# ruff: noqa: E402
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.live_config import LiveConfig, private_path
from moj_discovery.live_intent import RunIntentReceipt, claim_receipt
from moj_discovery.provider_protocol import ProviderScope
from moj_discovery.providers.api_football import ApiFootballClient, ProviderError
from moj_discovery.providers.football_normalizer import ObservationStamp, normalize_bundle
from moj_discovery.providers.poll_budget import PollSegment, estimate_requests
from moj_discovery.providers.quota import QuotaLedger
from moj_discovery.secrets_local import SecretValue

ProbeResult = dict[str, Any]


def inspect_provider(config: LiveConfig, client: ApiFootballClient) -> ProbeResult:
    """Shared finite sequence for real and injected MOCK transports; no fallback polling."""
    result: ProbeResult = {
        "KEY_CHECK": "NOT_CHECKED",
        "SUBSCRIPTION_CHECK": "UNKNOWN",
        "PROBE_RESULT": "FAIL",
        "REQUEST_ATTEMPTS": 0,
        "MISSING_CAPABILITIES": [],
    }
    missing: set[str] = set()
    cfg = config.public
    domain, started = str(uuid4()), client._mono()
    observations: list[dict[str, Any]] = []
    quota: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    try:
        status = client.get_status()
        result["KEY_CHECK"] = "AUTHENTICATED"
        quota = asdict(status)
        cost = estimate_requests([PollSegment(0, cfg["runtime"]["max_run_minutes"] * 60, 15)])
        if status.daily_limit is None or status.daily_remaining is None:
            missing.add("QUOTA_UNKNOWN")
        elif (
            not status.active
            or status.daily_remaining - (status.daily_limit + 4) // 5 < cost.with_reserve
        ):
            result["SUBSCRIPTION_CHECK"] = "INSUFFICIENT"
            missing.add("QUOTA_INSUFFICIENT")
        else:
            result["SUBSCRIPTION_CHECK"] = "CONFIRMED"
        coverage = client.get_coverage(cfg["provider"]["league_id"], cfg["provider"]["season"])
        if coverage["coverage"]["events"] is not True:
            missing.add("COVERAGE_UNKNOWN")
        previous: dict[int, dict[str, Any]] = {}
        for _ in range(2):
            response = client.get_fixture_bundle(config.fixture_ids)
            projected = normalize_bundle(
                response,
                config.fixture_ids,
                ObservationStamp(
                    client._utc(),
                    int(client._mono() * 1000000),
                    domain,
                    str(uuid4()),
                    cfg["provider"]["league_id"],
                    cfg["provider"]["season"],
                    previous,
                ),
            )
            if (
                projected.missing_ids
                or projected.rejected
                or set(projected.states) != set(config.fixture_ids)
            ):
                missing.add("BUNDLE_MISSING")
            for state in projected.states.values():
                if state["events_status"] not in {"OBSERVED", "OBSERVED_EMPTY"}:
                    missing.add("EVENTS_UNKNOWN")
            observations.append(
                {
                    "request_id": response.request_id,
                    "states": projected.states,
                    "missing_ids": list(projected.missing_ids),
                    "rejected": projected.rejected,
                }
            )
            previous = projected.states
    except ProviderError as error:
        if error.code == "AUTH_FAILED":
            result["KEY_CHECK"] = "FAILED"
        missing.add(
            {
                "AUTH_FAILED": "AUTH_FAILED",
                "SESSION_BUDGET": "BUDGET_LIMIT",
                "DAILY_BUDGET": "BUDGET_LIMIT",
                "MINUTE_BUDGET": "BUDGET_LIMIT",
                "PROVIDER_DAILY_RESERVE": "QUOTA_INSUFFICIENT",
                "RUN_DEADLINE_OR_AUTHORITY": "TIME_LIMIT",
            }.get(error.code, "PROVIDER_UNAVAILABLE")
        )
    except (ValueError, KeyboardInterrupt):
        missing.add("PROVIDER_UNAVAILABLE")
    if client._mono() >= client.scope.deadline_mono:
        missing.add("TIME_LIMIT")
    result.update(
        PROBE_RESULT="PASS"
        if not missing
        else "PARTIAL"
        if result["KEY_CHECK"] == "AUTHENTICATED"
        else "FAIL",
        REQUEST_ATTEMPTS=client.quota.count_attempts(),
        MISSING_CAPABILITIES=sorted(missing),
    )
    result["evidence"] = {
        "source_kind": client.scope.source_kind,
        "fixture_ids": list(config.fixture_ids),
        "quota": quota,
        "coverage": coverage,
        "observations": observations,
        "http_attempts": client.http_attempts,
        "requests": client.request_log,
        "elapsed_us": max(0, int((client._mono() - started) * 1000000)),
        "source_age": "UNKNOWN",
        "source_latency_measured": False,
        "events_fallback_enabled": False,
        "events_comparison_attempts": 0,
        "model_enabled": False,
        "money_ready": False,
    }
    return result


def run_probe(config: LiveConfig, secret: SecretValue, intent: RunIntentReceipt) -> ProbeResult:
    claim_receipt(intent, "PROVIDER_PROBE")
    if config.sha256 != intent.config.sha256:
        raise ValueError("E_PROBE_CONFIG")
    scope = ProviderScope(
        intent.run_id,
        config.fixture_ids,
        config.public["provider"]["league_id"],
        config.public["provider"]["season"],
        intent.deadline_mono,
        source_kind="OBSERVED_REAL",
        stage="PROVIDER_PROBE",
        max_attempts=intent.intent.public["max_http_attempts"],
        config_sha256=config.sha256,
        source_tree_sha256=intent.intent.public["source_tree_sha256"],
        receipt=intent,
    )
    # Admission is checked before constructing the fixed HTTPS opener, including on every attempt.
    from moj_discovery.live_intent import verify_provider_receipt

    verify_provider_receipt(intent, scope, "STATUS")
    directory = private_path(".local/part-b/provider-probes/" + intent.run_id, root=ROOT)
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    ledger = private_path(".local/part-b/quota/api-football-primary.sqlite3", root=ROOT)
    ledger.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    provider = config.public["provider"]
    with (
        QuotaLedger(
            ledger,
            scope_id=intent.run_id,
            daily_cap=provider["daily_soft_cap"],
            session_cap=scope.max_attempts,
            minute_cap=provider["max_requests_per_minute"],
            allow_status_bootstrap=True,
        ) as quota,
        ApiFootballClient(secret, quota, scope) as client,
    ):
        result = inspect_provider(config, client)
    report = {
        **result,
        "run_id": intent.run_id,
        "config_sha256": config.sha256,
        "source_tree_sha256": scope.source_tree_sha256,
        "intent_sha256": intent.intent.sha256,
        "confirmation_kind": intent.confirmation_kind,
        "finished_before_deadline": time.monotonic() < intent.deadline_mono,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "provider_config_scope": {
            "provider": config.public["provider"],
            "max_run_minutes": config.public["runtime"]["max_run_minutes"],
            "max_matches": config.public["runtime"]["max_matches"],
        },
    }
    data = json.dumps(report, indent=2).encode()
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("E_PROBE_EVIDENCE_CAP")
    fd = os.open(
        directory / "result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return result


if __name__ == "__main__":
    print("PROBE_NOT_STARTED: USE_USER_TERMINAL_KEY_LAUNCHER")
    raise SystemExit(2)
