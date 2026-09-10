import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from moj_discovery.operator_profile import (
    ProfileEvidence,
    activate_profile,
    parse_decimal_price,
    validate_extraction_profile,
)
from tests.live.test_live_store import binding

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 9, 18, tzinfo=UTC)


def profile() -> Any:
    schema = json.loads(
        (ROOT / "contracts/live_readonly/v1/operator-profile.schema.json").read_text()
    )
    fields = schema["properties"]["selectors"]["required"]
    return dict(
        schema_version="operator-extraction-profile/v1",
        profile_id=str(uuid4()),
        profile_version="1",
        status="DRAFT",
        source_kind="SYNTHETIC_TEST",
        origin="https://example.invalid",
        exact_paths=["/match/101"],
        permitted_fixture_ids=["SYNTHETIC-101"],
        locale="en",
        price_parser="DECIMAL_DOT",
        selectors={
            k: "#"
            + ("TEST_ONLY_MATCH" if k == "match_root" else k.replace("_", "-"))
            + (" > .selection-id" if k.endswith("_selection") else "")
            for k in fields
        },
        horizons=["FT"],
        observation_mode="FIXED_DOM_READONLY",
        evidence_hashes=[],
        capture_source_hash="a" * 64,
        reviewed_source_hash=None,
        expires_at=None,
        max_matches=1,
    )


def sample(value: Any) -> Any:
    return dict(
        schema_version="operator-profile-sample/v1",
        source_kind="SYNTHETIC_TEST",
        profile_id=value["profile_id"],
        origin=value["origin"],
        path="/match/101",
        fixture_id="SYNTHETIC-101",
        home_id="SYNTHETIC-H",
        away_id="SYNTHETIC-A",
        markets=[
            dict(
                market_id="SYNTHETIC-FT",
                horizon="FT",
                settlement_basis="NORMAL_TIME_INCLUDING_STOPPAGE",
                selections={side: "SYNTHETIC-" + side for side in ["HOME", "DRAW", "AWAY"]},
                labels={
                    "horizon": "FT",
                    "status": {"OPEN": "OPEN"},
                    "period": {"H1": "1H"},
                    "score_separator": "EN_DASH",
                },
            )
        ],
        field_map={
            k: {
                "selector": s,
                "reader": "ROOT_NODE"
                if k == "match_root"
                else "DATA_MARKET_ID"
                if k == "market_root"
                else "TEXT_CONTENT",
            }
            for k, s in value["selectors"].items()
            if s is not None
        },
    )


def evidence_for(tmp_path: Any, value: Any, observed: Any) -> Any:
    directory = tmp_path / ".local/part-b/operator"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sample.json"
    path.write_text(json.dumps(observed))
    value["evidence_hashes"] = [hashlib.sha256(path.read_bytes()).hexdigest()]
    return ProfileEvidence(tmp_path, NOW, (path,), fixture_bindings=(binding(),))


def test_draft_is_inert_and_synthetic_target_explicit() -> None:
    value = profile()
    draft = validate_extraction_profile(value, ProfileEvidence(ROOT, NOW))
    assert draft.status == "DRAFT"
    assert draft.field_map["home_odds"] == {"selector": "#home-odds", "reader": "TEXT_CONTENT"}
    assert activate_profile(draft, target="SYNTHETIC_TEST")["source_kind"] == "SYNTHETIC_TEST"
    with pytest.raises(ValueError, match="INACTIVE"):
        activate_profile(draft, target="OPERATOR")
    public = draft.public
    public["selectors"]["home_odds"] = "input"
    assert draft.public == value


@pytest.mark.parametrize(
    "selector",
    [
        "input[type=password]",
        "#account",
        ".balance",
        "form .odds",
        "textarea",
        "iframe",
        "[contenteditable]",
        "#cashout",
        ".betslip",
        "body",
        "*",
        "#x, #secret",
        "#x + #outside",
        ":has(input)",
        "xpath(//password)",
        "#x\\2c input",
        "[data-token=secret]",
        "[href='https://evil.invalid']",
    ],
)
def test_excluded_or_executable_selector_rejects(selector: Any) -> None:
    value = profile()
    value["selectors"]["home_odds"] = selector
    with pytest.raises(ValueError, match="PROFILE"):
        validate_extraction_profile(value, ProfileEvidence(ROOT, NOW))


def test_null_draft_remains_unconfigured() -> None:
    value = profile()
    value["selectors"] = dict.fromkeys(value["selectors"])
    draft = validate_extraction_profile(value, ProfileEvidence(ROOT, NOW))
    assert draft.field_map == {}
    with pytest.raises(ValueError, match="UNCONFIGURED"):
        activate_profile(draft, target="SYNTHETIC_TEST")


@pytest.mark.parametrize(
    "origin,path",
    [
        ("http://miseojeuplus.espacejeux.com", "/match/101"),
        ("https://example.invalid", "//evil.invalid"),
        ("https://u:p@example.invalid", "/match/101"),
        ("https://example.invalid", "/match/../account"),
        ("https://example.invalid", "/match/%3Ftoken"),
        ("https://example.invalid", "/match?token=x"),
    ],
)
def test_exact_url_scope_rejects_secrets_and_ambiguous_routes(origin: Any, path: Any) -> None:
    value = profile()
    value.update(origin=origin, exact_paths=[path])
    with pytest.raises(ValueError):
        validate_extraction_profile(value, ProfileEvidence(ROOT, NOW))


@pytest.mark.parametrize(
    "text,parser,expected",
    [
        ("2.10", "DECIMAL_DOT", "2.10"),
        ("3,20", "DECIMAL_COMMA", "3.20"),
        ("999999.123456", "DECIMAL_DOT", "999999.123456"),
    ],
)
def test_decimal_parser_is_explicit(text: Any, parser: Any, expected: Any) -> None:
    assert parse_decimal_price(text, parser) == expected


@pytest.mark.parametrize(
    "text",
    ["1", "1.0", "0.9", "NaN", "2/1", "+110", "2,10", "1 000.00", "2.1234567", "2.1\x00", "2e0"],
)
def test_ambiguous_price_never_coerced(text: Any) -> None:
    with pytest.raises(ValueError):
        parse_decimal_price(text, "DECIMAL_DOT")


def test_synthetic_observed_map_preserved_and_bound_to_sample_hash(tmp_path: Any) -> None:
    value = profile()
    observed = sample(value)
    evidence = evidence_for(tmp_path, value, observed)
    draft = validate_extraction_profile(value, evidence)
    assert draft.observed_markets["SYNTHETIC-101"] == observed["markets"]
    evidence.sample_paths[0].write_text("{}")
    with pytest.raises(ValueError):
        validate_extraction_profile(value, evidence)


@pytest.mark.parametrize(
    "mutation", ["orientation", "missing_draw", "wrong_market", "horizon", "reader", "source"]
)
def test_bad_sample_map_cannot_be_admitted(tmp_path: Any, mutation: Any) -> None:
    value = profile()
    observed = sample(value)
    if mutation == "orientation":
        observed["home_id"], observed["away_id"] = observed["away_id"], observed["home_id"]
    if mutation == "missing_draw":
        del observed["markets"][0]["selections"]["DRAW"]
    if mutation == "wrong_market":
        observed["markets"][0]["market_id"] = ""
    if mutation == "horizon":
        observed["markets"][0]["horizon"] = "FULL_TIME_OR_EXTRA_TIME"
    if mutation == "reader":
        observed["field_map"]["home_odds"]["reader"] = "OUTER_HTML"
    if mutation == "source":
        observed["source_kind"] = "OBSERVED_REAL"
    evidence = evidence_for(tmp_path, value, observed)
    with pytest.raises(ValueError):
        validate_extraction_profile(value, evidence)


def test_fake_acceptance_or_hash_only_cannot_activate_real_profile(tmp_path: Any) -> None:
    value = profile()
    value.update(
        status="ACCEPTED",
        source_kind="OBSERVED_REAL",
        origin="https://miseojeuplus.espacejeux.com",
        reviewed_source_hash="a" * 64,
        expires_at="2026-09-09T19:00:00Z",
        evidence_hashes=["b" * 64],
    )
    with pytest.raises(ValueError):
        validate_extraction_profile(value, ProfileEvidence(tmp_path, NOW))


def test_selection_field_aliases_rejected() -> None:
    value = profile()
    value["selectors"]["draw_selection"] = value["selectors"]["home_selection"]
    with pytest.raises(ValueError):
        validate_extraction_profile(value, ProfileEvidence(ROOT, NOW))


@pytest.mark.parametrize(
    "label_change", ["missing", "unknown_period", "duplicate_status", "extra", "control"]
)
def test_unobserved_or_ambiguous_labels_rejected(tmp_path: Any, label_change: str) -> None:
    value = profile()
    observed = sample(value)
    labels = observed["markets"][0]["labels"]
    if label_change == "missing":
        del observed["markets"][0]["labels"]
    if label_change == "unknown_period":
        labels["period"] = {"FIRST_HALF_MAYBE": "1H"}
    if label_change == "duplicate_status":
        labels["status"] = {"OPEN": "X", "SUSPENDED": "X"}
    if label_change == "extra":
        labels["script"] = "read page"
    if label_change == "control":
        labels["horizon"] = "FT\x00"
    with pytest.raises(ValueError):
        validate_extraction_profile(value, evidence_for(tmp_path, value, observed))
