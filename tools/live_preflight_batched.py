"""Read configured public evidence without reading credentials or starting a source."""

# ruff: noqa: E402
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.live_config import load_live_config
from moj_discovery.live_preflight_batched import evaluate_live_readiness, load_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = load_live_config(args.config)
        result = evaluate_live_readiness(config, load_evidence(config), key_present=None)
    except Exception:
        print("WAITING_REVIEW: invalid or unavailable public evidence")
        return 2
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.live_read_only_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
