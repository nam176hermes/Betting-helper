"""Durable sanitized delivery evidence alongside the shared ingest journal."""

import copy
import hashlib
import os
import re
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import rfc8785

from .canonical import parse_strict_json
from .ingest import Ingestor
from .offline_protocol import validate_context
from .store import RunStore, read_journal, validate_journal
from .synthetic_source import validate_synthetic_observation

DOMAIN = b"BH-OFFLINE-JOURNAL/v1\0"
HEX = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ERRORS = {
    "E_INGEST_GAP": "GAP",
    "E_INGEST_CONFLICT": "CONFLICT",
    "E_INGEST_GENERATION_CLOSED": "CLOSED_GENERATION",
}


def _read(path: Path, maximum: int = 16777216) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise ValueError("E_OFFLINE_FILE_INTEGRITY")
        return source.read(maximum + 1)


def _sync(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class InputJournal:
    def __init__(self, run_dir: Path, observer: Callable[[str, int], None] | None = None):
        self.observer = observer
        if any(path.is_symlink() for path in (run_dir, *run_dir.parents)):
            raise ValueError("E_OFFLINE_RUN_PATH")
        self.root = run_dir.absolute()
        if (self.root / "raw").is_symlink() or not (self.root / "raw").is_dir():
            raise ValueError("E_OFFLINE_RUN_PATH")
        self.context = cast(
            dict[str, Any], parse_strict_json(_read(self.root / "context.json", 262144))
        )
        validate_context(self.context)
        self.path = self.root / "receive.jsonl"
        self.store = RunStore(self.root / "run.sqlite3")
        self._verified_bytes = b""
        self._verified_rows: list[dict[str, Any]] = []

    def _rows(self) -> list[dict[str, Any]]:
        if any(path.is_symlink() for path in (self.root, *self.root.parents, self.root / "raw")):
            raise ValueError("E_OFFLINE_RUN_PATH")
        if not self.path.exists() and not self.path.is_symlink():
            if self._verified_bytes:
                raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
            return []
        data = _read(self.path)
        # Re-read every byte; same-size or restored-mtime tampering invalidates reuse.
        if data == self._verified_bytes:
            return self._verified_rows
        if not data.startswith(self._verified_bytes):
            raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
        if data and not data.endswith(b"\n"):
            raise ValueError("E_OFFLINE_JOURNAL_PARTIAL_TAIL")
        rows = []
        previous = "0" * 64
        receives: set[int] = set()
        outcomes: set[int] = set()
        for index, line in enumerate(data.splitlines(), 1):
            row = cast(dict[str, Any], parse_strict_json(line))
            common = {
                "row_index",
                "kind",
                "reference_receive_index",
                "previous_row_hash",
                "row_hash",
            }
            fields = {
                "RECEIVED": {"raw_hash", "batch_id", "generation", "sequence"},
                "OUTCOME": {"outcome"},
                "ACK_CONFIRMATION": {"generation", "sequence", "cursor_hash"},
                "PARTIAL_TAIL": {"artifact", "artifact_sha256"},
            }
            if (
                not isinstance(row, dict)
                or row.get("kind") not in fields
                or set(row) != common | fields[row["kind"]]
                or type(row["row_index"]) is not int
                or row["row_index"] != index
                or row["previous_row_hash"] != previous
                or rfc8785.dumps(row) != line
            ):
                raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
            digest = hashlib.sha256(
                DOMAIN + rfc8785.dumps({k: v for k, v in row.items() if k != "row_hash"})
            ).hexdigest()
            if row["row_hash"] != digest:
                raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
            reference = row["reference_receive_index"]
            if row["kind"] == "RECEIVED":
                if (
                    type(reference) is not int
                    or reference != len(receives) + 1
                    or not HEX.fullmatch(row["raw_hash"])
                    or not UUID.fullmatch(row["batch_id"])
                ):
                    raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
                receives.add(reference)
            elif row["kind"] == "OUTCOME":
                if reference not in receives or reference in outcomes:
                    raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
                outcomes.add(reference)
            elif reference is not None:
                raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
            rows.append(row)
            previous = digest
        self._verified_bytes, self._verified_rows = data, rows
        return rows

    def _append(self, value: dict[str, Any]) -> None:
        rows = self._rows()
        row = {
            "row_index": len(rows) + 1,
            "previous_row_hash": rows[-1]["row_hash"] if rows else "0" * 64,
            **value,
        }
        row["row_hash"] = hashlib.sha256(DOMAIN + rfc8785.dumps(row)).hexdigest()
        descriptor = os.open(
            self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "ab") as output:
            info = os.fstat(output.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size != len(self._verified_bytes)
            ):
                raise ValueError("E_OFFLINE_FILE_INTEGRITY")
            encoded = rfc8785.dumps(row) + b"\n"
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        _sync(self.root)
        self._verified_bytes += encoded
        self._verified_rows = [*rows, copy.deepcopy(row)]

    def record_received(self, raw_bytes: bytes, batch_id: str) -> int:
        if not UUID.fullmatch(batch_id):
            raise ValueError("E_OFFLINE_SCHEMA")
        self._rows()
        raw = validate_synthetic_observation(raw_bytes, self.context)
        data = rfc8785.dumps(raw)
        path = self.root / "raw" / (raw["content_hash"] + ".json")
        if path.exists() or path.is_symlink():
            if _read(path, 65536) != data:
                raise ValueError("E_OFFLINE_RAW_CONFLICT")
        else:
            temporary = self.root / "raw" / (".pending-" + str(uuid4()))
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            _sync(path.parent)
        receive_index = sum(1 for row in self._rows() if row["kind"] == "RECEIVED") + 1
        self._append(
            {
                "kind": "RECEIVED",
                "reference_receive_index": receive_index,
                "raw_hash": raw["content_hash"],
                "batch_id": batch_id,
                "generation": raw["generation"],
                "sequence": raw["sequence"],
            }
        )
        return receive_index

    def record_outcome(self, receive_index: int, outcome: dict[str, Any]) -> None:
        self._record_outcome(receive_index, outcome)

    def _record_outcome(
        self,
        receive_index: int,
        outcome: dict[str, Any],
        applied_raw: dict[str, Any] | None = None,
    ) -> None:
        rows = self._rows()
        received = [
            r
            for r in rows
            if r["kind"] == "RECEIVED" and r["reference_receive_index"] == receive_index
        ]
        if len(received) != 1:
            raise ValueError("E_OFFLINE_OUTCOME_BINDING")
        existing = [
            r
            for r in rows
            if r["kind"] == "OUTCOME" and r["reference_receive_index"] == receive_index
        ]
        if existing:
            if existing[0]["outcome"] != outcome:
                raise ValueError("E_OFFLINE_OUTCOME_CONFLICT")
            return
        if outcome.get("status") == "APPLIED" and set(outcome) == {"status", "ack"}:
            ack = outcome["ack"]
            if applied_raw is not None:
                # Same synchronous invocation of real Ingestor.apply, after its commit.
                # No caller-supplied outcome or fault observer may use this proof.
                if (
                    applied_raw["content_hash"] != received[0]["raw_hash"]
                    or applied_raw["generation"] != received[0]["generation"]
                    or applied_raw["sequence"] != received[0]["sequence"]
                    or str(ack["generation"]) != received[0]["generation"]
                    or str(ack["highest_contiguous_sequence"]) != received[0]["sequence"]
                ):
                    raise ValueError("E_OFFLINE_OUTCOME_BINDING")
            else:
                with closing(self.store.connect()) as connection:
                    validate_journal(read_journal(connection, ordered=False))
                    raw_row = connection.execute(
                        "SELECT raw_observation_content_hash FROM raw_commits "
                        "WHERE raw_commit_id=?",
                        (ack.get("raw_commit_id"),),
                    ).fetchone()
                    actual = connection.execute(
                        "SELECT * FROM ack_outbox WHERE ack_outbox_id=?",
                        (ack.get("ack_outbox_id"),),
                    ).fetchone()
                if (
                    actual is None
                    or raw_row is None
                    or raw_row[0] != received[0]["raw_hash"]
                    or dict(actual) != ack
                    or str(ack["generation"]) != received[0]["generation"]
                    or str(ack["highest_contiguous_sequence"]) != received[0]["sequence"]
                ):
                    raise ValueError("E_OFFLINE_OUTCOME_BINDING")
        elif not (
            set(outcome) == {"status", "code"}
            and outcome["status"] == "REJECTED"
            and outcome["code"] in {"GAP", "CONFLICT", "CLOSED_GENERATION", "STORAGE_FAILED"}
        ):
            raise ValueError("E_OFFLINE_OUTCOME_BINDING")
        self._append(
            {"kind": "OUTCOME", "reference_receive_index": receive_index, "outcome": outcome}
        )

    def apply(self, raw_bytes: bytes, batch_id: str) -> dict[str, Any]:
        index = self.record_received(raw_bytes, batch_id)
        if self.observer:
            self.observer("AFTER_RECEIVED", index)
        raw = validate_synthetic_observation(raw_bytes, self.context)
        return self._apply_received(index, raw)

    def _apply_received(self, index: int, raw: dict[str, Any]) -> dict[str, Any]:
        try:
            outcome = {"status": "APPLIED", "ack": Ingestor(self.store).apply(raw)}
        except ValueError as error:
            if str(error) not in ERRORS:
                raise
            outcome = {"status": "REJECTED", "code": ERRORS[str(error)]}
        except (sqlite3.Error, OSError):
            outcome = {"status": "REJECTED", "code": "STORAGE_FAILED"}
        if self.observer:
            self.observer("AFTER_APPLY", index)
        self._record_outcome(index, outcome, raw if self.observer is None else None)
        return outcome

    def record_ack_confirmation(self, generation: str, sequence: str, cursor_hash: str) -> None:
        with closing(self.store.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM ack_outbox WHERE generation=? "
                "AND highest_contiguous_sequence=? AND cursor_hash=?",
                (int(generation), int(sequence), cursor_hash),
            ).fetchone()
        if row is None:
            raise ValueError("E_OFFLINE_ACK_BINDING")
        Ingestor(self.store).confirm_ack(dict(row))
        self._append(
            {
                "kind": "ACK_CONFIRMATION",
                "reference_receive_index": None,
                "generation": generation,
                "sequence": sequence,
                "cursor_hash": cursor_hash,
            }
        )

    def iter_operations(self) -> Iterator[dict[str, Any]]:
        for row in self._rows():
            if row["kind"] == "RECEIVED":
                data = _read(self.root / "raw" / (row["raw_hash"] + ".json"), 65536)
                raw = validate_synthetic_observation(data, self.context)
                if (
                    raw["content_hash"] != row["raw_hash"]
                    or raw["generation"] != row["generation"]
                    or raw["sequence"] != row["sequence"]
                    or rfc8785.dumps(raw) != data
                ):
                    raise ValueError("E_OFFLINE_RAW_BINDING")
                yield {**row, "raw": raw}
            else:
                if row["kind"] == "PARTIAL_TAIL":
                    if row["artifact"] != "partial-tail-" + row["artifact_sha256"] + ".jsonl":
                        raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
                    if (
                        hashlib.sha256(_read(self.root / row["artifact"])).hexdigest()
                        != row["artifact_sha256"]
                    ):
                        raise ValueError("E_OFFLINE_JOURNAL_INTEGRITY")
                yield copy.deepcopy(row)

    def reconcile(self, store: RunStore) -> dict[str, int]:
        if store.db_path.absolute() != self.store.db_path:
            raise ValueError("E_OFFLINE_RUN_PATH")
        if self.path.exists():
            data = _read(self.path)
            if data and not data.endswith(b"\n"):
                digest = hashlib.sha256(data).hexdigest()
                retained = self.root / ("partial-tail-" + digest + ".jsonl")
                if retained.exists():
                    raise ValueError("E_OFFLINE_PARTIAL_ALREADY_RETAINED")
                os.rename(self.path, retained)
                prefix = data[: data.rfind(b"\n") + 1]
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    output.write(prefix)
                    output.flush()
                    os.fsync(output.fileno())
                self._append(
                    {
                        "kind": "PARTIAL_TAIL",
                        "reference_receive_index": None,
                        "artifact": retained.name,
                        "artifact_sha256": digest,
                    }
                )
        operations = list(self.iter_operations())
        completed = {r["reference_receive_index"] for r in operations if r["kind"] == "OUTCOME"}
        repaired = 0
        for row in operations:
            if row["kind"] == "RECEIVED" and row["reference_receive_index"] not in completed:
                with closing(store.connect()) as connection:
                    validate_journal(read_journal(connection, ordered=False))
                    gap = connection.execute(
                        "SELECT * FROM gap_records WHERE gap_id=?", ("gap:" + row["raw_hash"],)
                    ).fetchone()
                    ack = connection.execute(
                        "SELECT a.* FROM ack_outbox a JOIN raw_commits r "
                        "ON a.raw_commit_id=r.raw_commit_id WHERE r.raw_observation_content_hash=?",
                        (row["raw_hash"],),
                    ).fetchone()
                if gap is not None:
                    if (
                        gap["run_id"] != self.context["run_id"]
                        or gap["stream_id"] != self.context["stream_id"]
                        or gap["detected_sequence"] != int(row["sequence"])
                    ):
                        raise ValueError("E_OFFLINE_OUTCOME_BINDING")
                    code = {"MISSING_SEQUENCE": "GAP", "CONFLICTING_DUPLICATE": "CONFLICT"}[
                        gap["gap_reason"]
                    ]
                    self.record_outcome(
                        row["reference_receive_index"], {"status": "REJECTED", "code": code}
                    )
                elif ack is not None:
                    self.record_outcome(
                        row["reference_receive_index"], {"status": "APPLIED", "ack": dict(ack)}
                    )
                else:
                    self._apply_received(row["reference_receive_index"], row["raw"])
                repaired += 1
        return {"reconciled_operations": repaired}
