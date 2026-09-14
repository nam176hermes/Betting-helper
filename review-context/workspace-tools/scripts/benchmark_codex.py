#!/usr/bin/env python3
"""Opt-in, subscription-consuming safe paired benchmark; never touches production."""

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import codex_task as task

CASES: dict[str, Any] = {
    "mechanical": (
        {"README.md": "# Local sample\n\nOffline demonstration.\n"},
        "Change the README title to Offline sample. Preserve the remaining text.",
        ["docs"],
        {},
        "implementation",
        "from pathlib import Path; assert Path('README.md').read_text() == '# Offline sample\\n\\nOffline demonstration.\\n'",
    ),
    "normal": (
        {
            "validation.py": "def valid_port(value):\n    return isinstance(value, int) and 0 <= value <= 65535\n"
        },
        "Fix valid_port: accept integer ports 1..65535, reject booleans and other types. Keep the function API.",
        ["subsystem"],
        {"ambiguity": 1},
        "implementation",
        "from validation import valid_port; assert all(valid_port(x) for x in [1,80,65535]); assert all(not valid_port(x) for x in [True,False,0,-1,65536,'80',None,1.5])",
    ),
    "complex": (
        {
            "names.py": "def key(value):\n    return value.strip().lower()\n",
            "catalog.py": "from names import key\n\ndef lookup(rows, name):\n    return {key(k):v for k,v in rows}[key(name)]\n",
        },
        "Repair the cross-module lookup contract: Unicode casefold equivalence, surrounding whitespace ignored, collisions must raise ValueError, absent keys retain KeyError. Keep APIs; explain the collision decision briefly.",
        ["subsystem"],
        {"ambiguity": 2, "coupling": 2, "novelty": 1},
        "implementation",
        "from catalog import lookup; assert lookup([('Straße',7)],' STRASSE ')==7\ntry: lookup([('A',1),(' a ',2)],'a')\nexcept ValueError: pass\nelse: raise AssertionError('collision accepted')\ntry: lookup([],'missing')\nexcept KeyError: pass\nelse: raise AssertionError('missing accepted')",
    ),
    "critical": (
        {
            "ledger.py": "seen=set()\ndef execute(key, payload, send):\n    if key in seen: return 'duplicate'\n    send(payload)\n    seen.add(key)\n    return 'sent'\n"
        },
        "READ ONLY adversarial review of this synthetic ledger. Identify concrete failure modes and preserve HOLD. Return a JSON object as final answer: findings (array of {category,evidence,action}), qualification. Categories must be specific. No implementation or provider calls.",
        ["authority"],
        {
            "ambiguity": 2,
            "safety": 2,
            "critical_flags": ["idempotency", "concurrency", "recovery"],
        },
        "review",
        "from pathlib import Path; assert Path('ledger.py').read_text().startswith('seen=set()')",
    ),
}


def metrics(path: Path) -> dict[str, Any]:
    events = [
        json.loads(x)
        for x in path.read_text().splitlines()
        if x.strip().startswith("{")
    ]
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    commands = [
        i.get("command", "") for i in items if i.get("type") == "command_execution"
    ]
    texts = [i.get("text", "") for i in items if i.get("type") == "agent_message"]
    read_commands = [
        c
        for c in commands
        if any(x in c for x in ("cat ", "sed ", "rg ", "read_text", "head "))
    ]
    return {
        "host_turns": sum(e.get("type") == "turn.started" for e in events),
        "model_turns": "NOT AVAILABLE: exec JSONL does not expose every model request",
        "tool_calls": len(
            [
                i
                for i in items
                if i.get("type") not in {"agent_message", "reasoning", "error"}
            ]
        ),
        "commands": commands,
        "repeated_commands": len(commands) - len(set(commands)),
        "read_command_invocations": len(read_commands),
        "repeated_read_commands": len(read_commands) - len(set(read_commands)),
        "files_inspected": "NOT AVAILABLE: shell commands may combine reads",
        "spawns": sum(
            i.get("type") == "collab_tool_call" and i.get("tool") == "spawn_agent"
            for i in items
        ),
        "waits": sum(
            i.get("type") == "collab_tool_call" and "wait" in i.get("tool", "")
            for i in items
        ),
        "coordination_messages": sum(
            i.get("type") == "collab_tool_call" and i.get("tool") == "send_message"
            for i in items
        ),
        "text_and_command_output_bytes": sum(
            len(i.get("aggregated_output", "").encode())
            + len(i.get("text", "").encode())
            for i in items
        ),
        "output_bytes": sum(
            len(
                json.dumps(
                    {
                        k: v
                        for k, v in i.items()
                        if k in {"aggregated_output", "text", "result", "error"}
                    },
                    ensure_ascii=False,
                ).encode()
            )
            for i in items
        ),
        "measurement_scope": "Routed policy versus Astra/high Phase 1 baseline; bundled change, not a causal per-component comparison. Tool output counts include serialized MCP results.",
        "transcript_bytes": path.stat().st_size,
        "test_invocations_proxy": sum(
            len(
                re.findall(
                    r"(?:python3?|pytest)\s+(?:oracle\.py|-m\s+(?:pytest|unittest))", c
                )
            )
            + int("assert " in c and " <<" in c)
            for c in commands
        ),
        "retries_proxy": len(commands) - len(set(commands)),
        "usage": [e.get("usage") for e in events if e.get("usage")],
        "final": texts[-1] if texts else "",
        "session_id": next(
            (e.get("thread_id") for e in events if e.get("type") == "thread.started"),
            None,
        ),
    }


def run_case(name: str, variant: str, base: Path, binary: str) -> dict[str, Any]:
    files, request, areas, axes, role, oracle = CASES[name]
    directory = base / (name + "-" + variant)
    directory.mkdir()
    subprocess.run(["git", "init", "-q", str(directory)], check=True)
    for filename, content in files.items():
        (directory / filename).write_text(content)
    (directory / "oracle.py").write_text(oracle + "\n")
    subprocess.run(["git", "-C", str(directory), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(directory),
            "-c",
            "user.name=Benchmark",
            "-c",
            "user.email=benchmark@invalid",
            "commit",
            "-qm",
            "Synthetic fixture",
        ],
        check=True,
    )
    head = task.git(directory, "rev-parse", "HEAD")
    common = (
        request
        + "\nUse only this disposable repository. No network, credentials, dependencies, agents, or Git mutations. Inspect relevant files; run python3 oracle.py. Do not edit oracle.py. Keep the final answer concise."
    )
    packet = {
        "task": common,
        "expected_output": "Correct change or evidence-based review",
        "cwd": str(directory),
        "target_head": head,
        "dirty_ownership": {},
        "files": list(files) + ["oracle.py"],
        "constraints": ["Preserve oracle.py", "No production access"],
        "known_verified_facts": [
            "Synthetic disposable fixture; listed files are the complete relevant scope."
        ],
        "authority": "NONE",
        "required_checks": [
            {
                "id": "oracle",
                "argv": ["python3", "oracle.py"],
                "tier": "V0" if name == "mechanical" else "V2",
            }
        ],
        "do_not_reread": [],
        "exit_condition": "Oracle passes; review preserves HOLD",
        "risk": {**dict.fromkeys(task.AXES, 0), "critical_flags": [], **axes},
        "areas": areas,
        "role": role,
    }
    packet_path = base / (name + "-" + variant + ".packet.json")
    state = base / (name + "-" + variant + ".state.json")
    task.save(packet_path, packet)
    task.prepare(packet_path, state)
    if variant == "after":
        result = task.launch(state, binary)
        event_path = Path(result["events"])
        route = task.route(packet)
    else:
        event_path = base / (name + "-" + variant + ".events.jsonl")
        # Phase 1 defaults, same task/oracle; no deliberately wasteful instructions.
        guidance = (
            task.ROOT / "docs/codex/phase2-evidence/phase1-workflow.md"
        ).read_text()
        argv = [
            binary,
            "exec",
            "--json",
            "-s",
            "workspace-write" if role == "implementation" else "read-only",
            "-C",
            str(directory),
            "-m",
            "gpt-6-astra",
            "-c",
            'model_reasoning_effort="high"',
            "--disable",
            "multi_agent",
            "--disable",
            "multi_agent_v2",
            "-",
        ]
        with (
            event_path.open("w") as out,
            event_path.with_suffix(".stderr").open("w") as err,
        ):
            proc = subprocess.run(
                argv,
                input=common + "\nPhase 1 workflow guidance:\n" + guidance,
                text=True,
                stdout=out,
                stderr=err,
                timeout=900,
                check=False,
            )
        result = {"exit": proc.returncode}
        route = {
            "class": task.route(packet)["class"],
            "model": "gpt-6-astra",
            "reasoning": "high",
            "minimum_verification": task.route(packet)["minimum_verification"],
        }
    data = metrics(event_path)
    oracle_unchanged = (directory / "oracle.py").read_text() == oracle + "\n"
    check = subprocess.run(
        ["python3", "oracle.py"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )
    findings: str | dict[str, bool] = "NOT APPLICABLE"
    quality = check.returncode == 0 and oracle_unchanged and result["exit"] == 0
    if name == "critical":
        text = data["final"].lower()
        groups = {
            "concurrency": ["concurr", "race"],
            "crash_window": ["crash", "uncertain", "timeout", "ambiguous"],
            "durability": ["restart", "persist", "durab"],
            "payload_binding": ["payload", "different request", "key reuse"],
        }
        findings = {
            key: any(word in text for word in words) for key, words in groups.items()
        }
        quality = (
            quality
            and all(findings.values())
            and "hold" in text
            and all((directory / f).read_text() == v for f, v in files.items())
        )
    report = {
        "case": name,
        "variant": variant,
        "measurement": "MEASURED",
        "route": route,
        "metrics": data,
        "exit": result["exit"],
        "oracle_exit": check.returncode,
        "oracle_unchanged": oracle_unchanged,
        "external_oracle_invocations": 1,
        "quality": "PASS" if quality else "FAIL",
        "review_findings": findings,
        "actual_verification": "Synthetic local oracle only; no production V3/V4 qualification",
        "state": str(state),
    }
    task.save(base / (name + "-" + variant + ".result.json"), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--case", choices=sorted(CASES))
    parser.add_argument("--variant", choices=("before", "after"))
    args = parser.parse_args()
    if not args.run:
        parser.error(
            "Use --run to explicitly authorize one selected local model evaluation"
        )
    if not args.case or not args.variant:
        parser.error(
            "Select --case and --variant; reuse existing traces instead of running a matrix"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        parser.error("Output directory must be empty")
    result = run_case(args.case, args.variant, args.output, args.codex)
    print(
        json.dumps({k: result[k] for k in ("case", "variant", "quality", "exit")}),
        flush=True,
    )
    return int(result["quality"] != "PASS" or result["exit"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
