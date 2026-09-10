"""Network-free v2 evidence admission, separate from legacy v1 preflight."""

import copy
import hashlib
import importlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import rfc8785

from .canonical import parse_strict_json
from .live_config import ROOT, LiveConfig, private_path
from .live_contracts import validate_live_record
from .live_intent import RunIntentReceipt, claim_receipt, source_tree_hash, verify_receipt
from .operator_profile import (
    ExtractionProfile,
    ProfileEvidence,
    capture_source_hash,
    validate_extraction_profile,
)

_SEAL = object()
REQUIRED = {
    "provider": "REQUIRES_REAL_PROVIDER_EVIDENCE",
    "capture": "WAITING_OPERATOR_SAMPLE",
    "platform": "WAITING_PLATFORM",
    "offline": "REQUIRES_CURRENT_PART_A_EVIDENCE",
    "security": "WAITING_REVIEW",
}


def digest(value: Any) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def provider_config_scope(config: LiveConfig) -> dict[str, Any]:
    cfg = config.public
    return {
        "provider": cfg["provider"],
        "max_run_minutes": cfg["runtime"]["max_run_minutes"],
        "max_matches": cfg["runtime"]["max_matches"],
    }


def _read(path: Path, root: Path) -> tuple[dict[str, Any], str]:
    path = private_path(str(path.relative_to(root)), root=root, must_exist=True)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("E_LIVE_EVIDENCE_SIZE")
    raw = path.read_bytes()
    value = parse_strict_json(raw)
    if type(value) is not dict:
        raise ValueError("E_LIVE_EVIDENCE_OBJECT")
    return value, hashlib.sha256(raw).hexdigest()


def _expires(value: Any, now: datetime) -> datetime:
    expiry = datetime.fromisoformat(value)
    if expiry.utcoffset() != timedelta(0) or not now < expiry <= now + timedelta(days=1):
        raise ValueError("E_LIVE_REVIEW_EXPIRED")
    return expiry


def _host_trust_binding(root: Path) -> str:
    """Bind only configured public trust material and current boot; never a private key."""
    from tools.issue_review_launch_authorization import _regular_hash, review_public_key

    config_path = root / "review-config/review-authority.v1.json"
    config_hash = _regular_hash(config_path)
    config = json.loads(config_path.read_text())
    _, epoch = review_public_key(config)
    return digest(
        {
            "config": config_hash,
            "public_record": _regular_hash(Path(config["public_key_path"])),
            "epoch": epoch,
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        }
    )


def verify_external_review(
    bundle: dict[str, Any], scope: dict[str, Any], root: Path, now: datetime
) -> None:
    """Consume existing host-signed receipts. Never initialize/sign host authority."""
    from tools.issue_review_launch_authorization import (
        authorized_review_context,
        recheck_review_context,
        review_public_key,
    )

    from .review_aggregation import _review_is_well_formed
    from .review_authorization import verify_review_execution_receipt, verify_review_result_binding

    if (
        set(bundle) != {"schema_version", "scope", "result", "authorization", "receipt"}
        or bundle["schema_version"] != "part-b-review-evidence/v1"
        or digest(bundle["scope"]) != digest(scope)
    ):
        raise ValueError("E_LIVE_EXTERNAL_REVIEW")
    _expires(scope["expires_at"], now)
    result, authorization, receipt = (bundle[k] for k in ("result", "authorization", "receipt"))
    _review_is_well_formed(result, "CYBERSECURITY_REVIEWER", current=True)
    verify_review_result_binding(result, authorization)
    head = subprocess.check_output(
        ["/usr/bin/git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()  # noqa: S603 -- exact read-only checkout identity.
    if (
        result["repository_commit_oid"] != head
        or result["review_outcome"] != "PASS"
        or any(
            v != ("NONE" if k == "AUTHORIZED_PRODUCTION_PHASES" else "YES")
            for k, v in result["verdicts"].items()
        )
        or any(f["blocking"] for f in result["findings"])
        or not any(
            f["finding_id"] == "PART-B-SCOPE"
            and f["evidence_ids"] == ["sha256:" + digest(scope)]
            and not f["blocking"]
            for f in result["findings"]
        )
    ):
        raise ValueError("E_LIVE_REVIEW_SCOPE")
    # Only the configured public record is read. No caller-supplied trust key is accepted.
    authority_path = root / "review-config/review-authority.v1.json"
    if any(p.is_symlink() for p in (authority_path, *authority_path.parents)):
        raise ValueError("E_LIVE_REVIEW_TRUST")
    authority = json.loads(authority_path.read_text())
    public, epoch = review_public_key(authority)
    context = authorized_review_context(authorization, authority, runtime_root=root)
    verify_review_execution_receipt(
        receipt,
        authorization,
        public,
        result_sha256=digest(result),
        expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        expected_trust_epoch=epoch,
        now=now,
    )
    recheck_review_context(context)


def verify_profile_review(
    profile: dict[str, Any], review: dict[str, Any], evidence: ProfileEvidence
) -> None:
    scope = review.get("scope", {})
    expected = {
        "kind",
        "source_tree_sha256",
        "capture_source_sha256",
        "profile_sha256",
        "bindings",
        "sample_refs",
        "expires_at",
        "max_matches",
    }
    if (
        set(scope) != expected
        or scope["kind"] != "CAPTURE_PROFILE"
        or scope["source_tree_sha256"] != source_tree_hash(evidence.root)
        or scope["capture_source_sha256"] != capture_source_hash(evidence.root)
        or scope["profile_sha256"] != digest(profile)
        or scope["bindings"] != list(evidence.fixture_bindings)
        or scope["max_matches"] != profile["max_matches"]
        or profile["source_kind"] != "OBSERVED_REAL"
    ):
        raise ValueError("E_LIVE_CAPTURE_REVIEW")
    actual = {
        str(p.relative_to(evidence.root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in evidence.sample_paths
    }
    if scope["sample_refs"] != actual:
        raise ValueError("E_LIVE_CAPTURE_SAMPLES")
    verify_external_review(review, scope, evidence.root, evidence.now_utc)


@dataclass(frozen=True)
class EvidenceIndex:
    artifacts: dict[str, Any]
    checks: frozenset[str] = frozenset()
    config_sha256: str = ""
    source_sha256: str = ""
    root: Path = ROOT
    paths: dict[str, str] = field(default_factory=dict)
    profile: ExtractionProfile | None = field(default=None, repr=False)
    bindings: tuple[dict[str, Any], ...] = ()
    expires_at: datetime | None = None
    _proof: object = field(default=None, repr=False)
    _pid: int = field(default=0, repr=False)
    config_binding: str = ""
    trust_binding: str = ""


@dataclass(frozen=True)
class Readiness:
    live_read_only_ready: bool
    missing_inputs: tuple[str, ...]
    key_status: str
    independent_review: str = "NOT_RUN"
    model_enabled: bool = False
    money_ready: bool = False


def evaluate_live_readiness(
    config: LiveConfig, verified: EvidenceIndex, key_present: bool
) -> Readiness:
    """Pure decision over a locally verified snapshot; never tests a real credential."""
    if (
        type(config) is not LiveConfig
        or type(verified) is not EvidenceIndex
        or type(key_present) is not bool
    ):
        raise ValueError("E_LIVE_PREFLIGHT_TYPE")
    trusted = (
        verified._proof is _SEAL
        and verified._pid == os.getpid()
        and verified.config_sha256 == config.sha256
        and verified.config_binding == digest(config.public)
        and verified.expires_at is not None
        and datetime.now(UTC) < verified.expires_at
    )
    checks = verified.checks if trusted else frozenset()
    missing = [message for name, message in REQUIRED.items() if name not in checks]
    if not config.enabled:
        missing.append("LIVE_CONFIG_DISABLED")
    if not config.fixture_ids:
        missing.append("WAITING_MATCH_WINDOW")
    if not key_present:
        missing.append("WAITING_FOR_USER_SECRET")
    return Readiness(
        not missing,
        tuple(missing),
        "PRESENT_NOT_AUTHENTICATED" if key_present else "NOT_PRESENT",
        "VERIFIED_HOST_RECEIPT"
        if "security" in checks
        else "SELF_ONLY"
        if verified.artifacts.get("security", {}).get("review_kind") == "SELF_ONLY"
        else "NOT_RUN",
    )


def load_evidence(config: LiveConfig, *, root: Path = ROOT) -> EvidenceIndex:
    """Read/recheck only configured nonsecret artifacts; no browser or provider I/O."""
    cfg, now = config.public, datetime.now(UTC)
    source = source_tree_hash(root)
    refs = {
        "provider": cfg["gates"]["provider_feasibility_path"],
        "capture": cfg["gates"]["capture_review_path"],
        "profile": cfg["operator"]["capture_profile_path"],
        "platform": cfg["runtime"]["platform_qualification_path"],
        "offline": cfg["gates"]["offline_result_path"],
        "security": cfg["gates"]["security_review_path"],
    }
    artifacts, paths, raw_hashes = {}, {}, {}
    checks: set[str] = set()
    profile = None
    trust_binding = ""
    bindings: tuple[dict[str, Any], ...] = ()
    expiry = now + timedelta(
        minutes=1
    )  # Snapshot expires quickly; real run rechecks retained bindings.
    for name, ref in refs.items():
        if ref is None:
            continue
        try:
            artifacts[name], raw_hashes[name] = _read(root / ref, root)
            paths[ref] = raw_hashes[name]
        except (ValueError, OSError, TypeError):
            continue
    try:
        p = artifacts["provider"]
        ev = p["evidence"]
        if (
            p["PROBE_RESULT"] != "PASS"
            or p["KEY_CHECK"] != "AUTHENTICATED"
            or p["SUBSCRIPTION_CHECK"] != "CONFIRMED"
            or ev["source_kind"] != "OBSERVED_REAL"
            or p["source_tree_sha256"] != source
            or p["provider_config_scope"] != provider_config_scope(config)
            or ev["fixture_ids"] != list(config.fixture_ids)
            or p["finished_before_deadline"] is not True
            or not 0 < p["REQUEST_ATTEMPTS"] == ev["http_attempts"] <= 20
            or len(ev["requests"]) != ev["http_attempts"]
            or not 0 <= ev["elapsed_us"] <= 300000000
            or not now - timedelta(hours=24) <= datetime.fromisoformat(p["finished_at_utc"]) <= now
        ):
            raise ValueError()
        if len(ev["observations"]) != 2:
            raise ValueError()
        for row in ev["observations"]:
            if (
                row["missing_ids"]
                or row["rejected"]
                or {int(k) for k in row["states"]} != set(config.fixture_ids)
            ):
                raise ValueError()
            for state in row["states"].values():
                validate_live_record(state, "ProviderState")
        checks.add("provider")
    except (ValueError, KeyError, TypeError):
        pass
    try:
        review, value = artifacts["capture"], artifacts["profile"]
        scope = review["scope"]
        bindings = tuple(validate_live_record(b, "FixtureBinding") for b in scope["bindings"])
        sample_paths = []
        for ref, expected in scope["sample_refs"].items():
            sample, actual = _read(root / ref, root)
            if actual != expected or sample["source_kind"] != "OBSERVED_REAL":
                raise ValueError()
            paths[ref] = actual
            sample_paths.append(root / ref)
        if raw_hashes["profile"] != cfg["operator"]["profile_evidence_hash"]:
            raise ValueError()
        profile = validate_extraction_profile(
            value, ProfileEvidence(root, now, tuple(sample_paths), root / refs["capture"], bindings)
        )
        if (
            not profile._real_admitted
            or profile.public["max_matches"] != cfg["runtime"]["max_matches"]
            or {b["provider_fixture_id"] for b in bindings} != set(config.fixture_ids)
            or {b["binding_id"] for b in bindings}
            != set(cfg["operator"]["allowed_fixture_bindings"])
            or any(
                b["orientation_status"] != "VERIFIED"
                or b["league_id"] != cfg["provider"]["league_id"]
                or b["season"] != cfg["provider"]["season"]
                for b in bindings
            )
        ):
            raise ValueError()
        states = artifacts["provider"]["evidence"]["observations"][-1]["states"]
        for binding in bindings:
            state = states[str(binding["provider_fixture_id"])]
            if (
                state["home_id"] != binding["home_id"]
                or state["away_id"] != binding["away_id"]
                or datetime.fromisoformat(state["kickoff_utc"])
                != datetime.fromisoformat(binding["kickoff_utc"])
            ):
                raise ValueError()
        checks.add("capture")
    except (ValueError, KeyError, TypeError, OSError):
        profile = None
    try:
        p = artifacts["platform"]
        if (
            p["status"] != "PASS"
            or p["platform"] != cfg["runtime"]["platform"]
            or p["source_tree_sha256"] != source
            or p["exit"] != 0
            or p["source_kind"] != "SYNTHETIC"
            or p["operator_observed"] is not False
            or p["real_provider_attempts"] != 0
            or p["test_source_sha256"]
            != hashlib.sha256((root / "tests/live/test_local_bridge.py").read_bytes()).hexdigest()
        ):
            raise ValueError()
        parent = (root / refs["platform"]).parent
        observed = []
        for ref, expected in p["evidence"].items():
            path = private_path(str((parent / ref).relative_to(root)), root=root, must_exist=True)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError()
            if path.name == "observed-bridge.json":
                observed.append(json.loads(path.read_text()))
        if (
            len(observed) != 1
            or observed[0]["platform"] != p["platform"]
            or observed[0]["bound_addresses"] != ["127.0.0.1"]
        ):
            raise ValueError()
        checks.add("platform")
    except (ValueError, KeyError, TypeError, OSError):
        pass
    try:
        # The full verifier runs separately. Here its retained outputs are reopened and
        # later pinned by the host-signed enabled-surface review, never replaced by flags.
        p = artifacts["offline"]
        from tools.offline_harness import source_hashes
        from tools.verify_offline_slice import artifact

        current = hashlib.sha256(json.dumps(source_hashes(), sort_keys=True).encode()).hexdigest()
        if (
            p["OFFLINE_SLICE_PASS"] != "YES"  # noqa: S105 -- public status, not a credential.
            or p["provenance"]["source_tree_sha256"] != current
            or [r["case_id"] for r in p["records"]] != [f"OFF-{i:02d}" for i in range(1, 28)]
        ):
            raise ValueError()
        parent = (root / refs["offline"]).parent
        for row in p["records"]:
            if (
                row["status"] != "PASS"
                or row["executed"] is not True
                or row["command_exit"] != 0
                or not row["artifacts"]
            ):
                raise ValueError()
            for ref in row["artifacts"]:
                artifact(parent, ref)
        checks.add("offline")
    except (ValueError, KeyError, TypeError, OSError):
        pass
    try:
        review = artifacts["security"]
        scope = review["scope"]
        expected = {
            "kind": "LIVE_SECURITY",
            "source_tree_sha256": source,
            "config_sha256": config.sha256,
            "artifacts": {
                k: raw_hashes[k] for k in ("provider", "capture", "profile", "platform", "offline")
            },
            "max_matches": cfg["runtime"]["max_matches"],
            "expires_at": scope["expires_at"],
            "previous_scope_refs": scope.get("previous_scope_refs", {}),
        }
        verify_external_review(review, expected, root, now)
        if cfg["runtime"]["max_matches"] != 1:
            # PB-22's actual preceding bounded run must be verified before larger capacity.
            importlib.import_module("tools.qualify_live_readonly").verify_preceding_scope(
                config, review, root
            )
        expiry = min(
            _expires(scope["expires_at"], now),
            _expires(artifacts["capture"]["scope"]["expires_at"], now),
            _expires(review["authorization"]["expires_at"], now),
            _expires(artifacts["capture"]["authorization"]["expires_at"], now),
        )
        trust_binding = _host_trust_binding(root)
        checks.add("security")
    except (ValueError, KeyError, TypeError, OSError, ImportError):
        pass
    return EvidenceIndex(
        artifacts,
        frozenset(checks),
        config.sha256,
        source,
        root,
        paths,
        profile,
        bindings,
        expiry,
        _SEAL,
        os.getpid(),
        digest(config.public),
        trust_binding,
    )


@dataclass(frozen=True)
class _LiveAuthority:
    evidence: EvidenceIndex
    receipt: RunIntentReceipt
    binding: str
    receiver_binding: str
    _proof: object = field(default=None, repr=False)


def _admission_binding(admitted: Any) -> str:
    return digest(
        {
            "run_id": admitted.run_id,
            "config": admitted.config_sha256,
            "source": admitted.source_tree_sha256,
            "origin": admitted.extension_origin,
            "deadline": admitted.deadline_mono,
            "bindings": admitted.bindings,
            "profile": admitted.profile.public,
            "streams": admitted.capture_streams,
            "source_kind": admitted.source_kind,
        }
    )


def verify_live_receipt(receipt: RunIntentReceipt) -> _LiveAuthority:
    authority = receipt._live_authority
    if (
        type(authority) is not _LiveAuthority
        or authority._proof is not _SEAL
        or authority.receipt is not receipt
    ):
        raise ValueError("E_LIVE_AUTHORITY")
    verified = authority.evidence
    verify_receipt(receipt, "LIVE_READ_ONLY")
    if (
        not evaluate_live_readiness(receipt.config, verified, True).live_read_only_ready
        or source_tree_hash(verified.root) != verified.source_sha256
        or _host_trust_binding(verified.root) != verified.trust_binding
    ):
        raise ValueError("E_LIVE_AUTHORITY_STALE")
    for path, expected in verified.paths.items():
        if _read(verified.root / path, verified.root)[1] != expected:
            raise ValueError("E_LIVE_AUTHORITY_DRIFT")
    return authority


def verify_run_admission(config: LiveConfig, admitted: Any) -> None:
    authority = verify_live_receipt(admitted.provider_receipt)
    if (
        config.sha256 != authority.evidence.config_sha256
        or admitted.security_evidence is not authority
        or _admission_binding(admitted) != authority.binding
        or admitted.source_kind != "OBSERVED_REAL"
    ):
        raise ValueError("E_LIVE_ADMISSION_BINDING")


def verify_receiver_authority(context: dict[str, Any]) -> None:
    authority = context.get("authority")
    if type(authority) is not _LiveAuthority:
        raise ValueError("E_LIVE_RECEIVER_AUTHORITY")
    verify_live_receipt(authority.receipt)
    if digest({k: v for k, v in context.items() if k != "authority"}) != authority.receiver_binding:
        raise ValueError("E_LIVE_RECEIVER_AUTHORITY")


def admit_live_run(config: LiveConfig, receipt: RunIntentReceipt) -> Any:
    from tools.qualify_chrome_indexeddb import _extension_id

    from .live_service import RunAdmission

    verified = load_evidence(config)
    if (
        not evaluate_live_readiness(config, verified, True).live_read_only_ready
        or verified.profile is None
    ):
        raise ValueError("E_LIVE_ADMISSION_PENDING")
    verify_receipt(receipt, "LIVE_READ_ONLY")
    if receipt.config.sha256 != config.sha256 or receipt.intent.root != ROOT:
        raise ValueError("E_LIVE_ADMISSION_CONFIG")
    claim_receipt(receipt, "LIVE_READ_ONLY")
    streams = {}
    for binding in verified.bindings:
        markets = verified.profile.observed_markets[binding["operator_fixture_id"]]
        streams[str(uuid4())] = {
            "binding_id": binding["binding_id"],
            "binding_revision": binding["revision"],
            "operator_fixture_id": binding["operator_fixture_id"],
            "generation": "0",
            "profile_hash": verified.profile.profile_hash,
            "document_epoch": str(uuid4()),
            "markets": {
                m["horizon"]: {"market_id": m["market_id"], "selections": m["selections"]}
                for m in markets
            },
        }
    manifest = json.loads((ROOT / "extension/manifest.live.json").read_text())
    admitted = RunAdmission(
        ROOT,
        receipt.run_id,
        config.sha256,
        verified.source_sha256,
        "chrome-extension://" + _extension_id(manifest["key"]),
        receipt.deadline_mono,
        copy.deepcopy(verified.bindings),
        verified.profile,
        streams,
        "OBSERVED_REAL",
        receipt,
    )
    receiver_binding = digest(
        {
            "run_id": admitted.run_id,
            "allowed_extension_origin": admitted.extension_origin,
            "deadline_mono": admitted.deadline_mono,
            "source_kind": admitted.source_kind,
            "capture_streams": admitted.capture_streams,
        }
    )
    authority = _LiveAuthority(
        verified, receipt, _admission_binding(admitted), receiver_binding, _SEAL
    )
    object.__setattr__(receipt, "_live_authority", authority)
    object.__setattr__(admitted, "security_evidence", authority)
    verify_run_admission(config, admitted)
    return admitted
