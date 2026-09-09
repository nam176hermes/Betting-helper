import json
from pathlib import Path

import pytest

from moj_discovery.live_config import load_live_config
from moj_discovery.live_preflight import check_live_readiness


def load(tmp_path, value, **kwargs):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(value))
    return load_live_config(p, **kwargs)


def test_disabled_v2_and_v1_compatibility(tmp_path, disabled_live_config):
    config = load(tmp_path, disabled_live_config)
    assert config.public["schema_version"] == "bh-live-readonly-config/v2"
    assert config.public["provider"]["events_fallback_enabled"] is False
    assert config.fixture_ids == ()
    assert config.enabled is False
    v1 = json.loads(Path("config/live.example.json").read_text())
    assert check_live_readiness(v1, {}, {})["MONEY_READY"] == "NO"


@pytest.mark.parametrize(
    "path,value",
    [
        (("enabled",), True),
        (("model_enabled",), True),
        (("money_enabled",), True),
        (("provider", "base_url"), "https://v3.football.api-sports.io/predictions"),
        (("provider", "api_key"), "TEST_ONLY_FORBIDDEN"),
        (("provider", "fixture_ids"), [True]),
        (("provider", "fixture_ids"), [1, 1]),
        (("provider", "fixture_ids"), [1, 2]),
        (("provider", "fixture_ids"), [1, 2, 3, 4, 5, 6]),
        (("provider", "events_fallback_fixture_ids"), [1]),
        (("provider", "max_in_flight"), True),
        (("provider", "live_poll_seconds"), 1),
        (("runtime", "host"), "0.0.0.0"),  # noqa: S104 -- rejection fixture, never bound
        (("runtime", "max_matches"), True),
        (("operator", "capture_profile_path"), "../../outside.json"),
        (("gates", "security_review_path"), "/outside/fake-review.json"),
    ],
)
def test_closed_scope(tmp_path, disabled_live_config, path, value):
    cursor = disabled_live_config
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(ValueError, match="E_LIVE_CONFIG"):
        load(tmp_path, disabled_live_config)


def test_require_enabled_and_no_alias_mutation(tmp_path, disabled_live_config):
    with pytest.raises(ValueError):
        load(tmp_path, disabled_live_config, require_enabled=True)
    config = load(tmp_path, disabled_live_config)
    config.public["enabled"] = True
    assert config.enabled is False


def test_duplicate_json_key(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"enabled":false,"enabled":true}')
    with pytest.raises(ValueError):
        load_live_config(path)
