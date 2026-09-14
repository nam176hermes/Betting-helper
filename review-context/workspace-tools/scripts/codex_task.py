#!/usr/bin/env python3
"""Bounded Codex task packets, launch defaults, and local evidence. Stdlib only."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
AXES = ("ambiguity", "blast_radius", "failure_cost", "coupling", "novelty", "safety")
CRITICAL = {
    "live",
    "financial",
    "credentials",
    "authentication",
    "persistence",
    "recovery",
    "checkpoint",
    "concurrency",
    "idempotency",
    "kill_switch",
    "order_state",
    "state_ownership",
    "irreversible_migration",
}
AREAS = {
    "docs": 0,
    "mechanical": 0,
    "extension_ui": 1,
    "subsystem": 2,
    "workflow_tooling": 2,
    "shared_infrastructure": 3,
    "schema": 3,
    "clock": 3,
    "persistence": 3,
    "recovery": 3,
    "security": 4,
    "authority": 4,
    "release": 4,
}
MODELS = {
    "MECHANICAL": ("gpt-5.6-luna", "low"),
    "NORMAL": ("gpt-5.6-terra", "medium"),
    "COMPLEX": ("gpt-5.6-sol", "medium"),
    "CRITICAL": ("gpt-6-astra", "high"),
}
POLICY = """CODEX_WORKFLOW_POLICY_V2
Use the exact packet CWD, scope, HEAD/dirty ownership and required checks.
Read only relevant files/ranges; reuse unchanged facts. Repeat only for changed
inputs/state/environment, insufficient output, a new hypothesis, or required fresh evidence.
Before retry record previous attempt, new information and reason. Keep full logs by path;
normal tool output <=2000 tokens and final output <=2000 characters unless the task needs more.
No worker-created agents. Coordinator default is 0-2 independent workers; greater fan-out
needs a recorded reason. Dispatch independent work, do useful work, then collect when needed;
use one completion wait up to 60s, not repeated short status checks. Do not narrate empty waits.
Use the risk route and minimum verification plan. Critical risk never becomes mechanical
because the patch is small. Frozen decisions may reduce implementation effort, never checks.
Preserve authority, required independent reviews, negative tests and source-bound freshness.
No live/provider/credential access, signing, deployment, remote writes or formal review launch
is granted by this packet. Report HOLD for missing prerequisites. Formal A/B roles stay separate.
Return FINDING, EVIDENCE, IMPACT, ACTION, OPEN ISSUE; facts/checks are valid only for bound inputs.
"""
CODE_WORK = Path(
    "/mnt/c/Users/thenam/.codex/plugins/cache/openai-curated-remote/codex-engineering-guardrails/1.1.1/skills/code-work/SKILL.md"
)
MN_POLICY = """CODEX_WORKFLOW_POLICY_V3_MN
The bootstrap below freshly checked Git and applicable instruction presence. Reuse it; do not rescan
unchanged Git/AGENTS. Preflight checks are bound evidence: a failed precheck demonstrates the defect.
Do not rerun that precheck before changing its inputs; perform the post-change check.
No child agents. Read scoped ranges; retry only for changed inputs/environment, insufficient
output, a new hypothesis or required fresh evidence, recording previous attempt and reason.
Keep complete logs by path; normal tool output <=2000 tokens. Use one brief start update,
then material progress or required skill announcements. Final: FINDING / EVIDENCE / ACTION /
RESULT / OPEN ISSUE, normally five short lines; retain material failures and requested detail.
Authority is not granted by a packet. Preserve user-owned work, all required tests/reviews,
negative vectors and source-bound freshness. Missing prerequisites stay HOLD. Stop and
escalate newly discovered critical risk; critical work requires full C/D context and V3/V4.
"""
SERENA_HINT = """Known capabilities (use when available; all other required tools/skills remain available):
mcp__serena__initial_instructions({}); mcp__serena__activate_project({project:CWD});
mcp__serena__find_symbol({relative_path, name_path_pattern, include_body:true});
mcp__serena__find_referencing_symbols({relative_path, name_path}).
Initialize and activate sequentially in one exec, then read the returned manual before semantic work. Return one MCP text
representation, not both content and structured_content. Use direct symbol/body and caller
queries for named symbols; overview is only needed when names are unknown. Batch independent
queries and focused checks once prerequisites are satisfied; inspect every result.
If a tool name is unavailable, search ALL_TOOLS by NAME only and return at most eight NAMES,
never entire descriptions/catalogs. Do not skip mandatory skills, symbol checks or failing-test
reproduction to meet output targets. The complete skill below is already loaded from its
source path/hash; read it here instead of requesting the same unchanged file again.
"""
REQUIRED = {
    "task",
    "expected_output",
    "cwd",
    "target_head",
    "dirty_ownership",
    "files",
    "constraints",
    "known_verified_facts",
    "authority",
    "required_checks",
    "do_not_reread",
    "exit_condition",
    "risk",
    "areas",
    "role",
}
REASONS = {
    "changed_inputs",
    "changed_state",
    "insufficient_output",
    "different_environment",
    "fresh_evidence",
    "contract_rerun",
    "new_hypothesis",
}
BRIDGE = """\n<!-- codex-workflow:begin -->
## Codex operating defaults

Use `/home/thenam176/betting-helper/scripts/codex_task.py` for bounded launch/resume packets.
An injected `CODEX_WORKFLOW_POLICY_` supplies the operating rules once. Without a packet:
use 0-2 independent workers, scoped reads, evidence-based retries and targeted checks first.
Existing authority/HOLD, critical-risk verification and independent-review rules still govern.
Full workflow on demand: `/home/thenam176/betting-helper/docs/codex/workflow.md`.
<!-- codex-workflow:end -->
"""
BRIDGES = (
    "discovery-runtime-v6.3.6/AGENTS.md",
    "hybrid-discovery-v6.3.6-authoring/AGENTS.md",
    "authoring-controller-config-worktree/AGENTS.md",
)


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        fail("JSON object required")
    return dict(data)


def save(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Per-task state has one owner. Batch rejects shared state paths.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def digest(path: Path) -> str:
    if not path.is_file():
        return "ABSENT"
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if proc.returncode and args != ("rev-parse", "--verify", "HEAD"):
        fail("Git inspection failed: " + " ".join(args))
    return proc.stdout.rstrip("\n") if proc.returncode == 0 else "UNBORN"


def scoped(cwd: Path, name: str) -> Path:
    path = (cwd / name).resolve()
    if path == cwd or not path.is_relative_to(cwd):
        fail("File is outside exact CWD: " + name)
    if any(part in {".git", ".env"} for part in path.relative_to(cwd).parts):
        fail("Private/Git internals are not task context")
    if path.is_dir():
        fail("Scope must name files, not directories")
    return path


def snapshot(packet: dict[str, Any]) -> dict[str, Any]:
    cwd = Path(packet["cwd"]).resolve(strict=True)
    git_root = Path(git(cwd, "rev-parse", "--show-toplevel"))
    hierarchy: list[Path] = []
    cursor = cwd
    while cursor.is_relative_to(git_root):
        hierarchy.extend(cursor / name for name in ("AGENTS.md", "AGENTS.override.md"))
        if cursor == git_root:
            break
        cursor = cursor.parent
    # Byte bindings detect stale local guidance; renderer probes establish actual loading.
    config_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    hierarchy.extend(
        config_home / name
        for name in ("AGENTS.md", "AGENTS.override.md", "config.toml")
    )
    hierarchy.extend([ROOT / "docs/codex/workflow.md", Path(__file__).resolve()])
    if route(packet)["class"] == "NORMAL" and packet["role"] == "implementation":
        hierarchy.append(CODE_WORK)
    return {
        "instructions": {str(path): digest(path) for path in hierarchy},
        "cwd": str(cwd),
        "git_root": git(cwd, "rev-parse", "--show-toplevel"),
        "head": git(cwd, "rev-parse", "--verify", "HEAD"),
        "dirty": git(cwd, "status", "--porcelain=v1", "--untracked-files=normal"),
        "files": {name: digest(scoped(cwd, name)) for name in packet["files"]},
    }


def route(packet: dict[str, Any]) -> dict[str, Any]:
    risk = packet["risk"]
    if not isinstance(risk, dict) or set(risk) != set(AXES) | {"critical_flags"}:
        fail("Risk needs six axes (0..2) and explicit critical_flags")
    if any(type(risk[k]) is not int or risk[k] not in range(3) for k in AXES):
        fail("Risk axes must be integers 0..2")
    flags = risk["critical_flags"]
    if not isinstance(flags, list) or any(x not in CRITICAL for x in flags):
        fail("Unknown critical flag")
    areas = packet["areas"]
    if not isinstance(areas, list) or not areas or any(x not in AREAS for x in areas):
        fail("Explicit known areas required")
    if (
        flags
        or risk["safety"]
        or risk["failure_cost"] == 2
        or any(
            x in areas
            for x in ("security", "authority", "persistence", "recovery", "clock")
        )
    ):
        classification = "CRITICAL"
    elif max(risk[k] for k in AXES) == 2 or sum(risk[k] for k in AXES) >= 5:
        classification = "COMPLEX"
    elif sum(risk[k] for k in AXES) or any(AREAS[x] >= 2 for x in areas):
        classification = "NORMAL"
    else:
        classification = "MECHANICAL"
    model, effort = MODELS[classification]
    if packet["role"] == "coordinator":
        model = "gpt-6-astra"
        effort = {"COMPLEX": "medium", "CRITICAL": "high"}.get(classification, "low")
    if classification == "COMPLEX" and (risk["ambiguity"] == 2 or risk["novelty"] == 2):
        model = "gpt-6-astra"
    floor = max(AREAS[x] for x in areas)
    if classification == "CRITICAL":
        floor = max(floor, 3)
    if set(flags) & {"live", "financial"}:
        floor = max(floor, 4)
    transition = "initial risk route"
    decision = packet.get("frozen_decision")
    if decision is not None:
        if (
            packet["role"] != "implementation"
            or not isinstance(decision, dict)
            or not decision.get("evidence")
            or decision.get("open_questions") != []
            or decision.get("deterministic_implementation") is not True
        ):
            fail(
                "De-escalation needs an implementation role and resolved, evidenced decision"
            )
        if classification not in {"COMPLEX", "CRITICAL"}:
            fail("Only complex/critical decisions need de-escalation")
        evidence = decision["evidence"]
        if (
            not isinstance(evidence, dict)
            or not evidence.get("path")
            or digest(scoped(Path(packet["cwd"]), evidence["path"]))
            != evidence.get("sha256")
            or evidence.get("sha256") == "ABSENT"
        ):
            fail("Frozen decision evidence must match a scoped file hash")
        model, effort = "gpt-5.6-sol", "medium"
        transition = (
            "de-escalated implementation only; risk and verification floor unchanged"
        )
    return {
        "class": classification,
        "model": model,
        "reasoning": effort,
        "minimum_verification": "V" + str(floor),
        "transition": transition,
        "required_review": classification == "CRITICAL" or floor == 4,
    }


def validate(packet: dict[str, Any], initial: bool = True) -> dict[str, Any]:
    if REQUIRED - packet.keys():
        fail("Missing packet fields: " + ", ".join(sorted(REQUIRED - packet.keys())))
    if len(json.dumps(packet)) > 16000:
        fail("Packet exceeds 16000 characters; reference large artifacts by path")
    for key in (
        "task",
        "expected_output",
        "cwd",
        "target_head",
        "authority",
        "exit_condition",
    ):
        if not isinstance(packet[key], str) or not packet[key].strip():
            fail("Nonempty string required: " + key)
    for key in ("files", "constraints", "known_verified_facts", "do_not_reread"):
        if not isinstance(packet[key], list) or any(
            not isinstance(v, str) for v in packet[key]
        ):
            fail("String list required: " + key)
    if not packet["files"] or len(packet["files"]) > 40:
        fail("Name 1..40 relevant files; split broad tasks")
    if packet["role"] not in {
        "coordinator",
        "implementation",
        "review",
        "formal",
        "analysis",
    }:
        fail("Unknown role")
    if not isinstance(packet["dirty_ownership"], dict) or any(
        not isinstance(v, str) or not v.strip()
        for v in packet["dirty_ownership"].values()
    ):
        fail("dirty_ownership must map dirty paths to owners")
    checks = packet["required_checks"]
    if not isinstance(checks, list) or not checks:
        fail("At least one explicit check is required")
    ids: set[str] = set()
    for check in checks:
        if not isinstance(check, dict) or not {"id", "argv", "tier"} <= check.keys():
            fail("Each check needs id, argv, tier")
        if (
            not isinstance(check["id"], str)
            or not check["id"].isalnum()
            or check["id"] in ids
        ):
            fail("Unique alphanumeric check id required")
        ids.add(check["id"])
        if (
            not isinstance(check["argv"], list)
            or not check["argv"]
            or any(not isinstance(v, str) or not v for v in check["argv"])
        ):
            fail("Check argv must be a nonempty string array, never shell text")
        if (
            type(check.get("timeout", 1200)) is not int
            or not 1 <= check.get("timeout", 1200) <= 3600
        ):
            fail("Check timeout must be 1..3600 seconds")
        if check["tier"] not in {"V0", "V1", "V2", "V3", "V4"}:
            fail("Check tier must be V0..V4")
        if any(
            restricted in " ".join(check["argv"]).lower()
            for restricted in ("--password", "--token", "--api-key", "--secret")
        ):
            fail("Do not place credentials in command packets/logs")
    current = snapshot(packet)
    if initial and current["head"] != packet["target_head"]:
        fail("HOLD: target HEAD changed")
    dirty = set()
    for line in current["dirty"].splitlines():
        # Porcelain's quoted/renamed paths require exact caller acknowledgment.
        dirty.add(line[3:])
    if initial and dirty != set(packet["dirty_ownership"]):
        fail("HOLD: dirty ownership does not match current Git status")
    return current


def prepare(packet_path: Path, state_path: Path) -> dict[str, Any]:
    packet = load(packet_path)
    current = validate(packet)
    plan = route(packet)
    if state_path.exists():
        fail("State already exists; resume it or choose a new task state")
    state = {
        "packet": packet,
        "state_path": str(state_path.resolve()),
        "packet_path": str(packet_path.resolve()),
        "packet_hash": digest(packet_path),
        "snapshot": current,
        "route": plan,
        "attempts": [],
        "reads": [],
    }
    save(state_path, state)
    return {"state": str(state_path.resolve()), "snapshot": current, "route": plan}


def task_state(path: Path) -> dict[str, Any]:
    state = load(path)
    source = Path(state["packet_path"])
    if digest(source) != state["packet_hash"] or load(source) != state["packet"]:
        fail("Prepared packet changed; prepare a new task")
    validate(state["packet"], initial=False)
    if route(state["packet"]) != state["route"]:
        fail("Stored route changed")
    return state


def legacy_prompt(state: dict[str, Any]) -> str:
    return (
        POLICY
        + "\nTASK PACKET\n"
        + json.dumps(state["packet"], indent=2)
        + (
            "\nVERIFIED BOOTSTRAP (do not rediscover unchanged state)\n"
            + json.dumps(state["snapshot"], sort_keys=True)
            + "\nROUTE\n"
            + json.dumps(state["route"], sort_keys=True)
            + "\nLOCAL EVIDENCE COMMANDS (when the task permits tools):\n"
            + "Use the helper's read/check commands so reuse and attempts are recorded. "
            + "Helper: "
            + str(Path(__file__).resolve())
            + "; --state "
            + str(state["state_path"])
            + ". Invoke each required check by its id through check; this runs its argv once."
        )
    )


def prompt(state: dict[str, Any]) -> str:
    """M/N deduplicate representation; C/D retain Phase 2 context byte for byte."""
    if state["route"]["class"] not in {"MECHANICAL", "NORMAL"}:
        return legacy_prompt(state)
    packet = state["packet"]
    target = {
        "verified_by": "prepare: fresh Git state and instruction presence checked",
        "cwd_is_git_root": state["snapshot"]["cwd"] == state["snapshot"]["git_root"],
        "repo_instruction_files": {
            p: h
            for p, h in state["snapshot"].get("instructions", {}).items()
            if Path(p).is_relative_to(Path(state["snapshot"]["git_root"]))
            and Path(p).name in {"AGENTS.md", "AGENTS.override.md"}
            and h != "ABSENT"
        },
        "cwd": packet["cwd"],
        "head": packet["target_head"],
        "dirty_ownership": packet["dirty_ownership"],
        "files": state["snapshot"]["files"],
    }
    context = {
        "task": packet["task"],
        "expected_output": packet["expected_output"],
        "target": target,
        "role": packet["role"],
        "authority": packet["authority"],
        "required_checks": packet["required_checks"],
        "route": state["route"],
        "exit_condition": packet["exit_condition"],
    }
    for key in (
        "constraints",
        "known_verified_facts",
        "do_not_reread",
        "decisions",
        "unresolved_questions",
    ):
        if packet.get(key):
            context[key] = packet[key]
    latest = {a["id"]: a for a in state.get("attempts", [])}
    context["preflight_checks"] = [
        {k: a[k] for k in ("id", "exit", "log", "tail")}
        for a in latest.values()
        if a["fingerprint"]["inputs"] == state["snapshot"]
    ]
    context["check_command_prefix"] = (
        shlex.join(
            [
                "python3",
                str(Path(__file__).resolve()),
                "check",
                "--state",
                str(state["state_path"]),
            ]
        )
        + " CHECK_ID"
    )
    result = (
        MN_POLICY
        + "\nTASK CONTEXT\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )
    result += (
        "\nEvidence helper: "
        + str(Path(__file__).resolve())
        + "; --state "
        + str(state["state_path"])
    )
    result += ". Run required checks by id through check when permitted; state stores full bindings and attempts."
    if state["route"]["class"] == "NORMAL" and packet["role"] == "implementation":
        skill = CODE_WORK.read_text()
        result += (
            "\n"
            + SERENA_HINT
            + "\nLOADED REQUIRED SKILL "
            + str(CODE_WORK)
            + " SHA256="
            + digest(CODE_WORK)
            + "\n"
            + skill
        )
    return result


def retry_reason(args: argparse.Namespace) -> dict[str, str] | None:
    if not args.reason:
        return None
    if args.reason not in REASONS or not args.new_information:
        fail("Retry needs an allowed reason and new_information")
    return {"reason": args.reason, "new_information": args.new_information}


def read_file(
    state_path: Path,
    name: str,
    start: int,
    end: int,
    reason: dict[str, str] | None = None,
) -> dict[str, Any]:
    state = task_state(state_path)
    if (
        name not in state["packet"]["files"]
        or start < 1
        or end < start
        or end - start >= 200
    ):
        fail("Read must name a scoped file and at most 200 lines")
    path = scoped(Path(state["snapshot"]["cwd"]), name)
    key = {"file": name, "sha256": digest(path), "start": start, "end": end}
    if key in state["reads"] and not reason:
        return {"reused": True, "evidence": key, "action": "Use prior unchanged read"}
    with path.open() as stream:
        lines = itertools.islice(stream, start - 1, end)
        text = "".join(f"{n}: {line[:8000]}" for n, line in enumerate(lines, start))
    state["reads"].append(key)
    save(state_path, state)
    return {"evidence": key, "text": text[:8000], "truncated": len(text) > 8000}


def check(
    state_path: Path, check_id: str, reason: dict[str, str] | None = None
) -> dict[str, Any]:
    state = task_state(state_path)
    spec = next(
        (c for c in state["packet"]["required_checks"] if c["id"] == check_id), None
    )
    if spec is None:
        fail("Unknown required check")
    before = snapshot(state["packet"])
    fingerprint = {
        "inputs": before,
        "argv": spec["argv"],
        "python": sys.version,
        "platform": sys.platform,
        "environment": state["packet"].get("environment", ""),
    }
    previous = next(
        (a for a in reversed(state["attempts"]) if a["fingerprint"] == fingerprint),
        None,
    )
    if previous and not reason:
        fail(
            "Repeated unchanged check: record previous attempt, new information and retry reason"
        )
    log = state_path.with_name(
        f"{state_path.stem}-{check_id}-{len(state['attempts'])}.log"
    )
    with log.open("w") as stream:
        try:
            proc = subprocess.run(
                spec["argv"],
                cwd=before["cwd"],
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=min(int(spec.get("timeout", 1200)), 3600),
            )
            code: int | None = proc.returncode
        except subprocess.TimeoutExpired:
            code = None
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 2000))
        tail = stream.read().decode(errors="replace")
    result = {
        "id": check_id,
        "tier": spec["tier"],
        "exit": code,
        "log": str(log.resolve()),
        "log_bytes": log.stat().st_size,
        "tail": tail,
        "fingerprint": fingerprint,
        "retry": reason,
        "previous_attempt": previous["log"] if previous else None,
    }
    state["attempts"].append(result)
    save(state_path, state)
    return result


def resume(state_path: Path) -> dict[str, Any]:
    state = task_state(state_path)
    if snapshot(state["packet"]) != state["snapshot"]:
        fail(
            "HOLD: resume facts are stale; create a new packet with current state and revalidated facts"
        )
    latest = {a["id"]: a for a in state["attempts"]}
    completed = [
        key
        for key, a in latest.items()
        if a["exit"] == 0 and a["fingerprint"]["inputs"] == state["snapshot"]
    ]
    return {
        "valid": True,
        "exact_target": state["snapshot"]["cwd"],
        "head": state["snapshot"]["head"],
        "dirty_ownership": state["packet"]["dirty_ownership"],
        "task_status": state["packet"].get("task_status", "IN_PROGRESS"),
        "verified_facts": state["packet"]["known_verified_facts"],
        "decisions": state["packet"].get("decisions", []),
        "files_already_inspected": state["reads"],
        "completed_checks": completed,
        "remaining_checks": [
            c["id"]
            for c in state["packet"]["required_checks"]
            if c["id"] not in completed
        ],
        "unresolved_questions": state["packet"].get("unresolved_questions", []),
        "validity": "Exact bound HEAD, dirty state, scoped bytes and instruction hashes only",
    }


def close(state_path: Path) -> dict[str, Any]:
    state = task_state(state_path)
    current = snapshot(state["packet"])
    latest = {a["id"]: a for a in state["attempts"]}
    passed = {
        key: a
        for key, a in latest.items()
        if a["exit"] == 0 and a["fingerprint"]["inputs"] == current
    }
    # Tier labels are operator plans, not proof of contract completeness.
    # Only the governed controller can qualify V3/V4 or independent review.
    missing = [
        c["id"] for c in state["packet"]["required_checks"] if c["id"] not in passed
    ]
    highest = max((int(a["tier"][1]) for a in passed.values()), default=-1)
    floor = int(state["route"]["minimum_verification"][1])
    # This tool cannot issue formal readiness or attest independent review.
    review = state["route"]["required_review"] or floor >= 3
    return {
        "local_checks": "PASS" if not missing else "HOLD",
        "missing_checks": missing,
        "qualification": "HOLD"
        if missing or highest < floor or review
        else "LOCAL_PLAN_PASS",
        "required_review": review,
        "minimum_verification": "V" + str(floor),
        "authority": "NONE",
    }


def launch(
    state_path: Path, binary: str, resume_id: str | None = None
) -> dict[str, Any]:
    state = task_state(state_path)
    resume(state_path)  # Fresh packet/policy on new launches and resumes alike.
    if state["packet"]["role"] == "formal":
        fail("HOLD: formal reviews use the separately authorized signed launcher")
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=True, timeout=20
    ).stdout.strip()
    if state["route"]["model"] == "gpt-6-astra":
        numbers = version.split()[-1].split(".")
        if tuple(int(x) for x in numbers[:3]) < (0, 153, 0):
            fail(
                "Astra requires a newer executable here; choose the existing desktop binary, never silently downgrade"
            )
    mode = (
        "workspace-write"
        if state["packet"]["role"] == "implementation"
        else "read-only"
    )
    argv = [
        binary,
        "exec",
        "--json",
        "-s",
        mode,
        "-C",
        state["snapshot"]["cwd"],
        "-m",
        state["route"]["model"],
        "-c",
        'model_reasoning_effort="' + state["route"]["reasoning"] + '"',
        "-c",
        'model_verbosity="low"',
        "--disable",
        "multi_agent",
        "--disable",
        "multi_agent_v2",
    ]
    if resume_id:
        argv += ["resume", resume_id]
    argv += ["-"]
    event_path = state_path.with_suffix(".events.jsonl")
    error_path = state_path.with_suffix(".stderr")
    if event_path.exists():
        fail(
            "Launch transcript already exists; use a separate state for another attempt"
        )
    with event_path.open("w") as stdout, error_path.open("w") as stderr:
        proc = subprocess.run(
            argv,
            input=prompt(state),
            text=True,
            stdout=stdout,
            stderr=stderr,
            check=False,
            timeout=1800,
        )
    return {
        "exit": proc.returncode,
        "model": state["route"]["model"],
        "reasoning": state["route"]["reasoning"],
        "codex_version": version,
        "events": str(event_path),
        "stderr": str(error_path),
    }


def batch(
    paths: list[Path], binary: str, workers: int, justification: str
) -> list[dict[str, Any]]:
    if workers < 1 or workers > 8 or (workers > 2 and not justification.strip()):
        fail(
            "Default 1..2 workers; >2 needs explicit independent-workstream justification"
        )
    if len({p.resolve() for p in paths}) != len(paths):
        fail("State ownership overlaps")
    owned: set[Path] = set()
    write_roots: set[str] = set()
    for path in paths:
        state = task_state(path)
        if state["packet"].get("independent") is not True:
            fail("Each batch workstream must declare independence")
        if state["packet"]["role"] == "implementation":
            root = state["snapshot"]["git_root"]
            if root in write_roots:
                fail("Parallel implementation needs separate Git roots/worktrees")
            write_roots.add(root)
            files = {
                scoped(Path(state["snapshot"]["cwd"]), f)
                for f in state["packet"]["files"]
            }
            if files & owned:
                fail("Parallel write scopes overlap")
            owned |= files
    # Blocking futures deliver completions, without model-visible polling.
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(launch, p, binary) for p in paths]
        return [f.result() for f in concurrent.futures.as_completed(futures)]


def bridge(check_only: bool) -> dict[str, Any]:
    changed = []
    for name in BRIDGES:
        path = ROOT / name
        old = path.read_text() if path.exists() else ""
        begin, end = "<!-- codex-workflow:begin -->", "<!-- codex-workflow:end -->"
        if begin in old or end in old:
            if (
                old.count(begin) != 1
                or old.count(end) != 1
                or old.index(begin) > old.index(end)
            ):
                fail("Malformed bridge markers: " + name)
            expected = re.sub(
                re.escape(begin) + r".*?" + re.escape(end),
                lambda _: BRIDGE.strip(),
                old,
                flags=re.DOTALL,
            )
        else:
            expected = old.rstrip() + "\n" + BRIDGE
        if old != expected:
            changed.append(name)
            if not check_only:
                path.write_text(expected)
    return {"status": "FAIL" if changed and check_only else "PASS", "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--packet", type=Path, required=True)
    prep.add_argument("--state", type=Path, required=True)
    for name in ("prompt", "resume", "close", "read", "check", "launch"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--state", type=Path, required=True)
        if name in ("read", "check"):
            cmd.add_argument("--reason", choices=sorted(REASONS))
            cmd.add_argument("--new-information")
        if name == "read":
            cmd.add_argument("file")
            cmd.add_argument("--start", type=int, default=1)
            cmd.add_argument("--end", type=int, default=100)
        if name == "check":
            cmd.add_argument("check_id")
        if name == "launch":
            cmd.add_argument("--codex", default="codex")
            cmd.add_argument("--resume-id")
    cmd = sub.add_parser("batch")
    cmd.add_argument("states", nargs="+", type=Path)
    cmd.add_argument("--codex", default="codex")
    cmd.add_argument("--workers", type=int, default=2)
    cmd.add_argument("--justification", default="")
    cmd = sub.add_parser("bridge")
    cmd.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result: dict[str, Any] | list[dict[str, Any]]
    try:
        if args.command == "prepare":
            result = prepare(args.packet, args.state)
        elif args.command == "prompt":
            print(prompt(task_state(args.state)))
            return 0
        elif args.command == "resume":
            result = resume(args.state)
        elif args.command == "close":
            result = close(args.state)
        elif args.command == "read":
            result = read_file(
                args.state, args.file, args.start, args.end, retry_reason(args)
            )
        elif args.command == "check":
            result = check(args.state, args.check_id, retry_reason(args))
        elif args.command == "launch":
            result = launch(args.state, args.codex, args.resume_id)
        elif args.command == "batch":
            result = batch(args.states, args.codex, args.workers, args.justification)
        else:
            result = bridge(args.check)
        display = result
        if args.command == "check" and isinstance(result, dict):
            display = {
                key: result[key]
                for key in (
                    "id",
                    "exit",
                    "log",
                    "log_bytes",
                    "tail",
                    "retry",
                    "previous_attempt",
                )
            }
        print(json.dumps(display, indent=2))
        if isinstance(result, dict):
            if result.get("status") == "FAIL":
                return 1
            if args.command in {"check", "launch"}:
                return 0 if result.get("exit") == 0 else 1
            if args.command == "close":
                return 0 if result["qualification"] == "LOCAL_PLAN_PASS" else 2
        if isinstance(result, list):
            return 0 if all(item.get("exit") == 0 for item in result) else 1
        return 0
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(json.dumps({"status": "HOLD", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
