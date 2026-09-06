import sqlite3
from pathlib import Path

import pytest

from moj_discovery.governance import validate_ddl

DDL = Path("vendor/hybrid-discovery-v6.3.6/sql/discovery-store-v1.sql")


def _store() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(DDL.read_text())
    return connection


def _gate(
    *,
    issuer: str = "issuer:test-one",
    serial: str = "SERIAL-0001",
    nonce: str = "A" * 43,
) -> dict[str, object]:
    return {
        "consumption_id": f"consumption:{issuer}:{serial}",
        "run_id": None,
        "receipt_record_type": "GateReceipt",
        "receipt_schema_version": "gate-receipt/v1",
        "receipt_id": f"receipt:{issuer}:{serial}",
        "receipt_scope": "IMPLEMENTATION_GATE_ONLY",
        "gate_kind": "DISCOVERY_SECURITY_ACCEPTED",
        "gate_result": "PASS",
        "issuer": issuer,
        "issuer_key_id": "key:ed25519:" + "1" * 64,
        "audience": "hybrid-discovery:bootstrap-gate:v1",
        "scope_binding_hash": "2" * 64,
        "serial": serial,
        "nonce": nonce,
        "receipt_content_hash": ("3" if issuer == "issuer:test-one" else "4") * 64,
        "signature_algorithm": "Ed25519",
        "signature": "A" * 86,
        "receipt_verification_state": "CANONICAL_BYTES_CONTENT_HASH_AND_ED25519_SIGNATURE_VERIFIED",
        "one_use": 1,
        "declared_use_semantics": "SINGLE_USE",
        "consumed_before": "ATOMIC_LEDGER_COMMIT_BEFORE_GATE_USE",
        "consumption_commit_state": "COMMITTED_BEFORE_AUTHORIZED_ACTION",
        "verifier_clock_domain_id": "clock-domain:test",
        "verifier_boot_id": "00000000-0000-4000-8000-000000000001",
        "verifier_clock_unit": "MICROSECOND",
        "verifier_monotonic_value": 100,
        "verifier_clock_resolution_us": 1,
        "consumed_at_us": 100,
    }


def _insert(connection: sqlite3.Connection, table: str, record: dict[str, object]) -> None:
    columns = ",".join(record)
    placeholders = ",".join("?" for _ in record)
    connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",  # noqa: S608 - fixed table and local test columns
        tuple(record.values()),
    )


def test_literal_ddl_has_exact_table_set_and_integrity() -> None:
    validate_ddl()


def test_phase_gate_consumption_is_non_circular_atomic_and_issuer_scoped() -> None:
    connection = _store()
    first = _gate()
    connection.execute("BEGIN IMMEDIATE")
    _insert(connection, "authorization_consumptions", first)
    connection.rollback()
    assert connection.execute("SELECT count(*) FROM authorization_consumptions").fetchone() == (0,)

    _insert(connection, "authorization_consumptions", first)
    connection.commit()
    second_issuer = _gate(issuer="issuer:test-two")
    _insert(connection, "authorization_consumptions", second_issuer)
    connection.commit()
    assert connection.execute("SELECT count(*) FROM authorization_consumptions").fetchone() == (2,)

    serial_replay = _gate(serial="SERIAL-0001")
    serial_replay["consumption_id"] = "consumption:serial-replay"
    serial_replay["receipt_id"] = "receipt:serial-replay"
    serial_replay["receipt_content_hash"] = "5" * 64
    serial_replay["nonce"] = "B" * 43
    with pytest.raises(sqlite3.IntegrityError):
        _insert(connection, "authorization_consumptions", serial_replay)


def test_consumption_rejects_nonce_replay_bad_clock_and_missing_run() -> None:
    connection = _store()
    _insert(connection, "authorization_consumptions", _gate())
    connection.commit()

    nonce_replay = _gate(serial="SERIAL-0002")
    nonce_replay["consumption_id"] = "consumption:nonce-replay"
    nonce_replay["receipt_id"] = "receipt:nonce-replay"
    nonce_replay["receipt_content_hash"] = "6" * 64
    with pytest.raises(sqlite3.IntegrityError):
        _insert(connection, "authorization_consumptions", nonce_replay)
    connection.rollback()

    wrong_clock = _gate(serial="SERIAL-0003", nonce="C" * 43)
    wrong_clock["verifier_clock_unit"] = "MILLISECOND"
    with pytest.raises(sqlite3.IntegrityError):
        _insert(connection, "authorization_consumptions", wrong_clock)
    connection.rollback()

    discovery = _gate(serial="SERIAL-0004", nonce="D" * 43)
    discovery.update({
        "receipt_record_type": "DiscoveryRunAuthorization",
        "receipt_schema_version": "discovery-run-authorization/v1",
        "receipt_scope": "AUTHENTICATED_PASSIVE_DISCOVERY",
        "gate_kind": None,
        "gate_result": None,
        "declared_use_semantics": None,
        "consumed_before": "ATOMIC_LEDGER_COMMIT_BEFORE_DEBUGGER_ATTACH",
    })
    with pytest.raises(sqlite3.IntegrityError):
        _insert(connection, "authorization_consumptions", discovery)


def test_signed_revocation_chain_is_global_contiguous_and_immutable() -> None:
    connection = _store()

    def revocation(sequence: int, previous: str, digest: str) -> dict[str, object]:
        return {
            "revocation_id": f"revocation:{sequence}",
            "ledger_id": "00000000-0000-4000-8000-000000000011",
            "issuer": "issuer:revocation-test",
            "issuer_key_id": "key:ed25519:" + "1" * 64,
            "audience": "hybrid-discovery:revocation-ledger:v1",
            "subject_id": f"subject:{sequence}",
            "target_content_hash": str(sequence) * 64,
            "revocation_sequence": sequence,
            "previous_revocation_hash": previous,
            "revocation_hash": digest,
            "checkpoint_sequence": sequence,
            "checkpoint_head_hash": digest,
            "effective_at_utc": "2030-01-01T00:00:00.000000Z",
            "signature_algorithm": "Ed25519",
            "signature": "A" * 86,
            "verification_state": "CANONICAL_BYTES_CONTENT_HASH_ED25519_TRUST_AND_CHAIN_VERIFIED",
        }

    first = revocation(1, "0" * 64, "a" * 64)
    _insert(connection, "revocations", first)
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="E_REVOCATION_CHAIN"):
        _insert(connection, "revocations", revocation(3, "b" * 64, "c" * 64))
    connection.rollback()
    _insert(connection, "revocations", revocation(2, "a" * 64, "b" * 64))
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="E_IMMUTABLE_UPDATE"):
        connection.execute(
            "UPDATE revocations SET subject_id='changed' WHERE revocation_sequence=1"
        )
