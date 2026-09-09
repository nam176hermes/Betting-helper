"""Rebuild a closed run from recorded canonical events into a fresh physical database."""

import fcntl
import hashlib
import os
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import rfc8785

from .canonical import parse_strict_json
from .live_contracts import event_hash, validate_live_record
from .live_store import MAX_BYTES, TABLES, LiveStore, verify_live_database


@dataclass(frozen=True)
class ReplayResult:
    equal: bool
    events: int
    logical_sha256: str
    source_database_sha256: str
    replay_database_sha256: str


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def logical_state_hash(db: sqlite3.Connection) -> str:
    digest = hashlib.sha256(b"BH-LIVE-READONLY/Database/v1\0")
    for table in TABLES:
        digest.update(table.encode() + b"\0")
        for row in db.execute("SELECT * FROM " + table + " ORDER BY 1,2"):  # noqa: S608 - closed table enum
            digest.update(
                rfc8785.dumps([{"bytes_hex": v.hex()} if type(v) is bytes else v for v in row])
                + b"\n"
            )
    return digest.hexdigest()


def _record(row: tuple[Any, ...], expected_index: int) -> dict[str, Any]:
    if row[0] != expected_index or not isinstance(row[8], bytes):
        raise ValueError("E_LIVE_REPLAY_RECEIVE_ORDER")
    event = validate_live_record(parse_strict_json(row[8]), "LiveEvent")
    if rfc8785.dumps(event) != row[8] or event_hash(event) != event["content_hash"]:
        raise ValueError("E_LIVE_REPLAY_HASH")
    expected = (
        expected_index,
        event["run_id"],
        event["stream_id"],
        int(event["generation"]),
        int(event["sequence"]),
        event["observation_id"],
        event["source_kind"],
        event["payload_type"],
        row[8],
        event["previous_hash"],
        event["content_hash"],
        event["observed_at_utc"],
        int(event["received_mono_us"]),
    )
    if row != expected:
        raise ValueError("E_LIVE_REPLAY_COLUMNS")
    return event


def verify_live_replay(run_dir: Path, target_dir: Path) -> ReplayResult:
    source = run_dir / "live.sqlite3"
    if (
        not source.is_file()
        or any(p.is_symlink() for p in (source, *source.parents))
        or source.stat().st_size > MAX_BYTES
    ):
        raise ValueError("E_LIVE_REPLAY_SOURCE")
    if target_dir.exists() or any(p.is_symlink() for p in (target_dir, *target_dir.parents)):
        raise ValueError("E_LIVE_REPLAY_TARGET")
    try:
        lock = os.open(str(source) + ".lock", os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ValueError("E_LIVE_REPLAY_LOCK") from None
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("E_LIVE_REPLAY_WRITER_ACTIVE") from None
        before_hash = file_hash(source)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
            original.execute("PRAGMA query_only=ON")
            original.execute("PRAGMA trusted_schema=OFF")
            original.execute("BEGIN")
            verify_live_database(original)
            metas = original.execute("SELECT * FROM run_meta").fetchall()
            closures = original.execute("SELECT * FROM run_closures").fetchall()
            if len(metas) != 1 or len(closures) != 1:
                raise ValueError("E_LIVE_REPLAY_NOT_CLOSED")
            meta, closure = metas[0], closures[0]
            target_dir.mkdir(mode=0o700)
            with LiveStore(
                target_dir / "live.sqlite3",
                run_id=meta[0],
                source_tree_hash=meta[1],
                config_hash=meta[2],
                started_utc=meta[3],
                max_matches=meta[5],
            ) as replay:
                events = 0
                for events, row in enumerate(
                    original.execute("SELECT * FROM live_events ORDER BY receive_index"), start=1
                ):
                    event = _record(row, events)
                    receipt = replay.append(event)
                    if receipt.receive_index != events:
                        raise ValueError("E_LIVE_REPLAY_CURSOR")
                replay.close_run(closure[1], closure[2])
                logical = logical_state_hash(replay.db)
                if logical_state_hash(original) != logical:
                    raise ValueError("E_LIVE_REPLAY_MISMATCH")
            original.execute("COMMIT")
        if file_hash(source) != before_hash:
            raise ValueError("E_LIVE_REPLAY_SOURCE_CHANGED")
        result = ReplayResult(
            True, events, logical, before_hash, file_hash(target_dir / "live.sqlite3")
        )
        output = target_dir / "replay-result.json"
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as report:
            report.write(rfc8785.dumps(asdict(result)))
            report.flush()
            os.fsync(report.fileno())
        return result
    except sqlite3.Error:
        raise ValueError("E_LIVE_REPLAY_DATABASE") from None
    finally:
        os.close(lock)
