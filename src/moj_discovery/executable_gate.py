"""Fail closed before issuing EXECUTABLE_REFERENCE_COMPLETE."""
from __future__ import annotations

import hashlib
import json


def issue_executable_reference_complete_receipt(
    reference_result: dict[str, object], topology_result: dict[str, object]
) -> dict[str, object]:
    task_count = reference_result.get("task_count")
    command_count = reference_result.get("command_count")
    if (
        reference_result.get("result") != "PASS"
        or topology_result.get("result") != "PASS"
        or not isinstance(task_count, int)
        or task_count < 1
        or not isinstance(command_count, int)
        or command_count < 1
        or topology_result.get("group_count") != 11
        or topology_result.get("command_count") != 45
    ):
        raise ValueError("E_EXECUTABLE_REFERENCE_COMPLETE")
    record: dict[str, object] = {
        "gate": "EXECUTABLE_REFERENCE_COMPLETE",
        "production_authority": "NONE",
        "reference_result": reference_result,
        "topology_result": topology_result,
    }
    record["content_hash"] = hashlib.sha256(
        b"HD636/EXECUTABLE-REFERENCE-COMPLETE/v1\0"
        + json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return record
