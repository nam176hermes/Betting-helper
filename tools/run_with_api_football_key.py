"""User-terminal entry only. No automatic provider permission follows from a key."""

# ruff: noqa: E402
import argparse
import importlib
import os
import sys
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Never

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from moj_discovery.live_config import LiveConfig, load_live_config
from moj_discovery.providers.api_football import PROVIDER_DIAGNOSTICS
from moj_discovery.secrets_local import KEY_NAME, controlling_tty, obtain_api_football_key

PHRASES = {"probe": "ALLOW PROVIDER PROBE", "live-readonly": "START READ ONLY"}
STAGES = {"probe": "PROVIDER_PROBE", "live-readonly": "LIVE_READ_ONLY"}


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse's ordinary message may quote arbitrary user input.
        raise ValueError("E_KEY_LAUNCHER_ARGUMENTS")


def _load_action(
    action: str,
    config: LiveConfig,
    path: Path,
) -> tuple[Any, Callable[..., Any], Callable[..., Any]]:
    intents = importlib.import_module("moj_discovery.live_intent")
    intent = intents.load_run_intent(path, config, STAGES[action])
    if action == "probe":
        dispatch = importlib.import_module("tools.probe_football_provider").run_probe
    else:
        dispatch = importlib.import_module("tools.run_live_readonly").run_live_session
    return intent, intents.consume_user_intent, dispatch


def _failure(started: bool) -> None:
    print("KEY_CHECK: NOT_CHECKED")
    print("SUBSCRIPTION_CHECK: UNKNOWN")
    print("PROBE_RESULT: FAIL")
    print("REQUEST_ATTEMPTS: " + ("UNKNOWN" if started else "0"))
    print("MISSING_CAPABILITIES: USER_CONFIRMATION_OR_RUNTIME_GATE")


def _report(result: dict[str, Any]) -> None:
    selected = {}
    enums = {
        "KEY_CHECK": {"AUTHENTICATED", "FAILED", "NOT_CHECKED"},
        "SUBSCRIPTION_CHECK": {"CONFIRMED", "INSUFFICIENT", "UNKNOWN"},
        "PROBE_RESULT": {"PASS", "PARTIAL", "FAIL"},
    }
    for key, allowed in enums.items():
        if result.get(key) not in allowed:
            raise ValueError("E_KEY_LAUNCHER_RESULT")
        selected[key] = result[key]
    attempts = result.get("REQUEST_ATTEMPTS")
    if type(attempts) is not int or not 0 <= attempts <= 600:
        raise ValueError("E_KEY_LAUNCHER_RESULT")
    codes = result.get("MISSING_CAPABILITIES")
    allowed_codes = {
        "AUTH_FAILED",
        "QUOTA_UNKNOWN",
        "QUOTA_INSUFFICIENT",
        "COVERAGE_UNKNOWN",
        "BUNDLE_MISSING",
        "EVENTS_UNKNOWN",
        "TIME_LIMIT",
        "BUDGET_LIMIT",
        "SOURCE_MISMATCH",
        "PROVIDER_UNAVAILABLE",
        "REVIEW_REQUIRED",
        "EXACT_FIXTURE_PROBE_REQUIRED",
    }
    if type(codes) is not list or any(type(c) is not str or c not in allowed_codes for c in codes):
        raise ValueError("E_KEY_LAUNCHER_RESULT")
    diagnostic = result.get("PROVIDER_DIAGNOSTIC", "NONE")
    if type(diagnostic) is not str or diagnostic not in PROVIDER_DIAGNOSTICS:
        raise ValueError("E_KEY_LAUNCHER_RESULT")
    for key, value in selected.items():
        print(f"{key}: {value}")
    print(f"REQUEST_ATTEMPTS: {attempts}")
    print("MISSING_CAPABILITIES: " + (", ".join(codes) or "NONE"))
    print("PROVIDER_DIAGNOSTIC: " + diagnostic)


def _report_live(result: dict[str, Any]) -> None:
    if (
        set(result)
        != {
            "LIVE_SESSION_RESULT",
            "REQUEST_ATTEMPTS",
            "REAL_HTTP_ATTEMPTS",
            "RUN_DIRECTORY",
            "REPLAY_REQUIRED",
        }
        or result["LIVE_SESSION_RESULT"] != "CLOSED_PENDING_REPLAY"
        or result["REPLAY_REQUIRED"] is not True
        or any(
            type(result[k]) is not int or not 0 <= result[k] <= 600
            for k in ("REQUEST_ATTEMPTS", "REAL_HTTP_ATTEMPTS")
        )
    ):
        raise ValueError("E_KEY_LAUNCHER_RESULT")
    directory = Path(result["RUN_DIRECTORY"])
    if directory.resolve() != directory or not directory.is_relative_to(ROOT / ".local/part-b"):
        raise ValueError("E_KEY_LAUNCHER_RESULT")
    print("LIVE_SESSION_RESULT: CLOSED_PENDING_REPLAY")
    print("REQUEST_ATTEMPTS: " + str(result["REQUEST_ATTEMPTS"]))
    print("REAL_HTTP_ATTEMPTS: " + str(result["REAL_HTTP_ATTEMPTS"]))
    print("RUN_DIRECTORY: " + str(directory))
    print("REPLAY_REQUIRED: true — phiên đã đóng; chưa phải LIVE_READ_ONLY_PASS_ONE")


def main(argv: list[str] | None = None) -> int:
    started = False
    secret = None
    try:
        parser = SafeParser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--action", choices=tuple(PHRASES), required=True)
        parser.add_argument("--config", type=Path, required=True)
        parser.add_argument("--intent", type=Path, required=True)
        args = parser.parse_args(argv)
        config = load_live_config(args.config, require_enabled=args.action == "live-readonly")
        intent, consume, dispatch = _load_action(args.action, config, args.intent)
        preview = intent.public
        print("STAGE: " + STAGES[args.action])
        print("FIXTURE_IDS: " + ",".join(str(i) for i in preview["fixture_ids"]))
        for url in preview.get("operator_urls", []):
            print("OPERATOR_URL: " + url)
        if "lookup_date" in preview:
            print("LOOKUP_ONLY_LEAGUE: " + str(config.public["provider"]["league_id"]))
            print("LOOKUP_ONLY_SEASON: " + str(config.public["provider"]["season"]))
            print("LOOKUP_ONLY_DATE_UTC: " + preview["lookup_date"])
        print(f"MAX_DURATION_SECONDS: {preview['max_duration_seconds']}")
        print(f"MAX_HTTP_ATTEMPTS: {preview['max_http_attempts']}")
        print("Type " + PHRASES[args.action] + " to confirm this exact scope:")
        with controlling_tty() as terminal:
            confirmation = terminal.readline(65).rstrip("\r\n")
        if confirmation != PHRASES[args.action]:
            _failure(False)
            return 2
        receipt = consume(intent, config, confirmation)
        # Browser subprocesses must never inherit a credential supplied to this process.
        os.environ.pop(KEY_NAME, None)
        with ExitStack() as stack:
            credentials = config.public.get("credentials")
            if credentials is None:
                secret = obtain_api_football_key(interactive=True)
            else:
                from moj_discovery.windows_credential_store import stored_key

                secret = stack.enter_context(
                    stored_key(
                        args.action,
                        config.sha256,
                        preview["source_tree_sha256"],
                        credentials["generation"],
                        run_id=receipt.run_id,
                        intent_hash=intent.sha256,
                        native_python_sha256=credentials["native_python_sha256"],
                    )
                )
            started = True
            result = dispatch(config, secret, receipt)
            secret.check_usable()
        if args.action == "live-readonly":
            _report_live(result)
            return 0
        _report(result)
        return 0 if result["PROBE_RESULT"] == "PASS" else 2
    except (Exception, KeyboardInterrupt):
        _failure(started)
        return 2
    finally:
        # Drop our reference; Python strings are not claimed to be securely zeroized.
        secret = None


if __name__ == "__main__":
    raise SystemExit(main())
