import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from moj_discovery.pack_verifier import (  # noqa: E402
    BASELINE_RECEIPT_PATH,
    COMMAND_RESULT_PATH,
    RUNTIME_ROOT,
    build_repo0_baseline_receipt,
    verify_repository_baseline,
    write_repo0_baseline_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--accepted-result-set", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (
        args.runtime_root.absolute() != RUNTIME_ROOT
        or args.accepted_result_set.absolute() != COMMAND_RESULT_PATH
        or args.output.absolute() != BASELINE_RECEIPT_PATH
    ):
        raise ValueError("E_REPO0_RECEIPT_PATH")
    receipt = build_repo0_baseline_receipt(
        args.runtime_root.absolute(), args.accepted_result_set.absolute()
    )
    write_repo0_baseline_receipt(args.output.absolute(), receipt)
    errors = verify_repository_baseline(
        args.runtime_root.absolute(),
        receipt_path=args.output.absolute(),
        command_result_path=args.accepted_result_set.absolute(),
    )
    if errors:
        raise ValueError(errors[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
