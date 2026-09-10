import copy
import hashlib
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from moj_discovery.live_contracts import event_hash
from moj_discovery.live_state import (
    capture_observation_id,
    h2_score,
    reduce_live_event,
    request_reference,
)
from moj_discovery.market_book import CapturedFields, assemble_book
from moj_discovery.operator_profile import validate_extraction_profile
from moj_discovery.providers.football_normalizer import semantic_hash
from tests.live.test_live_store import binding, envelope
from tests.live.test_operator_profile import evidence_for, profile, sample
from tests.live.test_provider_normalization import normalize

CLOCK = "cb7a8852-8cfb-4e24-8768-839bce3e5700"


class Reducer:
    def __init__(self) -> None:
        b = binding()
        b.update(orientation_status="VERIFIED", evidence_hashes=["b" * 64])
        self.view: Any = None
        self.mono = 0
        self.last_event: dict[str, Any] = {}
        self.history: list[dict[str, Any]] = []
        self.chains: dict[str, tuple[int, str]] = {}
        event = envelope(
            "BindingChange",
            {"before_revision": None, "after": b, "reason": "SYNTHETIC_REGISTRATION"},
        )
        event["received_mono_us"] = "0"
        self.apply(event)
        self.control("PROFILE_ADMITTED", ["a" * 64])

    def apply(self, event: dict[str, Any]) -> None:
        sequence, previous = self.chains.get(event["stream_id"], (0, "0" * 64))
        event.update(sequence=str(sequence + 1), previous_hash=previous)
        event["content_hash"] = event_hash(event)
        self.view = reduce_live_event(self.view, event)
        self.chains[event["stream_id"]] = (sequence + 1, event["content_hash"])
        self.history.append(copy.deepcopy(event))

    def control(
        self, reason: str, evidence: list[str] | None = None, state: str = "WAITING_FOR_DATA"
    ) -> None:
        event = envelope(
            "HealthChange",
            dict(
                binding_id=self.view["binding_id"],
                reason=reason,
                state=state,
                epoch=str(self.view["epoch"]),
                evidence_hashes=evidence or [],
            ),
        )
        event["received_mono_us"] = str(self.mono)
        event["content_hash"] = event_hash(event)
        self.apply(event)
        self.last_event = event

    def provider(self, value: dict[str, Any], *, requested: bool = True) -> None:
        payload = copy.deepcopy(value)
        payload.update(
            received_mono_us=str(self.mono),
            clock_domain_id=CLOCK,
            request_id=str(uuid4()),
            batch_observation_id=str(uuid4()),
        )
        prior = self.view["provider"]
        payload["content_revision"] = str(
            1
            if prior is None
            else int(prior["content_revision"]) + (semantic_hash(prior) != semantic_hash(payload))
        )
        if requested:
            self.control("PROVIDER_REQUEST_STARTED", [request_reference(payload["request_id"])])
        self.last_event = envelope("ProviderState", payload)
        self.last_event["received_mono_us"] = str(self.mono)
        self.apply(self.last_event)

    def book(self, value: dict[str, Any], *, requested: bool = True, receipt: bool = True) -> None:
        payload = copy.deepcopy(value)
        prior = self.view["books"].get(payload["horizon"])
        payload["capture_revision"] = str(
            1 if prior is None else int(prior["capture_revision"]) + 1
        )
        payload["browser_mono_us"] = str(900000000000 + int(payload["capture_revision"]))
        event = envelope("MarketBook", payload)
        if requested:
            token = hashlib.sha256(uuid4().bytes).hexdigest()
            self.control("CAPTURE_REQUEST_STARTED", [token])
            event["observation_id"] = capture_observation_id(token, payload["horizon"])
        event["content_hash"] = event_hash(event)
        self.apply(event)
        if receipt:
            self.control("CAPTURE_RECEIVED", [event["content_hash"]])
        self.last_event = event

    def tick(self, seconds: int) -> None:
        self.mono += seconds * 1000000
        self.control("CLOCK_TICK")

    def ready(self, provider: dict[str, Any], book: dict[str, Any]) -> None:
        self.provider(provider)
        self.book(book)
        assert self.view["market_eligible"]


def test_display_current_never_source_update_or_money(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    r = Reducer()
    r.ready(normalize(synthetic_provider_response).states[101], synthetic_book)
    assert r.view["source_age"] is None and r.view["source_time_status"] == "UNKNOWN"
    assert r.view["books"]["FT"]["browser_mono_us"] != str(r.view["backend_now_us"])
    assert r.view["model_enabled"] is False and r.view["money_ready"] is False


@pytest.mark.parametrize("change", ["goal", "var_reversal", "card", "period"])
def test_invalidation_requires_two_new_observations_after_change(
    synthetic_provider_response: Any, synthetic_book: Any, change: str
) -> None:
    provider = normalize(synthetic_provider_response).states[101]
    if change == "var_reversal":
        provider["score_current"] = {"home": 1, "away": 0}
        synthetic_book["operator_score"] = provider["score_current"].copy()
    r = Reducer()
    r.ready(provider, synthetic_book)
    original = copy.deepcopy(r.view)
    if change in {"goal", "var_reversal"}:
        provider["score_current"]["home"] = 1 if change == "goal" else 0
    if change == "card":
        provider["events_status"] = "OBSERVED"
        provider["events"] = [
            dict(
                elapsed_minute=11,
                extra_minute=None,
                team_id=201,
                player_id=501,
                assist_id=None,
                type="CARD",
                detail="RED_CARD",
            )
        ]
    if change == "period":
        provider.update(period="HALFTIME", status_code="HT")
    r.tick(1)
    r.provider(provider)
    assert not r.view["market_eligible"] and r.view["epoch"] > original["epoch"]
    assert original["market_eligible"]  # reducer did not mutate the old view
    synthetic_book["operator_score"] = copy.deepcopy(provider["score_current"])
    synthetic_book["operator_period"] = provider["period"]
    r.book(synthetic_book)
    assert not r.view["market_eligible"]
    r.tick(1)
    r.provider(provider)
    r.book(synthetic_book)
    assert r.view["market_eligible"]


@pytest.mark.parametrize(
    "reason,state",
    [
        ("SEQUENCE_GAP", "GAP"),
        ("NAVIGATED", "CONTEXT_UNVERIFIED"),
        ("HIDDEN", "STALE_MARKET"),
        ("WORKER_RESTART", "CONTEXT_UNVERIFIED"),
    ],
)
def test_gap_and_lifecycle_never_reopen_by_timer(
    synthetic_provider_response: Any, synthetic_book: Any, reason: str, state: str
) -> None:
    provider = normalize(synthetic_provider_response).states[101]
    r = Reducer()
    r.ready(provider, synthetic_book)
    r.control(reason, state=state)
    r.tick(1)
    r.book(synthetic_book, requested=False)
    r.provider(provider, requested=False)
    assert not r.view["market_eligible"]
    r.tick(1)
    r.provider(provider)
    r.book(synthetic_book)
    assert r.view["market_eligible"]


def test_suspension_and_document_invalidate_old_open_book(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    provider = normalize(synthetic_provider_response).states[101]
    r = Reducer()
    r.ready(provider, synthetic_book)
    r.book({**synthetic_book, "market_status": "SUSPENDED"})
    assert r.view["market_states"]["FT"]["status"] == "MARKET_SUSPENDED"
    r.tick(1)
    r.book(synthetic_book)
    assert not r.view["market_eligible"]
    r.provider(provider)
    assert r.view["market_eligible"]
    r.book({**synthetic_book, "document_epoch": str(uuid4())})
    assert not r.view["market_eligible"]


def test_receipt_content_and_source_ages_stay_separate(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    provider = normalize(synthetic_provider_response).states[101]
    r = Reducer()
    r.ready(provider, synthetic_book)
    r.tick(30)
    r.provider(provider)
    r.book(synthetic_book)
    assert r.view["provider_receipt_age_us"] == 0
    assert r.view["provider_content_age_us"] == 30000000
    assert r.view["market_states"]["FT"]["receipt_age_us"] == 0
    assert r.view["market_states"]["FT"]["content_age_us"] == 30000000
    assert r.view["market_states"]["FT"]["source_age"] is None
    r.tick(36)
    assert r.view["market_states"]["FT"]["status"] == "STALE_MARKET"
    r.tick(10)
    assert r.view["market_states"]["FT"]["status"] == "STALE_PROVIDER"


def test_ht_interval_uses_125_second_provider_threshold(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    provider = normalize(synthetic_provider_response).states[101]
    provider.update(period="HALFTIME", status_code="HT")
    synthetic_book["operator_period"] = "HALFTIME"
    r = Reducer()
    r.control("SCHEDULE_60")
    r.ready(provider, synthetic_book)
    r.tick(60)
    r.book(synthetic_book)
    assert r.view["market_eligible"]
    r.tick(66)
    r.book(synthetic_book)
    assert r.view["market_states"]["FT"]["status"] == "STALE_PROVIDER"


@pytest.mark.parametrize("missing", ["operator_score", "operator_period"])
def test_missing_context_is_visible_unverified(
    synthetic_provider_response: Any, synthetic_book: Any, missing: str
) -> None:
    r = Reducer()
    r.provider(normalize(synthetic_provider_response).states[101])
    synthetic_book[missing] = None
    r.book(synthetic_book)
    assert r.view["market_states"]["FT"]["status"] == "CONTEXT_UNVERIFIED"


def test_h2_requires_observed_halftime_baseline_and_normal_time(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    provider = normalize(synthetic_provider_response).states[101]
    provider.update(
        period="H2",
        status_code="2H",
        score_current={"home": 2, "away": 1},
        score_ht={"home": 2, "away": 0},
    )
    synthetic_book.update(horizon="H2", operator_period="H2", operator_score={"home": 2, "away": 1})
    r = Reducer()
    r.provider(provider)
    r.book(synthetic_book)
    assert r.view["h2_score"] is None
    assert r.view["market_states"]["H2"]["status"] == "CONTEXT_UNVERIFIED"
    r = Reducer()
    r.provider(
        {
            **provider,
            "period": "HALFTIME",
            "status_code": "HT",
            "score_current": provider["score_ht"],
        }
    )
    r.provider(provider)
    r.provider(provider)
    r.book(synthetic_book)
    assert r.view["h2_score"] == {"home": 0, "away": 1}
    assert r.view["market_eligible"]
    # H2 context uses the whole-match score; a 0-1 display must not be mistaken for 2-1.
    r.book({**synthetic_book, "operator_score": {"home": 0, "away": 1}})
    assert r.view["market_states"]["H2"]["status"] == "STATE_CONFLICT"
    r.provider({**provider, "period": "OUT_OF_SCOPE", "status_code": "ET"})
    assert not r.view["market_eligible"]


def test_horizons_and_five_fixture_projections_are_independent(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    r = Reducer()
    provider = normalize(synthetic_provider_response).states[101]
    r.ready(provider, synthetic_book)
    r.book({**synthetic_book, "horizon": "H1", "market_status": "CLOSED"})
    r.provider(provider)
    r.book(synthetic_book)
    assert r.view["market_states"]["FT"]["market_eligible"]
    assert not r.view["market_states"]["H1"]["market_eligible"]
    untouched = [copy.deepcopy(r.view) for _ in range(4)]
    r.control("SEQUENCE_GAP", state="GAP")
    assert all(v["market_eligible"] for v in untouched)
    for index, v in enumerate(untouched, start=1):
        v["binding"]["provider_fixture_id"] += index
        with pytest.raises(ValueError, match="BINDING"):
            reduce_live_event(v, envelope("ProviderState", provider))


def test_old_capture_after_binding_change_and_fake_receipt_reject(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    r = Reducer()
    r.ready(normalize(synthetic_provider_response).states[101], synthetic_book)
    revised = {**r.view["binding"], "revision": "2"}
    r.view = reduce_live_event(
        r.view,
        envelope(
            "BindingChange", dict(before_revision="1", after=revised, reason="DOCUMENT_CHANGED")
        ),
    )
    with pytest.raises(ValueError, match="BINDING"):
        r.book(synthetic_book)
    with pytest.raises(ValueError, match="RECEIPT"):
        r.control("CAPTURE_RECEIVED", ["c" * 64])


def test_stop_profile_expiry_and_clock_drift_cannot_be_refreshed(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    provider = normalize(synthetic_provider_response).states[101]
    for reason in ("STOPPED", "PROFILE_EXPIRED"):
        r = Reducer()
        r.ready(provider, synthetic_book)
        r.control(reason, state=reason)
        r.tick(1)
        assert not r.view["market_eligible"]
        with pytest.raises(ValueError):
            r.control("USER_RESUME")
    r = Reducer()
    r.ready(provider, synthetic_book)
    r.tick(1)
    r.mono = 0
    with pytest.raises(ValueError, match="CLOCK"):
        r.control("CLOCK_TICK")


def captured(tmp_path: Any, synthetic_book: Any) -> tuple[CapturedFields, Any]:
    p = profile()
    observed = sample(p)
    evidence = evidence_for(tmp_path, p, observed)
    admitted = validate_extraction_profile(p, evidence)
    fields = {
        k: copy.deepcopy(synthetic_book[k])
        for k in (
            "operator_fixture_id",
            "market_id",
            "horizon",
            "settlement_basis",
            "market_status",
            "operator_score",
            "operator_period",
        )
    }
    fields.update(
        home_id="SYNTHETIC-H",
        away_id="SYNTHETIC-A",
        selections={
            side: {"selection_id": quote["selection_id"], "price_text": quote["decimal_odds"]}
            for side, quote in synthetic_book["selections"].items()
        },
    )
    return CapturedFields(
        (fields, copy.deepcopy(fields)),
        binding(),
        "https://example.invalid/match/101",
        synthetic_book["observed_at_utc"],
        900000,
        1000000,
        CLOCK,
        "1",
        synthetic_book["document_epoch"],
    ), admitted


def test_complete_book_uses_only_observed_profile_map(tmp_path: Any, synthetic_book: Any) -> None:
    capture, p = captured(tmp_path, synthetic_book)
    result = assemble_book(capture, p)
    assert result["selections"] == synthetic_book["selections"]
    assert result["profile_hash"] == p.profile_hash
    assert result["source_updated_at"] is None and result["native_revision"] is None
    assert result["capture_evidence_tier"] == "DISPLAY_COHERENT"


@pytest.mark.parametrize(
    "mutation",
    [
        "partial",
        "mixed",
        "swapped",
        "market",
        "horizon",
        "settlement",
        "price",
        "same_id",
        "path",
        "too_fast",
        "attribute",
    ],
)
def test_partial_or_mixed_capture_is_not_a_book(
    tmp_path: Any, synthetic_book: Any, mutation: str
) -> None:
    capture, p = captured(tmp_path, synthetic_book)
    first, second = capture.snapshots
    if mutation == "mixed":
        second["selections"]["HOME"]["price_text"] = "1.91"
    else:
        if mutation == "partial":
            del first["selections"]["DRAW"]
        if mutation == "swapped":
            first["home_id"], first["away_id"] = first["away_id"], first["home_id"]
        if mutation == "market":
            first["market_id"] = "TEST_ONLY_WRONG"
        if mutation == "horizon":
            first["horizon"] = "H2"
        if mutation == "settlement":
            first["settlement_basis"] = "UNSUPPORTED"
        if mutation == "price":
            first["selections"]["HOME"]["price_text"] = "NaN"
        if mutation == "same_id":
            first["selections"]["HOME"]["selection_id"] = first["selections"]["AWAY"][
                "selection_id"
            ]
        if mutation == "attribute":
            first["cookie"] = "TEST_ONLY_REJECTED"
        capture = replace(capture, snapshots=(first, copy.deepcopy(first)))
    if mutation == "path":
        capture = replace(capture, exact_url="https://example.invalid/other")
    if mutation == "too_fast":
        capture = replace(capture, first_read_mono_us=999999)
    with pytest.raises(ValueError, match="BOOK"):
        assemble_book(capture, p)


def test_binding_starts_waiting() -> None:
    view = reduce_live_event(
        None,
        envelope(
            "BindingChange",
            {"before_revision": None, "after": binding(), "reason": "SYNTHETIC_REGISTRATION"},
        ),
    )
    assert view["market_eligible"] is False
    assert view["source_age"] is None


def test_h2_baseline() -> None:
    assert h2_score((2, 0), (2, 1)) == (0, 1)
    assert h2_score(None, (2, 1)) is None


def test_repeated_requests_remain_bounded_and_old_capture_cannot_reopen(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    r = Reducer()
    provider = normalize(synthetic_provider_response).states[101]
    r.ready(provider, synthetic_book)
    stale_token = hashlib.sha256(uuid4().bytes).hexdigest()
    r.control("CAPTURE_REQUEST_STARTED", [stale_token])
    for _ in range(40):
        r.control("CAPTURE_REQUEST_STARTED", [hashlib.sha256(uuid4().bytes).hexdigest()])
        r.control("PROVIDER_REQUEST_STARTED", [request_reference(str(uuid4()))])
    assert len(r.view["capture_requests"]) == 3 and len(r.view["requests"]) == 1
    book = {**synthetic_book, "capture_revision": "2"}
    event = envelope("MarketBook", book)
    event["observation_id"] = capture_observation_id(stale_token, "FT")
    r.apply(event)
    r.control("CAPTURE_RECEIVED", [event["content_hash"]])
    assert not r.view["market_eligible"]


def test_reducer_controls_replay_from_actual_sqlite(
    tmp_path: Any, synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    from moj_discovery.live_replay import verify_live_replay
    from moj_discovery.live_store import LiveStore
    from tests.live.test_live_store import metadata

    r = Reducer()
    provider = normalize(synthetic_provider_response).states[101]
    r.ready(provider, synthetic_book)
    r.tick(30)
    r.provider(provider)
    r.book(synthetic_book)
    r.control("SEQUENCE_GAP", state="GAP")
    r.tick(1)
    r.provider(provider)
    r.book(synthetic_book)
    r.tick(36)
    run = tmp_path / "observed-run"
    with LiveStore(run / "live.sqlite3", **metadata()) as store:
        for event in r.history:
            store.append(event)
        actual = store.read_projection(r.view["binding_id"])
        assert actual["market_eligible"] is False
        assert actual["market_states"]["FT"]["status"] == "STALE_MARKET"
        assert actual["source_age"] is None
        assert actual == r.view
        store.close_run("2026-09-09T18:20:00Z", "USER_STOP")
    first = verify_live_replay(run, tmp_path / "replay-one")
    second = verify_live_replay(run, tmp_path / "replay-two")
    assert first.equal and second.equal
    assert first.events == len(r.history)
    assert first.logical_sha256 == second.logical_sha256


def test_five_actual_sqlite_projections_do_not_cross_refresh(
    tmp_path: Any, synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    from moj_discovery.live_store import LiveStore
    from tests.live.test_live_store import metadata

    provider = normalize(synthetic_provider_response).states[101]
    with LiveStore(tmp_path / "five" / "live.sqlite3", **{**metadata(), "max_matches": 5}) as store:
        bindings = []
        provider_events = []
        for offset in range(5):
            b = {
                **binding(),
                "binding_id": str(uuid4()),
                "provider_fixture_id": 101 + offset,
                "operator_fixture_id": f"SYNTHETIC-{101 + offset}",
            }
            bindings.append(b)
            store.append(
                envelope(
                    "BindingChange",
                    {"before_revision": None, "after": b, "reason": "SYNTHETIC_REGISTRATION"},
                    stream=str(uuid4()),
                )
            )
            event = envelope(
                "ProviderState",
                {**provider, "fixture_id": 101 + offset, "request_id": str(uuid4())},
                stream=str(uuid4()),
            )
            provider_events.append(event)
            store.append(event)
            store.append(
                envelope(
                    "MarketBook",
                    {
                        **synthetic_book,
                        "binding_id": b["binding_id"],
                        "operator_fixture_id": b["operator_fixture_id"],
                    },
                    stream=str(uuid4()),
                )
            )
        before = [store.read_projection(b["binding_id"]) for b in bindings]
        first = provider_events[0]
        changed = envelope(
            "ProviderState",
            {
                **first["payload"],
                "content_revision": "2",
                "score_current": {"home": 1, "away": 0},
                "request_id": str(uuid4()),
            },
            sequence=2,
            previous=first["content_hash"],
            stream=first["stream_id"],
        )
        store.append(changed)
        assert store.read_projection(bindings[0]["binding_id"])["epoch"] > before[0]["epoch"]
        for index in range(1, 5):
            assert store.read_projection(bindings[index]["binding_id"]) == before[index]


def test_new_challenge_cannot_reuse_an_old_capture_revision(
    synthetic_provider_response: Any, synthetic_book: Any
) -> None:
    r = Reducer()
    r.ready(normalize(synthetic_provider_response).states[101], synthetic_book)
    token = hashlib.sha256(uuid4().bytes).hexdigest()
    r.control("CAPTURE_REQUEST_STARTED", [token])
    event = envelope("MarketBook", r.view["books"]["FT"])
    event["observation_id"] = capture_observation_id(token, "FT")
    with pytest.raises(ValueError, match="CAPTURE_REVISION"):
        r.apply(event)
