# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from moj_discovery.review_aggregation import aggregate_independent_reviews
from tools.bootstrap_review_authority import bootstrap_review_authority
from tools.finalize_review import _validate_consumed_authorization


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--review-a", required=True, type=Path)
    parser.add_argument("--receipt-a", required=True, type=Path)
    parser.add_argument("--authorization-a", required=True, type=Path)
    parser.add_argument("--review-b", required=True, type=Path)
    parser.add_argument("--receipt-b", required=True, type=Path)
    parser.add_argument("--authorization-b", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    authorization_a = json.loads(args.authorization_a.read_text())
    authorization_b = json.loads(args.authorization_b.read_text())
    authority = json.loads((RUNTIME_ROOT / "review-config/review-authority.v1.json").read_text())
    bootstrap_review_authority(authority, initialize_if_absent=False)
    _validate_consumed_authorization(authorization_a, authority)
    _validate_consumed_authorization(authorization_b, authority)
    private = serialization.load_pem_private_key(
        Path(cast(str, authority["private_key_path"])).read_bytes(), password=None
    )
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("E_REVIEW_AUTH_BINDING")
    result = aggregate_independent_reviews(
        json.loads(args.review_a.read_text()), json.loads(args.review_b.read_text()),
        json.loads(args.receipt_a.read_text()), json.loads(args.receipt_b.read_text()),
        authorization_a, authorization_b, private.public_key(),
        json.loads(args.config.read_text()),
        expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        expected_trust_epoch=cast(int, authorization_a["trust_epoch"]),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
