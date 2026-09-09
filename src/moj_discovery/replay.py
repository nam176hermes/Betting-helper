"""Reconstruct observed deliveries in a fresh store through the actual shared ingest."""

import argparse
import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from time import monotonic, sleep
from typing import Any

import rfc8785

from .ingest import Ingestor
from .input_journal import ERRORS, InputJournal, _read
from .offline_faults import WriteDeniedStore
from .offline_projection import semantic_projection
from .offline_run import create_offline_run


def _operations(original: InputJournal, writer_closed: Path | None) -> Iterator[dict[str, Any]]:
    consumed: list[dict[str, Any]] = []
    deadline = monotonic() + 120
    while writer_closed is not None and not writer_closed.exists():
        if monotonic() >= deadline:
            raise TimeoutError("E_OFFLINE_REPLAY_TIMEOUT")
        batch = list(original.iter_operations(start=len(consumed), complete_prefix=True))
        consumed.extend(batch)
        yield from batch
        sleep(0.25)
    # Reopen every retained input after the writer stops; cached observations alone
    # cannot prove that source bytes survived or that the final journal is complete.
    original.reconcile(original.store)
    final = list(original.iter_operations())
    if final[: len(consumed)] != consumed:
        raise ValueError("E_OFFLINE_REPLAY_SOURCE_CHANGED")
    yield from final[len(consumed) :]


def verify_replay_equivalence(
    run_dir: Path, replay_dir: Path, *, writer_closed: Path | None = None
) -> dict[str, Any]:
    original = InputJournal(run_dir)
    operations = _operations(original, writer_closed)
    replay_store = create_offline_run(replay_dir, original.context)
    fault_path = run_dir / "sqlite-faults.jsonl"
    if fault_path.exists():
        # Replay the recorded SQLite fault mechanism, never a supplied outcome string.
        replay_store = WriteDeniedStore(replay_store.db_path, replay_dir / "sqlite-faults.jsonl")
    replay = Ingestor(replay_store)
    acks: dict[tuple[str, str, str], dict[str, Any]] = {}
    applied: dict[int, dict[str, Any]] = {}
    for operation in operations:
        kind = operation["kind"]
        if kind == "RECEIVED":
            try:
                ack = replay.apply(operation["raw"])
                outcome = {"status": "APPLIED", "ack": ack}
                acks[
                    (
                        str(ack["generation"]),
                        str(ack["highest_contiguous_sequence"]),
                        ack["cursor_hash"],
                    )
                ] = ack
            except ValueError as error:
                if str(error) not in ERRORS:
                    raise
                outcome = {"status": "REJECTED", "code": ERRORS[str(error)]}
            except (sqlite3.Error, OSError):
                outcome = {"status": "REJECTED", "code": "STORAGE_FAILED"}
            applied[operation["reference_receive_index"]] = outcome
        elif kind == "OUTCOME":
            observed = applied[operation["reference_receive_index"]]
            recorded = operation["outcome"]

            def logical(outcome: dict[str, Any]) -> dict[str, Any]:
                if outcome["status"] != "APPLIED":
                    return outcome
                return {
                    **outcome,
                    "ack": {k: v for k, v in outcome["ack"].items() if k != "committed_at_us"},
                }

            if logical(observed) != logical(recorded):
                raise ValueError("E_OFFLINE_REPLAY_OUTCOME")
        elif kind == "ACK_CONFIRMATION":
            key = (operation["generation"], operation["sequence"], operation["cursor_hash"])
            if key not in acks:
                raise ValueError("E_OFFLINE_ACK_BINDING")
            replay.confirm_ack(acks[key])
        elif kind != "PARTIAL_TAIL":
            raise ValueError("E_OFFLINE_REPLAY_OPERATION")
    expected_actual = semantic_projection(original.store.db_path)
    actual = semantic_projection(replay_store.db_path)
    if fault_path.exists() and _read(fault_path) != _read(replay_dir / "sqlite-faults.jsonl"):
        raise ValueError("E_OFFLINE_REPLAY_FAULT")
    if actual != expected_actual:
        raise ValueError("E_OFFLINE_REPLAY_MISMATCH")
    result: dict[str, Any] = {
        "equal": True,
        "deliveries": len(applied),
        "projection_sha256": hashlib.sha256(rfc8785.dumps(actual)).hexdigest(),
    }
    (replay_dir / "replay-result.json").write_bytes(rfc8785.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("replay_dir", type=Path)
    parser.add_argument("--writer-closed", type=Path, required=True)
    args = parser.parse_args()
    verify_replay_equivalence(args.run_dir, args.replay_dir, writer_closed=args.writer_closed)
