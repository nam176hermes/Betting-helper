"""Atomic offline ingest journal; no domain reducer or external I/O authority."""

import sqlite3
from contextlib import closing
from time import time_ns
from typing import Any

from .canonical import canonical_content_hash, verify_canonical_content_hash
from .errors import ContractNotImplementedError
from .schema_registry import validate_artifact
from .store import VENDOR, RunStore, read_journal, validate_journal

# The inherited DDL/schema select one universal H0, not a per-identity seed.
H0 = "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c"
REGISTRY = VENDOR / "registries/canonical-hash-domains.v1.json"
POSITION = "run_id=? AND browser_run_id=? AND producer_id=? AND stream_id=? AND generation=?"


def _integer(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 9223372036854775807:
        raise ValueError("E_INGEST_INTEGER_RANGE")
    return parsed


class Ingestor:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def apply(self, observation: dict[str, Any]) -> dict[str, Any]:
        validate_artifact(
            observation, "raw-observation.schema.json", bootstrap_only=True, vendor=VENDOR
        )
        verify_canonical_content_hash(
            "RawObservation", observation, observation["content_hash"], registry_path=REGISTRY
        )
        # Lifecycle/GAP observations require semantic handlers beyond this journal.
        if observation["observation_kind"] in {"LIFECYCLE", "GAP"}:
            raise ContractNotImplementedError("F0A-T04:OBSERVATION_SEMANTICS")
        run = observation["discovery_run_id"]
        browser = observation["context"]["browser_run_id"]
        stream = observation["stream_id"]
        generation, sequence = (_integer(observation[key]) for key in ("generation", "sequence"))
        content_hash = observation["content_hash"]
        now = time_ns() // 1000
        rejected: str | None = None
        ack: dict[str, Any] = {}
        with closing(self.store.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            validate_journal(read_journal(connection))
            meta = connection.execute("SELECT * FROM run_meta").fetchall()
            if len(meta) != 1 or (
                meta[0]["run_id"] != run
                or meta[0]["run_status"] != "OPEN"
                or meta[0]["pack_hash"] != observation["pack_hash"]
                or meta[0]["build_hash"] != observation["build_hash"]
            ):
                raise ValueError("E_INGEST_RUN_BINDING")
            generations = connection.execute(
                "SELECT * FROM stream_generations WHERE run_id=? AND browser_run_id=? "
                "AND stream_id=? AND generation=?",
                (run, browser, stream, generation),
            ).fetchall()
            if len(generations) != 1:
                raise ValueError("E_INGEST_GENERATION_BINDING")
            current = generations[0]
            if current["generation_state"] != "ACTIVE":
                raise ValueError("E_INGEST_GENERATION_CLOSED")
            key = (run, browser, current["producer_id"], stream, generation)
            if (
                connection.execute(
                    f"SELECT 1 FROM raw_conflicts WHERE {POSITION} LIMIT 1",  # noqa: S608
                    key,
                ).fetchone()
                is not None
            ):
                raise ValueError("E_INGEST_CONFLICT")
            raw = connection.execute(
                f"SELECT * FROM raw_commits WHERE {POSITION} AND sequence=?",  # noqa: S608
                (*key, sequence),
            ).fetchone()
            previous = connection.execute(
                f"SELECT * FROM reducer_cursors WHERE {POSITION} "  # noqa: S608
                "ORDER BY highest_contiguous_sequence DESC LIMIT 1",
                key,
            ).fetchone()
            highest = 0 if previous is None else previous["highest_contiguous_sequence"]
            if raw is not None and raw["raw_observation_content_hash"] == content_hash:
                row = connection.execute(
                    f"SELECT * FROM ack_outbox WHERE {POSITION} "  # noqa: S608
                    "AND highest_contiguous_sequence=?",
                    (*key, sequence),
                ).fetchone()
                if row is None:
                    raise ValueError("E_INGEST_INCOMPLETE_DURABLE_CHAIN")
                ack = dict(row)
            elif raw is not None or sequence != highest + 1:
                if sequence <= highest and raw is None:
                    raise ValueError("E_INGEST_INCOMPLETE_DURABLE_CHAIN")
                if raw is not None:
                    connection.execute(
                        "INSERT INTO raw_conflicts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            "conflict:" + content_hash,
                            raw["raw_commit_id"],
                            *key,
                            sequence,
                            observation["raw_observation_id"],
                            content_hash,
                            now,
                        ),
                    )
                    self._gap(
                        connection,
                        current,
                        highest,
                        sequence,
                        content_hash,
                        now,
                        "CONFLICTING_DUPLICATE",
                    )
                    rejected = "E_INGEST_CONFLICT"
                else:
                    self._gap(
                        connection,
                        current,
                        highest,
                        sequence,
                        content_hash,
                        now,
                        "MISSING_SEQUENCE",
                    )
                    rejected = "E_INGEST_GAP"
            else:
                prior_hash = H0 if previous is None else previous["cursor_hash"]
                cursor = canonical_content_hash(
                    "CursorStep",
                    {
                        "schema_version": "cursor-step/v1",
                        "discovery_run_id": run,
                        "browser_run_id": browser,
                        "producer_id": current["producer_id"],
                        "stream_id": stream,
                        "generation": str(generation),
                        "sequence": str(sequence),
                        "raw_observation_hash": content_hash,
                        "previous_cursor_hash": prior_hash,
                    },
                    registry_path=REGISTRY,
                )
                raw_id, application_id, revision_id, reducer_id, outbox_id = (
                    prefix + ":" + cursor
                    for prefix in ("raw", "application", "revision", "cursor", "ack")
                )
                connection.execute(
                    "INSERT INTO raw_commits VALUES (?,?,?,?,?,?,?,?,?,?,?,1,'APPLIED',?)",
                    (
                        raw_id,
                        *key,
                        sequence,
                        observation["raw_observation_id"],
                        content_hash,
                        prior_hash,
                        cursor,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO application_records VALUES (?,?,?,?,?,?,?,?,?,?,'APPLIED',?)",
                    (application_id, raw_id, *key, sequence, content_hash, prior_hash, now),
                )
                # Journal revision = the committed input-chain digest. No domain state is inferred.
                connection.execute(
                    "INSERT INTO derived_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        revision_id,
                        application_id,
                        raw_id,
                        *key,
                        sequence,
                        sequence,
                        None if previous is None else prior_hash,
                        cursor,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO reducer_cursors VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (
                        reducer_id,
                        revision_id,
                        *key,
                        sequence,
                        prior_hash,
                        cursor,
                        content_hash,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO ack_outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                    (
                        outbox_id,
                        raw_id,
                        application_id,
                        revision_id,
                        reducer_id,
                        *key,
                        sequence,
                        cursor,
                        now,
                    ),
                )
                ack = dict(
                    connection.execute(
                        "SELECT * FROM ack_outbox WHERE ack_outbox_id=?", (outbox_id,)
                    ).fetchone()
                )
        # The connection context has committed, including deferred constraints, before return.
        if rejected is not None:
            raise ValueError(rejected)
        return ack

    def confirm_ack(self, ack: dict[str, Any]) -> dict[str, Any]:
        """Persist an idempotent confirmation only for the exact durable outbox ACK."""
        with closing(self.store.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            validate_journal(read_journal(connection))
            durable = connection.execute(
                "SELECT * FROM ack_outbox WHERE ack_outbox_id=?", (ack.get("ack_outbox_id"),)
            ).fetchone()
            if durable is None or dict(durable) != ack:
                raise ValueError("E_ACK_CONFIRMATION_BINDING")
            key = tuple(
                ack[name]
                for name in (
                    "run_id",
                    "browser_run_id",
                    "producer_id",
                    "stream_id",
                    "generation",
                )
            )
            previous = connection.execute(
                f"SELECT * FROM ack_cursors WHERE {POSITION} AND owner='BACKEND' "  # noqa: S608
                "ORDER BY highest_contiguous_sequence DESC LIMIT 1",
                key,
            ).fetchone()
            if previous is not None:
                if previous["highest_contiguous_sequence"] > ack["highest_contiguous_sequence"]:
                    raise ValueError("E_ACK_CONFIRMATION_REGRESSION")
                if previous["highest_contiguous_sequence"] == ack["highest_contiguous_sequence"]:
                    if previous["cursor_hash"] != ack["cursor_hash"]:
                        raise ValueError("E_ACK_CONFIRMATION_BINDING")
                    return dict(previous)
            identifier = "confirmation:" + ack["cursor_hash"]
            connection.execute(
                "INSERT INTO ack_cursors VALUES (?,?,?,?,?,?,'BACKEND',?,?,1,"
                "'BACKEND_DURABLE_CHAIN',?,?)",
                (
                    identifier,
                    *key,
                    ack["highest_contiguous_sequence"],
                    ack["cursor_hash"],
                    None if previous is None else previous["ack_cursor_id"],
                    time_ns() // 1000,
                ),
            )
            result = dict(
                connection.execute(
                    "SELECT * FROM ack_cursors WHERE ack_cursor_id=?",
                    (identifier,),
                ).fetchone()
            )
        return result

    @staticmethod
    def _gap(
        connection: sqlite3.Connection,
        current: sqlite3.Row,
        highest: int,
        sequence: int,
        digest: str,
        now: int,
        reason: str,
    ) -> None:
        controllers = connection.execute(
            "SELECT * FROM coherence_controllers WHERE run_id=?", (current["run_id"],)
        ).fetchall()
        # No stream-to-fixture mapping exists in this DDL: ambiguous multi-fixture input holds.
        if len(controllers) != 1 or controllers[0]["controller_state"] not in {
            "OPEN",
            "NEW_EPOCH_OPEN",
        }:
            raise ValueError("E_INGEST_GAP_COHERENCE_BINDING")
        controller = controllers[0]
        key = tuple(
            current[field] for field in ("run_id", "browser_run_id", "producer_id", "stream_id")
        )
        generation = current["generation"]
        gap, shock, transition, binding = (
            prefix + ":" + digest for prefix in ("gap", "shock", "transition", "binding")
        )
        conflict = reason == "CONFLICTING_DUPLICATE"
        missing_from = sequence if conflict else highest + 1
        missing_to = sequence if conflict else sequence - 1
        connection.execute(
            "INSERT INTO gap_records VALUES (?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?)",
            (
                gap,
                *key,
                generation,
                generation + 1,
                missing_from,
                missing_to,
                sequence,
                reason,
                sequence - 1 if conflict else highest,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO shock_observations VALUES (?,?,?,?,?,?,?,?)",
            (
                shock,
                key[0],
                controller["fixture_id"],
                "SCHEMA_CONFLICT" if conflict else "SEQUENCE_GAP",
                now,
                now,
                digest,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO coherence_transitions VALUES (?,?,?,?, 'SHOCKED_CLOSED',?,NULL,?,"
            "NULL,NULL,1,'SHOCK_ATOMIC_CLOSE',?)",
            (
                transition,
                controller["coherence_controller_id"],
                controller["fixture_id"],
                controller["controller_state"],
                controller["current_epoch_id"],
                shock,
                now,
            ),
        )
        connection.execute(
            "UPDATE coherence_controllers SET controller_state='SHOCKED_CLOSED',"
            "active_shock_observation_id=?,controller_revision=controller_revision+1,"
            "updated_at_us=? "
            "WHERE coherence_controller_id=?",
            (shock, now, controller["coherence_controller_id"]),
        )
        connection.execute(
            "INSERT INTO gap_epoch_bindings VALUES (?,?,?,?,?,?,"
            "'AFFECTED_EPOCH_PERMANENTLY_CLOSED',?)",
            (
                binding,
                gap,
                controller["current_epoch_id"],
                controller["coherence_controller_id"],
                shock,
                transition,
                now,
            ),
        )
        connection.execute(
            "UPDATE stream_generations SET generation_state=?,closed_at_us=?,"
            "close_reason=? WHERE generation_id=?",
            ("CLOSED" if conflict else "QUARANTINED_GAP", now, reason, current["generation_id"]),
        )
        connection.execute(
            "INSERT INTO generation_transitions VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "generation-transition:" + digest,
                gap,
                *key,
                generation,
                generation + 1,
                "CONFLICT" if conflict else "GAP",
                now,
            ),
        )
        connection.execute(
            "INSERT INTO stream_generations VALUES (?,?,?,?,?,?,?,'ACTIVE',?,NULL,NULL)",
            ("generation:" + digest, *key, generation + 1, generation, now),
        )
