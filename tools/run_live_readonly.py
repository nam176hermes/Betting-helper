"""Live service dispatch exclusively through a consumed user-terminal intent."""

# ruff: noqa: E402
import base64
import importlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from moj_discovery.live_config import LiveConfig
from moj_discovery.live_service import LiveService, run_live_service
from moj_discovery.secrets_local import SecretValue, controlling_tty


def show_local_pairing(service: LiveService) -> None:
    """Deliver one-use extension pairing only to the user's controlling terminal."""
    with controlling_tty() as terminal:
        ticket: dict[str, Any] = {
            "version": 1,
            "runId": service.admitted.run_id,
            "durationSeconds": max(
                1, min(7200, int(service.admitted.deadline_mono - time.monotonic()))
            ),
        }
        for field, role in (("ui", "UI_SUBSCRIBER"), ("capture", "CAPTURE_PRODUCER")):
            item = service.pairing.issue(role)
            ticket[field] = {
                "sessionId": item.session_id,
                "key": base64.urlsafe_b64encode(item.key).decode().rstrip("="),
            }
        terminal.write(
            "Local pairing ticket, valid for 120 seconds. Paste only into the extension panel.\n"
        )
        terminal.write(json.dumps(ticket, separators=(",", ":")) + "\n")
        terminal.flush()


def run_live_session(config: LiveConfig, secret: SecretValue, receipt: object) -> dict[str, Any]:
    try:
        gate = importlib.import_module("moj_discovery.live_preflight_batched")
        admission = gate.admit_live_run(config, receipt)
    except Exception:
        raise ValueError("E_LIVE_RUN_ADMISSION") from None
    result = run_live_service(config, secret, admission, on_ready=show_local_pairing)
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
