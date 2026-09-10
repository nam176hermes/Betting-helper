"""Real-source admission cannot be obtained by transplanting a tested mock run."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.live_config import LiveConfig
from moj_discovery.live_service import LiveService
from moj_discovery.secrets_local import SecretValue
from tests.live.test_live_service import make_service


@pytest.mark.parametrize("change", ["real_flag", "enabled_config", "profile_flag"])
def test_mock_binding_and_key_cannot_create_real_admission(
    tmp_path: Path,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    service, http, _, _ = make_service(
        tmp_path,
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )
    config, admitted = service.config, service.admitted
    asyncio.run(service.close())
    assert len(admitted.bindings) == 1
    assert admitted.profile.profile_hash == service.admitted.profile.profile_hash
    admitted = replace(admitted, source_kind="OBSERVED_REAL")
    if change == "enabled_config":
        raw = config.public
        raw["enabled"] = True
        config = LiveConfig(raw, config.sha256)
    if change == "profile_flag":
        data = admitted.profile.public
        data.update(status="ACCEPTED", source_kind="OBSERVED_REAL")
        admitted = replace(
            admitted, profile=replace(admitted.profile, _data=data, _real_admitted=True)
        )
    with pytest.raises(ValueError):
        LiveService(config, SecretValue("TEST_ONLY_NOT_A_REAL_KEY"), admitted)
    assert http.paths == []
    assert config.public["model_enabled"] is False and config.public["money_enabled"] is False
