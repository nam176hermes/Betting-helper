"""The midpoint vectors execute the exact governed SQLite DDL."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.run_clock_vector_qualification import _coherence_sql_observation

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "vendor/hybrid-discovery-v6.3.6"
VECTORS = json.loads(
    (PACK / "docs/vectors/inherited/clock-coherence-v6.2.json").read_text()
)


@pytest.mark.parametrize(
    "vector", VECTORS["midpoint_constraint_vectors"], ids=lambda item: item["id"]
)
def test_midpoint_vector_executes_governed_clock_mapping_constraints(
    vector: dict[str, object],
) -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript((PACK / "sql/discovery-store-v1.sql").read_text())
    connection.execute(
        "INSERT INTO run_meta VALUES (?,1,'OPEN',?,?,?,0,NULL)",
        ("11111111-1111-4111-8111-111111111111", "test-only:clock", "0" * 64, "1" * 64),
    )
    values = (
        "MAP:" + "2" * 64,
        "11111111-1111-4111-8111-111111111111",
        "source", "source-boot", "EXTENSION_SERVICE_WORKER",
        "target", "target-boot", "BACKEND_PROCESS", "MICROSECOND", 8, 0,
        vector["offset_lower_us"], vector["offset_upper_us"],
        vector["offset_midpoint_us"], vector["base_uncertainty_us"],
        0, 100, 0, 1, "OPEN", 0,
    )
    sql = """INSERT INTO clock_mappings (
        clock_mapping_id, run_id, source_clock_domain_id, source_boot_id, source_owner,
        target_clock_domain_id, target_boot_id, target_owner, unit, sample_count,
        source_anchor_us, offset_lower_us, offset_upper_us, offset_midpoint_us,
        base_uncertainty_us, network_rtt_us, relative_drift_ppm,
        valid_from_source_us, valid_until_source_us, mapping_status, created_at_us
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    if str(vector["expected"]).startswith("ACCEPT"):
        connection.execute(sql, values)
    else:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql, values)


@pytest.mark.parametrize(
    ("case_id", "expected_error", "proof_status", "release_mapping_close"),
    [
        ("CANDIDATE-NEG-02-SQL-UNKNOWN", "E_RESNAPSHOT_CANDIDATE_BINDING",
         "UNKNOWN", False),
        ("CANDIDATE-NEG-03-NOT-OBSERVED", "E_RESNAPSHOT_CANDIDATE_BINDING",
         "NOT_OBSERVED", False),
        ("CANDIDATE-NEG-04-UNSIGNED-UNVERIFIED", "E_RESNAPSHOT_CANDIDATE_BINDING",
         "UNKNOWN", False),
        ("RELEASE-NEG-09-MAPPING-CLOSED", "E_RELEASE_BINDING", None, True),
    ],
)
def test_coherence_negative_executes_exact_governed_ddl(
    case_id: str, expected_error: str, proof_status: str | None,
    release_mapping_close: bool,
) -> None:
    observation = _coherence_sql_observation(
        proof_status=proof_status, release_mapping_close=release_mapping_close,
    )
    assert observation["accepted"] is False
    assert observation["error"] == expected_error
    assert expected_error in str(observation["sqlite_error"])
    assert observation["ddl_sha256"]
    if case_id.startswith("RELEASE-"):
        assert observation["candidate_acceptance_executed"] is True
        assert observation["mapping_close_executed"] is True
