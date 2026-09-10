"""Write a nonsecret, unconsumed scope preview. This command does not authorize I/O."""

# ruff: noqa: E402
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
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


if __name__ == "__main__":
    raise SystemExit(main())
