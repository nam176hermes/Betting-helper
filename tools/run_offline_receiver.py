"""Run a loopback receiver; ephemeral credentials arrive only on private stdin."""

# ruff: noqa: E402
import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from websockets.asyncio.server import ServerConnection

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from moj_discovery.canonical import parse_strict_json
from moj_discovery.input_journal import InputJournal
from moj_discovery.offline_faults import WriteDeniedStore
from moj_discovery.offline_receiver import serve_offline


async def run(run_dir: Path, fault: str | None = None) -> None:
    journal = InputJournal(run_dir)
    journal.reconcile(journal.store)
    if fault in {"AFTER_RECEIVED", "AFTER_APPLY"}:

        def observer(stage: str, index: int) -> None:
            if stage == fault and index == 1:
                import rfc8785

                with (run_dir / "checkpoint.json").open("xb") as output:
                    output.write(
                        rfc8785.dumps(
                            {
                                "stage": stage,
                                "receive_index": index,
                                "pid": os.getpid(),
                                "run_id": journal.context["run_id"],
                            }
                        )
                    )
                    output.flush()
                    os.fsync(output.fileno())
                os.kill(os.getpid(), signal.SIGSTOP)

        journal.observer = observer
    if fault == "SQLITE_DENY_THIRD":
        journal.store = WriteDeniedStore(journal.store.db_path, run_dir / "sqlite-faults.jsonl")
    keys: dict[str, bytes] = {}
    receiver = await serve_offline(journal.context, keys.get, journal.store, journal)
    if fault in {"DROP_ACK", "FAKE_ACK"}:
        used = False

        async def before_send(socket: ServerConnection, kind: str, body: dict[str, Any]) -> bool:
            nonlocal used
            if kind == "ACK" and not used:
                used = True
                import rfc8785

                (run_dir / "wire-fault.json").write_bytes(
                    rfc8785.dumps(
                        {
                            "fault": fault,
                            "run_id": journal.context["run_id"],
                            "pid": os.getpid(),
                            "sequence": body["highest_contiguous_sequence"],
                        }
                    )
                )
                if fault == "DROP_ACK":
                    await socket.close(1000, "OFFLINE_ACK_LOSS")
                    return False
                body["cursor_hash"] = "0" * 64
            return True

        receiver.before_send = before_send
    try:
        print('{"status":"LISTENING","pid":' + str(os.getpid()) + "}", flush=True)
        while True:
            line = await asyncio.to_thread(sys.stdin.buffer.readline, 4097)
            if not line:
                break
            if len(line) > 4096 or not line.endswith(b"\n"):
                raise ValueError("E_OFFLINE_CONTROL")
            command = parse_strict_json(line)
            if command == {"operation": "STOP"}:
                break
            if (
                not isinstance(command, dict)
                or set(command) != {"operation", "session_id", "key_hex"}
                or command["operation"] != "REGISTER_SESSION"
            ):
                raise ValueError("E_OFFLINE_CONTROL")
            sid = command["session_id"]
            if str(UUID(sid, version=4)) != sid or sid in keys or len(keys) >= 128:
                raise ValueError("E_OFFLINE_CONTROL")
            key = bytes.fromhex(command["key_hex"])
            if len(key) != 32:
                raise ValueError("E_OFFLINE_CONTROL")
            keys[sid] = key
            print('{"status":"REGISTERED"}', flush=True)
    finally:
        await receiver.close()
        keys.clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--fault",
        choices=["AFTER_RECEIVED", "AFTER_APPLY", "SQLITE_DENY_THIRD", "DROP_ACK", "FAKE_ACK"],
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.run_dir, args.fault))
    except Exception:
        print("E_OFFLINE_RECEIVER_STOPPED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
