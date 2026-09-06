"""Release gate for completely executed process-level durability vectors."""
from __future__ import annotations


def validate_full_durability_release(
    declared_vector_ids: list[str], executed_vector_ids: list[str], *, mutation_survivors: int
) -> dict[str, object]:
    if (
        not declared_vector_ids
        or len(declared_vector_ids) != len(set(declared_vector_ids))
        or declared_vector_ids != executed_vector_ids
    ):
        raise ValueError("E_DURABILITY_EXECUTION_COVERAGE")
    if mutation_survivors != 0:
        raise ValueError("E_DURABILITY_MUTATION_SURVIVOR")
    return {
        "result": "PASS",
        "declared_count": len(declared_vector_ids),
        "mutation_survivors": mutation_survivors,
    }
