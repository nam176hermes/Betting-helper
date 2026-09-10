"""Live service dispatch exclusively through a consumed user-terminal intent."""

# ruff: noqa: E402
import importlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from moj_discovery.live_config import LiveConfig
from moj_discovery.live_service import run_live_service
from moj_discovery.secrets_local import SecretValue


def run_live_session(config: LiveConfig, secret: SecretValue, receipt: object) -> dict[str, Any]:
    try:
        gate = importlib.import_module("moj_discovery.live_preflight_batched")
        admission = gate.admit_live_run(config, receipt)
    except Exception:
        raise ValueError("E_LIVE_RUN_ADMISSION") from None
    result = run_live_service(config, secret, admission)
    return {
        "KEY_CHECK": "AUTHENTICATED" if result.authenticated else "NOT_CHECKED",
        "SUBSCRIPTION_CHECK": "UNKNOWN",
        "PROBE_RESULT": "PARTIAL",
        "REQUEST_ATTEMPTS": result.request_attempts,
        "MISSING_CAPABILITIES": ["REVIEW_REQUIRED"],
    }


def main(argv: list[str] | None = None) -> int:
    # This CLI has no credential/env bypass and cannot independently authorize a run.
    print("WAITING_REVIEW: use the no-echo user-terminal launcher after current run admission")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
