"""Inert extraction profiles; live admission requires observed source-bound review."""

import copy
import hashlib
import importlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import rfc8785

from .canonical import parse_strict_json
from .live_config import private_path
from .live_contracts import MAX_INTEGER, schema_validate, validate_live_record

CAPTURE_FILES = (
    "extension/src/live/dom_reader.ts",
    "extension/src/live/capture.ts",
    "extension/src/live/background.ts",
    "extension/src/live/panel.ts",
    "extension/src/live/workspace.ts",
    "extension/src/live/contracts.ts",
    "extension/src/live/protocol.ts",
    "extension/src/live/spool.ts",
    "extension/src/live/transport.ts",
    "extension/src/storage/durable_idb.ts",
    "src/moj_discovery/operator_profile.py",
    "contracts/live_readonly/v1/operator-profile.schema.json",
    "contracts/live_readonly/v1/records.schema.json",
    "contracts/live_readonly/v1/wire.schema.json",
)
EXCLUDED = re.compile(
    r"password|passwd|token|cookie|account|balance|betslip|cashout|login|email|username|wallet|form|input|textarea|iframe|contenteditable",
    re.I,
)
IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_-]{0,127}"
TAG = r"(?:div|span|section|article|header|h[1-6]|p|strong|em|label)"
SUFFIX = (
    rf"(?:[.#]{IDENTIFIER}|\[data-(?:testid|role|fixture-id|market-id|selection-id)="
    r"""["'][A-Za-z0-9_-]{1,128}["']\])"""
)
COMPOUND = re.compile(rf"(?:{TAG}(?:{SUFFIX})*|(?:{SUFFIX})+)")
REQUIRED_CAPTURE = frozenset(
    {
        "match_root",
        "fixture_id",
        "home_team",
        "away_team",
        "home_id",
        "away_id",
        "market_root",
        "horizon_label",
        "home_selection",
        "draw_selection",
        "away_selection",
        "home_odds",
        "draw_odds",
        "away_odds",
        "market_status",
    }
)


@dataclass(frozen=True)
class ProfileEvidence:
    root: Path
    now_utc: datetime
    sample_paths: tuple[Path, ...] = ()
    review_path: Path | None = None
    fixture_bindings: tuple[dict[str, Any], ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class ExtractionProfile:
    _data: dict[str, Any] = field(repr=False)
    field_map: dict[str, dict[str, str]]
    observed_markets: dict[str, list[dict[str, Any]]]
    profile_hash: str
    _real_admitted: bool = False
    _review_proof: object = field(default=None, repr=False)

    @property
    def status(self) -> str:
        return str(self._data["status"])

    @property
    def public(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)


def capture_source_hash(root: Path) -> str:
    hashes = {}
    for name in CAPTURE_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("E_PROFILE_CAPTURE_SOURCE_MISSING")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(
        b"BH-LIVE-READONLY/CaptureSource/v1\0" + rfc8785.dumps(hashes)
    ).hexdigest()


def validate_selector(value: str) -> None:
    if type(value) is not str or not 1 <= len(value) <= 512 or EXCLUDED.search(value):
        raise ValueError("E_PROFILE_SELECTOR")
    # No escapes, pseudo selectors, wildcard, sibling traversal or selector-list union.
    parts = re.split(r"\s*>\s*|\s+", value)
    if not 1 <= len(parts) <= 8 or any(COMPOUND.fullmatch(p) is None for p in parts):
        raise ValueError("E_PROFILE_SELECTOR")


def parse_decimal_price(text: str, parser: str) -> str:
    if type(text) is not str or parser not in {"DECIMAL_DOT", "DECIMAL_COMMA"}:
        raise ValueError("E_PROFILE_PRICE")
    separator = r"\." if parser == "DECIMAL_DOT" else ","
    if re.fullmatch(rf"[1-9][0-9]{{0,5}}(?:{separator}[0-9]{{1,6}})?", text) is None:
        raise ValueError("E_PROFILE_PRICE")
    normalized = text.replace(",", ".")
    if Decimal(normalized) <= 1:
        raise ValueError("E_PROFILE_PRICE")
    return normalized


def _private_bytes(path: Path, root: Path) -> bytes:
    relative = path.absolute().relative_to(root.absolute())
    checked = private_path(str(relative), root=root, must_exist=True)
    if checked is None or checked.stat().st_size > 65536:
        raise ValueError("E_PROFILE_EVIDENCE_SIZE")
    return checked.read_bytes()


def _observed_labels(value: object) -> None:
    if type(value) is not dict or set(value) != {"horizon", "status", "period", "score_separator"}:
        raise ValueError("E_PROFILE_LABELS")
    if value["score_separator"] not in {None, "EN_DASH", "COLON", "HYPHEN"}:
        raise ValueError("E_PROFILE_LABELS")
    strings = [value["horizon"]]
    for name, permitted in (
        ("status", {"OPEN", "SUSPENDED", "CLOSED", "UNKNOWN"}),
        (
            "period",
            {"PREGAME", "H1", "HALFTIME", "H2", "FINISHED", "BLOCKED", "OUT_OF_SCOPE", "UNKNOWN"},
        ),
    ):
        mapping = value[name]
        if type(mapping) is not dict or not set(mapping) <= permitted:
            raise ValueError("E_PROFILE_LABELS")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("E_PROFILE_LABELS")
        strings.extend(mapping.values())
    for label in strings:
        if (
            type(label) is not str
            or not 1 <= len(label) <= 256
            or label != unicodedata.normalize("NFC", label)
            or any(ord(c) < 32 or ord(c) == 127 for c in label)
        ):
            raise ValueError("E_PROFILE_LABELS")


def _samples(
    value: dict[str, Any], evidence: ProfileEvidence, field_map: dict[str, dict[str, str]]
) -> dict[str, list[dict[str, Any]]]:
    bindings = {
        b["operator_fixture_id"]: validate_live_record(b, "FixtureBinding")
        for b in evidence.fixture_bindings
    }
    markets: dict[str, list[dict[str, Any]]] = {}
    hashes = []
    for path in evidence.sample_paths:
        raw = _private_bytes(path, evidence.root)
        hashes.append(hashlib.sha256(raw).hexdigest())
        sample = parse_strict_json(raw)
        keys = {
            "schema_version",
            "source_kind",
            "profile_id",
            "origin",
            "path",
            "fixture_id",
            "home_id",
            "away_id",
            "markets",
            "field_map",
        }
        if (
            type(sample) is not dict
            or set(sample) != keys
            or sample["schema_version"] != "operator-profile-sample/v1"
            or any(sample[k] != value[k] for k in ("source_kind", "profile_id", "origin"))
            or sample["path"] not in value["exact_paths"]
            or sample["fixture_id"] not in value["permitted_fixture_ids"]
            or sample["field_map"] != field_map
        ):
            raise ValueError("E_PROFILE_SAMPLE_SCOPE")
        binding = bindings[sample["fixture_id"]]
        if (
            sample["home_id"] != binding["operator_home_id"]
            or sample["away_id"] != binding["operator_away_id"]
            or binding["operator_match_url"] != sample["origin"] + sample["path"]
        ):
            raise ValueError("E_PROFILE_SAMPLE_ORIENTATION")
        if type(sample["markets"]) is not list or not 1 <= len(sample["markets"]) <= 3:
            raise ValueError("E_PROFILE_SAMPLE_MARKET")
        horizons = set()
        for market in sample["markets"]:
            if (
                type(market) is not dict
                or set(market)
                != {"market_id", "horizon", "settlement_basis", "selections", "labels"}
                or market["horizon"] not in value["horizons"]
                or market["horizon"] in horizons
                or market["settlement_basis"] != "NORMAL_TIME_INCLUDING_STOPPAGE"
                or type(market["selections"]) is not dict
                or set(market["selections"]) != {"HOME", "DRAW", "AWAY"}
                or len(set(market["selections"].values())) != 3
            ):
                raise ValueError("E_PROFILE_SAMPLE_MARKET")
            _observed_labels(market["labels"])
            for identifier in (market["market_id"], *market["selections"].values()):
                if (
                    type(identifier) is not str
                    or not 1 <= len(identifier) <= 128
                    or any(ord(c) < 32 or ord(c) == 127 for c in identifier)
                ):
                    raise ValueError("E_PROFILE_SAMPLE_MARKET")
            horizons.add(market["horizon"])
        if sample["fixture_id"] in markets and markets[sample["fixture_id"]] != sample["markets"]:
            raise ValueError("E_PROFILE_SAMPLE_CONFLICT")
        markets[sample["fixture_id"]] = sample["markets"]
    if sorted(hashes) != sorted(value["evidence_hashes"]):
        raise ValueError("E_PROFILE_SAMPLE_HASH")
    return markets


def validate_extraction_profile(value: object, evidence: ProfileEvidence) -> ExtractionProfile:
    try:
        schema_validate(value, "operator-profile")
        if (
            type(value) is not dict
            or not isinstance(evidence, ProfileEvidence)
            or evidence.now_utc.tzinfo is None
            or evidence.now_utc.utcoffset() != UTC.utcoffset(evidence.now_utc)
        ):
            raise ValueError()
        data = copy.deepcopy(value)
        if (
            int(data["profile_version"]) > MAX_INTEGER
            or len(data["permitted_fixture_ids"]) > data["max_matches"]
        ):
            raise ValueError()
        origin = urlsplit(data["origin"])
        if (
            origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path
            or not origin.hostname
        ):
            raise ValueError()
        if data["source_kind"] == "SYNTHETIC_TEST":
            if data["status"] != "DRAFT" or not (
                data["origin"] == "https://example.invalid"
                or (origin.scheme == "http" and origin.hostname == "127.0.0.1")
            ):
                raise ValueError()
        elif origin.scheme != "https" or origin.port not in {None, 443}:
            raise ValueError()
        for path in data["exact_paths"]:
            if (
                path.startswith("//")
                or "%" in path
                or "\\" in path
                or any(p in {".", ".."} for p in path.split("/"))
                or len(path) > 2048
            ):
                raise ValueError()
        selectors = data["selectors"]
        for selector in selectors.values():
            if selector is not None:
                validate_selector(selector)
        root_selector = selectors["match_root"]
        if root_selector is not None and "#" not in root_selector and "[data-" not in root_selector:
            raise ValueError()
        for fields in (
            ("home_team", "away_team"),
            ("home_id", "away_id"),
            ("home_selection", "draw_selection", "away_selection"),
            ("home_odds", "draw_odds", "away_odds"),
        ):
            present = [selectors[k] for k in fields if selectors[k] is not None]
            if len(set(present)) != len(present):
                raise ValueError()
        field_map = {
            name: {
                "selector": selector,
                "reader": "ROOT_NODE"
                if name == "match_root"
                else "DATA_MARKET_ID"
                if name == "market_root"
                else "TEXT_CONTENT",
            }
            for name, selector in selectors.items()
            if selector is not None
        }
        markets = _samples(data, evidence, field_map)
        admitted = False
        review_proof = None
        if data["status"] == "ACCEPTED":
            expires = datetime.fromisoformat(data["expires_at"])
            if (
                expires.tzinfo is None
                or not evidence.now_utc < expires
                or not field_map.keys() >= REQUIRED_CAPTURE
                or set(markets) != set(data["permitted_fixture_ids"])
                or evidence.review_path is None
                or int(data["profile_version"]) < 1
            ):
                raise ValueError()
            current = capture_source_hash(evidence.root)
            if data["capture_source_hash"] != current or data["reviewed_source_hash"] != current:
                raise ValueError()
            review = parse_strict_json(_private_bytes(evidence.review_path, evidence.root))
            # PB-16 verifies the external review authority. Its absence keeps the profile inert.
            review_proof = importlib.import_module(
                "moj_discovery.live_preflight_batched"
            ).verify_profile_review(data, review, evidence)
            admitted = True
        return ExtractionProfile(
            data,
            field_map,
            markets,
            hashlib.sha256(rfc8785.dumps(data)).hexdigest(),
            admitted,
            review_proof,
        )
    except Exception:
        raise ValueError("E_PROFILE_REJECTED") from None


def activate_profile(profile: ExtractionProfile, target: str) -> dict[str, Any]:
    value = profile.public
    if (
        target == "SYNTHETIC_TEST"
        and value["source_kind"] == "SYNTHETIC_TEST"
        and profile.status == "DRAFT"
    ):
        if not profile.field_map.keys() >= REQUIRED_CAPTURE:
            raise ValueError("E_PROFILE_UNCONFIGURED")
        return value
    if (
        target != "OPERATOR"
        or value["source_kind"] != "OBSERVED_REAL"
        or profile.status != "ACCEPTED"
        or not profile._real_admitted
    ):
        raise ValueError("E_PROFILE_INACTIVE")
    return value
