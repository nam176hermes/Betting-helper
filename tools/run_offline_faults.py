"""Execute exact offline cases in owned workers; compare actual artifacts in the parent."""

# ruff: noqa: E402
import argparse
import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tools.offline_harness import SliceHarness
from tools.offline_results import artifacts, inventory, reference

META = {"OFF-20", "OFF-21", "OFF-22", "OFF-25"}


def observed_case(case: str, root: Path) -> dict[str, Any]:
    if case in META:
        from tools.offline_meta import check_meta
        from tools.verify_offline_slice import verify_offline_slice

        return check_meta(case, root, verify_offline_slice)
    from tools.offline_oracle import assert_case

    return assert_case(case, root / case / "run")


def run_required_cases(
    output: Path, browser_binary: Path, case_ids: list[str] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from tools.run_offline_slice import write_result

    selected = case_ids or [row["case_id"] for row in inventory()]
    records, observations = [], []
    commands = output / "commands"
    commands.mkdir()
    expected = {row["case_id"]: row["expected_behavior"] for row in inventory()}
    for case in selected:
        command = [
            sys.executable,
            str(ROOT / "tools/run_offline_faults.py"),
            "--case",
            case,
            "--output",
            str(output),
            "--browser-binary",
            str(browser_binary),
        ]
        with (
            (commands / (case + ".stdout")).open("xb") as out,
            (commands / (case + ".stderr")).open("xb") as err,
        ):
            process = subprocess.Popen(  # noqa: S603 -- fixed owned worker, no shell
                command, cwd=ROOT, stdout=out, stderr=err
            )
            try:
                code = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise RuntimeError("E_OFFLINE_OWNED_CLEANUP_TIMEOUT") from None
                code = process.returncode
        (commands / (case + ".json")).write_text(
            json.dumps({"command": command, "exit": code, "pid": process.pid})
        )
        status, reason = "FAIL", "E_OFFLINE_CASE_EXECUTION"
        observed = {"case_id": case, "reason": reason}
        if code == 0:
            try:
                observed = observed_case(case, output)
            except Exception:
                reason = "E_OFFLINE_ORACLE"
            else:
                status, reason = "PASS", "VERIFIED_OBSERVATIONS"
        refs = artifacts(output, case)
        refs.extend(
            reference(commands / (case + suffix), output)
            for suffix in [".stdout", ".stderr", ".json"]
        )
        if case in {"OFF-20", "OFF-22", "OFF-25"}:
            refs.append(reference(output / "reference.json", output))
        if case == "OFF-22":
            refs.extend(
                reference(path, output) for path in sorted(output.glob("negative-OFF-22-*.json"))
            )
        records.append(
            {
                "case_id": case,
                "status": status,
                "executed": True,
                "expected_behavior": expected[case],
                "actual_code": "OBSERVED_CASE_PASS" if status == "PASS" else reason,
                "command_exit": code,
                "artifacts": refs,
                "reason_code": reason,
            }
        )
        observations.append(observed)
        print(json.dumps({"case_id": case, "status": status, "command_exit": code}), flush=True)
        if case == "OFF-01" and status == "PASS":
            write_result(
                output,
                "single-stream",
                records[:1],
                observations[:1],
                name="reference.json",
                diagnostic_name="reference-diagnostic.html",
            )
    return records, observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-binary", required=True, type=Path)
    args = parser.parse_args()

    def terminate(_signum: int, _frame: Any) -> None:
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, terminate)
    try:
        if args.case in META:
            from tools.offline_meta import run_meta
            from tools.verify_offline_slice import verify_offline_slice

            run_meta(args.case, args.output, verify_offline_slice)
        else:
            SliceHarness(args.output, args.browser_binary).run_case(args.case)
    except Exception:
        print("E_OFFLINE_CASE_EXECUTION", file=sys.stderr)
        return 1
    print(json.dumps({"case_id": args.case, "execution": "FINISHED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
