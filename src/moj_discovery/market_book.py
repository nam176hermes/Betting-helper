"""One bounded two-read DOM snapshot becomes one complete display-only book."""

import copy
from dataclasses import dataclass
from typing import Any

from .live_contracts import MAX_INTEGER, validate_live_record
from .operator_profile import ExtractionProfile, activate_profile, parse_decimal_price

SNAPSHOT_FIELDS = frozenset(
    {
        "operator_fixture_id",
        "home_id",
        "away_id",
        "market_id",
        "horizon",
        "settlement_basis",
        "selections",
        "market_status",
        "operator_score",
        "operator_period",
    }
)


@dataclass(frozen=True)
class CapturedFields:
    snapshots: tuple[dict[str, Any], dict[str, Any]]
    binding: dict[str, Any]
    exact_url: str
    observed_at_utc: str
    first_read_mono_us: int
    browser_mono_us: int
    clock_domain_id: str
    capture_revision: str
    document_epoch: str


def assemble_book(capture: CapturedFields, profile: ExtractionProfile) -> dict[str, Any]:
    try:
        data = activate_profile(
            profile,
            "SYNTHETIC_TEST" if profile.public["source_kind"] == "SYNTHETIC_TEST" else "OPERATOR",
        )
        binding = validate_live_record(capture.binding, "FixtureBinding")
        first, second = capture.snapshots
        if (
            set(first) != SNAPSHOT_FIELDS
            or first != second
            or type(capture.first_read_mono_us) is not int
            or type(capture.browser_mono_us) is not int
            or not 0 <= capture.first_read_mono_us < capture.browser_mono_us <= MAX_INTEGER
            or not 100000 <= capture.browser_mono_us - capture.first_read_mono_us <= 1000000
            or capture.exact_url != binding["operator_match_url"]
            or capture.exact_url not in {data["origin"] + p for p in data["exact_paths"]}
            or first["operator_fixture_id"] != binding["operator_fixture_id"]
            or first["home_id"] != binding["operator_home_id"]
            or first["away_id"] != binding["operator_away_id"]
        ):
            raise ValueError()
        observed = [
            m
            for m in profile.observed_markets[first["operator_fixture_id"]]
            if m["market_id"] == first["market_id"] and m["horizon"] == first["horizon"]
        ]
        if (
            len(observed) != 1
            or first["settlement_basis"] != observed[0]["settlement_basis"]
            or set(first["selections"]) != {"HOME", "DRAW", "AWAY"}
        ):
            raise ValueError()
        selections = {}
        for side, quote in first["selections"].items():
            if (
                set(quote) != {"selection_id", "price_text"}
                or quote["selection_id"] != observed[0]["selections"][side]
            ):
                raise ValueError()
            selections[side] = {
                "selection_id": quote["selection_id"],
                "decimal_odds": parse_decimal_price(quote["price_text"], data["price_parser"]),
            }
        return validate_live_record(
            {
                **{
                    k: copy.deepcopy(first[k])
                    for k in SNAPSHOT_FIELDS - {"home_id", "away_id", "selections"}
                },
                "binding_id": binding["binding_id"],
                "binding_revision": binding["revision"],
                "selections": selections,
                "capture_revision": capture.capture_revision,
                "native_revision": None,
                "observed_at_utc": capture.observed_at_utc,
                "browser_mono_us": str(capture.browser_mono_us),
                "clock_domain_id": capture.clock_domain_id,
                "source_updated_at": None,
                "capture_evidence_tier": "DISPLAY_COHERENT",
                "profile_hash": profile.profile_hash,
                "document_epoch": capture.document_epoch,
                "quality_flags": ["SYNTHETIC"] if data["source_kind"] == "SYNTHETIC_TEST" else [],
            },
            "MarketBook",
        )
    except Exception:
        raise ValueError("E_LIVE_BOOK") from None
