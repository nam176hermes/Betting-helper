# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("E_SELF_REVIEW_BINDING")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_runtime_self_review(
    governed_root: Path, repo0_receipt: Path, output_dir: Path
) -> dict[str, object]:
    root = json.loads(governed_root.read_text())
    receipt = json.loads(repo0_receipt.read_text())
    if not isinstance(root, dict) or not isinstance(receipt, dict):
        raise ValueError("E_SELF_REVIEW_BINDING")
    task_manifest = output_dir / "docs/tasks/task-manifest.v6.3.6.json"
    if (
        root.get("algorithm") != "HD636-GOVERNED-ROOT-SHA256-v1"
        or root.get("schema_version") != "governed-content-root/v1"
        or not isinstance(root.get("root_sha256"), str)
        or set(receipt) != {
            "schema_version",
            "production_authority",
            "baseline_commit",
            "baseline_tree",
            "baseline_file_root_sha256",
            "candidate_qualification_sha256",
            "candidate_command_evidence_sha256",
            "command_result_root",
            "baseline_registry_sha256",
            "toolchain_versions",
            "lockfile_hashes",
            "vendor_root_sha256",
            "normative_source_map_sha256",
            "normative_source_set_root",
            "normative_source_set_count",
        }
        or receipt.get("schema_version") != "repo0-baseline-receipt/v2"
        or receipt.get("production_authority") != "NONE"
    ):
        raise ValueError("E_SELF_REVIEW_BINDING")
    candidate = receipt.get("candidate_qualification_sha256")
    command_root = receipt.get("command_result_root")
    governed = root.get("root_sha256")
    if not all(
        isinstance(value, str) and len(value) == 64
        for value in (candidate, command_root, governed)
    ):
        raise ValueError("E_SELF_REVIEW_BINDING")
    record: dict[str, object] = {
        "schema_version": "runtime-self-review/v1",
        "governed_content_root": governed,
        "repo0_receipt_sha256": _sha256(repo0_receipt),
        "candidate_qualification_sha256": candidate,
        "task_manifest_sha256": _sha256(task_manifest),
        "command_result_root": command_root,
        "checks": [{"check_id": "NO_FUTURE_SEAL_IDENTITY", "result": "PASS"}],
        "authority_granted": "NONE",
    }
    if set(record) != {
        "schema_version",
        "governed_content_root",
        "repo0_receipt_sha256",
        "candidate_qualification_sha256",
        "task_manifest_sha256",
        "command_result_root",
        "checks",
        "authority_granted",
    }:
        raise ValueError("E_SELF_REVIEW_BINDING")
    output_dir.joinpath("SELF_REVIEW_REPORT.json").write_text(
        json.dumps(cast(Any, record), sort_keys=True, separators=(",", ":")) + "\n"
    )
    output_dir.joinpath("SELF_REVIEW_REPORT.md").write_text(
        "# Runtime self-review\n\n"
        f"Governed content root: `{governed}`.\n\n"
        "Authority granted: NONE.\n"
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--governed-root", type=Path)
    parser.add_argument("--repo0-receipt", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.input is not None and args.output is not None and args.output_dir is None:
        runtime_root = Path(__file__).resolve().parents[1]
        sys.path[:0] = [str(runtime_root), str(runtime_root / "src")]
        from moj_discovery.review_aggregation import build_plan_self_review

        result = build_plan_self_review(json.loads(args.input.read_text()))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    elif all(
        value is not None
        for value in (args.governed_root, args.repo0_receipt, args.output_dir)
    ):
        result = build_runtime_self_review(args.governed_root, args.repo0_receipt, args.output_dir)
    else:
        parser.error("provide exactly one self-review mode")
        return
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
