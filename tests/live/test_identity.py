import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from moj_discovery.live_identity import bind_fixture
from tests.live.test_live_store import binding
from tests.live.test_provider_normalization import normalize


def test_identity_entry_is_behavioral(synthetic_provider_response: Any) -> None:
    with pytest.raises(ValueError):
        bind_fixture(normalize(synthetic_provider_response).states[101], {}, cast(Any, None))


def identity_inputs(tmp_path: Any, provider: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    from moj_discovery.live_identity import BindingEvidence
    from moj_discovery.operator_profile import ProfileEvidence, validate_extraction_profile
    from tests.live.test_operator_profile import profile

    root = tmp_path / ".local/part-b"
    root.mkdir(parents=True)
    p = profile()
    draft = validate_extraction_profile(
        p,
        ProfileEvidence(
            tmp_path,
            datetime(2026, 9, 9, 18, tzinfo=UTC),
        ),
    )
    operator = dict(
        fixture_id="SYNTHETIC-101",
        home_id="SYNTHETIC-H",
        away_id="SYNTHETIC-A",
        competition_id="TEST_ONLY_COMPETITION",
        season=2026,
        kickoff_utc=provider["kickoff_utc"],
        match_url=p["origin"] + p["exact_paths"][0],
    )
    metadata = {k: provider[k] for k in ("fixture_id", "home_id", "away_id", "kickoff_utc")}
    metadata.update(league_id=999, season=2026)
    mapping = dict(
        schema_version="fixture-mapping/v1",
        source_kind="SYNTHETIC_TEST",
        binding_id=binding()["binding_id"],
        revision="1",
        provider=metadata,
        operator=operator,
        livescore_match_url=None,
    )
    path = root / "mapping.json"
    path.write_text(json.dumps(mapping))
    return BindingEvidence(
        tmp_path,
        path,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        "SYNTHETIC_TEST",
        metadata,
        draft,
    ), operator


def test_exact_observed_mapping_and_names_are_only_display(
    tmp_path: Any, synthetic_provider_response: Any
) -> None:
    from moj_discovery.live_identity import fixture_key

    provider = normalize(synthetic_provider_response).states[101]
    evidence, operator = identity_inputs(tmp_path, provider)
    result = bind_fixture(provider, operator, evidence)
    assert result["orientation_status"] == "VERIFIED"
    assert result["provider_fixture_id"] == 101
    assert result["livescore_match_url"] is None
    assert fixture_key(result).endswith(":1")
    provider["home_name"] = "TEST_ONLY alternate display spelling"
    assert bind_fixture(provider, operator, evidence)["home_name"] == provider["home_name"]
    evidence.mapping_path.write_text("{}")
    with pytest.raises(ValueError, match="IDENTITY"):
        bind_fixture(provider, operator, evidence)


@pytest.mark.parametrize(
    "mutation",
    [
        "provider_id",
        "home",
        "date",
        "league",
        "season",
        "operator_swap",
        "operator_league",
        "path",
        "revision",
        "source",
    ],
)
def test_identity_drift_no_fuzzy_autoapproval(
    tmp_path: Any, synthetic_provider_response: Any, mutation: str
) -> None:
    provider = normalize(synthetic_provider_response).states[101]
    evidence, operator = identity_inputs(tmp_path, provider)
    if mutation == "provider_id":
        provider["fixture_id"] = 102
    if mutation == "home":
        provider["home_id"] = 202
    if mutation == "date":
        provider["kickoff_utc"] = "2026-09-10T18:00:00Z"
    if mutation in {"league", "season"}:
        evidence.provider_metadata["league_id" if mutation == "league" else "season"] += 1
    if mutation == "operator_swap":
        operator["home_id"], operator["away_id"] = operator["away_id"], operator["home_id"]
    if mutation == "operator_league":
        operator["competition_id"] = "TEST_ONLY_OTHER"
    if mutation == "path":
        operator["match_url"] = "https://example.invalid/unapproved"
    if mutation == "revision":
        evidence = replace(evidence, previous=binding())
    if mutation == "source":
        evidence = replace(evidence, source_kind="OBSERVED_REAL")
    with pytest.raises(ValueError, match="IDENTITY"):
        bind_fixture(provider, operator, evidence)
