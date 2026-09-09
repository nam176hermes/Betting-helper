"""Run isolated synthetic accounting scenarios using real Chrome and SQLite."""

# ruff: noqa: E402
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.diagnostic import render_diagnostic
from tools.offline_results import build_result, gate_view, reference
from tools.run_offline_faults import run_required_cases
from tools.verify_offline_slice import verify_offline_slice


def write_result(
    output: Path,
    scenario_id: str,
    records: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    name: str,
    diagnostic_name: str,
) -> Path:
    diagnostic = output / diagnostic_name
    with diagnostic.open("x") as stream:
        stream.write("")
    value = build_result(output, scenario_id, records, diagnostic_name)
    diagnostic.write_text(render_diagnostic(gate_view(value, observations)))
    value["diagnostic"] = reference(diagnostic, output)
    result = output / name
    with result.open("x") as stream:
        json.dump(value, stream, indent=2)
    return result


def run_scenario(scenario_id: str, output: Path, browser_binary: Path) -> dict[str, Any]:
    if scenario_id not in {"single-stream", "acceptance"}:
        raise ValueError("E_OFFLINE_SCENARIO")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    records, observations = run_required_cases(
        output, browser_binary, ["OFF-01"] if scenario_id == "single-stream" else None
    )
    candidate = write_result(
        output,
        scenario_id,
        records,
        observations,
        name="candidate.json",
        diagnostic_name="diagnostic.html",
    )
    verified = verify_offline_slice(candidate)
    candidate.rename(output / "result.json")
    return verified


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
