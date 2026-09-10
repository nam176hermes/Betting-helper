"""Exact observed identity binding; names are display data, never matching keys."""

import hashlib
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canonical import parse_strict_json
from .live_contracts import validate_live_record
from .operator_profile import ExtractionProfile, _private_bytes, activate_profile

OPERATOR_FIELDS = frozenset(
    {"fixture_id", "home_id", "away_id", "competition_id", "season", "kickoff_utc", "match_url"}
)
PROVIDER_FIELDS = frozenset(
    {"fixture_id", "home_id", "away_id", "league_id", "season", "kickoff_utc"}
)


@dataclass(frozen=True)
class BindingEvidence:
    root: Path
    mapping_path: Path
    mapping_sha256: str
    source_kind: str
    provider_metadata: dict[str, Any]
    profile: ExtractionProfile = field(repr=False)
    previous: dict[str, Any] | None = None


def bind_fixture(
    provider: dict[str, Any], operator: dict[str, Any], evidence: BindingEvidence
) -> dict[str, Any]:
    try:
        provider = validate_live_record(provider, "ProviderState")
        if not isinstance(evidence, BindingEvidence) or evidence.source_kind not in {
            "SYNTHETIC_TEST",
            "OBSERVED_REAL",
        }:
            raise ValueError()
        raw = _private_bytes(evidence.mapping_path, evidence.root)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != evidence.mapping_sha256:
            raise ValueError()
        mapping = parse_strict_json(raw)
        if (
            not isinstance(mapping, dict)
            or set(mapping)
            != {
                "schema_version",
                "source_kind",
                "binding_id",
                "revision",
                "provider",
                "operator",
                "livescore_match_url",
            }
            or mapping["schema_version"] != "fixture-mapping/v1"
        ):
            raise ValueError()
        if (
            mapping["source_kind"] != evidence.source_kind
            or set(operator) != OPERATOR_FIELDS
            or set(evidence.provider_metadata) != PROVIDER_FIELDS
            or mapping["provider"] != evidence.provider_metadata
            or mapping["operator"] != operator
        ):
            raise ValueError()
        if any(
            provider[k] != evidence.provider_metadata[k]
            for k in ("fixture_id", "home_id", "away_id", "kickoff_utc")
        ):
            raise ValueError()
        if (
            operator["kickoff_utc"] != provider["kickoff_utc"]
            or operator["season"] != evidence.provider_metadata["season"]
            or not isinstance(operator["competition_id"], str)
            or not 1 <= len(operator["competition_id"]) <= 128
        ):
            raise ValueError()
        target = "SYNTHETIC_TEST" if evidence.source_kind == "SYNTHETIC_TEST" else "OPERATOR"
        profile = activate_profile(evidence.profile, target)
        if (
            operator["fixture_id"] not in profile["permitted_fixture_ids"]
            or operator["match_url"]
            not in {profile["origin"] + path for path in profile["exact_paths"]}
            or ("SYNTHETIC" in provider["quality_flags"]) != (target == "SYNTHETIC_TEST")
        ):
            raise ValueError()
        if target == "OPERATOR":
            # Real admission belongs to the current evidence/host verifier, never this hash check.
            importlib.import_module("moj_discovery.live_preflight_batched").verify_binding_evidence(
                mapping, evidence
            )
        previous = evidence.previous
        if previous is not None:
            previous = validate_live_record(previous, "FixtureBinding")
        if int(mapping["revision"]) != (
            1 if previous is None else int(previous["revision"]) + 1
        ) or (
            previous is not None
            and (
                mapping["binding_id"] != previous["binding_id"]
                or provider["fixture_id"] != previous["provider_fixture_id"]
            )
        ):
            raise ValueError()
        return validate_live_record(
            {
                "binding_id": mapping["binding_id"],
                "revision": mapping["revision"],
                "provider_fixture_id": provider["fixture_id"],
                "league_id": evidence.provider_metadata["league_id"],
                "season": evidence.provider_metadata["season"],
                **{
                    k: provider[k]
                    for k in ("kickoff_utc", "home_id", "away_id", "home_name", "away_name")
                },
                "operator_fixture_id": operator["fixture_id"],
                "operator_home_id": operator["home_id"],
                "operator_away_id": operator["away_id"],
                "operator_match_url": operator["match_url"],
                "livescore_match_url": mapping["livescore_match_url"],
                "orientation_status": "VERIFIED",
                "evidence_hashes": [digest],
            },
            "FixtureBinding",
        )
    except Exception:
        raise ValueError("E_LIVE_IDENTITY") from None


def fixture_key(binding: dict[str, Any]) -> str:
    value = validate_live_record(binding, "FixtureBinding")
    return f"{value['provider_fixture_id']}:{value['binding_id']}:{value['revision']}"
