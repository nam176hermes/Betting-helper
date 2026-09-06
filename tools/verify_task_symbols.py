"""Resolve explicitly declared Python symbols from safe source paths."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from moj_discovery.symbol_inventory import resolve_python_symbol


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    resolve_python_symbol(args.source, args.symbol)
    print("PASS")


if __name__ == "__main__":
    main()
