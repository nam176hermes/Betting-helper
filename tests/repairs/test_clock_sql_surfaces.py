"""The midpoint vectors execute the exact governed SQLite DDL."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

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
