"""Killable child for gap, generation, epoch, and clock durability checkpoints."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import sleep


def contract_not_implemented() -> None:
    raise RuntimeError("E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vector-id", required=True)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    if args.ready is not None:
        args.ready.write_text(json.dumps({"vector_id": args.vector_id}))
    if args.hold:
        while True:
            sleep(1)
    print(json.dumps({"vector_id": args.vector_id}, sort_keys=True))


if __name__ == "__main__":
    main()
