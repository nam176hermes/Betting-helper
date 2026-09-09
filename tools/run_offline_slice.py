"""Run isolated synthetic accounting scenarios using real Chrome and SQLite."""

# ruff: noqa: E402
import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tools.offline_harness import SliceHarness


def run_scenario(scenario_id: str, output: Path, browser_binary: Path) -> dict[str, Any]:
    if scenario_id != "single-stream":
        raise ValueError("E_OFFLINE_ACCEPTANCE_NOT_IMPLEMENTED")
    harness = SliceHarness(output, browser_binary)
    result = asdict(harness.run_case("OFF-01"))
    result["run_dir"] = str(result["run_dir"])
    (output / "single-stream.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["single-stream", "acceptance"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-binary", type=Path, default=os.environ.get("BH_CHROME_BINARY"))
    args = parser.parse_args()
    if args.browser_binary is None:
        parser.error("Supply the approved browser via --browser-binary or BH_CHROME_BINARY")
    try:
        run_scenario(args.scenario, args.output, args.browser_binary)
    except Exception:
        print("E_OFFLINE_SCENARIO_FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
