import importlib
import math
import re
from dataclasses import dataclass
from uuid import UUID

from .errors import ContractNotImplementedError


@dataclass(frozen=True)
class ProviderScope:
    scope_id: str
    fixture_ids: tuple[int, ...]
    league_id: int
    season: int
    deadline_mono: float
    source_kind: str = "MOCK"
    stage: str = "PROVIDER_PROBE"
    max_attempts: int = 20
    config_sha256: str = "0" * 64
    source_tree_sha256: str = "0" * 64
    receipt: object = None
    events_fixture_ids: tuple[int, ...] = ()
    lookup_date: str | None = None


def verify_probe_protocol(scope: ProviderScope | None = None) -> None:
    if type(scope) is not ProviderScope:
        raise ContractNotImplementedError("D0-T01")
    if (
        str(UUID(scope.scope_id)) != scope.scope_id
        or scope.source_kind not in {"MOCK", "OBSERVED_REAL"}
        or scope.stage not in {"PROVIDER_PROBE", "LIVE_READ_ONLY"}
        or not 1 <= len(scope.fixture_ids) <= 5
        or len(set(scope.fixture_ids)) != len(scope.fixture_ids)
        or any(type(i) is not int or not 0 < i <= 2**53 - 1 for i in scope.fixture_ids)
        or type(scope.league_id) is not int
        or not 0 < scope.league_id <= 2**53 - 1
        or type(scope.season) is not int
        or not 2000 <= scope.season <= 2100
        or type(scope.max_attempts) is not int
        or not 1 <= scope.max_attempts <= (20 if scope.stage == "PROVIDER_PROBE" else 600)
        or type(scope.deadline_mono) not in {int, float}
        or not math.isfinite(scope.deadline_mono)
        or not set(scope.events_fixture_ids) <= set(scope.fixture_ids)
        or any(type(i) is not int for i in scope.events_fixture_ids)
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", h)
            for h in (scope.config_sha256, scope.source_tree_sha256)
        )
    ):
        raise ValueError("E_PROVIDER_SCOPE")


def verify_call_authorization(
    scope: ProviderScope | None = None, *, purpose: str = "STATUS", now_mono: float = 0
) -> None:
    verify_probe_protocol(scope)
    assert scope is not None
    if (
        purpose not in {"STATUS", "COVERAGE", "LOOKUP", "BUNDLE", "EVENTS_FALLBACK"}
        or not math.isfinite(now_mono)
        or not now_mono < scope.deadline_mono
        or scope.deadline_mono > now_mono + (300 if scope.stage == "PROVIDER_PROBE" else 7200)
    ):
        raise ValueError("E_PROVIDER_DEADLINE_OR_PURPOSE")
    if scope.source_kind == "OBSERVED_REAL":
        try:
            # PB-14 supplies this owner. Missing owner/evidence always refuses real I/O.
            admission = importlib.import_module("moj_discovery.live_intent")
            admission.verify_provider_receipt(scope.receipt, scope, purpose)
        except Exception:
            raise ValueError("E_PROVIDER_REAL_AUTHORITY_REQUIRED") from None
