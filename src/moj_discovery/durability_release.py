"""Release gate for completely executed process-level durability vectors."""
from __future__ import annotations

from typing import Any


def validate_full_durability_release(
    declared_vector_ids: list[str], executed_vector_ids: list[str], *, mutation_survivors: int,
    evidence: list[dict[str, Any]] | None = None,
    mutation_summary: dict[str, Any] | None = None,
) -> dict[str, object]:
    if evidence is None:
        raise ValueError("E_DURABILITY_EVIDENCE_REQUIRED")
    from tools.verify_repair_evidence import aggregate_repair_evidence, full_required_ids

    qualification = aggregate_repair_evidence(full_required_ids(), evidence)
    if qualification["legacy_full_qualification"] != "PASS":
        raise ValueError("E_DURABILITY_EVIDENCE_NOT_QUALIFIED")
    required = full_required_ids()
    if declared_vector_ids != required or executed_vector_ids != required:
        raise ValueError("E_DURABILITY_EXECUTION_COVERAGE")
    if mutation_survivors != 0:
        raise ValueError("E_DURABILITY_MUTATION_SURVIVOR")
    if mutation_summary != {
        "required": 105,
        "verified": 105,
        "survivors": 0,
        "complete": True,
    }:
        raise ValueError("E_DURABILITY_MUTATION_EVIDENCE_REQUIRED")
    return {
        "result": "PASS",
        "declared_count": len(declared_vector_ids),
        "mutation_survivors": mutation_survivors,
    }
