"""Reconstruct observed deliveries in a fresh store through the actual shared ingest."""

import hashlib
from pathlib import Path
from typing import Any

import rfc8785

from .input_journal import InputJournal
from .offline_projection import semantic_projection
from .offline_run import create_offline_run


def verify_replay_equivalence(run_dir: Path, replay_dir: Path) -> dict[str, Any]:
    original = InputJournal(run_dir)
    original.reconcile(original.store)
    operations = list(original.iter_operations())
    expected_actual = semantic_projection(original.store.db_path)
    replay_store = create_offline_run(replay_dir, original.context)
    replay = InputJournal(replay_dir)
    applied: dict[int, dict[str, Any]] = {}
    for operation in operations:
        kind = operation["kind"]
        if kind == "RECEIVED":
            applied[operation["reference_receive_index"]] = replay.apply(
                rfc8785.dumps(operation["raw"]), operation["batch_id"]
            )
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
            replay.record_ack_confirmation(
                operation["generation"], operation["sequence"], operation["cursor_hash"]
            )
        elif kind != "PARTIAL_TAIL":
            raise ValueError("E_OFFLINE_REPLAY_OPERATION")
    actual = semantic_projection(replay_store.db_path)
    if actual != expected_actual:
        raise ValueError("E_OFFLINE_REPLAY_MISMATCH")
    result: dict[str, Any] = {
        "equal": True,
        "deliveries": len(applied),
        "projection_sha256": hashlib.sha256(rfc8785.dumps(actual)).hexdigest(),
    }
    (replay_dir / "replay-result.json").write_bytes(rfc8785.dumps(result))
    return result
