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
from tools.build_candidate_qualification_receipt import _read_bytes
from tools.finalize_review import _validate_consumed_authorization
from tools.full_verifier_config import FullVerifierConfig
from tools.issue_review_launch_authorization import (
    _regular_hash,
    _scope_record,
    authorized_review_context,
    recheck_review_context,
    review_public_key,
    validate_review_scope,
)
from tools.retained_artifact_io import RetainedArtifactIO


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
    config = json.loads(args.config.read_text())
    context_a = context_b = None
    if config.get("schema_version") == "review-aggregation-config/v2" or any(
        auth.get("schema_version") == "review-launch-authorization/v2"
        for auth in (authorization_a, authorization_b)
    ):
        if config.get("schema_version") != "review-aggregation-config/v2":
            raise ValueError("E_REVIEW_AUTH_BINDING")
        context_a = authorized_review_context(authorization_a, authority, runtime_root=RUNTIME_ROOT)
        context_b = authorized_review_context(authorization_b, authority, runtime_root=RUNTIME_ROOT)
        if (
            context_a["transport"] != context_b["transport"]
            or context_a["seal"] != context_b["seal"]
            or context_a["mounts"] != context_b["mounts"]
        ):
            raise ValueError("E_REVIEW_AUTH_BINDING")
        pack = Path(cast(list[dict[str, str]], context_a["mounts"])[0]["source_root"])
        named = pack / "docs/configs/review-aggregation.v2.json"
        controller = cast(FullVerifierConfig, context_a["controller"])
        artifacts = cast(RetainedArtifactIO, context_a["artifacts"])
        _regular_hash(args.config)
        _regular_hash(named)
        if (
            args.config != RUNTIME_ROOT / "review-config/review-aggregation.v2.json"
            or args.config.read_bytes() != named.read_bytes()
            or named.read_bytes()
            != _read_bytes(
                controller.governed_source_pack / "docs/configs/review-aggregation.v2.json",
                artifacts,
            )
            or config.get("repository_identity")
            != {
                "kind": "DESCENDANT",
                "receipt": str(
                    pack / "docs/receipts/descendant-repository-qualification-receipt.json"
                ),
            }
        ):
            raise ValueError("E_REVIEW_AUTH_BINDING")
        for context in (context_a, context_b):
            cast(dict[str, str], context["snapshots"])[str(args.config)] = _regular_hash(
                args.config
            )
            cast(dict[str, str], context["snapshots"])[str(named)] = _regular_hash(named)
            recheck_review_context(context)
        public_key, epoch = review_public_key(authority)
        configs = [cast(dict[str, object], context["config"]) for context in (context_a, context_b)]
        if any(
            selected.get("schema_version") == "review-config/v3" for selected in configs
        ) and any(
            selected.get("schema_version") != "review-config/v3"
            or _scope_record(selected)[0]["scope"]["kind"] != "CANDIDATE_READINESS"
            for selected in configs
        ):
            raise ValueError("E_REVIEW_AUTH_BINDING")
        validate_review_scope(
            cast(dict[str, object], context_a["config"]), json.loads(args.review_a.read_bytes())
        )
        validate_review_scope(
            cast(dict[str, object], context_b["config"]), json.loads(args.review_b.read_bytes())
        )
        result = aggregate_independent_reviews(
            json.loads(args.review_a.read_text()),
            json.loads(args.review_b.read_text()),
            json.loads(args.receipt_a.read_text()),
            json.loads(args.receipt_b.read_text()),
            authorization_a,
            authorization_b,
            public_key,
            config,
            expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            expected_trust_epoch=epoch,
            external_seal=cast(dict[str, object], context_a["seal"]),
        )
    bootstrap_review_authority(authority, initialize_if_absent=False)
    _validate_consumed_authorization(authorization_a, authority)
    _validate_consumed_authorization(authorization_b, authority)
    private = serialization.load_pem_private_key(
        Path(cast(str, authority["private_key_path"])).read_bytes(), password=None
    )
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("E_REVIEW_AUTH_BINDING")
    if context_a is None:
        result = aggregate_independent_reviews(
            json.loads(args.review_a.read_text()),
            json.loads(args.review_b.read_text()),
            json.loads(args.receipt_a.read_text()),
            json.loads(args.receipt_b.read_text()),
            authorization_a,
            authorization_b,
            private.public_key(),
            config,
            expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            expected_trust_epoch=cast(int, authorization_a["trust_epoch"]),
        )
    else:
        recheck_review_context(context_a)
        assert context_b is not None
        recheck_review_context(context_b)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output != args.output.resolve():
        raise ValueError("E_REVIEW_AUTH_BINDING")
    with args.output.open("x") as output:
        output.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
