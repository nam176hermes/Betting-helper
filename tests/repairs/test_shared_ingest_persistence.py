"""Offline ingest integration and the inherited universal-H0 contract."""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moj_discovery.canonical import canonical_content_hash
from moj_discovery.ingest import Ingestor
from moj_discovery.schema_formats import STRICT_FORMAT_CHECKER
from moj_discovery.schema_registry import validate_artifact
from moj_discovery.store import RunStore

VENDOR = Path(__file__).resolve().parents[2] / "vendor/hybrid-discovery-v6.3.6"
REGISTRY = VENDOR / "registries/canonical-hash-domains.v1.json"
H0 = "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c"
RUN = "00000000-0000-4000-8000-000000000010"
BROWSER = "00000000-0000-4000-8000-000000000001"
PRODUCER = "00000000-0000-4000-8000-000000000003"
STREAM = "00000000-0000-4000-8000-000000000002"


def test_canonical_seed_matches_independent_published_preimage() -> None:
    vectors = json.loads((VENDOR / "vectors/canonical-hashing-v1.json").read_text())
    seed = next(row for row in vectors["valid_vectors"] if row["vector_id"] == "CURSOR-SEED-H0")
    assert hashlib.sha256(bytes.fromhex(seed["preimage_hex"])).hexdigest() == seed["sha256"]
    assert (
        canonical_content_hash("CursorSeed", seed["input"], registry_path=REGISTRY)
        == seed["sha256"]
    )


@pytest.mark.parametrize("run_suffix", ["000000000010", "000000000011"])
@pytest.mark.parametrize("boundary", ["first_raw_commit", "zero_ack"])
@pytest.mark.parametrize("substitute_identity_seed", [False, True])
def test_valid_generation_seed_is_accepted_by_durable_boundary(
    run_suffix: str, boundary: str, substitute_identity_seed: bool
) -> None:
    run_id = f"00000000-0000-4000-8000-{run_suffix}"
    browser_id = "00000000-0000-4000-8000-000000000001"
    producer_id = "00000000-0000-4000-8000-000000000003"
    stream_id = "00000000-0000-4000-8000-000000000002"
    schema = json.loads((VENDOR / "schemas/durability-records.schema.json").read_text())
    Draft202012Validator(
        {"$defs": schema["$defs"], "$ref": "#/$defs/GenerationKey"},
        format_checker=STRICT_FORMAT_CHECKER,
    ).validate(
        {
            "stream": {
                "browser_run_id": browser_id,
                "producer_id": producer_id,
                "stream_id": stream_id,
            },
            "generation": "0",
        }
    )
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
    preimage = (
        b"HYBRID-DISCOVERY/v6.2/CursorSeed/v1\0"
        + json.dumps(seed_input, sort_keys=True, separators=(",", ":")).encode()
    )
    assert seed == hashlib.sha256(preimage).hexdigest()
    assert seed != H0
    seed = seed if substitute_identity_seed else H0
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
                    (
                        "raw:test",
                        run_id,
                        browser_id,
                        producer_id,
                        stream_id,
                        "observation:" + "1" * 64,
                        "1" * 64,
                        seed,
                        step,
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO ack_cursors VALUES (?,?,?,?,?,0,'BACKEND',0,?,1,"
                    "'BACKEND_DURABLE_CHAIN',NULL,1)",
                    ("ack:test", run_id, browser_id, producer_id, stream_id, seed),
                )
        except sqlite3.IntegrityError as error:
            assert substitute_identity_seed
            assert str(error) == (
                "E_CURSOR_FIRST_STEP_NOT_H0"
                if boundary == "first_raw_commit"
                else "E_ACK_ZERO_NOT_H0"
            )
            return
        assert not substitute_identity_seed
        connection.commit()


def observation(sequence: int = 1, generation: int = 0) -> dict[str, Any]:
    """Schema-valid synthetic accounting input; conveys no external authority."""
    value: dict[str, Any] = {
        "schema_version": "raw-observation/v1",
        "raw_observation_id": "observation:"
        + hashlib.sha256(f"{generation}:{sequence}".encode()).hexdigest(),
        "observation_kind": "TERMINAL",
        "pack_hash": "a" * 64,
        "build_hash": "b" * 64,
        "implementation_baseline_hash": "c" * 64,
        "capability_manifest_hash": "d" * 64,
        "discovery_run_id": RUN,
        "run_receipt_hash": "e" * 64,
        "stream_id": STREAM,
        "generation": str(generation),
        "sequence": str(sequence),
        "context": {
            "context_kind": "RUN_BOUND_NOT_DOCUMENT",
            "browser_run_id": BROWSER,
            "browser_boot_id": BROWSER,
            "binding_reason": "TERMINAL_ACCOUNTING",
        },
        "clock_context": {
            "clock_domain_id": PRODUCER,
            "boot_id": BROWSER,
            "unit": "MICROSECOND",
            "monotonic_value": str(sequence),
            "resolution_us": "1",
            "owner": "BACKEND",
            "mapping_id": "NOT_APPLICABLE",
            "mapping_status": "NOT_APPLICABLE",
        },
        "sanitizer_version": "sanitizer/v1",
        "content_hash": "0" * 64,
        "production_authority": "NONE",
        "facts": {
            "terminal_code": "MANUAL_STOP",
            "final_generation": str(generation),
            "final_sequence": str(sequence),
            "observation_count": str(sequence),
            "gap_count": "0",
            "safety_disposition": "PARTIAL_EVIDENCE_ONLY",
        },
    }
    value["content_hash"] = canonical_content_hash("RawObservation", value, registry_path=REGISTRY)
    validate_artifact(value, "raw-observation.schema.json", bootstrap_only=True, vendor=VENDOR)
    return value


def prepared_store(tmp_path: Path) -> RunStore:
    run_dir = tmp_path / RUN
    run_dir.mkdir()
    store = RunStore(run_dir / "run.sqlite3")
    store.bootstrap_v1()
    # Existing SQL fixtures are offline prerequisites, not signed run authorization.
    with closing(sqlite3.connect(store.db_path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO run_meta VALUES (?,1,'OPEN','test-only:offline',?,?,0,NULL)",
            (RUN, "a" * 64, "b" * 64),
        )
        connection.execute(
            "INSERT INTO stream_generations VALUES ('generation:0',?,?,?,?,0,NULL,"
            "'ACTIVE',0,NULL,NULL)",
            (RUN, BROWSER, PRODUCER, STREAM),
        )
        connection.execute(
            "INSERT INTO coherence_epochs VALUES ('epoch:0',?,'fixture:test',0,NULL,"
            "'OPEN',NULL,NULL,0,0)",
            (RUN,),
        )
        connection.execute(
            "INSERT INTO coherence_controllers VALUES ('controller:test',?,'fixture:test',"
            "'OPEN','epoch:0',NULL,NULL,NULL,0,0)",
            (RUN,),
        )
    return store


def counts(store: RunStore) -> list[int]:
    with closing(sqlite3.connect(store.db_path)) as connection:
        return [
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in (
                "raw_commits",
                "application_records",
                "derived_revisions",
                "reducer_cursors",
                "ack_outbox",
            )
        ]


def test_real_ingest_is_atomic_idempotent_and_replayable(tmp_path: Path) -> None:
    store = prepared_store(tmp_path)
    first = observation()
    ack = Ingestor(store).apply(first)
    assert ack["highest_contiguous_sequence"] == 1
    assert ack["cursor_hash_verified"] == 1
    assert counts(store) == [1, 1, 1, 1, 1]
    assert Ingestor(RunStore(store.db_path)).apply(first) == ack
    assert counts(store) == [1, 1, 1, 1, 1]
    second = Ingestor(store).apply(observation(2))
    assert second["highest_contiguous_sequence"] == 2
    assert counts(store) == [2, 2, 2, 2, 2]
    with closing(sqlite3.connect(store.db_path)) as connection:
        assert connection.execute(
            "SELECT previous_cursor_hash FROM raw_commits ORDER BY sequence"
        ).fetchall() == [(H0,), (ack["cursor_hash"],)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize(
    "fail_table", ["application_records", "derived_revisions", "reducer_cursors", "ack_outbox"]
)
def test_failure_at_each_write_rolls_back_complete_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_table: str
) -> None:
    store = prepared_store(tmp_path)
    original: Callable[[], sqlite3.Connection] = store.connect

    def fail_connection() -> sqlite3.Connection:
        connection = original()
        connection.set_authorizer(
            lambda action, table, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == fail_table
                else sqlite3.SQLITE_OK
            )
        )
        return connection

    monkeypatch.setattr(store, "connect", fail_connection)
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        Ingestor(store).apply(observation())
    assert counts(store) == [0, 0, 0, 0, 0]


def test_observation_rejections_do_not_write(tmp_path: Path) -> None:
    store = prepared_store(tmp_path)
    value = observation()
    value["content_hash"] = "f" * 64
    with pytest.raises(ValueError, match="CONTENT_HASH_MISMATCH"):
        Ingestor(store).apply(value)
    value = observation()
    value["pack_hash"] = "f" * 64
    value["content_hash"] = canonical_content_hash("RawObservation", value, registry_path=REGISTRY)
    with pytest.raises(ValueError, match="E_INGEST_RUN_BINDING"):
        Ingestor(store).apply(value)
    assert counts(store) == [0, 0, 0, 0, 0]


def test_gap_closes_epoch_and_opens_exact_successor_without_ack(tmp_path: Path) -> None:
    store = prepared_store(tmp_path)
    Ingestor(store).apply(observation())
    with pytest.raises(ValueError, match="E_INGEST_GAP"):
        Ingestor(store).apply(observation(3))
    assert counts(store) == [1, 1, 1, 1, 1]
    with closing(sqlite3.connect(store.db_path)) as connection:
        assert connection.execute(
            "SELECT generation,generation_state FROM stream_generations ORDER BY generation"
        ).fetchall() == [(0, "QUARANTINED_GAP"), (1, "ACTIVE")]
        assert connection.execute(
            "SELECT controller_state,current_epoch_id FROM coherence_controllers"
        ).fetchall() == [("SHOCKED_CLOSED", "epoch:0")]
        assert connection.execute("SELECT count(*) FROM gap_records").fetchone() == (1,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(ValueError, match="E_INGEST_GENERATION_CLOSED"):
        Ingestor(store).apply(observation(2))
    assert counts(store) == [1, 1, 1, 1, 1]


def test_conflict_persists_evidence_and_blocks_generation_without_inventing_gap(
    tmp_path: Path,
) -> None:
    store = prepared_store(tmp_path)
    Ingestor(store).apply(observation())
    value = observation()
    value["facts"]["terminal_code"] = "BUDGET_STOP"
    value["raw_observation_id"] = "observation:" + "f" * 64
    value["content_hash"] = canonical_content_hash("RawObservation", value, registry_path=REGISTRY)
    with pytest.raises(ValueError, match="E_INGEST_CONFLICT"):
        Ingestor(store).apply(value)
    with pytest.raises(ValueError, match="E_INGEST_CONFLICT"):
        Ingestor(RunStore(store.db_path)).apply(observation(2))
    assert counts(store) == [1, 1, 1, 1, 1]
    with closing(sqlite3.connect(store.db_path)) as connection:
        assert connection.execute("SELECT count(*) FROM raw_conflicts").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM gap_records").fetchone() == (0,)


def test_store_denies_schema_changes_deletion_and_attach(tmp_path: Path) -> None:
    store = prepared_store(tmp_path)
    for sql in (
        "DELETE FROM run_meta",
        "DROP TABLE raw_commits",
        "VACUUM",
        "ATTACH DATABASE ':memory:' AS other",
        "PRAGMA foreign_keys=OFF",
    ):
        with closing(store.connect()) as connection, pytest.raises(sqlite3.DatabaseError):
            connection.execute(sql)


def test_reopened_store_retains_ddl_connection_safety_limits(tmp_path: Path) -> None:
    store = prepared_store(tmp_path)
    with closing(store.connect()) as connection:
        connection.set_authorizer(None)  # Test-only inspection of connection pragmas.
        assert connection.execute("PRAGMA temp_store").fetchone()[0] == 2
        assert connection.execute("PRAGMA max_page_count").fetchone()[0] == 32768
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_gap_failure_before_successor_insert_rolls_back_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = prepared_store(tmp_path)
    Ingestor(store).apply(observation())
    original = store.connect

    def fail_successor() -> sqlite3.Connection:
        connection = original()
        connection.set_authorizer(
            lambda action, table, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == "stream_generations"
                else sqlite3.SQLITE_OK
            )
        )
        return connection

    monkeypatch.setattr(store, "connect", fail_successor)
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        Ingestor(store).apply(observation(3))
    with closing(sqlite3.connect(store.db_path)) as connection:
        assert connection.execute("SELECT generation_state FROM stream_generations").fetchall() == [
            ("ACTIVE",),
        ]
        assert connection.execute(
            "SELECT controller_state FROM coherence_controllers"
        ).fetchall() == [
            ("OPEN",),
        ]
        assert connection.execute("SELECT count(*) FROM gap_records").fetchone() == (0,)


def test_journal_replay_digests_are_deterministic_across_stores(tmp_path: Path) -> None:
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    stores = [prepared_store(left), prepared_store(right)]
    revisions = []
    for store in stores:
        for sequence in (1, 2):
            Ingestor(store).apply(observation(sequence))
        with closing(sqlite3.connect(store.db_path)) as connection:
            revisions.append(
                connection.execute(
                    "SELECT revision,previous_revision_hash,revision_hash FROM derived_revisions "
                    "ORDER BY revision"
                ).fetchall()
            )
    assert revisions[0] == revisions[1]
    assert [row[0] for row in revisions[0]] == [1, 2]
    assert revisions[0][0][1] is None
    assert revisions[0][1][1] == revisions[0][0][2]
