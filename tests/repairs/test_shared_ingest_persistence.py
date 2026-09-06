"""BH-R02 HOLD: valid generation seeds must be representable by the vendor DDL.

These are deliberately failing contract regressions, not runtime ingest proof.
No production schema, receipt, hash override, or disabled trigger is used.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moj_discovery.canonical import canonical_content_hash
from moj_discovery.schema_formats import STRICT_FORMAT_CHECKER

VENDOR = Path(__file__).resolve().parents[2] / "vendor/hybrid-discovery-v6.3.6"
REGISTRY = VENDOR / "registries/canonical-hash-domains.v1.json"


def test_canonical_seed_matches_independent_published_preimage() -> None:
    vectors = json.loads((VENDOR / "vectors/canonical-hashing-v1.json").read_text())
    seed = next(row for row in vectors["valid_vectors"] if row["vector_id"] == "CURSOR-SEED-H0")
    assert hashlib.sha256(bytes.fromhex(seed["preimage_hex"])).hexdigest() == seed["sha256"]
    assert canonical_content_hash("CursorSeed", seed["input"], registry_path=REGISTRY) == seed[
        "sha256"
    ]


@pytest.mark.parametrize("run_suffix", ["000000000010", "000000000011"])
@pytest.mark.parametrize("boundary", ["first_raw_commit", "zero_ack"])
def test_valid_generation_seed_is_accepted_by_durable_boundary(
    run_suffix: str, boundary: str
) -> None:
    run_id = f"00000000-0000-4000-8000-{run_suffix}"
    browser_id = "00000000-0000-4000-8000-000000000001"
    producer_id = "00000000-0000-4000-8000-000000000003"
    stream_id = "00000000-0000-4000-8000-000000000002"
    schema = json.loads((VENDOR / "schemas/durability-records.schema.json").read_text())
    Draft202012Validator(
        {"$defs": schema["$defs"], "$ref": "#/$defs/GenerationKey"},
        format_checker=STRICT_FORMAT_CHECKER,
    ).validate({
        "stream": {
            "browser_run_id": browser_id,
            "producer_id": producer_id,
            "stream_id": stream_id,
        },
        "generation": "0",
    })
    seed_input = {
        "schema_version": "cursor-seed/v1",
        "discovery_run_id": run_id,
        "browser_run_id": browser_id,
        "producer_id": producer_id,
        "stream_id": stream_id,
        "generation": "0",
    }
    seed = canonical_content_hash("CursorSeed", seed_input, registry_path=REGISTRY)
    # All fields are ASCII strings, so this independent encoding is exact JCS.
    preimage = b"HYBRID-DISCOVERY/v6.2/CursorSeed/v1\0" + json.dumps(
        seed_input, sort_keys=True, separators=(",", ":")
    ).encode()
    assert seed == hashlib.sha256(preimage).hexdigest()
    step_input = {
        **seed_input,
        "schema_version": "cursor-step/v1",
        "sequence": "1",
        "raw_observation_hash": "1" * 64,
        "previous_cursor_hash": seed,
    }
    step = canonical_content_hash("CursorStep", step_input, registry_path=REGISTRY)
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript((VENDOR / "sql/discovery-store-v1.sql").read_text())
        connection.execute(
            "INSERT INTO run_meta VALUES (?,1,'OPEN',?,?,?,0,NULL)",
            (run_id, "test-only:not-an-authorization-receipt", "a" * 64, "b" * 64),
        )
        connection.execute(
            "INSERT INTO stream_generations VALUES (?,?,?,?,?,0,NULL,'ACTIVE',0,NULL,NULL)",
            ("generation:test", run_id, browser_id, producer_id, stream_id),
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        try:
            if boundary == "first_raw_commit":
                connection.execute(
                    "INSERT INTO raw_commits VALUES (?,?,?,?,?,0,1,?,?,?,?,1,'APPLIED',1)",
                    ("raw:test", run_id, browser_id, producer_id, stream_id,
                     "observation:" + "1" * 64, "1" * 64, seed, step),
                )
            else:
                connection.execute(
                    "INSERT INTO ack_cursors VALUES (?,?,?,?,?,0,'BACKEND',0,?,1,"
                    "'BACKEND_DURABLE_CHAIN',NULL,1)",
                    ("ack:test", run_id, browser_id, producer_id, stream_id, seed),
                )
        except sqlite3.IntegrityError as error:
            pytest.fail(f"BH-R02_HOLD: {boundary}, run={run_id}, computed_H0={seed}: {error}")
        connection.commit()
