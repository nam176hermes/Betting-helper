"""Independently reopen source-bound offline evidence; no authority is granted."""

# ruff: noqa: E402
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.canonical import parse_strict_json
from moj_discovery.diagnostic import render_diagnostic
from moj_discovery.input_journal import _read
from moj_discovery.offline_protocol import _validator
from moj_discovery.replay import verify_replay_equivalence
from tools.offline_browser import OfflineBrowser, prepare_offline_extension
from tools.offline_harness import source_hashes
from tools.offline_meta import check_meta
from tools.offline_oracle import assert_case
from tools.offline_results import gate_view


def artifact(root: Path, reference: dict[str, Any]) -> Path:
    name = reference["relative_path"]
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise ValueError("E_OFFLINE_ARTIFACT_PATH")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or any(
        p.is_symlink() for p in (path, *path.parents)
    ):
        raise ValueError("E_OFFLINE_ARTIFACT_PATH")
    data = _read(path)
    if len(data) != reference["bytes"] or hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ValueError("E_OFFLINE_ARTIFACT_HASH")
    return path


def verify_offline_slice(result_path: Path) -> dict[str, Any]:
    if not __debug__:
        raise RuntimeError("E_OFFLINE_OPTIMIZED_EXECUTION")
    result = cast(dict[str, Any], parse_strict_json(_read(result_path)))
    _validator("result.schema.json").validate(result)
    root = result_path.absolute().parent
    provenance = result["provenance"]
    registry = json.loads((ROOT / "registries/offline-cases.json").read_text())["cases"]
    complete = [f"OFF-{index:02d}" for index in range(1, 28)]
    if [row["case_id"] for row in registry] != complete:
        raise ValueError("E_OFFLINE_CASE_INVENTORY")
    required = complete if provenance["scenario_id"] == "acceptance" else ["OFF-01"]
    if (
        result["required_case_ids"] != required
        or [r["case_id"] for r in result["records"]] != required
        or result["run_id"] != provenance["run_id"]
    ):
        raise ValueError("E_OFFLINE_CASE_INVENTORY")
    full = provenance["scenario_id"] == "acceptance"
    if result["OFFLINE_SLICE_PASS"] != ("YES" if full else "NO"):
        raise ValueError("E_OFFLINE_FORGED_PASS")
    if result["LEGACY_FULL_QUALIFICATION"] not in {"HOLD", "NOT_EVALUATED"} or result[
        "INDEPENDENT_SECURITY_REVIEW"
    ] not in {"NOT_RUN", "SELF_ONLY"}:
        raise ValueError("E_OFFLINE_UNSUPPORTED_AUTHORITY_CLAIM")
    current = source_hashes()
    tree_hash = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
    head = subprocess.check_output(
        ["/usr/bin/git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if tree_hash != provenance["source_tree_sha256"] or head != provenance["code_revision"]:
        raise ValueError("E_OFFLINE_SOURCE_STALE")
    bindings = {
        "python_lock_sha256": "uv.lock",
        "node_lock_sha256": "pnpm-lock.yaml",
        "vendor_sha256": "vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json",
        "scenario_sha256": "registries/offline-cases.json",
    }
    for field, path in bindings.items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != provenance[field]:
            raise ValueError("E_OFFLINE_SOURCE_BINDING")
    browser_path = Path(os.environ.get("BH_CHROME_BINARY", "/opt/google/chrome/chrome"))
    if hashlib.sha256(browser_path.read_bytes()).hexdigest() != provenance["browser_sha256"]:
        raise ValueError("E_OFFLINE_BROWSER_BINDING")
    artifact(root, result["diagnostic"])
    expectations = {r["case_id"]: r["expected_behavior"] for r in registry}
    cases = []
    verification = root / "verification" / str(uuid4())
    prepare_offline_extension(verification / "current-modules")
    expected_modules = json.loads(_read(verification / "current-modules/module-hashes.json"))
    for record in result["records"]:
        if (
            record["status"] != "PASS"
            or record["executed"] is not True
            or record["command_exit"] != 0
            or record["expected_behavior"] != expectations[record["case_id"]]
            or not record["artifacts"]
        ):
            raise ValueError("E_OFFLINE_CASE_NOT_PASSED")
        names = [r["relative_path"] for r in record["artifacts"]]
        if len(set(names)) != len(names):
            raise ValueError("E_OFFLINE_ARTIFACT_DUPLICATE")
        for reference in record["artifacts"]:
            artifact(root, reference)
        case = record["case_id"]
        directory = root / case
        consumed = {
            str(path.relative_to(root))
            for path in directory.rglob("*")
            if path.is_file()
            and "profile" not in path.parts
            and "offline-extension" not in path.parts
        }
        if not consumed.issubset(names):
            raise ValueError("E_OFFLINE_UNBOUND_EVIDENCE")
        command_names = {f"commands/{case}{suffix}" for suffix in [".json", ".stdout", ".stderr"]}
        if not command_names.issubset(names):
            raise ValueError("E_OFFLINE_MISSING_COMMAND_EVIDENCE")
        command = json.loads(_read(root / "commands" / (case + ".json")))
        expected_command = [
            str(ROOT / "tools/run_offline_faults.py"),
            "--case",
            case,
            "--output",
            str(root),
            "--browser-binary",
            str(browser_path),
        ]
        if (
            command["exit"] != 0
            or command["pid"] <= 0
            or command["command"][1:] != expected_command
        ):
            raise ValueError("E_OFFLINE_COMMAND_BINDING")
        finished = json.loads(_read(root / "commands" / (case + ".stdout")))
        if finished != {"case_id": case, "execution": "FINISHED"}:
            raise ValueError("E_OFFLINE_COMMAND_BINDING")
        if case in {"OFF-20", "OFF-21", "OFF-22", "OFF-25"}:
            required_meta = {
                "OFF-20": ["input.json", "diagnostic.html"],
                "OFF-21": ["config.json", "observed.json"],
                "OFF-22": ["observed.json", "tampered.bin"],
                "OFF-25": [
                    "observed.json",
                    "original-config.json",
                    "changed-config.json",
                    "changed-sources.json",
                ],
            }[case]
            if not {f"{case}/{name}" for name in required_meta}.issubset(names):
                raise ValueError("E_OFFLINE_MISSING_META_EVIDENCE")
            if case in {"OFF-20", "OFF-22", "OFF-25"} and "reference.json" not in names:
                raise ValueError("E_OFFLINE_MISSING_META_EVIDENCE")
            if case == "OFF-22" and not {
                f"negative-{case}-{kind}.json"
                for kind in ["missing", "tampered", "duplicate", "forged"]
            }.issubset(names):
                raise ValueError("E_OFFLINE_MISSING_META_EVIDENCE")
            cases.append(check_meta(case, root, verify_offline_slice))
            continue
        mandatory = [
            f"{case}/{name}"
            for name in [
                "readback.json",
                "timings.json",
                "sources.json",
                "module-hashes.json",
                "run/context.json",
                "run/run.sqlite3",
                "browser/identity.json",
                "reader/identity.json",
                "browser/termination.json",
                "reader/termination.json",
                "backend.json",
            ]
        ]
        if not set(mandatory).issubset(names):
            raise ValueError("E_OFFLINE_MISSING_READER_EVIDENCE")
        if json.loads(_read(directory / "sources.json")) != current:
            raise ValueError("E_OFFLINE_SOURCE_STALE")
        modules = json.loads(_read(directory / "module-hashes.json"))
        extension = directory / "offline-extension"
        actual_modules = {
            str(p.relative_to(extension)): hashlib.sha256(_read(p)).hexdigest()
            for p in extension.rglob("*")
            if p.is_file()
        }
        if modules != actual_modules or modules != expected_modules:
            raise ValueError("E_OFFLINE_BROWSER_MODULES")
        context = json.loads(_read(directory / "run/context.json"))
        if (
            context["code_sha256"] != tree_hash
            or context["vendor_sha256"] != provenance["vendor_sha256"]
        ):
            raise ValueError("E_OFFLINE_SOURCE_BINDING")
        writer = json.loads(_read(directory / "browser/identity.json"))
        reader = json.loads(_read(directory / "reader/identity.json"))
        if (
            writer["pid"] == reader["pid"]
            or writer["document"]["origin"] != provenance["extension_origin"]
            or reader["document"]["origin"] != context["allowed_extension_origin"]
            or reader["binary_sha256"] != provenance["browser_sha256"]
            or writer["binary_sha256"] != provenance["browser_sha256"]
            or writer["version"]["product"] != provenance["browser_version"]
            or reader["version"]["product"] != provenance["browser_version"]
        ):
            raise ValueError("E_OFFLINE_BROWSER_IDENTITY")
        for name in ["browser", "reader"]:
            termination = json.loads(_read(directory / name / "termination.json"))
            if (
                termination["method"] != "SIGKILL_PROCESS_GROUP"
                or termination["returncode"] != -9
                or termination["graceful"]
            ):
                raise ValueError("E_OFFLINE_CRASH_EVIDENCE")
        probe = OfflineBrowser(
            root / "verification" / str(uuid4()) / case,
            extension,
            context["allowed_extension_origin"],
            browser_path,
            profile=directory / "browser/profile",
        )
        try:
            reopened = probe.command({"operation": "INIT", "context": context, "credentials": []})
        finally:
            probe.close()
        if reopened.get("status") != "OK":
            raise ValueError("E_OFFLINE_STORAGE_CHANGED")
        previous = json.loads(_read(directory / "readback.json"))["reader"]
        if reopened["state"] != previous["state"] or reopened["retained"] != previous["retained"]:
            raise ValueError("E_OFFLINE_STORAGE_CHANGED")
        replay_target = verification / case / "replay"
        if case == "OFF-16":
            try:
                verify_replay_equivalence(directory / "run", replay_target)
            except (ValueError, OSError):
                pass
            else:
                raise ValueError("E_OFFLINE_MISSING_RAW_ACCEPTED")
        else:
            verify_replay_equivalence(directory / "run", replay_target)
        cases.append(assert_case(case, directory / "run"))
    full = provenance["scenario_id"] == "acceptance"
    if result["OFFLINE_SLICE_PASS"] != ("YES" if full else "NO"):
        raise ValueError("E_OFFLINE_FORGED_PASS")
    if source_hashes() != current:
        raise ValueError("E_OFFLINE_SOURCE_STALE")
    verified = gate_view(result, cases)
    if (root / result["diagnostic"]["relative_path"]).read_text() != render_diagnostic(verified):
        raise ValueError("E_OFFLINE_DIAGNOSTIC_BINDING")
    return verified


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_offline_slice(args.input)
    except Exception:
        print("E_OFFLINE_GATE_REJECTED", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
