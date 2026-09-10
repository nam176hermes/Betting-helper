"""One-use local terminal consent. This is not an independent review or signature."""

import copy
import fcntl
import hashlib
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import rfc8785

from .canonical import parse_strict_json
from .live_config import ROOT, LiveConfig, private_path
from .live_contracts import schema_validate
from .provider_protocol import ProviderScope
from .secrets_local import controlling_tty

PHRASES = {
    "PROVIDER_PROBE": "ALLOW PROVIDER PROBE",
    "OPERATOR_DISCOVERY": "ALLOW OPERATOR OBSERVATION",
    "LIVE_READ_ONLY": "START READ ONLY",
}
_SEAL = object()
_claim_lock = threading.Lock()


def source_tree_hash(root: Path = ROOT) -> str:
    """Hash source and pinned build inputs only; never enumerate local credential files."""
    files: set[Path] = set()
    for folder, suffix in (
        ("src/moj_discovery", ".py"),
        ("tools", ".py"),
        ("tools", ".cjs"),
        ("extension/src", ".ts"),
        ("extension/src/live", ".html"),
        ("extension/src/live", ".css"),
        ("contracts/live_readonly/v1", ".json"),
        ("contracts/live_readonly/v1", ".sql"),
    ):
        files.update((root / folder).rglob("*" + suffix))
    files.update(
        root / name
        for name in (
            "pyproject.toml",
            "uv.lock",
            "package.json",
            "pnpm-lock.yaml",
            "extension/package.json",
            "extension/pnpm-lock.yaml",
            "extension/manifest.live.json",
            "extension/tsconfig.json",
            "extension/tsconfig.live.json",
        )
    )
    hashes = {}
    for path in sorted(files):
        if not path.exists():
            continue  # Optional root/extension lock location; the installed lock is included.
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("E_INTENT_SOURCE_PATH")
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hashes:
        raise ValueError("E_INTENT_SOURCE_EMPTY")
    return hashlib.sha256(b"BH-PartB-Source/v1\0" + rfc8785.dumps(hashes)).hexdigest()


def validate_intent_window(issued: datetime, expires: datetime, now: datetime) -> None:
    if (
        any(t.tzinfo is None or t.utcoffset() != UTC.utcoffset(t) for t in (issued, expires, now))
        or not 0 < (expires - issued).total_seconds() <= 900
        or not issued <= now < expires
    ):
        raise ValueError("E_INTENT_EXPIRED")


@dataclass(frozen=True)
class RunIntent:
    _data: dict[str, Any] = field(repr=False)
    sha256: str
    root: Path = field(repr=False, default=ROOT)
    original_json: str | None = field(default=None, repr=False)

    @property
    def public(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)


@dataclass(frozen=True)
class RunIntentReceipt:
    intent: RunIntent
    config: LiveConfig = field(repr=False)
    run_id: str
    deadline_mono: float
    consumed_at_utc: str
    started_mono: float
    confirmation_kind: str = "LOCAL_TTY_USER_CONFIRMATION"
    _proof: object = field(default=None, repr=False)
    _pid: int = field(default=0, repr=False)
    _claimed: bool = field(default=False, repr=False)
    _live_authority: object = field(default=None, repr=False, init=False)


def _validate(intent: RunIntent, config: LiveConfig, now: datetime) -> dict[str, Any]:
    try:
        if type(intent) is not RunIntent or type(config) is not LiveConfig:
            raise ValueError()
        value, cfg = intent.public, config.public
        schema_validate(value, "run-intent")
        validate_intent_window(
            datetime.fromisoformat(value["issued_at"]),
            datetime.fromisoformat(value["expires_at"]),
            now,
        )
        if (
            value["config_sha256"] != config.sha256
            or value["source_tree_sha256"] != source_tree_hash(intent.root)
            or tuple(sorted(value["fixture_ids"])) != config.fixture_ids
            or not 1 <= len(config.fixture_ids) <= cfg["runtime"]["max_matches"]
            or cfg["provider"]["league_id"] is None
            or cfg["provider"]["season"] is None
            or cfg["provider"]["events_fallback_enabled"]
            or cfg["provider"]["events_fallback_fixture_ids"]
        ):
            raise ValueError()
        if value["stage"] == "LIVE_READ_ONLY" and (
            not config.enabled
            or not 1 <= value["max_http_attempts"] <= cfg["provider"]["max_requests_per_run"]
            or len(value["operator_urls"]) != len(config.fixture_ids)
            or value["max_duration_seconds"] > cfg["runtime"]["max_run_minutes"] * 60
        ):
            raise ValueError()
        if (
            value["stage"] == "PROVIDER_PROBE"
            and value["max_http_attempts"] > cfg["provider"]["max_requests_per_run"]
        ):
            raise ValueError()
        for url in value["operator_urls"]:
            from urllib.parse import urlsplit

            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError()
        return value
    except Exception:
        raise ValueError("E_INTENT_SCOPE_OR_SOURCE") from None


def load_run_intent(path: Path, config: LiveConfig, stage: str, *, root: Path = ROOT) -> RunIntent:
    try:
        relative = str(path.relative_to(root)) if path.is_absolute() else str(path)
        checked = private_path(relative, root=root, must_exist=True)
        if checked.stat().st_size > 65536:
            raise ValueError()
        raw = checked.read_bytes()
        value = parse_strict_json(raw)
        if type(value) is not dict or value["stage"] != stage or stage not in PHRASES:
            raise ValueError()
        intent = RunIntent(value, hashlib.sha256(raw).hexdigest(), root, raw.decode())
        _validate(intent, config, datetime.now(UTC))
        if stage == "LIVE_READ_ONLY" and relative != config.public["gates"]["live_intent_path"]:
            raise ValueError()
        return intent
    except Exception:
        raise ValueError("E_INTENT_LOAD") from None


@contextmanager
def _ledger(root: Path) -> Iterator[sqlite3.Connection]:
    path = private_path(".local/part-b/intent-consumptions.sqlite3", root=root)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with closing(sqlite3.connect(path, timeout=5, isolation_level=None)) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                db.executescript((ROOT / "contracts/live_readonly/v1/intent-store.sql").read_text())
            elif version != 1:
                raise ValueError("E_INTENT_LEDGER_VERSION")
            yield db
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def consume_user_intent(
    intent: RunIntent, config: LiveConfig, confirmation: str
) -> RunIntentReceipt:
    """Only the user-terminal launcher calls this after displaying the exact scope."""
    now = datetime.now(UTC)
    value = _validate(intent, config, now)
    if type(confirmation) is not str or confirmation != PHRASES[value["stage"]]:
        raise ValueError("E_INTENT_DECLINED")
    # Presence of an environment credential never replaces the controlling terminal.
    with controlling_tty():
        pass
    run_id, stamp = str(uuid4()), now.isoformat().replace("+00:00", "Z")
    try:
        with _ledger(intent.root) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO intent_consumptions VALUES (?,?,?,?,?,?,?,?,0)",
                (
                    value["intent_id"],
                    intent.sha256,
                    run_id,
                    value["stage"],
                    value["source_tree_sha256"],
                    config.sha256,
                    stamp,
                    "LOCAL_TTY_USER_CONFIRMATION",
                ),
            )
            db.execute("COMMIT")
    except Exception:
        raise ValueError("E_INTENT_CONSUMED_OR_LEDGER") from None
    started = time.monotonic()
    return RunIntentReceipt(
        intent,
        config,
        run_id,
        started + value["max_duration_seconds"],
        stamp,
        started,
        _proof=_SEAL,
        _pid=os.getpid(),
    )


def verify_receipt(receipt: RunIntentReceipt, stage: str) -> None:
    try:
        if (
            type(receipt) is not RunIntentReceipt
            or receipt._proof is not _SEAL
            or receipt._pid != os.getpid()
            or receipt.intent.public["stage"] != stage
            or not receipt.started_mono <= time.monotonic() < receipt.deadline_mono
            or not 0
            <= (datetime.now(UTC) - datetime.fromisoformat(receipt.consumed_at_utc)).total_seconds()
            < receipt.intent.public["max_duration_seconds"]
            or receipt.config.sha256 != receipt.intent.public["config_sha256"]
            or source_tree_hash(receipt.intent.root) != receipt.intent.public["source_tree_sha256"]
        ):
            raise ValueError()
        with _ledger(receipt.intent.root) as db:
            row = db.execute(
                "SELECT intent_hash,run_id,config_hash,source_tree_hash "
                "FROM intent_consumptions WHERE intent_id=?",
                (receipt.intent.public["intent_id"],),
            ).fetchone()
            if row != (
                receipt.intent.sha256,
                receipt.run_id,
                receipt.config.sha256,
                receipt.intent.public["source_tree_sha256"],
            ):
                raise ValueError()
    except Exception:
        raise ValueError("E_INTENT_RECEIPT") from None


def claim_receipt(receipt: RunIntentReceipt, stage: str) -> None:
    with _claim_lock:
        verify_receipt(receipt, stage)
        if receipt._claimed:
            raise ValueError("E_INTENT_OPERATION_REPLAY")
        object.__setattr__(receipt, "_claimed", True)


def verify_provider_receipt(receipt: RunIntentReceipt, scope: ProviderScope, purpose: str) -> None:
    verify_receipt(receipt, scope.stage)
    if scope.stage == "LIVE_READ_ONLY":
        from .live_preflight_batched import verify_live_receipt

        verify_live_receipt(receipt)
    value, provider = receipt.intent.public, receipt.config.public["provider"]
    if (
        not receipt._claimed
        or receipt.intent.root.resolve() != ROOT.resolve()
        or scope.scope_id != receipt.run_id
        or scope.source_kind != "OBSERVED_REAL"
        or scope.config_sha256 != receipt.config.sha256
        or scope.source_tree_sha256 != value["source_tree_sha256"]
        or tuple(sorted(scope.fixture_ids)) != tuple(sorted(value["fixture_ids"]))
        or scope.league_id != provider["league_id"]
        or scope.season != provider["season"]
        or scope.max_attempts > value["max_http_attempts"]
        or scope.deadline_mono > receipt.deadline_mono
        or scope.events_fixture_ids
        or scope.lookup_date is not None
        or purpose not in {"STATUS", "COVERAGE", "BUNDLE"}
    ):
        raise ValueError("E_INTENT_PROVIDER_SCOPE")
