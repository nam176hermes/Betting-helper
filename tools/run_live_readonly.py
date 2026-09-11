"""Live service dispatch exclusively through a consumed user-terminal intent."""

# ruff: noqa: E402
import asyncio
import base64
import importlib
import json
import sys
import time
from collections.abc import Callable
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


def enable_local_repair(service: LiveService) -> Callable[[], None]:
    """Only an explicit PAIR line in the same user terminal can renew pairing."""
    scope = controlling_tty()
    terminal = scope.__enter__()
    loop = asyncio.get_running_loop()
    descriptor = terminal.fileno()
    closed = False

    def close() -> None:
        nonlocal closed
        if not closed:
            closed = True
            loop.remove_reader(descriptor)
            scope.__exit__(None, None, None)

    def ready() -> None:
        line = terminal.readline(256)
        if line == "":
            close()
        elif line.strip() == "PAIR":
            try:
                show_local_pairing(service)
            except ValueError:
                terminal.write("PAIRING_UNAVAILABLE: existing ticket, cap or expired session.\n")
                terminal.flush()
        elif line.startswith("CHECK "):
            try:
                _, fixture, home, draw, away = line.split()
                service.record_manual_ft_check(int(fixture), (home, draw, away))
                terminal.write("FT_CHECK_RECORDED\n")
            except (ValueError, KeyError, StopIteration):
                terminal.write(
                    "FT_CHECK_REFUSED: not current, mismatched, duplicate or outside scope.\n"
                )
            terminal.flush()

    try:
        show_local_pairing(service)
        terminal.write("After worker restart, type PAIR here for a fresh local ticket.\n")
        terminal.write(
            "Compare the exact fixture, market and HOME/DRAW/AWAY selection IDs in both views.\n"
            "Then record the visible prices: CHECK fixture_id home_price draw_price away_price\n"
            "Record three distinct current FT captures per fixture, at least 30 seconds apart.\n"
        )
        terminal.flush()
        loop.add_reader(descriptor, ready)
    except BaseException:
        close()
        raise
    return close


def run_live_session(config: LiveConfig, secret: SecretValue, receipt: object) -> dict[str, Any]:
    try:
        gate = importlib.import_module("moj_discovery.live_preflight_batched")
        admission = gate.admit_live_run(config, receipt)
    except Exception:
        raise ValueError("E_LIVE_RUN_ADMISSION") from None
    result = run_live_service(config, secret, admission, on_ready=enable_local_repair)
    return {
        "LIVE_SESSION_RESULT": "CLOSED_PENDING_REPLAY",
        "REQUEST_ATTEMPTS": result.request_attempts,
        "REAL_HTTP_ATTEMPTS": result.real_http_attempts,
        "RUN_DIRECTORY": result.run_directory,
        "REPLAY_REQUIRED": True,
    }


def main(argv: list[str] | None = None) -> int:
    # This CLI has no credential/env bypass and cannot independently authorize a run.
    print("WAITING_REVIEW: use the no-echo user-terminal launcher after current run admission")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
