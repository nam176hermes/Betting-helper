from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from moj_discovery.live_config import load_live_config
from tools import run_with_api_football_key


def test_clean_live_close_is_distinct_from_probe_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_with_api_football_key._report_live(
        {
            "LIVE_SESSION_RESULT": "CLOSED_PENDING_REPLAY",
            "REQUEST_ATTEMPTS": 4,
            "REAL_HTTP_ATTEMPTS": 4,
            "RUN_DIRECTORY": str(run_with_api_football_key.ROOT / ".local/part-b/test-run"),
            "REPLAY_REQUIRED": True,
        }
    )
    out = capsys.readouterr().out
    assert "CLOSED_PENDING_REPLAY" in out and "PROBE_RESULT" not in out
    assert "chưa phải LIVE_READ_ONLY_PASS_ONE" in out


def test_fixture_setup_preserves_limits_and_never_enables_live(tmp_path: Path) -> None:
    from tools.launch_part_b import fixture_config

    original = load_live_config(Path("config/live-batched.example.json")).public
    value = fixture_config(original, 2, 2026, 1635632)
    assert value["provider"]["fixture_ids"] == [1635632]
    assert value["provider"]["max_requests_per_run"] == 600
    assert value["provider"]["events_fallback_enabled"] is False
    assert value["enabled"] is False and value["model_enabled"] is False
    assert original["provider"]["fixture_ids"] == []
    for fixture in (0, -1, True, "1635632"):
        with pytest.raises(ValueError):
            fixture_config(original, 2, 2026, cast(Any, fixture))


def test_public_paths_cannot_escape_private_workspace(tmp_path: Path) -> None:
    from tools.launch_part_b import local_config_path

    for path in (
        ".env",
        str(tmp_path / "config.json"),
        ".local/../.env",
        "config/live-batched.example.json",
    ):
        with pytest.raises(ValueError):
            local_config_path(path)


def test_live_menu_uses_reviewed_url_and_reuses_only_unconsumed_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from moj_discovery import live_config, live_intent, live_preflight_batched
    from tools import launch_part_b, prepare_part_b_intent

    relative = ".local/part-b/live-intent.json"
    config = SimpleNamespace(fixture_ids=(101,))
    exact = "https://miseojeuplus.espacejeux.com/sports/TEST_ONLY/101"
    calls: list[Any] = []
    monkeypatch.setattr(launch_part_b, "ROOT", tmp_path)
    monkeypatch.setattr(
        live_preflight_batched,
        "load_evidence",
        lambda config: SimpleNamespace(
            checks={"capture"}, bindings=[{"provider_fixture_id": 101, "operator_match_url": exact}]
        ),
    )

    def prepare(args: Any) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(prepare_part_b_intent, "main", prepare)
    assert launch_part_b.prepare_live_intent(tmp_path / "config.json", config, relative)
    assert calls[-1][-2:] == ["--operator-url", exact]
    target = live_config.private_path(relative, root=tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("TEST_ONLY_OLD_INTENT")
    loaded = SimpleNamespace(public={"operator_urls": [exact]})
    monkeypatch.setattr(live_intent, "load_run_intent", lambda *args, **kwargs: loaded)
    monkeypatch.setattr(live_intent, "intent_is_consumed", lambda intent: False)
    assert launch_part_b.prepare_live_intent(tmp_path / "config.json", config, relative)
    assert len(calls) == 1
    loaded.public["operator_urls"] = [exact + "/wrong"]
    monkeypatch.setattr(launch_part_b, "public_input", lambda prompt: "NO")
    assert not launch_part_b.prepare_live_intent(tmp_path / "config.json", config, relative)
    loaded.public["operator_urls"] = [exact]
    monkeypatch.setattr(live_intent, "intent_is_consumed", lambda intent: True)
    monkeypatch.setattr(launch_part_b, "public_input", lambda prompt: "NO")
    assert not launch_part_b.prepare_live_intent(tmp_path / "config.json", config, relative)
    assert target.exists() and len(calls) == 1
    monkeypatch.setattr(launch_part_b, "public_input", lambda prompt: "NEW LIVE INTENT")
    assert launch_part_b.prepare_live_intent(tmp_path / "config.json", config, relative)
    assert len(calls) == 2 and not target.exists()
    assert next(target.parent.glob("*.archived-*.json")).read_text() == "TEST_ONLY_OLD_INTENT"


def test_readiness_key_presence_requires_matching_generation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    from moj_discovery import live_config, live_preflight_batched
    from tools import launch_part_b

    configured = {"generation": "TEST_ONLY_GENERATION"}
    raw = load_live_config(Path("config/live-batched.example.json")).public
    raw["credentials"] = configured
    config = SimpleNamespace(public=raw, fixture_ids=(101,), sha256="a" * 64)
    monkeypatch.setattr(live_config, "load_live_config", lambda path: config)
    monkeypatch.setattr(live_preflight_batched, "load_evidence",
                        lambda config: SimpleNamespace(source_sha256="b" * 64))
    seen = []

    def evaluate(config: Any, evidence: Any, key_present: bool) -> Any:
        seen.append(key_present)
        return live_preflight_batched.Readiness(False, (), "NOT_PRESENT")

    monkeypatch.setattr(live_preflight_batched, "evaluate_live_readiness", evaluate)
    monkeypatch.setattr(launch_part_b, "key_metadata", lambda: configured)
    launch_part_b.readiness(Path("TEST_ONLY.json"))
    monkeypatch.setattr(launch_part_b, "key_metadata", lambda: {"generation": "ROTATED"})
    launch_part_b.readiness(Path("TEST_ONLY.json"))
    assert seen == [True, False]
    assert "Kho key: ROTATED" in capsys.readouterr().out
