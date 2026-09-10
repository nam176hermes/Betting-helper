"""Write a nonsecret, unconsumed scope preview. This command does not authorize I/O."""

# ruff: noqa: E402
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.live_config import load_live_config, private_path
from moj_discovery.live_intent import RunIntent, _validate, source_tree_hash
from tools.run_with_api_football_key import SafeParser

STAGES = {
    "provider-probe": "PROVIDER_PROBE",
    "operator-discovery": "OPERATOR_DISCOVERY",
    "live-readonly": "LIVE_READ_ONLY",
}


def main(argv: list[str] | None = None) -> int:
    try:
        parser = SafeParser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--stage", choices=tuple(STAGES), required=True)
        parser.add_argument("--config", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--duration", type=int)
        parser.add_argument("--attempts", type=int)
        parser.add_argument("--operator-url", action="append", default=[])
        parser.add_argument("--lookup-date")
        args = parser.parse_args(argv)
        config = load_live_config(args.config)
        stage = STAGES[args.stage]
        duration, attempts = {
            "PROVIDER_PROBE": (300, 20),
            "OPERATOR_DISCOVERY": (600, 0),
            "LIVE_READ_ONLY": (
                config.public["runtime"]["max_run_minutes"] * 60,
                config.public["provider"]["max_requests_per_run"],
            ),
        }[stage]
        relative = (
            str(args.output.relative_to(ROOT)) if args.output.is_absolute() else str(args.output)
        )
        target = private_path(relative, root=ROOT)
        now = datetime.now(UTC)
        value = dict(
            schema_version="part-b-run-intent/v1",
            intent_id=str(uuid4()),
            stage=stage,
            config_sha256=config.sha256,
            source_tree_sha256=source_tree_hash(ROOT),
            fixture_ids=list(config.fixture_ids),
            operator_urls=args.operator_url,
            max_duration_seconds=duration if args.duration is None else args.duration,
            max_http_attempts=attempts if args.attempts is None else args.attempts,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=15)).isoformat(),
            user_confirmation_required=True,
            money_authority=False,
        )
        if args.lookup_date is not None:
            value["lookup_date"] = args.lookup_date
        _validate(RunIntent(value, "0" * 64, ROOT), config, now)
        if stage == "LIVE_READ_ONLY" and relative != config.public["gates"]["live_intent_path"]:
            raise ValueError()
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        print("INTENT_PREPARED: USER_TERMINAL_CONFIRMATION_REQUIRED")
        print("MAX_DURATION_SECONDS: " + str(value["max_duration_seconds"]))
        print("MAX_HTTP_ATTEMPTS: " + str(value["max_http_attempts"]))
        return 0
    except Exception:
        print("INTENT_NOT_CREATED: INVALID_SCOPE_OR_EXISTING_FILE")
        return 2


def execute_discovery(argv: list[str]) -> int:
    """User-terminal execution only. No API key acquisition or browser attachment."""
    import asyncio

    from moj_discovery.canonical import parse_strict_json
    from moj_discovery.live_intent import (
        consume_user_intent,
        discovery_review_scope,
        load_run_intent,
        serve_operator_discovery,
    )
    from moj_discovery.live_preflight_batched import verify_external_review
    from moj_discovery.secrets_local import controlling_tty

    try:
        parser = SafeParser(allow_abbrev=False)
        parser.add_argument("--config", required=True, type=Path)
        parser.add_argument("--intent", required=True, type=Path)
        parser.add_argument("--selectors", required=True, type=Path)
        parser.add_argument("--review", required=True, type=Path)
        parser.add_argument("--profile-name", required=True)
        args = parser.parse_args(argv)
        config = load_live_config(args.config)
        intent = load_run_intent(args.intent, config, "OPERATOR_DISCOVERY", root=ROOT)

        def read(path: Path) -> dict[str, Any]:
            relative = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
            checked = private_path(relative, root=ROOT, must_exist=True)
            if checked.stat().st_size > 65536:
                raise ValueError()
            value = parse_strict_json(checked.read_bytes())
            if type(value) is not dict:
                raise ValueError()
            return value

        selectors, review = read(args.selectors), read(args.review)
        scope = discovery_review_scope(
            intent,
            config,
            selectors,
            args.profile_name,
            review.get("scope", {}).get("expires_at", ""),
        )
        # No prompt to grant capture until the real independent tool review verifies.
        verify_external_review(review, scope, ROOT, datetime.now(UTC))
        print("STAGE: OPERATOR_DISCOVERY")
        print("PROFILE: " + args.profile_name)
        print("EXACT_URL: " + scope["exact_url"])
        print("MAX_DURATION_SECONDS: " + str(scope["max_duration_seconds"]))
        print("MAX_PROVIDER_REQUESTS: 0")
        print("PROFILE_ACCEPTED: false")
        print("Type ALLOW OPERATOR OBSERVATION to confirm this exact scope:")
        with controlling_tty() as terminal:
            confirmation = terminal.readline(65).rstrip("\r\n")
        receipt = consume_user_intent(intent, config, confirmation)
        output = ROOT / ".local/part-b/operator-discovery" / receipt.run_id / "result.json"
        result = asyncio.run(
            serve_operator_discovery(receipt, selectors, args.profile_name, review, output)
        )
        print("DISCOVERY_RESULT: " + result["status"])
        print("PROFILE_ACCEPTED: false")
        return 0 if result["status"] == "UNADMITTED_SAMPLE_SAVED" else 2
    except (Exception, KeyboardInterrupt):
        print("DISCOVERY_NOT_STARTED_OR_REJECTED: CHECK_SCOPE_REVIEW_AND_TERMINAL")
        return 2


if __name__ == "__main__":
    if sys.argv[1:2] == ["execute-discovery"]:
        raise SystemExit(execute_discovery(sys.argv[2:]))
    raise SystemExit(main())
