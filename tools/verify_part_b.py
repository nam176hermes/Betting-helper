"""Run finite source-bound Part B checks and retain actual process/test observations."""

# ruff: noqa: E402
import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.live_intent import source_tree_hash

VerificationResult = dict[str, Any]
SECURITY_TESTS = [
    "test_live_preflight_batched.py",
    "test_live_security.py",
    "test_secret_entry.py",
    "test_secret_nonleakage.py",
    "test_provider_http_boundary.py",
    "test_live_wire.py",
    "test_operator_profile.py",
    "test_run_intents.py",
]


def test_source_hashes() -> dict[str, str]:
    files = [ROOT / "config/live-batched.example.json"]
    for folder in ("tests/live", "extension/test/live"):
        files.extend(
            p for p in (ROOT / folder).rglob("*") if p.suffix in {".py", ".ts", ".html", ".json"}
        )
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(files)
        if p.is_file() and not p.is_symlink()
    }


def executed_tests(report: Path) -> dict[str, str]:
    """A collected, skipped or failing test cannot be reported as executed PASS."""
    tree = ET.parse(report)  # noqa: S314 -- own bounded local pytest output, not network XML.
    rows = {}
    for test in tree.iter("testcase"):
        identity = test.attrib["classname"] + "::" + test.attrib["name"]
        if identity in rows:
            raise ValueError("E_PART_B_DUPLICATE_TEST")
        rows[identity] = "PASS" if not list(test) else "NOT_PASS"
    if not rows or any(value != "PASS" for value in rows.values()):
        raise ValueError("E_PART_B_TESTS_NOT_EXECUTED")
    return rows


def run_check(argv: list[str], output: Path, name: str, *, timeout: int = 600) -> dict[str, Any]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/home/thenam176",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    started = time.monotonic()
    log_path = output / (name + ".log")
    with log_path.open("xb") as log:
        try:
            result = subprocess.run(  # noqa: S603 -- fixed local checks, no shell.
                argv,
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )  # noqa: S603 -- fixed local checks, never shell/user code.
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    record = {
        "argv": argv,
        "cwd": str(ROOT),
        "exit": code,
        "seconds": time.monotonic() - started,
        "log": log_path.name,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
    }
    (output / (name + ".command.json")).write_text(json.dumps(record, indent=2))
    return record


def verify_profile(profile: str, output: Path) -> VerificationResult:
    if profile not in {"mock", "security"}:
        raise ValueError("E_PART_B_PROFILE")
    if not __debug__:
        raise ValueError("E_PART_B_OPTIMIZED")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = source_tree_hash()
    test_sources = test_source_hashes()
    records = []
    missing = []
    tests = {}
    cases: list[str] = []
    targets = (
        ["tests/live/" + name for name in SECURITY_TESTS]
        if profile == "security"
        else ["tests/live"]
    )
    record = run_check(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *targets,
            "--junitxml=" + str(output / "python.xml"),
            "--basetemp=" + str(output / "observations"),
        ],
        output,
        "python",
    )
    records.append(record)
    try:
        if record["exit"] != 0:
            raise ValueError()
        tests = executed_tests(output / "python.xml")
    except (ValueError, OSError, ET.ParseError):
        missing.append("PYTHON_CHECKS_NOT_PASSED")
    if profile == "mock":
        pnpm, node = shutil.which("pnpm"), shutil.which("node")
        if not pnpm or not node:
            missing.append("NODE_RUNTIME_MISSING")
        else:
            record = run_check(
                [
                    pnpm,
                    "--dir",
                    "extension",
                    "exec",
                    "tsc",
                    "-p",
                    "tsconfig.live.json",
                    "--moduleDetection",
                    "legacy",
                    "--outDir",
                    str(output / "compiled"),
                ],
                output,
                "compile",
            )
            records.append(record)
            if record["exit"] == 0:
                (output / "compiled/package.json").write_text('{"type":"module"}\n')
                nodes = sorted(str(p) for p in (output / "compiled/test/live").glob("*.test.js"))
                if not nodes:
                    missing.append("NODE_TESTS_MISSING")
                else:
                    record = run_check(
                        [node, "--test", "--test-reporter=tap", *nodes], output, "node"
                    )
                    records.append(record)
                    if record["exit"] != 0:
                        missing.append("NODE_CHECKS_NOT_PASSED")
            else:
                missing.append("TYPESCRIPT_CHECKS_NOT_PASSED")
        # PB-17 owns the explicit case-to-observed-test inventory. Missing owner is a HOLD.
        if not (ROOT / "tests/live/test_part_b_inventory.py").is_file():
            missing.append("REQUIRED_CASE_INVENTORY_MISSING")
        else:
            try:
                cases = importlib.import_module(
                    "tests.live.test_part_b_inventory"
                ).verify_executed_inventory(output, tests, records)
            except (ValueError, OSError):
                missing.append("REQUIRED_CASE_EVIDENCE_MISSING")
    if source != source_tree_hash() or test_sources != test_source_hashes():
        missing.append("SOURCE_CHANGED_DURING_CHECKS")
    result = {
        "schema_version": "part-b-verification/v1",
        "profile": profile,
        "status": "PASS" if not missing else "HOLD",
        "source_tree_sha256": source,
        "test_source_hashes": test_sources,
        "command_records": records,
        "executed_tests": tests,
        "executed_case_ids": cases,
        "missing_inputs": missing,
        "PART_B_MOCK_PASS": profile == "mock" and not missing,
        "independent_review": "SELF_ONLY",
        "live_read_only_pass": False,
        "real_provider_attempts": 0,
        "operator_observed": False,
        "model_enabled": False,
        "money_ready": False,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["mock", "security"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = verify_profile(args.profile, args.output)
    print(
        json.dumps(
            {k: result[k] for k in ("status", "profile", "missing_inputs", "PART_B_MOCK_PASS")},
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
