"""Synthetic-only test inputs. No real credentials, identifiers or browser authority."""

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def selected_browser_platform(request: Any, monkeypatch: Any) -> None:
    """The complete mock gate runs its browser-required cases on the selected platform."""
    if os.environ.get("PB_BROWSER_PLATFORM") != "WINDOWS_CHROME_WSL2":
        return
    from tools import offline_browser
    from tools.qualify_live_platform import WindowsBrowser

    class SelectedWindowsBrowser:
        def __init__(
            self, workspace: Path, extension: Path, origin: str, *, profile: Path | None = None
        ):
            self.workspace = workspace
            workspace.mkdir(parents=True, exist_ok=False)
            alias = profile / "windows-owned-profile.json" if profile is not None else None
            retained = (
                Path(json.loads(alias.read_text())["profile"])
                if alias is not None and alias.exists()
                else None
            )
            self.native = WindowsBrowser(
                extension, origin, offline_browser.ROOT / "tools/chrome_pipe.cjs", profile=retained
            )
            self.ready = self.native.ready
            if alias is not None and not alias.exists():
                alias.parent.mkdir(parents=True, exist_ok=False)
                alias.write_text(json.dumps({"profile": str(self.native.profile)}))

        def command(self, value: dict[str, Any]) -> dict[str, Any]:
            return self.native.command(value)

        def close(self) -> None:
            try:
                self.native.close()
            finally:
                # Retain native observation/termination/pipe records with the case; no profile copy.
                for path in self.native.workspace.iterdir():
                    if path.is_file() and path.suffix in {
                        ".json",
                        ".ndjson",
                        ".stdout",
                        ".stderr",
                        ".png",
                    }:
                        shutil.copy2(path, self.workspace / path.name)
                (self.workspace / "native-workspace.json").write_text(
                    json.dumps({"path": str(self.native.workspace)})
                )

    monkeypatch.setattr(offline_browser, "OfflineBrowser", SelectedWindowsBrowser)
    if hasattr(request.module, "OfflineBrowser"):
        monkeypatch.setattr(request.module, "OfflineBrowser", SelectedWindowsBrowser)


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
