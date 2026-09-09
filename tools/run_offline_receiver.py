"""Run a loopback receiver; ephemeral credentials arrive only on private stdin."""

# ruff: noqa: E402
import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from moj_discovery.canonical import parse_strict_json
from moj_discovery.input_journal import InputJournal
from moj_discovery.offline_receiver import serve_offline


async def run(run_dir: Path) -> None:
    journal = InputJournal(run_dir)
    journal.reconcile(journal.store)
    keys: dict[str, bytes] = {}
    receiver = await serve_offline(journal.context, keys.get, journal.store, journal)
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
    args = parser.parse_args()
    try:
        asyncio.run(run(args.run_dir))
    except Exception:
        print("E_OFFLINE_RECEIVER_STOPPED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
