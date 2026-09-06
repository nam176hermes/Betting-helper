"""Closed process-crash vector mapping validation."""
from __future__ import annotations


def validate_crash_harness_registry(
    registry: dict[str, object],
    child_registry: dict[str, object],
    vectors: dict[str, object],
) -> dict[str, object]:
    entries = registry.get("entries")
    cases = vectors.get("cases")
    children = child_registry.get("entries")
    if not isinstance(entries, list) or not isinstance(cases, list) or not isinstance(children, list):
        raise ValueError("E_CRASH_REGISTRY")
    source = {case.get("id"): case for case in cases if isinstance(case, dict)}
    mapped = {entry.get("vector_id"): entry for entry in entries if isinstance(entry, dict)}
    if (
        len(source) != 46
        or len(mapped) != 46
        or len(entries) != 46
        or set(source) != set(mapped)
        or registry.get("source_case_count") != 46
        or registry.get("mapped_case_count") != 46
    ):
        raise ValueError("E_CRASH_COVERAGE")
    by_harness = {
        child.get("harness"): child
        for child in children
        if isinstance(child, dict) and isinstance(child.get("harness"), str)
    }
    if len(by_harness) != 5 or len(children) != 5:
        raise ValueError("E_CRASH_CHILD")
    for vector_id, case in source.items():
        if not isinstance(vector_id, str):
            raise ValueError("E_CRASH_COVERAGE")
        entry = mapped[vector_id]
        if (
            entry.get("source_case_index") != cases.index(case)
            or entry.get("source_boundary") != case.get("boundary")
            or entry.get("kill_action") != case.get("kill")
            or entry.get("expected_post_restart_state") != case.get("expected")
            or entry.get("harness") not in by_harness
            or not isinstance(entry.get("child_command_id"), str)
            or not entry["child_command_id"].startswith("CRASH_VECTOR_")
            or not isinstance(entry.get("crash_checkpoint"), str)
            or not entry["crash_checkpoint"].strip()
            or not isinstance(entry.get("owner_task"), str)
            or not entry["owner_task"].startswith("V636-P03-T")
            or not isinstance(entry.get("verification_command_id"), str)
            or not entry["verification_command_id"].startswith("TEST_V636_P03_T")
        ):
            raise ValueError("E_CRASH_CHILD")
    return {"result": "PASS", "case_count": 46, "harness_count": len(by_harness)}
