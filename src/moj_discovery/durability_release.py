"""Release gate for completely executed process-level durability vectors."""
from __future__ import annotations

from typing import Any


def validate_full_durability_release(
    declared_vector_ids: list[str], executed_vector_ids: list[str], *, mutation_survivors: int,
    evidence: list[dict[str, Any]] | None = None,
    mutation_summary: dict[str, Any] | None = None,
    mutation_evidence: dict[str, Any] | None = None,
) -> dict[str, object]:
    if evidence is None:
        raise ValueError("E_DURABILITY_EVIDENCE_REQUIRED")
    from tools.verify_repair_evidence import PACK, aggregate_repair_evidence, full_required_ids

    qualification = aggregate_repair_evidence(full_required_ids(), evidence)
    if qualification["legacy_full_qualification"] != "PASS":
        raise ValueError("E_DURABILITY_EVIDENCE_NOT_QUALIFIED")
    required = full_required_ids()
    if declared_vector_ids != required or executed_vector_ids != required:
        raise ValueError("E_DURABILITY_EXECUTION_COVERAGE")
    if mutation_survivors != 0:
        raise ValueError("E_DURABILITY_MUTATION_SURVIVOR")
    if mutation_evidence is None:
        raise ValueError("E_DURABILITY_MUTATION_EVIDENCE_REQUIRED")
    from tools.run_indexeddb_crash_matrix import validate_full_mutation_reports

    verified = validate_full_mutation_reports(
        PACK,
        mutation_evidence["owner_reports"],
        mutation_evidence["clock_report"],
    )
    if verified != {
        "required": 105,
        "verified": 105,
        "survivors": 0,
        "complete": True,
    }:
        raise ValueError("E_DURABILITY_MUTATION_EVIDENCE_REQUIRED")
    del mutation_summary
    return {
        "result": "PASS",
        "declared_count": len(declared_vector_ids),
        "mutation_survivors": mutation_survivors,
    }
