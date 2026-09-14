#!/usr/bin/env python3
"""Offline context/usage decomposition of explicitly selected Codex rollouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def visible(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(visible(x) for x in value)
    if isinstance(value, dict):
        return str(value.get("text", ""))
    return ""


def measure(text: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text).strip()
    return {
        "bytes": len(text.encode()),
        "characters": len(text),
        "lines": len(text.splitlines()),
        "normalized_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
    }


def analyze(path: Path) -> dict[str, Any]:
    components: dict[str, Any] = {}
    records = []
    outputs = []
    calls = []
    narrative = []
    usage = {}
    packet = {}
    skill_names = []
    startup = True
    task_seen = False
    with path.open() as stream:
        for line_number, line in enumerate(stream, 1):
            data = json.loads(line)
            p = data.get("payload", {})
            typ = data["type"]
            if typ == "event_msg" and p.get("type") == "task_started":
                if task_seen:
                    break  # A later resume is a separate evaluation, not first-turn cost.
                task_seen = True
            if typ == "session_meta":
                components["model_base_instructions"] = measure(
                    visible(p.get("base_instructions", {}))
                )
                components["cli_version"] = p.get("cli_version")
            if typ == "turn_context":
                components["model"] = p.get("model")
                components["effort"] = p.get("effort")
            if typ == "token_usage_record":
                # Native records expose one response id, unlike exec's host-turn summary.
                usage[p["response_id"]] = {"line": line_number, "usage": p["usage"]}
            if typ != "response_item":
                continue
            kind = p.get("type")
            if kind == "message":
                text = visible(p.get("content", []))
                role = p.get("role")
                if role in {"user", "developer"} and startup:
                    name = f"{role}_line_{line_number}"
                    components[name] = measure(text)
                    records.append({"name": name, **measure(text)})
                    if "<skills_instructions>" in text:
                        skill = text.split("<skills_instructions>", 1)[1].split(
                            "</skills_instructions>", 1
                        )[0]
                        components["skill_section_inclusive"] = measure(skill)
                        catalog = skill.split("### Available skills", 1)[-1]
                        skill_names = re.findall(
                            r"^- ([^:\n]+(?::[^:\n]+)?):.*?\(file:",
                            catalog,
                            re.MULTILINE,
                        )
                        components["skill_catalog_subset"] = measure(catalog)
                    if "<recommended_plugins>" in text:
                        rec = text.split("<recommended_plugins>", 1)[1].split(
                            "</recommended_plugins>", 1
                        )[0]
                        components["recommended_plugins_subset"] = measure(rec)
                        components["recommended_plugin_count"] = len(
                            re.findall(r"^- ", rec, re.MULTILINE)
                        )
                        if "# AGENTS.md" in text:
                            agents = text.split("# AGENTS.md", 1)[1].split(
                                "<environment_context>", 1
                            )[0]
                            components["machine_agents_subset"] = measure(agents)
                    if text.startswith("PONYTAIL MODE"):
                        components["ponytail_body_subset"] = measure(text)
                    if text.startswith("CODEX_WORKFLOW_POLICY_V2"):
                        policy, rest = text.split("\nTASK PACKET\n", 1)
                        packet_text, tail = rest.split("\nVERIFIED BOOTSTRAP", 1)
                        packet = json.loads(packet_text)
                        components["injected_policy_subset"] = measure(policy)
                        components["task_packet_subset"] = measure(packet_text)
                        components["bootstrap_route_subset"] = measure(tail)
                        components["task_prompt"] = measure(text)
                    elif text.startswith("CODEX_WORKFLOW_POLICY_V3_MN"):
                        policy, rest = text.split("\nTASK CONTEXT\n", 1)
                        packet_text, tail = rest.split("\nEvidence helper:", 1)
                        packet = json.loads(packet_text)
                        components["injected_policy_subset"] = measure(policy)
                        components["task_packet_subset"] = measure(packet_text)
                        components["helper_capability_skill_subset"] = measure(tail)
                        components["task_prompt"] = measure(text)
                        if "\nLOADED REQUIRED SKILL " in tail:
                            components["preloaded_required_skill_subset"] = measure(
                                tail.split("\nLOADED REQUIRED SKILL ", 1)[1]
                            )
                    elif "Phase 1 workflow guidance:" in text:
                        task, guidance = text.split("Phase 1 workflow guidance:", 1)
                        components["task_prompt"] = measure(text)
                        components["task_specific_prefix_subset"] = measure(task)
                        components["frozen_workflow_subset"] = measure(guidance)
                elif role == "assistant":
                    startup = False
                    narrative.append(
                        {
                            "line": line_number,
                            "channel": p.get("channel"),
                            **measure(text),
                        }
                    )
            elif kind in {"custom_tool_call", "function_call"}:
                startup = False
                call = visible(p.get("input", p.get("arguments", "")))
                calls.append(
                    {
                        "line": line_number,
                        "name": p.get("name"),
                        **measure(call),
                        "catalog_search": "ALL_TOOLS" in call,
                    }
                )
            elif kind in {"custom_tool_call_output", "function_call_output"}:
                text = visible(p.get("output", p.get("content", [])))
                entry = {"line": line_number, **measure(text)}
                discovered = []
                value = p.get("output", [])
                for part in value if isinstance(value, list) else []:
                    block = visible(part)
                    if block.startswith('[{"name"'):
                        descriptors = json.loads(block)
                        discovered = [
                            {
                                "name": x["name"],
                                "description_bytes": len(
                                    x.get("description", "").encode()
                                ),
                            }
                            for x in descriptors
                        ]
                if discovered:
                    entry["discovered_tools"] = discovered
                entry["contains_code_work_body"] = "# Code Work" in text
                entry["contains_serena_manual"] = "<serena>" in text
                outputs.append(entry)
    packets = {
        k: measure(json.dumps(v, ensure_ascii=False, separators=(",", ":")))
        for k, v in packet.items()
    }
    values = list(usage.values())
    total = {
        k: sum(v["usage"].get(k, 0) for v in values)
        for k in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        )
    }
    if values:
        total["uncached_input_tokens"] = (
            total["input_tokens"] - total["cached_input_tokens"]
        )
        total["cache_hit_ratio"] = total["cached_input_tokens"] / total["input_tokens"]
    duplicate = Counter(r["normalized_sha256"] for r in records)
    return {
        "source": str(path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "components": components,
        "packet_fields": packets,
        "catalog_skill_count": len(skill_names),
        "catalog_skill_names": skill_names,
        "model_requests": len(values),
        "request_usage": values,
        "total_usage": total,
        "model_visible_tool_outputs": outputs,
        "visible_tool_output_bytes": sum(x["bytes"] for x in outputs),
        "orchestrator_calls": calls,
        "assistant_messages": narrative,
        "assistant_message_bytes": sum(x["bytes"] for x in narrative),
        "exact_duplicate_startup_block_hashes": {
            k: v for k, v in duplicate.items() if v > 1
        },
        "wire_tool_schema_tokens": "NOT AVAILABLE; discovered descriptions are a separate observable subset",
        "root_and_nested_agents_in_fixture": "ABSENT: disposable Git roots; machine AGENTS is separately present",
        "attribution": "Bytes/characters/JSON measures overlap where labeled subset. Usage is per response; component token attribution unavailable.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = json.loads(args.paths.read_text())
    result = {k: analyze(Path(v)) for k, v in paths.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: {
                    "requests": v["model_requests"],
                    "usage": v["total_usage"],
                    "visible_output_bytes": v["visible_tool_output_bytes"],
                }
                for k, v in result.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
