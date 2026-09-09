"""Export static diagnostics only after independently validating actual offline evidence."""

# ruff: noqa: E402
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.diagnostic import render_diagnostic
from tools.verify_offline_slice import verify_offline_slice


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input.parent / "diagnostic-export.html"
    try:
        boundary = args.input.resolve().parent
        if not output.resolve().is_relative_to(boundary) or any(
            p.is_symlink() for p in (output, *output.parents)
        ):
            raise ValueError("E_OFFLINE_DIAGNOSTIC_PATH")
        verified = verify_offline_slice(args.input)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as target:
            target.write(render_diagnostic(verified))
    except Exception:
        print("E_OFFLINE_DIAGNOSTIC_REJECTED", file=sys.stderr)
        return 1
    print(str(output.absolute()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
