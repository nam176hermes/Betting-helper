import json
from pathlib import Path
from typing import Any

from moj_discovery.live_config import load_live_config
from tests.live.test_api_football import STATUS, Reply, make_client
from tests.live.test_run_intents import make_intent
from tools import configure_live_batched as wizard
from tools import prepare_part_b_intent as prepare
from tools.probe_football_provider import inspect_provider


def test_disabled_wizard_preserves_existing_config_and_reserves_budget(
    tmp_path: Any, monkeypatch: Any, capsys: Any
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/live-batched.example.json").write_bytes(
        Path("config/live-batched.example.json").read_bytes()
    )
    monkeypatch.setattr(wizard, "ROOT", tmp_path)
    args = [
        "--platform",
        "LINUX_CHROME",
        "--league",
        "999",
        "--season",
        "2026",
        "--fixtures",
        "101",
    ]
    assert wizard.main(args) == 0
    output = tmp_path / "config/live.local.json"
    config = load_live_config(output)
    assert not config.enabled and config.fixture_ids == (101,)
    before = output.read_bytes()
    assert wizard.main(args) == 2 and output.read_bytes() == before
    assert wizard.main([*args, "--replace", "--requests", "500"]) == 2
    assert output.read_bytes() == before
    assert wizard.main([*args, "--replace", "--fixtures", "101,102"]) == 2
    assert output.read_bytes() == before
    text = capsys.readouterr().out
    assert "582" in text and "API_FOOTBALL_KEY=" not in text
    assert not (tmp_path / ".local").exists()


def test_prepare_draft_does_not_consume_or_overwrite(tmp_path: Any, monkeypatch: Any) -> None:
    _, config, _, _ = make_intent(tmp_path)
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    args = [
        "--stage",
        "provider-probe",
        "--config",
        str(tmp_path / "config.json"),
        "--output",
        ".local/part-b/intents/new.json",
    ]
    assert prepare.main(args) == 0
    data = json.loads((tmp_path / ".local/part-b/intents/new.json").read_text())
    assert data["max_http_attempts"] == 20 and data["max_duration_seconds"] == 300
    assert data["config_sha256"] == config.sha256 and data["user_confirmation_required"] is True
    assert not (tmp_path / ".local/part-b/intent-consumptions.sqlite3").exists()
    assert prepare.main(args) == 2


def test_discovery_launcher_checks_review_before_prompt_and_never_requests_key(
    tmp_path: Any, monkeypatch: Any, capsys: Any
) -> None:
    from moj_discovery import live_preflight_batched, secrets_local
    from tests.live.test_run_intents import make_discovery_intent

    _, _, selectors, scope = make_discovery_intent(tmp_path, monkeypatch)
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    selector_path = tmp_path / ".local/part-b/selectors.json"
    review_path = tmp_path / ".local/part-b/review.json"
    selector_path.write_text(json.dumps(selectors))
    review_path.write_text(json.dumps({"scope": scope}))
    calls = []

    def deny(*args: Any) -> None:
        calls.append("REVIEW_REJECTED")
        raise ValueError("TEST_ONLY_NO_REAL_REVIEW")

    def no_terminal() -> Any:
        raise AssertionError("Must not ask for confirmation before tool review")

    def no_key(**kwargs: Any) -> Any:
        raise AssertionError("Discovery must never request an API key")

    monkeypatch.setattr(live_preflight_batched, "verify_external_review", deny)
    monkeypatch.setattr(secrets_local, "controlling_tty", no_terminal)
    monkeypatch.setattr(secrets_local, "obtain_api_football_key", no_key)
    assert (
        prepare.execute_discovery(
            [
                "--config",
                str(tmp_path / "config.json"),
                "--intent",
                str(tmp_path / ".local/part-b/intents/probe.json"),
                "--selectors",
                str(selector_path),
                "--review",
                str(review_path),
                "--profile-name",
                "TEST_ONLY_PROFILE",
            ]
        )
        == 2
    )
    assert calls == ["REVIEW_REJECTED"]
    assert "Type ALLOW" not in capsys.readouterr().out
    assert not (tmp_path / ".local/part-b/intent-consumptions.sqlite3").exists()


def test_mock_probe_counts_fixed_calls_and_retains_projected_fields_only(
    tmp_path: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    monkeypatch: Any,
) -> None:
    _, config, _, _ = make_intent(tmp_path)
    coverage = {
        "errors": [],
        "results": 1,
        "paging": {"current": 1, "total": 1},
        "response": [
            {
                "league": {"id": 999},
                "seasons": [
                    {
                        "year": 2026,
                        "coverage": {
                            "fixtures": {
                                "events": True,
                                "lineups": True,
                                "statistics_fixtures": True,
                                "statistics_players": True,
                            }
                        },
                    }
                ],
            }
        ],
    }
    client, ledger, http = make_client(
        tmp_path,
        fake_clock,
        [
            Reply(STATUS),
            Reply(coverage),
            Reply(synthetic_provider_response),
            Reply(synthetic_provider_response),
        ],
    )
    with ledger, client:
        result = inspect_provider(config, client)
        assert result["PROBE_RESULT"] == "PASS"
        assert result["REQUEST_ATTEMPTS"] == len(http.calls) == 4 <= 20
        assert result["evidence"]["source_kind"] == "MOCK"
        assert result["evidence"]["source_latency_measured"] is False
        assert result["evidence"]["events_comparison_attempts"] == 0
        raw = json.dumps(result)
        assert (
            "PRIVATE_NOT_RETAINED" not in raw
            and "TEST_ONLY_HTTP_KEY" not in raw
            and '"account"' not in raw
        )
        assert all("/fixtures/events" not in req.full_url for req, _ in http.calls)


def test_probe_auth_failure_stops_and_cannot_satisfy_real_gate(
    tmp_path: Any, fake_clock: Any
) -> None:
    _, config, _, _ = make_intent(tmp_path)
    client, ledger, http = make_client(tmp_path, fake_clock, [Reply({}, status=401)])
    with ledger, client:
        result = inspect_provider(config, client)
        assert result["KEY_CHECK"] == "FAILED" and result["PROBE_RESULT"] == "FAIL"
        assert result["MISSING_CAPABILITIES"] == ["AUTH_FAILED"]
        assert result["REQUEST_ATTEMPTS"] == len(http.calls) == 1


def test_mock_probe_attempt_and_deadline_guards_precede_http(
    tmp_path: Any, fake_clock: Any
) -> None:
    _, config, _, _ = make_intent(tmp_path)
    client, ledger, http = make_client(tmp_path, fake_clock, [Reply(STATUS)], max_attempts=1)
    with ledger, client:
        result = inspect_provider(config, client)
        assert result["REQUEST_ATTEMPTS"] == len(http.calls) == 1
        assert result["MISSING_CAPABILITIES"] == ["BUDGET_LIMIT"]
    client, ledger, http = make_client(tmp_path / "expired", fake_clock, [])
    with ledger, client:
        fake_clock.advance(301)
        result = inspect_provider(config, client)
        assert result["REQUEST_ATTEMPTS"] == len(http.calls) == 0
        assert result["MISSING_CAPABILITIES"] == ["TIME_LIMIT"]


def test_enabled_config_can_name_future_intent_but_launcher_requires_its_bytes(
    tmp_path: Any, monkeypatch: Any
) -> None:
    import hashlib

    import pytest

    from moj_discovery import live_config
    from moj_discovery.live_intent import load_run_intent

    _, _, _, _ = make_intent(tmp_path)
    data = json.loads((tmp_path / "config.json").read_text())
    record = tmp_path / ".local/part-b/mock-evidence.json"
    record.write_text('{"source_kind":"MOCK","authority":false}')
    ref = ".local/part-b/mock-evidence.json"
    data["enabled"] = True
    data["operator"].update(
        capture_profile_path=ref,
        profile_evidence_hash=hashlib.sha256(record.read_bytes()).hexdigest(),
        allowed_fixture_bindings=["11111111-1111-4111-8111-111111111111"],
    )
    data["runtime"]["platform_qualification_path"] = ref
    data["gates"] = dict.fromkeys(data["gates"], ref)
    data["gates"]["live_intent_path"] = ".local/part-b/intents/future.json"
    (tmp_path / "config.json").write_text(json.dumps(data))
    original = live_config.private_path
    monkeypatch.setattr(
        live_config, "private_path", lambda name, **kw: original(name, root=tmp_path, **kw)
    )
    config = load_live_config(tmp_path / "config.json", require_enabled=True)
    # Parsing enables no I/O; actual intent and PB16 independent review still required.
    with pytest.raises(ValueError, match="LOAD"):
        load_run_intent(
            Path(data["gates"]["live_intent_path"]), config, "LIVE_READ_ONLY", root=tmp_path
        )
