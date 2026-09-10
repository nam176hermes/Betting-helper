"""Typed append-only journal; a durable receipt is returned only after COMMIT."""

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

import rfc8785

from .canonical import parse_strict_json
from .live_contracts import CONTRACTS, event_hash, validate_live_record
from .live_state import reduce_live_event
from .store import _schema_objects

TABLES = (
    "run_meta",
    "live_events",
    "stream_cursors",
    "projection_versions",
    "request_links",
    "run_closures",
)
ZERO = "0" * 64
MAX_BYTES = 512 * 1024 * 1024


def view_hash(view: dict[str, Any]) -> str:
    return hashlib.sha256(b"BH-LIVE-READONLY/View/v1\0" + rfc8785.dumps(view)).hexdigest()


def verify_live_database(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("E_LIVE_STORE_SCHEMA")
    query = "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
    if tuple(tuple(r) for r in db.execute(query)) != _schema_objects(
        (CONTRACTS / "live-store.sql").read_text()
    ):
        raise ValueError("E_LIVE_STORE_SCHEMA")
    if (
        db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
        or db.execute("PRAGMA foreign_key_check").fetchall()
    ):
        raise ValueError("E_LIVE_STORE_INTEGRITY")


def _timestamp(value: str) -> None:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() != UTC.utcoffset(stamp):
        raise ValueError("E_LIVE_STORE_TIME")


def _authorizer(
    action: int, first: str | None, second: str | None, db: str | None, trigger: str | None
) -> int:
    if action in {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_RECURSIVE,
    }:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_INSERT and first in TABLES:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and second in {"max", "coalesce", "length", "raise"}:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


@dataclass(frozen=True)
class DurableReceipt:
    receive_index: int
    run_id: str
    stream_id: str
    generation: str
    sequence: str
    content_hash: str


def reduce_projection(previous: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    return reduce_live_event(previous, event)


class LiveStore:
    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        source_tree_hash: str,
        config_hash: str,
        started_utc: str,
        max_matches: int,
        max_bytes: int = MAX_BYTES,
    ):
        if (
            str(UUID(run_id)) != run_id
            or any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in (source_tree_hash, config_hash))
            or type(max_matches) is not int
            or max_matches not in {1, 3, 5}
        ):
            raise ValueError("E_LIVE_RUN_META")
        _timestamp(started_utc)
        if type(max_bytes) is not int or not 131072 <= max_bytes <= MAX_BYTES:
            raise ValueError("E_LIVE_STORE_CAP")
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("E_LIVE_STORE_PATH")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.stat().st_mode & 0o077:
            raise ValueError("E_LIVE_STORE_PATH")
        self._fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._fd)
            raise ValueError("E_LIVE_STORE_LOCK") from None
        self.path, self.run_id, self.max_bytes = path, run_id, max_bytes
        self._mutex = threading.RLock()
        self._pid, self._closed = os.getpid(), False
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            if path.stat().st_mode & 0o077:
                raise ValueError("E_LIVE_STORE_PATH")
            self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            if not self.db.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchone():
                self.db.executescript((CONTRACTS / "live-store.sql").read_text())
            for pragma in (
                "journal_mode=DELETE",
                "synchronous=FULL",
                "foreign_keys=ON",
                "trusted_schema=OFF",
                "busy_timeout=5000",
                "temp_store=MEMORY",
            ):
                self.db.execute("PRAGMA " + pragma)
            page = self.db.execute("PRAGMA page_size").fetchone()[0]
            if (
                self.db.execute("PRAGMA max_page_count=" + str(max_bytes // page)).fetchone()[0]
                > max_bytes // page
            ):
                raise ValueError("E_LIVE_STORE_CAP")
            verify_live_database(self.db)
            expected = (
                run_id,
                source_tree_hash,
                config_hash,
                started_utc,
                "LIVE_READ_ONLY",
                max_matches,
                0,
            )
            existing = self.db.execute("SELECT * FROM run_meta").fetchall()
            if existing and existing != [expected]:
                raise ValueError("E_LIVE_RUN_META")
            if not existing:
                self.db.execute("INSERT INTO run_meta VALUES(?,?,?,?,?,?,?)", expected)
            self.db.set_authorizer(_authorizer)
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            os.close(self._fd)
            raise

    def __enter__(self) -> "LiveStore":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _owner(self) -> None:
        if self._closed or self._pid != os.getpid():
            raise ValueError("E_LIVE_STORE_OWNER")

    def close(self) -> None:
        with self._mutex:
            if not self._closed:
                self.db.close()
                os.close(self._fd)
                self._closed = True

    def read_projection(self, binding_id: str) -> dict[str, Any]:
        with self._mutex:
            self._owner()
            row = self.db.execute(
                "SELECT canonical_view,content_hash FROM projection_versions WHERE run_id=? "
                "AND binding_id=? ORDER BY revision DESC LIMIT 1",
                (self.run_id, binding_id),
            ).fetchone()
            if row is None:
                raise ValueError("E_LIVE_BINDING_REQUIRED")
            view = cast(dict[str, Any], parse_strict_json(bytes(row[0])))
            if view_hash(view) != row[1] or rfc8785.dumps(view) != row[0]:
                raise ValueError("E_LIVE_PROJECTION_HASH")
            return view

    def bindings(self) -> dict[str, dict[str, Any]]:
        with self._mutex:
            self._owner()
            ids = [
                r[0]
                for r in self.db.execute(
                    "SELECT DISTINCT binding_id FROM projection_versions WHERE run_id=?",
                    (self.run_id,),
                )
            ]
            return {i: self.read_projection(i)["binding"] for i in ids}

    def cursor(self, stream_id: str, generation: str = "0") -> tuple[int, str]:
        with self._mutex:
            self._owner()
            row = self.db.execute(
                "SELECT sequence,content_hash FROM stream_cursors WHERE run_id=? AND "
                "stream_id=? AND generation=? ORDER BY sequence DESC LIMIT 1",
                (self.run_id, stream_id, int(generation)),
            ).fetchone()
            return (0, ZERO) if row is None else (int(row[0]), str(row[1]))

    def _binding_ids(self, event: dict[str, Any]) -> list[str]:
        kind, payload = event["payload_type"], event["payload"]
        bindings = self.bindings()
        if kind == "BindingChange":
            after = payload["after"]
            if any(
                b["provider_fixture_id"] == after["provider_fixture_id"]
                and b["binding_id"] != after["binding_id"]
                for b in bindings.values()
            ):
                raise ValueError("E_LIVE_BINDING_DUPLICATE")
            if (
                after["binding_id"] not in bindings
                and len(bindings)
                >= self.db.execute(
                    "SELECT max_matches FROM run_meta WHERE run_id=?", (self.run_id,)
                ).fetchone()[0]
            ):
                raise ValueError("E_LIVE_BINDING_SCOPE")
            return [str(after["binding_id"])]
        if kind == "ProviderState":
            ids = [
                i for i, b in bindings.items() if b["provider_fixture_id"] == payload["fixture_id"]
            ]
        elif kind == "HealthChange" and payload["binding_id"] is None:
            return list(bindings)
        else:
            ids = [payload["binding_id"]] if payload["binding_id"] in bindings else []
        if not ids:
            raise ValueError("E_LIVE_BINDING_REQUIRED")
        return ids

    def _stream_check(self, event: dict[str, Any]) -> None:
        stream, generation = event["stream_id"], int(event["generation"])
        previous = self.db.execute(
            "SELECT generation,source_kind,payload_canonical,receive_index FROM live_events "
            "WHERE run_id=? AND stream_id=? ORDER BY receive_index DESC LIMIT 1",
            (self.run_id, stream),
        ).fetchone()
        if previous is None:
            if generation != 0:
                raise ValueError("E_LIVE_GENERATION_REVIEW")
            return
        if (
            previous[1] != event["source_kind"]
            or generation < previous[0]
            or generation > previous[0] + 1
        ):
            raise ValueError("E_LIVE_STREAM_SCOPE")
        prior = json.loads(previous[2])
        if event["source_kind"] == "OPERATOR":
            if event["payload"]["binding_id"] != prior["payload"]["binding_id"]:
                raise ValueError("E_LIVE_BINDING_STREAM")
            if (
                generation == previous[0]
                and event["payload"]["document_epoch"] != prior["payload"]["document_epoch"]
            ):
                raise ValueError("E_LIVE_GENERATION_REVIEW")
        if generation > previous[0] and (
            event["source_kind"] != "OPERATOR"
            or event["payload"]["binding_revision"] == prior["payload"]["binding_revision"]
            or event["payload"]["document_epoch"] == prior["payload"]["document_epoch"]
        ):
            raise ValueError("E_LIVE_GENERATION_REVIEW")
        if generation == previous[0] and int(event["received_mono_us"]) < int(
            prior["received_mono_us"]
        ):
            raise ValueError("E_LIVE_STREAM_CLOCK")
        health_stream = str(uuid5(UUID(stream), "BH-LIVE-STORE/health"))
        controls = self.db.execute(
            "SELECT payload_canonical FROM live_events WHERE run_id=? AND stream_id=?",
            (self.run_id, health_stream),
        )
        if any(
            (p := json.loads(r[0])["payload"])["reason"] == "STREAM_CONFLICT"
            and int(p["epoch"]) == generation
            for r in controls
        ):
            raise ValueError("E_LIVE_STREAM_FROZEN")

    def _control_rejection(self, event: dict[str, Any], reason: str) -> None:
        if event["source_kind"] == "CONTROL":
            return
        ids = self._binding_ids(event)
        stream = str(uuid5(UUID(event["stream_id"]), "BH-LIVE-STORE/health"))
        sequence, previous = self.cursor(stream)
        control = {
            **event,
            "source_kind": "CONTROL",
            "stream_id": stream,
            "generation": "0",
            "sequence": str(sequence + 1),
            "observation_id": str(uuid4()),
            "payload_type": "HealthChange",
            "previous_hash": previous,
            "content_hash": ZERO,
            "payload": {
                "binding_id": ids[0] if len(ids) == 1 else None,
                "state": "PAUSED" if reason == "STREAM_CONFLICT" else "GAP",
                "reason": reason,
                "epoch": event["generation"],
                "evidence_hashes": [event["content_hash"]],
            },
        }
        control["content_hash"] = event_hash(control)
        self._append(control)

    def append(self, event: object) -> DurableReceipt:
        record = validate_live_record(event, "LiveEvent")
        if record["run_id"] != self.run_id or event_hash(record) != record["content_hash"]:
            raise ValueError("E_LIVE_EVENT_HASH_OR_RUN")
        _timestamp(record["observed_at_utc"])
        if (
            record["payload_type"] in {"ProviderState", "MarketBook"}
            and record["observed_at_utc"] != record["payload"]["observed_at_utc"]
        ):
            raise ValueError("E_LIVE_EVENT_OBSERVATION_TIME")
        with self._mutex:
            self._owner()
            try:
                return self._append(record)
            except ValueError as error:
                if str(error) in {"E_LIVE_STREAM_CONFLICT", "E_LIVE_SEQUENCE_GAP"}:
                    self._control_rejection(
                        record,
                        "STREAM_CONFLICT" if str(error).endswith("CONFLICT") else "SEQUENCE_GAP",
                    )
                raise

    def _append(self, event: dict[str, Any]) -> DurableReceipt:
        canonical = rfc8785.dumps(event)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            position = (
                self.run_id,
                event["stream_id"],
                int(event["generation"]),
                int(event["sequence"]),
            )
            existing = self.db.execute(
                "SELECT receive_index,payload_canonical FROM live_events WHERE run_id=? AND "
                "stream_id=? AND generation=? AND sequence=?",
                position,
            ).fetchone()
            if existing and existing[1] == canonical:
                self._verify_receipt(int(existing[0]), event)
                self.db.execute("COMMIT")
                return DurableReceipt(
                    int(existing[0]),
                    *position[:2],
                    event["generation"],
                    event["sequence"],
                    event["content_hash"],
                )
            if self.db.execute(
                "SELECT 1 FROM run_closures WHERE run_id=?", (self.run_id,)
            ).fetchone():
                raise ValueError("E_LIVE_RUN_CLOSED")
            self._stream_check(event)
            if existing:
                raise ValueError("E_LIVE_STREAM_CONFLICT")
            sequence, previous_hash = self.cursor(event["stream_id"], event["generation"])
            if int(event["sequence"]) != sequence + 1:
                raise ValueError("E_LIVE_SEQUENCE_GAP")
            if event["previous_hash"] != previous_hash:
                raise ValueError("E_LIVE_CURSOR_MISMATCH")
            ids = self._binding_ids(event)
            projections = []
            for binding_id in ids:
                row = self.db.execute(
                    "SELECT revision FROM projection_versions WHERE run_id=? AND "
                    "binding_id=? ORDER BY revision DESC LIMIT 1",
                    (self.run_id, binding_id),
                ).fetchone()
                prior = None if row is None else self.read_projection(binding_id)
                view = reduce_projection(prior, event)
                projections.append(
                    (
                        binding_id,
                        1 if row is None else row[0] + 1,
                        rfc8785.dumps(view),
                        view_hash(view),
                    )
                )
            used = sum(p.stat().st_size for p in self.path.parent.iterdir() if p.is_file())
            if (
                used + 2 * len(canonical) + sum(len(p[2]) for p in projections) + 65536
                > self.max_bytes
            ):
                raise ValueError("E_LIVE_STORE_CAP")
            index = self.db.execute(
                "SELECT coalesce(max(receive_index),0)+1 FROM live_events"
            ).fetchone()[0]
            self.db.execute(
                "INSERT INTO live_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    index,
                    *position[:3],
                    position[3],
                    event["observation_id"],
                    event["source_kind"],
                    event["payload_type"],
                    canonical,
                    event["previous_hash"],
                    event["content_hash"],
                    event["observed_at_utc"],
                    int(event["received_mono_us"]),
                ),
            )
            self.db.execute(
                "INSERT INTO "
                "stream_cursors(receive_index,run_id,stream_id,generation,sequence,content_hash) "
                "VALUES(?,?,?,?,?,?)",
                (index, *position, event["content_hash"]),
            )
            for binding_id, revision, payload, digest in projections:
                self.db.execute(
                    "INSERT INTO "
                    "projection_versions(receive_index,run_id,binding_id,revision,"
                    "canonical_view,content_hash) "
                    "VALUES(?,?,?,?,?,?)",
                    (index, self.run_id, binding_id, revision, payload, digest),
                )
            if event["payload_type"] == "ProviderState":
                p = event["payload"]
                self.db.execute(
                    "INSERT INTO request_links VALUES(?,?,?)",
                    (index, p["request_id"], p["batch_observation_id"]),
                )
            self.db.execute("COMMIT")
            self._verify_receipt(index, event)
            row = self.db.execute(
                "SELECT payload_canonical FROM live_events WHERE receive_index=?", (index,)
            ).fetchone()
            if row is None or row[0] != canonical:
                raise ValueError("E_LIVE_POSTCOMMIT_READBACK")
            return DurableReceipt(
                index,
                self.run_id,
                event["stream_id"],
                event["generation"],
                event["sequence"],
                event["content_hash"],
            )
        except BaseException as error:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                raise ValueError("E_LIVE_STORE_IO") from None
            raise

    def _verify_receipt(self, index: int, event: dict[str, Any]) -> None:
        cursor = self.db.execute(
            "SELECT run_id,stream_id,generation,sequence,content_hash FROM stream_cursors "
            "WHERE receive_index=?",
            (index,),
        ).fetchone()
        expected = (
            self.run_id,
            event["stream_id"],
            int(event["generation"]),
            int(event["sequence"]),
            event["content_hash"],
        )
        if cursor != expected:
            raise ValueError("E_LIVE_POSTCOMMIT_CURSOR")
        projections = self.db.execute(
            "SELECT canonical_view,content_hash FROM projection_versions WHERE receive_index=?",
            (index,),
        ).fetchall()
        if event["payload_type"] != "HealthChange" and len(projections) != 1:
            raise ValueError("E_LIVE_POSTCOMMIT_PROJECTION")
        for canonical, digest in projections:
            view = cast(dict[str, Any], parse_strict_json(canonical))
            if rfc8785.dumps(view) != canonical or view_hash(view) != digest:
                raise ValueError("E_LIVE_POSTCOMMIT_PROJECTION")
        links = self.db.execute(
            "SELECT request_id,batch_observation_id FROM request_links WHERE receive_index=?",
            (index,),
        ).fetchall()
        expected_links = (
            []
            if event["payload_type"] != "ProviderState"
            else [(event["payload"]["request_id"], event["payload"]["batch_observation_id"])]
        )
        if links != expected_links:
            raise ValueError("E_LIVE_POSTCOMMIT_REQUEST_LINK")

    def close_run(self, closed_at_utc: str, reason_code: str) -> None:
        _timestamp(closed_at_utc)
        if reason_code not in {
            "USER_STOP",
            "RUN_DEADLINE",
            "SOURCE_STOPPED",
            "STORAGE_CAP",
            "SECURITY_HOLD",
        }:
            raise ValueError("E_LIVE_CLOSE_REASON")
        with self._mutex:
            self._owner()
            row = (
                self.run_id,
                closed_at_utc,
                reason_code,
                self.db.execute("SELECT max(receive_index) FROM live_events").fetchone()[0],
            )
            old = self.db.execute(
                "SELECT * FROM run_closures WHERE run_id=?", (self.run_id,)
            ).fetchone()
            if old is not None:
                if old != row:
                    raise ValueError("E_LIVE_RUN_CLOSED")
                return
            self.db.execute("INSERT INTO run_closures VALUES(?,?,?,?)", row)
