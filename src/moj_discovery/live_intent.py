"""One-use local terminal consent. This is not an independent review or signature."""

import copy
import fcntl
import hashlib
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

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


def discovery_field_map(value: Any) -> dict[str, Any]:
    """Bound selector data only; this does not assert the selectors were observed."""
    from .operator_profile import REQUIRED_CAPTURE, validate_selector

    if type(value) is dict and value == {"selection_mode": "USER_SELECTED_REGION_V1"}:
        return copy.deepcopy(value)
    if type(value) is not dict or set(value) != set(REQUIRED_CAPTURE) | {"score", "period"}:
        raise ValueError("E_DISCOVERY_FIELD_MAP")
    for name, selector in value.items():
        if selector is None and name != "match_root":
            continue
        validate_selector(selector)
    root = value["match_root"]
    if "#" not in root and "[data-" not in root:
        raise ValueError("E_DISCOVERY_ROOT")
    return copy.deepcopy(value)


def discovery_review_scope(
    intent: "RunIntent",
    config: LiveConfig,
    selectors: dict[str, Any],
    profile_name: str,
    expires_at: str,
) -> dict[str, Any]:
    """Pre-sample tool review, deliberately independent of accepted profile evidence."""
    from urllib.parse import urlsplit

    from .live_preflight_batched import _expires
    from .operator_profile import capture_source_hash

    value = _validate(intent, config, datetime.now(UTC))
    if value["stage"] != "OPERATOR_DISCOVERY" or len(value["fixture_ids"]) != 1:
        raise ValueError("E_DISCOVERY_INTENT")
    parsed = urlsplit(value["operator_urls"][0])
    if parsed.netloc != "miseojeuplus.espacejeux.com" or not parsed.path.startswith("/sports/"):
        raise ValueError("E_DISCOVERY_ORIGIN")
    if (
        type(profile_name) is not str
        or not 1 <= len(profile_name) <= 80
        or any(ord(c) < 32 or ord(c) == 127 for c in profile_name)
    ):
        raise ValueError("E_DISCOVERY_PROFILE_NAME")
    _expires(expires_at, datetime.now(UTC))
    return dict(
        kind="OPERATOR_DISCOVERY_TOOL",
        source_tree_sha256=source_tree_hash(intent.root),
        capture_source_sha256=capture_source_hash(intent.root),
        config_sha256=config.sha256,
        fixture_ids=value["fixture_ids"],
        exact_url=value["operator_urls"][0],
        selectors=discovery_field_map(selectors),
        profile_name=profile_name,
        max_duration_seconds=value["max_duration_seconds"],
        max_http_attempts=0,
        expires_at=expires_at,
    )


def discovery_mac(key: bytes, kind: str, run_id: str, nonce: str, payload: str = "") -> str:
    import hmac

    if len(key) != 32 or kind not in {"AUTH", "PLAN", "SAMPLE", "ACK"}:
        raise ValueError("E_DISCOVERY_MAC")
    data = f"BH-DISCOVERY/v1\0{kind}\0{run_id}\0{nonce}\0{payload}".encode()
    return hmac.new(key, data, "sha256").hexdigest()


async def serve_operator_discovery(
    receipt: "RunIntentReceipt",
    selectors: dict[str, Any],
    profile_name: str,
    review: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """One reviewed, consented, keyless exchange with the fixed extension reader."""
    import asyncio
    import base64
    import hmac
    import json
    import secrets

    from websockets.asyncio.server import serve
    from websockets.typing import Origin

    from tools.qualify_chrome_indexeddb import _extension_id

    from .live_preflight_batched import verify_external_review

    verify_receipt(receipt, "OPERATOR_DISCOVERY")
    scope = discovery_review_scope(
        receipt.intent,
        receipt.config,
        selectors,
        profile_name,
        review.get("scope", {}).get("expires_at", ""),
    )
    verify_external_review(review, scope, receipt.intent.root, datetime.now(UTC))
    # Claim only after actual tool review. An accepted capture profile is not required.
    claim_receipt(receipt, "OPERATOR_DISCOVERY")
    path = private_path(str(output.relative_to(receipt.intent.root)), root=receipt.intent.root)
    if path.exists():
        raise ValueError("E_DISCOVERY_OUTPUT_EXISTS")
    key = secrets.token_bytes(32)
    manifest = json.loads((receipt.intent.root / "extension/manifest.live.json").read_text())
    origin = "chrome-extension://" + _extension_id(manifest["key"])
    deadline = min(
        receipt.deadline_mono,
        time.monotonic()
        + (datetime.fromisoformat(scope["expires_at"]) - datetime.now(UTC)).total_seconds(),
    )
    finished = asyncio.Event()
    result: dict[str, Any] = {"status": "NOT_OBSERVED", "profile_accepted": False}
    claimed = False

    def current() -> None:
        verify_receipt(receipt, "OPERATOR_DISCOVERY")
        if time.monotonic() >= deadline:
            raise ValueError("E_DISCOVERY_EXPIRED")
        verify_external_review(review, scope, receipt.intent.root, datetime.now(UTC))

    async def exchange(ws: Any) -> None:
        nonlocal claimed, result
        if claimed or ws.request.path != "/operator-discovery":
            await ws.close(code=1008)
            return
        claimed = True
        nonce = secrets.token_hex(32)
        try:
            async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                current()
                await ws.send(json.dumps({"run_id": receipt.run_id, "nonce": nonce}))
                auth = parse_strict_json((await asyncio.wait_for(ws.recv(), 5)).encode())
                if (
                    type(auth) is not dict
                    or set(auth) != {"mac"}
                    or not hmac.compare_digest(
                        str(auth["mac"]), discovery_mac(key, "AUTH", receipt.run_id, nonce)
                    )
                ):
                    raise ValueError("E_DISCOVERY_AUTH")
                current()
                plan = dict(
                    exactUrl=scope["exact_url"],
                    sourceKind="OBSERVED_REAL",
                    fieldMapHash=hashlib.sha256(rfc8785.dumps(scope["selectors"])).hexdigest(),
                    selectors=scope["selectors"],
                    expiresAt=scope["expires_at"],
                    leaseMs=max(1, int((deadline - time.monotonic()) * 1000)),
                )
                payload = json.dumps(plan, separators=(",", ":"), ensure_ascii=False)
                await ws.send(
                    json.dumps(
                        {
                            "payload": payload,
                            "mac": discovery_mac(key, "PLAN", receipt.run_id, nonce, payload),
                        }
                    )
                )
                frame = parse_strict_json((await ws.recv()).encode())
                if (
                    type(frame) is not dict
                    or set(frame) != {"payload", "mac"}
                    or type(frame["payload"]) is not str
                    or not hmac.compare_digest(
                        str(frame["mac"]),
                        discovery_mac(key, "SAMPLE", receipt.run_id, nonce, frame["payload"]),
                    )
                ):
                    raise ValueError("E_DISCOVERY_SAMPLE_MAC")
                sample = parse_strict_json(frame["payload"].encode())
                validate_discovery_sample(sample, plan)
                current()
                candidate = dict(
                    status="UNADMITTED_SAMPLE",
                    profile_accepted=False,
                    binding_verified=False,
                    source_kind="OBSERVED_REAL",
                    sample=sample,
                    run_id=receipt.run_id,
                    intent_sha256=receipt.intent.sha256,
                    source_tree_sha256=scope["source_tree_sha256"],
                    review_scope_sha256=hashlib.sha256(rfc8785.dumps(scope)).hexdigest(),
                    profile_name_user_supplied=profile_name,
                    provider_requests=0,
                )
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as handle:
                    json.dump(candidate, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                result = {**candidate, "status": "UNADMITTED_SAMPLE_SAVED"}
                payload = json.dumps({"status": "UNADMITTED_SAMPLE_SAVED"}, separators=(",", ":"))
                await ws.send(
                    json.dumps(
                        {
                            "payload": payload,
                            "mac": discovery_mac(key, "ACK", receipt.run_id, nonce, payload),
                        }
                    )
                )
        except Exception:
            if result["status"] != "UNADMITTED_SAMPLE_SAVED":
                result = {"status": "DISCOVERY_REJECTED", "profile_accepted": False}
        finally:
            finished.set()

    # Same pinned local authority as Part B. No arbitrary URL, port or proxy surface.
    async with serve(
        exchange,
        "127.0.0.1",
        8765,
        origins=[Origin(origin)],
        max_size=16384,
        max_queue=1,
        compression=None,
        ping_interval=None,
        close_timeout=1,
    ):
        ticket = dict(
            kind="OPERATOR_DISCOVERY",
            runId=receipt.run_id,
            key=base64.urlsafe_b64encode(key).decode().rstrip("="),
        )
        print(
            "LOCAL_DISCOVERY_PAIRING_TICKET: " + json.dumps(ticket, separators=(",", ":")),
            flush=True,
        )
        with suppress(TimeoutError):
            await asyncio.wait_for(finished.wait(), max(0.001, deadline - time.monotonic()))
    return result


def validate_selection_map(value: Any) -> None:
    """Only observed candidate text/selectors; no semantic profile admission."""
    import json
    import unicodedata

    from .operator_profile import validate_selector

    if (
        type(value) is not dict
        or set(value) != {"match_root_selector", "candidates"}
        or type(value["candidates"]) is not list
        or not 1 <= len(value["candidates"]) <= 32
        or len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) > 10000
    ):
        raise ValueError("E_DISCOVERY_MAP")
    validate_selector(value["match_root_selector"])
    if "#" not in value["match_root_selector"] and "[data-" not in value["match_root_selector"]:
        raise ValueError("E_DISCOVERY_ROOT")
    seen = set()
    for row in value["candidates"]:
        if type(row) is not dict or set(row) != {"selector", "text", "market_id"}:
            raise ValueError("E_DISCOVERY_MAP")
        validate_selector(row["selector"])
        if row["selector"] in seen or row["text"] is None and row["market_id"] is None:
            raise ValueError("E_DISCOVERY_MAP")
        seen.add(row["selector"])
        for text in (row["text"], row["market_id"]):
            if text is not None and (
                type(text) is not str
                or not 1 <= len(text) <= 256
                or text != unicodedata.normalize("NFC", text)
                or any(ord(c) < 32 or ord(c) == 127 for c in text)
            ):
                raise ValueError("E_DISCOVERY_TEXT")


def validate_discovery_sample(sample: Any, plan: dict[str, Any]) -> None:
    import unicodedata

    mapping = discovery_field_map(plan["selectors"]) == {
        "selection_mode": "USER_SELECTED_REGION_V1"
    }
    fields = set(discovery_field_map(plan["selectors"])) - {"match_root"}
    if (
        type(sample) is not dict
        or set(sample)
        != {
            "status",
            "source_kind",
            "exact_url",
            "field_map_hash",
            "tab_id",
            "document_id",
            "document_epoch",
            "fields",
            "observed_at_utc",
            "browser_mono_us",
            "profile_accepted",
            "binding_verified",
        }
        or sample["status"] != "UNADMITTED_SAMPLE"
        or sample["source_kind"] != plan["sourceKind"]
        or sample["exact_url"] != plan["exactUrl"]
        or sample["field_map_hash"] != plan["fieldMapHash"]
        or sample["profile_accepted"] is not False
        or sample["binding_verified"] is not False
    ):
        raise ValueError("E_DISCOVERY_SAMPLE_SCOPE")
    if mapping:
        validate_selection_map(sample["fields"])
    elif type(sample["fields"]) is not dict or set(sample["fields"]) != fields:
        raise ValueError("E_DISCOVERY_FIELDS")
    for value in [] if mapping else sample["fields"].values():
        if value is not None and (
            type(value) is not str
            or not 1 <= len(value) <= 256
            or value != unicodedata.normalize("NFC", value)
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("E_DISCOVERY_TEXT")
    if type(sample["tab_id"]) is not int or sample["tab_id"] < 0:
        raise ValueError("E_DISCOVERY_TAB")
    for name in ("document_id", "document_epoch", "observed_at_utc", "browser_mono_us"):
        if type(sample[name]) is not str or not 1 <= len(sample[name]) <= 128:
            raise ValueError("E_DISCOVERY_IDENTITY")

    try:
        stamp = datetime.fromisoformat(sample["observed_at_utc"])
        age = (datetime.now(UTC) - stamp).total_seconds()
        mono = sample["browser_mono_us"]
        if (
            stamp.utcoffset() != UTC.utcoffset(stamp)
            or not -1 <= age <= 600
            or str(UUID(sample["document_epoch"])) != sample["document_epoch"]
            or not mono.isascii()
            or not mono.isdecimal()
            or str(int(mono)) != mono
            or not 0 <= int(mono) <= 9223372036854775807
            or any(ord(c) < 32 or ord(c) == 127 for c in sample["document_id"])
        ):
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise ValueError("E_DISCOVERY_CLOCK_OR_DOCUMENT") from None


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
        lookup = value.get("lookup_date")
        if lookup is not None:
            from datetime import date

            if date.fromisoformat(lookup).isoformat() != lookup:
                raise ValueError()
        validate_intent_window(
            datetime.fromisoformat(value["issued_at"]),
            datetime.fromisoformat(value["expires_at"]),
            now,
        )
        if (
            value["config_sha256"] != config.sha256
            or value["source_tree_sha256"] != source_tree_hash(intent.root)
            or tuple(sorted(value["fixture_ids"])) != config.fixture_ids
            or not (0 if lookup is not None else 1)
            <= len(config.fixture_ids)
            <= cfg["runtime"]["max_matches"]
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
        or scope.lookup_date != value.get("lookup_date")
        or purpose
        not in (
            {"STATUS", "LOOKUP"}
            if scope.lookup_date is not None
            else {"STATUS", "COVERAGE", "BUNDLE"}
        )
    ):
        raise ValueError("E_INTENT_PROVIDER_SCOPE")
