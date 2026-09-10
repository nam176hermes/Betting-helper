import asyncio
import copy
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from moj_discovery.live_config import load_live_config
from moj_discovery.live_contracts import event_hash
from moj_discovery.live_replay import verify_live_replay
from moj_discovery.live_service import (
    LiveService,
    MockProviderTransport,
    RunAdmission,
    run_live_service,
)
from moj_discovery.live_state import capture_observation_id
from moj_discovery.operator_profile import ProfileEvidence, validate_extraction_profile
from moj_discovery.providers import api_football
from moj_discovery.providers.bundle_poller import ProviderBundlePoller
from moj_discovery.secrets_local import SecretValue
from tests.live.test_api_football import STATUS
from tests.live.test_live_store import binding, envelope
from tests.live.test_live_wire import paired_socket
from tests.live.test_operator_profile import profile, sample


def test_service_requires_typed_current_admission_before_any_io() -> None:
    args: Any = (None, None, {"source_kind": "MOCK"})
    with pytest.raises(ValueError, match="ADMISSION"):
        run_live_service(*args)


def make_service(
    tmp_path: Any, config: Any, clock: Any, provider: Any, book: Any, monkeypatch: Any
) -> Any:
    clock.mono = time.monotonic()
    p = profile()
    b = binding()
    evidence = tmp_path / ".local/part-b/profile-sample.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps(sample(p)))
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    p["evidence_hashes"] = [digest]
    b.update(orientation_status="VERIFIED", evidence_hashes=[digest])
    draft = validate_extraction_profile(
        p, ProfileEvidence(tmp_path, clock.utc, (evidence,), fixture_bindings=(b,))
    )
    config["provider"].update(fixture_ids=[101], league_id=999, season=2026)
    config["operator"]["allowed_fixture_bindings"] = [b["binding_id"]]
    config["runtime"].update(platform="LINUX_CHROME", run_output_dir=".local/part-b/mock-service")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    loaded = load_live_config(config_path)
    stream = str(uuid4())
    book = copy.deepcopy(book)
    book["profile_hash"] = draft.profile_hash
    scope = {
        "binding_id": b["binding_id"],
        "binding_revision": b["revision"],
        "operator_fixture_id": b["operator_fixture_id"],
        "generation": "0",
        "profile_hash": draft.profile_hash,
        "document_epoch": book["document_epoch"],
        "markets": {
            "FT": {
                "market_id": book["market_id"],
                "selections": {s: q["selection_id"] for s, q in book["selections"].items()},
            }
        },
    }
    admitted = RunAdmission(
        tmp_path,
        str(uuid4()),
        loaded.sha256,
        "a" * 64,
        "chrome-extension://" + "a" * 32,
        clock.mono + 7200,
        (b,),
        draft,
        {stream: scope},
    )
    http = MockProviderTransport([STATUS, provider, provider, provider])

    def no_network() -> Any:
        raise AssertionError("A mock must never construct a real provider opener")

    monkeypatch.setattr(api_football, "build_fixed_opener", no_network)
    service = LiveService(
        loaded,
        SecretValue("TEST_ONLY_SERVICE_KEY"),
        admitted,
        mock_transport=http,
        now_mono=lambda: clock.mono,
        now_utc=lambda: clock.utc,
        sleep=clock.advance,
    )
    return service, http, book, stream


def test_shared_subscriptions_pause_refresh_and_persisted_replay(
    tmp_path: Any,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    with patch(
        "moj_discovery.live_service.ProviderBundlePoller", wraps=ProviderBundlePoller
    ) as constructed:
        service, http, book, stream = make_service(
            tmp_path,
            disabled_live_config,
            fake_clock,
            synthetic_provider_response,
            synthetic_book,
            monkeypatch,
        )
        assert constructed.call_count == 1

    async def scenario() -> None:
        await service.start()
        queues = [service.subscribe(), service.subscribe(), service.subscribe()]
        assert constructed.call_count == 1
        for queue in queues:
            initial = await queue.get()
            assert initial["views"][0]["status"] == "WAITING_FOR_DATA"
        await service.tick()
        assert len(http.paths) == service.quota.count_attempts() == 2
        assert http.paths[-1].endswith("/fixtures?ids=101")
        binding_id = book["binding_id"]
        assert service.view(binding_id)["provider_epoch"] == service.view(binding_id)["epoch"]
        challenge = await service.request_capture(binding_id)
        assert challenge is not None
        event = envelope("MarketBook", book, stream=stream)
        event.update(
            run_id=service.admitted.run_id, observation_id=capture_observation_id(challenge, "FT")
        )
        event["content_hash"] = event_hash(event)
        # Same path called after the receiver's SQLite COMMIT, with an actual readback.
        receipt = service.store.append(event)
        await service.capture_received(event)
        assert receipt.content_hash == event["content_hash"]
        view = service.view(binding_id)
        assert view["market_states"]["FT"]["status"] == "CURRENT_DISPLAY_ONLY"
        assert view["source_time_status"] == "UNKNOWN"
        revision = service.store.projection_revision(binding_id)
        await service.capture_received(event)
        assert service.store.projection_revision(binding_id) == revision
        for _ in range(5):
            await service.on_ui("REFRESH", binding_id)
            await service.on_ui("SELECT_ACTIVE", binding_id)
        assert len(http.paths) == 2
        await service.on_ui("WATCHLIST_REMOVE", binding_id)
        fake_clock.advance(60)
        await service.tick()
        assert len(http.paths) == 2 and service.view(binding_id)["status"] == "PAUSED"
        assert service.view(binding_id)["books"]["FT"]["selections"] == book["selections"]
        await service.on_ui("WATCHLIST_ADD", binding_id)
        await service.tick()
        assert len(http.paths) == 3
        assert service.view(binding_id)["market_eligible"] is False
        for queue in queues:
            snapshot = await queue.get()
            assert snapshot["model_enabled"] is False and snapshot["money_ready"] is False
            assert "TEST_ONLY_SERVICE_KEY" not in json.dumps(snapshot)
            service.unsubscribe(queue)
        result = await service.close()
        assert result.request_attempts == 3 and result.real_http_attempts == 0
        assert result.authenticated is True and result.reason == "USER_STOP"

    with patch("moj_discovery.live_service.ProviderBundlePoller", constructed):
        asyncio.run(scenario())
    assert constructed.call_count == 1
    replay = verify_live_replay(service.directory, tmp_path / "replay")
    assert replay.equal


def test_missing_provider_pause_keeps_last_values(
    tmp_path: Any,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    service, http, book, _ = make_service(
        tmp_path,
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )

    async def scenario() -> None:
        await service.start()
        await service.tick()
        first = service.view(book["binding_id"])["provider"]
        http.responses.clear()
        fake_clock.advance(15)
        await service.tick()
        assert service.view(book["binding_id"])["provider"] == first
        assert service._reason == "SOURCE_STOPPED"
        assert service.view(book["binding_id"])["status"] == "PAUSED"
        result = await service.close()
        assert result.reason == "SOURCE_STOPPED"

    asyncio.run(scenario())


def test_real_flag_or_existing_run_never_authorizes_io(
    tmp_path: Any,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    service, _, _, _ = make_service(
        tmp_path,
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )
    secret = SecretValue("TEST_ONLY_SERVICE_KEY")
    try:
        for admission in [
            replace(service.admitted, source_kind="OBSERVED_REAL"),
            replace(service.admitted, config_sha256="b" * 64),
            replace(service.admitted, deadline_mono=fake_clock.mono - 1),
        ]:
            with pytest.raises(ValueError, match="ADMISSION"):
                LiveService(service.config, secret, admission)
        with pytest.raises(ValueError, match="TRANSPORT"):
            LiveService(service.config, secret, service.admitted)
        with pytest.raises(ValueError, match="RESTART"):
            LiveService(
                service.config, secret, service.admitted, mock_transport=MockProviderTransport([])
            )
    finally:
        asyncio.run(service.close())
    assert not any(p.suffix == ".env" for p in Path(tmp_path).rglob("*"))


def test_stop_and_expiry_prevent_further_requests(
    tmp_path: Any,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    service, http, _, _ = make_service(
        tmp_path,
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )

    async def scenario() -> None:
        await service.start()
        await service.tick()
        fake_clock.advance(7200)
        await service.tick()
        assert service._reason == "RUN_DEADLINE"
        assert len(http.paths) == 2
        result = await service.close()
        assert result.reason == "RUN_DEADLINE"

    asyncio.run(scenario())


def test_real_loopback_subscription_challenge_commit_ack(
    tmp_path: Any,
    disabled_live_config: Any,
    fake_clock: Any,
    synthetic_provider_response: Any,
    synthetic_book: Any,
    monkeypatch: Any,
) -> None:
    service, http, book, stream = make_service(
        tmp_path,
        disabled_live_config,
        fake_clock,
        synthetic_provider_response,
        synthetic_book,
        monkeypatch,
    )

    async def read(socket: Any, session: Any, key: Any) -> Any:
        raw = await asyncio.wait_for(socket.recv(), 3)
        return session.receive(raw.encode(), key)

    async def scenario() -> None:
        await service.start()
        ui, ui_session, ui_key = await paired_socket(service.pairing, "UI_SUBSCRIBER")
        producer, session, key = await paired_socket(service.pairing)
        try:
            initial = await read(ui, ui_session, ui_key)
            assert initial["body"]["provider_state"] is None
            first = await read(producer, session, key)
            assert first["body"]["health"]["reason"] == "CAPTURE_REQUEST_STARTED"
            await service.tick()
            fresh = await read(producer, session, key)
            challenge = fresh["body"]["health"]["evidence_hashes"][0]
            event = envelope("MarketBook", book, stream=stream)
            event.update(
                run_id=service.admitted.run_id,
                observation_id=capture_observation_id(challenge, "FT"),
            )
            event["content_hash"] = event_hash(event)
            body = dict(
                run_id=service.admitted.run_id,
                stream_id=stream,
                generation="0",
                batch_id=str(uuid4()),
                first_sequence="1",
                last_sequence="1",
                events=[event],
            )
            await producer.send(session.send("CAPTURE_BATCH", body, key).decode())
            ack = await read(producer, session, key)
            assert ack["message_type"] == "ACK"
            assert service.store.cursor(stream) == (1, event["content_hash"])
            actual = service.view(book["binding_id"])
            assert actual["book_meta"]["FT"]["receipt_us"] is not None
            assert actual["market_states"]["FT"]["status"] == "CURRENT_DISPLAY_ONLY"
            while True:
                projection = await read(ui, ui_session, ui_key)
                if projection["body"]["books"]:
                    break
            assert projection["body"]["books"] == [book]
            assert "TEST_ONLY_SERVICE_KEY" not in json.dumps(projection)
            assert len(http.paths) == 2
            bad = copy.deepcopy(body)
            bad["events"][0]["payload"]["profile_hash"] = "b" * 64
            bad["events"][0]["content_hash"] = event_hash(bad["events"][0])
            await producer.send(session.send("CAPTURE_BATCH", bad, key).decode())
            from websockets.exceptions import ConnectionClosed

            with pytest.raises(ConnectionClosed):
                await producer.recv()
            assert service.store.cursor(stream) == (1, event["content_hash"])
        finally:
            await producer.close()
            await ui.close()
            await service.close()

    asyncio.run(scenario())


def test_deadline_at_fractional_monotonic_boundary() -> None:
    from moj_discovery.provider_protocol import ProviderScope, verify_call_authorization

    for now in (0.1, 123456.789000001, 1000000.1, 2353242.140056624):
        scope = ProviderScope(
            str(uuid4()), (101,), 999, 2026, now + 7200, stage="LIVE_READ_ONLY", max_attempts=600
        )
        verify_call_authorization(scope, now_mono=now)
        with pytest.raises(ValueError):
            verify_call_authorization(replace(scope, deadline_mono=now + 7200.01), now_mono=now)
