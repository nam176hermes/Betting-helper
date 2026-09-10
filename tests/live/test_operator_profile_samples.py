"""Profile evidence checks. An empty index proves no real operator capability."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.live_config import private_path
from moj_discovery.operator_profile import ProfileEvidence, validate_extraction_profile


def verify_admitted_profile_index(index: dict[str, Any], root: Path) -> list[str]:
    if (
        set(index) != {"schema_version", "status", "profiles"}
        or index["schema_version"] != "part-b-admitted-profile-index/v1"
        or type(index["profiles"]) is not list
    ):
        raise ValueError("E_PROFILE_INDEX")
    if index["status"] == "WAITING_OPERATOR_SAMPLE" and not index["profiles"]:
        return []
    if index["status"] != "OBSERVED_REAL" or not 1 <= len(index["profiles"]) <= 5:
        raise ValueError("E_PROFILE_INDEX_NOT_OBSERVED")

    def artifact(ref: str, expected: str) -> Path:
        path = private_path(ref, root=root, must_exist=True)
        if path.stat().st_size > 65536 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("E_PROFILE_INDEX_HASH")
        return path

    admitted = []
    for row in index["profiles"]:
        if type(row) is not dict or set(row) != {
            "profile",
            "profile_sha256",
            "review",
            "review_sha256",
            "samples",
            "bindings",
        }:
            raise ValueError("E_PROFILE_INDEX_FIELDS")
        value = json.loads(artifact(row["profile"], row["profile_sha256"]).read_text())
        if value["source_kind"] != "OBSERVED_REAL" or value["status"] != "ACCEPTED":
            raise ValueError("E_PROFILE_INDEX_SYNTHETIC_OR_DRAFT")
        profile = validate_extraction_profile(
            value,
            ProfileEvidence(
                root,
                datetime.now(UTC),
                tuple(artifact(ref, sha) for ref, sha in row["samples"].items()),
                artifact(row["review"], row["review_sha256"]),
                tuple(row["bindings"]),
            ),
        )
        if (
            not profile._real_admitted
            or "FT" not in profile.public["horizons"]
            or any(b["orientation_status"] != "VERIFIED" for b in row["bindings"])
        ):
            raise ValueError("E_PROFILE_INDEX_SCOPE")
        admitted.append(profile.profile_hash)
    if len(set(admitted)) != len(admitted):
        raise ValueError("E_PROFILE_INDEX_DUPLICATE")
    return admitted


def test_missing_or_synthetic_index_is_never_real_acceptance(tmp_path: Path) -> None:
    pending = {
        "schema_version": "part-b-admitted-profile-index/v1",
        "status": "WAITING_OPERATOR_SAMPLE",
        "profiles": [],
    }
    assert verify_admitted_profile_index(pending, tmp_path) == []
    for value in (
        {**pending, "status": "OBSERVED_REAL"},
        {**pending, "profiles": [{"profile": ".env"}]},
        {**pending, "live_pass": True},
    ):
        with pytest.raises(ValueError):
            verify_admitted_profile_index(value, tmp_path)


def test_index_stays_pending_or_reopens_actual_reviewed_samples() -> None:
    root = Path(__file__).resolve().parents[2]
    index = json.loads((Path(__file__).parent / "fixtures/admitted-profile-index.json").read_text())
    actual = verify_admitted_profile_index(index, root)
    assert bool(actual) == (index["status"] == "OBSERVED_REAL")
