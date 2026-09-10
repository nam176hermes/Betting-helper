"""Qualify frozen observations; never starts a browser, provider or live session."""

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from moj_discovery.canonical import parse_strict_json  # noqa: E402
from moj_discovery.live_replay import file_hash, verify_live_replay  # noqa: E402

LiveQualification = dict[str, Any]


def qualify_recorded_run(run_dir: Path, *, expected_scope: int | None = None) -> LiveQualification:
    run_dir = run_dir.absolute()
    if not run_dir.is_dir() or any(p.is_symlink() for p in (run_dir, *run_dir.parents)):
        raise ValueError("E_LIVE_QUALIFICATION_PATH")
    # Replay output is separate from the frozen run's 512 MiB retention boundary.
    output = run_dir.parent / (run_dir.name + "-qualification-" + str(uuid4()))
    replay = verify_live_replay(run_dir, output)
    missing: list[str] = []
    database = run_dir / "live.sqlite3"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        meta = db.execute("SELECT * FROM run_meta").fetchone()
        closure = db.execute("SELECT * FROM run_closures").fetchone()
        assert meta and closure
        if expected_scope is not None and meta[5] != expected_scope:
            raise ValueError("E_LIVE_QUALIFICATION_SCOPE")
        events = [
            cast(dict[str, Any], parse_strict_json(r[0]))
            for r in db.execute("SELECT payload_canonical FROM live_events ORDER BY receive_index")
        ]
    bindings = {
        e["payload"]["after"]["binding_id"]: e["payload"]["after"]
        for e in events
        if e["payload_type"] == "BindingChange"
    }
    states = [e["payload"] for e in events if e["payload_type"] == "ProviderState"]
    books = [e for e in events if e["payload_type"] == "MarketBook"]
    observed_ids = sorted({s["fixture_id"] for s in states})
    artifacts = {"live.sqlite3": replay.source_database_sha256}
    run: dict[str, Any] = {}
    for name in (
        "intent.json",
        "config-public.json",
        "source-bindings.json",
        "requests.jsonl",
        "result.json",
        "manual-ft-checks.jsonl",
    ):
        path = run_dir / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
            missing.append("RUN_ARTIFACTS_MISSING")
            continue
        artifacts[name] = file_hash(path)
        raw = path.read_bytes()
        run[name] = (
            [parse_strict_json(line) for line in raw.splitlines() if line]
            if name.endswith(".jsonl")
            else parse_strict_json(raw)
        )
    checks: dict[str, int] = {b: 0 for b in bindings}
    if not missing:
        try:
            _verify_run_artifacts(run, meta, closure, bindings, states, run_dir)
            checks = _verify_manual_checks(
                run["manual-ft-checks.jsonl"], books, bindings, meta, closure
            )
        except (ValueError, KeyError, TypeError, OSError):
            missing.append("RUN_AUTHORITY_OR_OBSERVATIONS_NOT_VERIFIED")
    if any(n < 3 for n in checks.values()) or not checks:
        missing.append("THREE_MANUAL_FT_CHECKS_PER_FIXTURE_REQUIRED")
    selected = sorted(b["provider_fixture_id"] for b in bindings.values())
    if observed_ids != selected or len(selected) != meta[5]:
        missing.append("SELECTED_FIXTURE_COVERAGE_MISSING")
    playing = {s["fixture_id"] for s in states if s["period"] in {"H1", "H2"}}
    if playing != set(selected):
        missing.append("REAL_IN_PROGRESS_PERIOD_NOT_OBSERVED")
    cohorts: dict[str, set[int]] = {}
    for state in states:
        if state["period"] in {"H1", "H2"}:
            cohorts.setdefault(state["batch_observation_id"], set()).add(state["fixture_id"])
    if meta[5] > 1 and set(selected) not in cohorts.values():
        missing.append("SIMULTANEOUS_SHARED_COHORT_NOT_OBSERVED")
    synthetic = any("SYNTHETIC" in s["quality_flags"] for s in states) or any(
        "SYNTHETIC" in e["payload"]["quality_flags"] for e in books
    )
    if synthetic:
        missing.append("SYNTHETIC_OBSERVATIONS")
    result: LiveQualification = {
        "schema_version": "part-b-live-qualification/v1",
        "status": "PASS" if not missing else "HOLD",
        "run_id": meta[0],
        "run_directory": str(run_dir),
        "replay_directory": str(output),
        "source_tree_sha256": meta[1],
        "config_sha256": meta[2],
        "source_kind": "SYNTHETIC" if synthetic else "UNVERIFIED" if missing else "OBSERVED_REAL",
        "scope": {"max_matches": meta[5], "fixture_ids": selected},
        "observed_fixture_ids": observed_ids,
        "complete_ft_book_checks": sum(checks.values()),
        "ft_checks_by_binding": checks,
        "replay": asdict(replay),
        "artifacts": artifacts,
        "real_http_attempts": run.get("result.json", {}).get("real_http_attempts", 0),
        "missing_inputs": sorted(set(missing)),
        "LIVE_READ_ONLY_PASS": not missing,
        "model_enabled": False,
        "money_ready": False,
        "rare_real_events": "NOT_OBSERVED_UNLESS_RETAINED_IN_JOURNAL",
        "H1_H2_qualification": "NOT_QUALIFIED",
        "qualified_at_utc": datetime.now(UTC).isoformat(),
    }
    if file_hash(database) != replay.source_database_sha256 or any(
        file_hash(run_dir / name) != sha for name, sha in artifacts.items()
    ):
        raise ValueError("E_LIVE_QUALIFICATION_SOURCE_CHANGED")
    (output / "qualification.json").write_text(json.dumps(result, indent=2))
    return result


def _verify_run_artifacts(
    run: dict[str, Any],
    meta: tuple[Any, ...],
    closure: tuple[Any, ...],
    bindings: dict[str, Any],
    states: list[dict[str, Any]],
    run_dir: Path,
) -> None:
    from moj_discovery.live_config import LiveConfig, private_path
    from moj_discovery.live_contracts import schema_validate, validate_live_record
    from moj_discovery.live_intent import source_tree_hash, validate_intent_window
    from moj_discovery.live_preflight_batched import _read, digest, verify_external_review

    result, intent = run["result.json"], run["intent.json"]
    scope, public = run["source-bindings.json"], run["config-public.json"]
    cfg, value = public["value"], intent["intent"]
    for artifact, expected_value, expected_hash in (
        (public, cfg, meta[2]),
        (intent, value, intent["intent_sha256"]),
    ):
        if not isinstance(artifact["original_json"], str):
            raise ValueError("E_LIVE_RUN_ORIGINAL_BYTES")
        original = artifact["original_json"].encode()
        if (
            hashlib.sha256(original).hexdigest() != expected_hash
            or parse_strict_json(original) != expected_value
        ):
            raise ValueError("E_LIVE_RUN_ORIGINAL_BYTES")
    schema_validate(cfg, "config")
    schema_validate(value, "run-intent")
    start = datetime.fromisoformat(intent["consumed_at_utc"])
    validate_intent_window(
        datetime.fromisoformat(value["issued_at"]),
        datetime.fromisoformat(value["expires_at"]),
        start,
    )
    if (
        result["schema_version"] != "part-b-recorded-run/v1"
        or result["run_id"] != meta[0]
        or scope["run_id"] != meta[0]
        or result["source_kind"] != "OBSERVED_REAL"
        or scope["source_kind"] != "OBSERVED_REAL"
        or result["status"] != "STOPPED"
        or result["reason"] != closure[2]
        or result["started_at_utc"] != meta[3]
        or result["closed_at_utc"] != closure[1]
        or value["stage"] != "LIVE_READ_ONLY"
        or intent["confirmation_kind"] != "LOCAL_TTY_USER_CONFIRMATION"
        or meta[1] != scope["source_tree_sha256"]
        or meta[1] != value["source_tree_sha256"]
        or meta[1] != source_tree_hash(ROOT)
        or meta[2] != value["config_sha256"]
        or meta[2] != public["original_sha256"]
        or public["canonical_sha256"] != digest(cfg)
        or cfg["enabled"] is not True
        or result["authenticated"] is not True
        or result["model_enabled"] is not False
        or result["money_ready"] is not False
        or not 0 < result["duration_us"] <= value["max_duration_seconds"] * 1000000
        or not start <= datetime.fromisoformat(meta[3]) <= datetime.fromisoformat(closure[1])
        or (datetime.fromisoformat(closure[1]) - start).total_seconds()
        > value["max_duration_seconds"] + 1
        or cfg["runtime"]["max_matches"] != meta[5]
        or sorted(cfg["provider"]["fixture_ids"]) != sorted(value["fixture_ids"])
        or sorted(b["provider_fixture_id"] for b in bindings.values())
        != sorted(value["fixture_ids"])
        or cfg["provider"]["events_fallback_enabled"]
        or cfg["provider"]["events_fallback_fixture_ids"]
    ):
        raise ValueError("E_LIVE_RUN_SOURCE_BINDING")
    if {
        b["binding_id"]: validate_live_record(b, "FixtureBinding") for b in scope["bindings"]
    } != bindings:
        raise ValueError("E_LIVE_RUN_FIXTURE_BINDING")
    if scope["profile_sha256"] != digest(scope["profile"]):
        raise ValueError("E_LIVE_RUN_PROFILE_BINDING")
    config = LiveConfig(cfg, meta[2])
    if private_path(cfg["runtime"]["run_output_dir"], root=ROOT) != run_dir:
        raise ValueError("E_LIVE_RUN_DIRECTORY_BINDING")
    # Reopen exact start-admission evidence. This never initializes or signs host authority.
    artifacts = {}
    for ref, sha in scope["evidence_refs"].items():
        data, actual = _read(private_path(ref, root=ROOT, must_exist=True), ROOT)
        if actual != sha:
            raise ValueError("E_LIVE_RUN_EVIDENCE_DRIFT")
        artifacts[ref] = data
    security = artifacts[cfg["gates"]["security_review_path"]]
    capture = artifacts[cfg["gates"]["capture_review_path"]]
    expected_refs = {
        "provider": cfg["gates"]["provider_feasibility_path"],
        "capture": cfg["gates"]["capture_review_path"],
        "profile": cfg["operator"]["capture_profile_path"],
        "platform": cfg["runtime"]["platform_qualification_path"],
        "offline": cfg["gates"]["offline_result_path"],
    }
    expected = {
        "kind": "LIVE_SECURITY",
        "source_tree_sha256": meta[1],
        "config_sha256": meta[2],
        "max_matches": meta[5],
        "expires_at": security["scope"]["expires_at"],
        "artifacts": {k: scope["evidence_refs"][ref] for k, ref in expected_refs.items()},
        "previous_scope_refs": security["scope"].get("previous_scope_refs", {}),
    }
    verify_external_review(security, expected, ROOT, start)
    verify_external_review(capture, capture["scope"], ROOT, start)
    if (
        capture["scope"]["bindings"] != scope["bindings"]
        or capture["scope"]["profile_sha256"] != scope["profile_sha256"]
    ):
        raise ValueError("E_LIVE_RUN_REVIEW_BINDING")
    # Durable consumption survives process exit; the process seal is never a signature.
    ledger = private_path(".local/part-b/intent-consumptions.sqlite3", root=ROOT, must_exist=True)
    with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        row = db.execute(
            "SELECT run_id,intent_hash,source_tree_hash,config_hash,consumed_at_utc,"
            "stage,confirmation_kind,money_authority "
            "FROM intent_consumptions WHERE intent_id=?",
            (value["intent_id"],),
        ).fetchone()
    if row != (
        meta[0],
        intent["intent_sha256"],
        meta[1],
        meta[2],
        intent["consumed_at_utc"],
        "LIVE_READ_ONLY",
        "LOCAL_TTY_USER_CONFIRMATION",
        0,
    ):
        raise ValueError("E_LIVE_RUN_INTENT_CONSUMPTION")
    requests = run["requests.jsonl"]
    quota = private_path(
        ".local/part-b/quota/api-football-primary.sqlite3", root=ROOT, must_exist=True
    )
    with closing(sqlite3.connect(quota.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        actual_requests = db.execute(
            "SELECT r.attempt_id,r.purpose,r.reserved_at_utc,r.reserved_mono_us,o.result_code "
            "FROM quota_reservations r LEFT JOIN quota_outcomes o USING(attempt_id) "
            "WHERE r.scope_id=? ORDER BY r.reserved_mono_us,r.attempt_id",
            (meta[0],),
        ).fetchall()
    fields = ("attempt_id", "purpose", "reserved_at_utc", "reserved_mono_us", "outcome")
    if actual_requests != [tuple(r[k] for k in fields) for r in requests]:
        raise ValueError("E_LIVE_RUN_QUOTA_EXPORT")
    count = len(requests)
    if not (
        0
        < count
        == result["reserved_attempts"]
        == result["http_attempts"]
        == result["real_http_attempts"]
        <= value["max_http_attempts"]
        <= 600
    ):
        raise ValueError("E_LIVE_RUN_REQUEST_COUNT")
    if len({r["attempt_id"] for r in requests}) != count or not {
        r["purpose"] for r in requests
    } >= {"STATUS", "BUNDLE"}:
        raise ValueError("E_LIVE_RUN_REQUEST_TYPES")
    for i, request in enumerate(requests):
        if (
            set(request)
            != {"attempt_id", "purpose", "reserved_at_utc", "reserved_mono_us", "outcome"}
            or request["purpose"] not in {"STATUS", "BUNDLE"}
            or request["outcome"] is None
            or i
            and request["reserved_mono_us"] - requests[i - 1]["reserved_mono_us"] < 10000000
            or sum(
                0 <= request["reserved_mono_us"] - prior["reserved_mono_us"] < 60000000
                for prior in requests[: i + 1]
            )
            > cfg["provider"]["max_requests_per_minute"]
        ):
            raise ValueError("E_LIVE_RUN_REQUEST_BUDGET")
    if not {s["request_id"] for s in states} <= {
        r["attempt_id"] for r in requests if r["purpose"] == "BUNDLE"
    }:
        raise ValueError("E_LIVE_RUN_REQUEST_LINK")
    if meta[5] > 1:
        verify_preceding_scope(config, security, ROOT)


def _verify_manual_checks(
    checks: list[dict[str, Any]],
    books: list[dict[str, Any]],
    bindings: dict[str, Any],
    meta: tuple[Any, ...],
    closure: tuple[Any, ...],
) -> dict[str, int]:
    by_hash = {e["content_hash"]: e for e in books}
    totals = dict.fromkeys(bindings, 0)
    previous: dict[str, datetime] = {}
    used: set[str] = set()
    if len(checks) > 30:
        raise ValueError("E_LIVE_MANUAL_CHECK_CAP")
    for row in checks:
        if set(row) != {
            "confirmation_kind",
            "source_kind",
            "run_id",
            "binding_id",
            "capture_event_hash",
            "checked_at_utc",
            "selections",
            "market_id",
        }:
            raise ValueError("E_LIVE_MANUAL_CHECK_FIELDS")
        event = by_hash[row["capture_event_hash"]]
        book, binding = event["payload"], row["binding_id"]
        stamp = datetime.fromisoformat(row["checked_at_utc"])
        if (
            row["confirmation_kind"] != "LOCAL_TTY_USER_CHECK"
            or row["source_kind"] != "OBSERVED_REAL"
            or row["run_id"] != meta[0]
            or book["binding_id"] != binding
            or book["horizon"] != "FT"
            or book["market_status"] != "OPEN"
            or book["settlement_basis"] != "NORMAL_TIME_INCLUDING_STOPPAGE"
            or book["selections"] != row["selections"]
            or book["market_id"] != row["market_id"]
            or row["capture_event_hash"] in used
            or stamp.utcoffset() != UTC.utcoffset(stamp)
            or not datetime.fromisoformat(meta[3]) <= stamp <= datetime.fromisoformat(closure[1])
            or not 0
            <= (stamp - datetime.fromisoformat(book["observed_at_utc"])).total_seconds()
            <= 30
            or binding in previous
            and (stamp - previous[binding]).total_seconds() < 30
        ):
            raise ValueError("E_LIVE_MANUAL_CHECK_BINDING")
        previous[binding] = stamp
        used.add(row["capture_event_hash"])
        totals[binding] += 1
    return totals


def verify_preceding_scope(config: Any, review: dict[str, Any], root: Path) -> None:
    """Reopen prior physical recordings, not just their claimed PASS fields."""
    from moj_discovery.live_config import private_path

    limit = config.public["runtime"]["max_matches"]
    needed = {1: set(), 3: {"1"}, 5: {"1", "3"}}[limit]
    refs = review["scope"].get("previous_scope_refs", {})
    if set(refs) != needed:
        raise ValueError("E_LIVE_PRECEDING_SCOPE_REQUIRED")
    seen = set()
    for scope in sorted(needed):
        ref = refs[scope]
        if set(ref) != {"path", "sha256"}:
            raise ValueError("E_LIVE_PRECEDING_SCOPE_REFERENCE")
        path = private_path(ref["path"], root=root, must_exist=True)
        if path.stat().st_size > 1024 * 1024 or file_hash(path) != ref["sha256"]:
            raise ValueError("E_LIVE_PRECEDING_SCOPE_HASH")
        old = cast(dict[str, Any], parse_strict_json(path.read_bytes()))
        relative = str(Path(old["run_directory"]).relative_to(root))
        run = private_path(relative, root=root)
        actual = qualify_recorded_run(run, expected_scope=int(scope))
        for key in (
            "schema_version",
            "run_id",
            "source_tree_sha256",
            "config_sha256",
            "scope",
            "observed_fixture_ids",
            "ft_checks_by_binding",
            "artifacts",
            "real_http_attempts",
        ):
            if old[key] != actual[key]:
                raise ValueError("E_LIVE_PRECEDING_SCOPE_DRIFT")
        if (
            not actual["LIVE_READ_ONLY_PASS"]
            or old["LIVE_READ_ONLY_PASS"] is not True
            or actual["run_id"] in seen
        ):
            raise ValueError("E_LIVE_PRECEDING_SCOPE_NOT_QUALIFIED")
        seen.add(actual["run_id"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = qualify_recorded_run(args.run_dir)
        print(
            json.dumps(
                {k: result[k] for k in ("status", "scope", "missing_inputs", "LIVE_READ_ONLY_PASS")}
            )
        )
        return 0 if result["LIVE_READ_ONLY_PASS"] else 2
    except Exception:
        print("LIVE_QUALIFICATION_REFUSED: INVALID_OR_OPEN_RECORDING")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
