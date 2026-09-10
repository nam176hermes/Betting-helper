"""Synthetic-only test inputs. No real credentials, identifiers or browser authority."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def disabled_live_config() -> Any:
    return json.loads(Path("config/live-batched.example.json").read_text())


class FakeClock:
    mono = 0.0
    utc = datetime(2026, 9, 9, 18, tzinfo=UTC)

    def advance(self, seconds: Any) -> Any:
        from datetime import timedelta

        self.mono += seconds
        self.utc += timedelta(seconds=seconds)


@pytest.fixture
def fake_clock() -> Any:
    return FakeClock()


@pytest.fixture
def synthetic_provider_response() -> Any:
    return {
        "get": "fixtures",
        "parameters": {"ids": "101"},
        "errors": [],
        "results": 1,
        "paging": {"current": 1, "total": 1},
        "response": [
            {
                "fixture": {
                    "id": 101,
                    "date": "2026-09-09T18:00:00Z",
                    "timestamp": 1788976800,
                    "status": {"short": "1H", "elapsed": 10, "extra": None},
                },
                "league": {"id": 999, "season": 2026},
                "teams": {
                    "home": {"id": 201, "name": "SYNTHETIC HOME"},
                    "away": {"id": 202, "name": "SYNTHETIC AWAY"},
                },
                "goals": {"home": 0, "away": 0},
                "score": {
                    "halftime": {"home": None, "away": None},
                    "fulltime": {"home": None, "away": None},
                },
                "events": [],
            }
        ],
    }


@pytest.fixture
def synthetic_book() -> Any:
    return {
        "binding_id": "11111111-1111-4111-8111-111111111111",
        "binding_revision": "1",
        "operator_fixture_id": "SYNTHETIC-101",
        "market_id": "SYNTHETIC-FT",
        "horizon": "FT",
        "settlement_basis": "NORMAL_TIME_INCLUDING_STOPPAGE",
        "selections": {
            side: {"selection_id": "SYNTHETIC-" + side, "decimal_odds": odds}
            for side, odds in [("HOME", "2.10"), ("DRAW", "3.20"), ("AWAY", "3.40")]
        },
        "market_status": "OPEN",
        "capture_revision": "1",
        "native_revision": None,
        "observed_at_utc": "2026-09-09T18:00:00Z",
        "browser_mono_us": "1000000",
        "clock_domain_id": "22222222-2222-4222-8222-222222222222",
        "source_updated_at": None,
        "operator_score": {"home": 0, "away": 0},
        "operator_period": "H1",
        "capture_evidence_tier": "DISPLAY_COHERENT",
        "profile_hash": "a" * 64,
        "document_epoch": "33333333-3333-4333-8333-333333333333",
        "quality_flags": ["SYNTHETIC"],
    }
