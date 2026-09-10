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
BROWSER_TESTS = [
    "test_live_spool_bridge.py",
    "test_capture_graph.py",
    "test_workspace_projection.py",
    "test_local_bridge.py",
]
PART_B_PYTHON = [
    *sorted(
        str(p.relative_to(ROOT))
        for p in (ROOT / "src/moj_discovery").glob("live_*.py")
        if p.name != "live_preflight.py"
    ),
    "src/moj_discovery/providers",
    "src/moj_discovery/provider_protocol.py",
    "src/moj_discovery/provider_records.py",
    "src/moj_discovery/operator_profile.py",
    "src/moj_discovery/secrets_local.py",
    "src/moj_discovery/workspace_projection.py",
    "tools/configure_live_batched.py",
    "tools/prepare_part_b_intent.py",
    "tools/qualify_live_platform.py",
    "tools/live_preflight_batched.py",
    "tools/probe_football_provider.py",
    "tools/run_live_readonly.py",
    "tools/run_with_api_football_key.py",
    "tools/verify_part_b.py",
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


def run_check(
    argv: list[str],
    output: Path,
    name: str,
    *,
    timeout: int = 600,
    windows_browser: bool = False,
) -> dict[str, Any]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/home/thenam176",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if windows_browser:
        environment.update(
            PB_BROWSER_PLATFORM="WINDOWS_CHROME_WSL2", PB_PLATFORM="WINDOWS_CHROME_WSL2"
        )
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
        "browser_platform": "WINDOWS_CHROME_WSL2" if windows_browser else None,
    }
    (output / (name + ".command.json")).write_text(json.dumps(record, indent=2))
    return record


def verify_profile(profile: str, output: Path) -> VerificationResult:
    if profile not in {"mock", "security", "portable"}:
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
    if profile == "portable":
        targets += ["--ignore=tests/live/" + name for name in BROWSER_TESTS]
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
        timeout=1200,
        windows_browser=profile == "mock",
    )
    records.append(record)
    try:
        if record["exit"] != 0:
            raise ValueError()
        tests = executed_tests(output / "python.xml")
    except (ValueError, OSError, ET.ParseError):
        missing.append("PYTHON_CHECKS_NOT_PASSED")
    if profile in {"mock", "portable"}:
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
                (output / "compiled/node_modules").symlink_to(
                    ROOT / "extension/node_modules", target_is_directory=True
                )
                nodes = sorted(str(p) for p in (output / "compiled/test/live").glob("*.test.js"))
                if not nodes:
                    missing.append("NODE_TESTS_MISSING")
                else:
                    # One module graph executes shared test imports once (spool imports wire).
                    entrypoint = output / "compiled/live-tests.mjs"
                    entrypoint.write_text(
                        "\n".join(
                            "import " + json.dumps("./test/live/" + Path(p).name) + ";"
                            for p in nodes
                        )
                        + "\n"
                    )
                    record = run_check(
                        [node, "--test", "--test-reporter=tap", str(entrypoint)], output, "node"
                    )
                    records.append(record)
                    if record["exit"] != 0:
                        missing.append("NODE_CHECKS_NOT_PASSED")
            else:
                missing.append("TYPESCRIPT_CHECKS_NOT_PASSED")
            record = run_check(
                [
                    pnpm,
                    "--dir",
                    "extension",
                    "exec",
                    "eslint",
                    "src/live",
                    "src/storage",
                    "test/live",
                ],
                output,
                "eslint",
            )
            records.append(record)
        for name, argv in (
            ("registry", [sys.executable, "tools/run_command_registry.py", "--self-check"]),
            ("ruff", [sys.executable, "-m", "ruff", "check", *PART_B_PYTHON, "tests/live"]),
            ("mypy", [sys.executable, "-m", "mypy", *PART_B_PYTHON]),
        ):
            records.append(run_check(argv, output, name))
        if any(r["exit"] != 0 for r in records):
            missing.append("STATIC_OR_UNIT_CHECKS_NOT_PASSED")
    if profile == "mock" and not missing:
        records.append(
            run_check(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    *[
                        "tests/offline/" + name
                        for name in (
                            "test_protocol.py",
                            "test_receiver.py",
                            "test_retry_deadline.py",
                            "test_spool_cache.py",
                            "test_spool_payload_contract.py",
                            "test_pre_spool_redaction.py",
                        )
                    ],
                    "--basetemp=" + str(output / "shared-observations"),
                ],
                output,
                "shared-regressions",
            )
        )
        records.append(
            run_check(
                [
                    sys.executable,
                    "tools/run_offline_slice.py",
                    "--scenario",
                    "acceptance",
                    "--output",
                    str(output / "part-a"),
                    "--browser-binary",
                    "/opt/google/chrome/chrome",
                ],
                output,
                "part-a",
                timeout=1800,
            )
        )
        if records[-1]["exit"] == 0:
            records.append(
                run_check(
                    [
                        sys.executable,
                        "tools/verify_offline_slice.py",
                        "--input",
                        str(output / "part-a/result.json"),
                    ],
                    output,
                    "part-a-verify",
                    timeout=900,
                )
            )
        # PB-17 owns the explicit case-to-observed-test inventory. Missing owner is a HOLD.
        if not (ROOT / "tests/live/test_part_b_inventory.py").is_file():
            missing.append("REQUIRED_CASE_INVENTORY_MISSING")
        else:
            try:
                cases = importlib.import_module(
                    "tests.live.test_part_b_inventory"
                ).verify_executed_inventory(output, tests, records)
            except (ValueError, OSError) as error:
                missing.append("REQUIRED_CASE_EVIDENCE_MISSING:" + type(error).__name__)
                (output / "inventory-error.txt").write_text(str(error))
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
        "PORTABLE_UNIT_PASS": profile == "portable" and not missing,
        "browser_cases_not_executed": BROWSER_TESTS if profile == "portable" else [],
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
    parser.add_argument("--profile", choices=["mock", "security", "portable"], required=True)
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
