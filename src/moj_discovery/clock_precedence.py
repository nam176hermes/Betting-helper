"""Shared frozen precedence and coverage validation for clock vectors."""
from __future__ import annotations


def load_clock_failure_precedence(
    precedence: dict[str, object],
    coverage: dict[str, object],
    vectors: dict[str, object],
) -> dict[str, object]:
    negative = precedence.get("negative_vectors")
    source_negative = vectors.get("mapping_negative_vectors")
    entries = coverage.get("entries")
    ordered = precedence.get("ordered_error_codes")
    if (
        not isinstance(negative, list)
        or not isinstance(source_negative, list)
        or not isinstance(entries, list)
        or not isinstance(ordered, list)
        or precedence.get("negative_mapping_count") != 16
        or len(negative) != 16
        or len(source_negative) != 16
        or coverage.get("total_named_vectors") != 65
        or len(entries) != 65
        or len(ordered) != len(set(ordered))
    ):
        raise ValueError("E_CLOCK_PRECEDENCE")
    for index, (frozen, source) in enumerate(zip(negative, source_negative), 1):
        expected = source.get("expected_error") or "SOURCE_AGE_UNKNOWN"
        if (
            frozen.get("vector_id") != source.get("id")
            or frozen.get("source_index") != index - 1
            or frozen.get("mutation") != source.get("mutation")
            or frozen.get("expected_error") != source.get("expected_error")
            or frozen.get("mapping_eligible") != source.get("mapping_eligible")
            or frozen.get("precedence_rank") != index
            or ordered[index - 1] != expected
        ):
            raise ValueError("E_CLOCK_PRECEDENCE")
    ids = [entry.get("vector_id") for entry in entries if isinstance(entry, dict)]
    if len(ids) != len(set(ids)) or any(not isinstance(vector_id, str) for vector_id in ids):
        raise ValueError("E_CLOCK_COVERAGE")
    return {
        "negative_mapping_count": len(negative),
        "total_named_vectors": len(ids),
        "ordered_error_codes": ordered,
    }
