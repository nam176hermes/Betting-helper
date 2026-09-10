"""Create a disabled local Part B config using nonsecret choices only."""

# ruff: noqa: E402
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.live_config import load_live_config
from moj_discovery.providers.poll_budget import PollSegment, estimate_requests
from moj_discovery.secrets_local import controlling_tty
from tools.run_with_api_football_key import SafeParser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = SafeParser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--output", type=Path, default=Path("config/live.local.json"))
        parser.add_argument("--platform", choices=("WINDOWS_CHROME_WSL2", "LINUX_CHROME"))
        parser.add_argument("--league", type=int)
        parser.add_argument("--season", type=int)
        parser.add_argument("--fixtures")
        parser.add_argument("--max-matches", type=int, choices=(1, 3, 5), default=1)
        parser.add_argument("--minutes", type=int, default=120)
        parser.add_argument("--requests", type=int, default=600)
        parser.add_argument("--daily-cap", type=int, default=6000)
        parser.add_argument("--minute-cap", type=int, default=6)
        parser.add_argument("--replace", action="store_true")
        args = parser.parse_args(argv)
        if any(
            getattr(args, name) is None for name in ("platform", "league", "season", "fixtures")
        ):
            with controlling_tty() as terminal:
                for name in ("platform", "league", "season", "fixtures"):
                    if getattr(args, name) is None:
                        terminal.write(
                            name
                            + (
                                " (WINDOWS_CHROME_WSL2 / LINUX_CHROME)"
                                if name == "platform"
                                else " (nonsecret)"
                            )
                            + ": "
                        )
                        terminal.flush()
                        raw = terminal.readline(257).strip()
                        setattr(args, name, int(raw) if name in {"league", "season"} else raw)
        output = args.output if args.output.is_absolute() else ROOT / args.output
        if output != ROOT / "config/live.local.json" or any(
            p.is_symlink() for p in (output, *output.parents)
        ):
            raise ValueError()
        if output.exists() and not args.replace:
            raise ValueError()
        value = json.loads((ROOT / "config/live-batched.example.json").read_text())
        fixtures = [int(v) for v in args.fixtures.split(",")]
        if len(set(fixtures)) != len(fixtures) or not fixtures:
            raise ValueError()
        value["provider"].update(
            league_id=args.league,
            season=args.season,
            fixture_ids=sorted(fixtures),
            max_requests_per_run=args.requests,
            daily_soft_cap=args.daily_cap,
            max_requests_per_minute=args.minute_cap,
        )
        value["runtime"].update(
            platform=args.platform, max_matches=args.max_matches, max_run_minutes=args.minutes
        )
        estimate = estimate_requests([PollSegment(0, args.minutes * 60, 15)] * len(fixtures))
        # This is an upper estimate at the live cadence, not measured provider latency.
        if estimate.with_reserve > args.requests:
            raise ValueError()
        temporary = output.with_name("live.local.json.pending")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(value, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            load_live_config(temporary)
            if args.replace:
                os.replace(temporary, output)
            else:
                os.link(temporary, output)
                temporary.unlink()
        except Exception:
            # Only this invocation's unpublished temporary file is removed.
            temporary.unlink(missing_ok=True)
            raise
        print("CONFIG_CREATED: DISABLED")
        print("ESTIMATED_ATTEMPTS_WITH_RESERVE: " + str(estimate.with_reserve))
        print("MODEL_ENABLED: false\nMONEY_READY: NO")
        return 0
    except Exception:
        print("CONFIG_NOT_CREATED: INVALID_OR_EXISTING_LOCAL_CONFIG")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
