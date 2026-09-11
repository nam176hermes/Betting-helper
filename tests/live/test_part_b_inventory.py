"""Explicit required-case mappings; expected assertions never substitute for observations."""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

REQUIRED_MOCK_IDS = tuple(f"BCASE-{i:02d}" for i in range(1, 40))


def test_release_preserves_external_holds_and_exact_mock_revision(
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    """Exercise report assembly only; patched checks are not browser/live evidence."""
    from types import SimpleNamespace

    from moj_discovery import live_preflight_batched
    from tools import qualify_live_platform
    from tools import verify_part_b as verifier

    (tmp_path / "config").mkdir()
    (tmp_path / "config/live-batched.example.json").write_bytes(
        Path("config/live-batched.example.json").read_bytes()
    )

    def mock_campaign(profile: str, output: Path) -> Any:
        assert profile == "mock"
        output.mkdir()
        result = dict(PART_B_MOCK_PASS=True, source_revision="a" * 40, source_tree_sha256="b" * 64)
        (output / "result.json").write_text(json.dumps(result))
        return result

    def platform_check(config: Any, output: Path) -> Any:
        assert not config.enabled
        output.mkdir()
        result = {"status": "PASS"}
        (output / "result.json").write_text(json.dumps(result))
        return result

    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "verify_profile", mock_campaign)
    monkeypatch.setattr(verifier, "source_tree_hash", lambda *_: "b" * 64)
    monkeypatch.setattr(qualify_live_platform, "qualify_platform", platform_check)
    monkeypatch.setattr(
        live_preflight_batched,
        "load_evidence",
        lambda *_: SimpleNamespace(checks=frozenset(), profile=None),
    )
    result = verifier.verify_release(tmp_path / "release")
    assert result["source_revision"] == "a" * 40
    assert result["PART_B_MOCK_PASS"] and result["status"] == "HOLD"
    assert result["verdicts"]["LIVE_READ_ONLY_PASS_ONE"] == "NOT_EXECUTED"  # noqa: S105 -- verdict.
    assert result["verdicts"]["INDEPENDENT_LIVE_SECURITY_REVIEW"] == "WAITING_REVIEW"
    assert result["MODEL_ENABLED"] is False and result["MONEY_READY"] == "NO"
    monkeypatch.setattr(verifier, "source_tree_hash", lambda *_: "c" * 64)
    assert not verifier.verify_release(tmp_path / "changed")["PART_B_MOCK_PASS"]


# Names identify executed Python assertions, including their parameterized variants.
CASE_TESTS = {
    1: ["test_part_b_inventory::test_existing_descendant_and_immutable_baseline"],
    2: [
        "test_live_config::test_disabled_v2_and_v1_compatibility",
        "test_live_config::test_closed_scope",
    ],
    3: ["test_live_config::test_closed_scope"],
    4: [
        "test_secret_entry::test_real_pseudoterminal_noecho",
        "test_secret_entry::test_no_tty_prevents_secret_read",
        "test_secret_entry::test_getpass_warning_never_falls_back",
    ],
    5: [
        "test_secret_nonleakage::test_repr_and_serialization_are_closed",
        "test_secret_nonleakage::test_key_removed_from_child_environment_before_dispatch",
    ],
    6: [
        "test_quota_concurrency::test_reservation_committed_before_io_and_no_crash_refund",
        "test_quota_concurrency::test_shared_day_budget_survives_sequential_owners",
    ],
    7: [
        "test_provider_budget::test_gap_and_sliding_minute",
        "test_api_football::test_timeout_retries_all_reserved",
    ],
    8: [
        "test_provider_budget::test_day_rollover_requires_provider_reconciliation",
        "test_provider_budget::test_bootstrap_and_missing_quota_are_fail_closed",
    ],
    9: ["test_provider_budget::test_budget_oracle_concurrent_sequential_and_fallback"],
    10: [
        "test_api_football::test_status_projection_and_sorted_bundle",
        "test_api_football::test_scope_invalid_ids_never_reach_io",
    ],
    11: [
        "test_provider_http_boundary::test_default_opener_disables_proxy_redirect_and_keeps_tls",
        "test_provider_http_boundary::test_transport_bounds_and_redirects",
    ],
    12: ["test_provider_budget::test_provider_minute_limit_remains_distinct_from_daily"],
    13: [
        "test_provider_normalization::test_bad_fixture_cannot_corrupt_sibling",
        "test_bundle_poller::test_missing_member_does_not_erase_or_activate_fallback",
    ],
    14: ["test_provider_normalization::test_scoped_snapshot_preserves_nulls_and_source_time"],
    15: [
        "test_provider_corrections::test_reorder_preserves_multiset_and_duplicate_multiplicity",
        "test_provider_corrections::test_removed_or_changed_goal_is_correction",
    ],
    16: ["test_provider_normalization::test_missing_sections_and_discarded_details"],
    17: [
        "test_batch_request_counts::test_two_hour_concurrent_union_is_480",
        "test_bundle_poller::test_adaptive_union_and_panel_reopen",
    ],
    18: ["test_bundle_poller::test_adaptive_union_and_panel_reopen"],
    19: [
        "test_bundle_poller::test_slow_io_and_sleep_never_catch_up",
        "test_bundle_poller::test_inflight_request_has_one_owner",
    ],
    20: [
        "test_bundle_poller::test_terminal_checks_are_anchored_and_stop",
        "test_bundle_poller::test_sleep_past_ft_checks_is_not_catchup_or_confirmed",
    ],
    21: ["test_batch_request_counts::test_fallback_insufficient_budget_rejected_before_io"],
    22: [
        "test_live_store::test_process_kill_at_commit_boundary",
        "test_live_wire::test_socket_commit_before_ack_and_role_rejection",
    ],
    23: [
        "test_live_replay::test_fresh_sqlite_replays_observed_rows_twice",
        "test_live_replay::test_actual_observation_and_projection_tamper_detected",
    ],
    24: ["test_live_spool_bridge::test_real_service_worker_idb_commit_ack_loss_and_crash_restart"],
    25: [
        "test_live_wire::test_wrong_origin_path_and_key_write_nothing",
        "test_live_wire::test_role_matrix_counter_and_mac",
    ],
    26: [
        "test_operator_profile::test_draft_is_inert_and_synthetic_target_explicit",
        "test_operator_profile::test_excluded_or_executable_selector_rejects",
    ],
    27: ["test_capture_graph::test_real_fixed_dom_complete_book_and_rejections"],
    28: ["test_capture_graph::test_real_fixed_dom_complete_book_and_rejections"],
    29: ["test_identity::test_identity_drift_no_fuzzy_autoapproval"],
    30: ["test_market_state_join::test_h2_requires_observed_halftime_baseline_and_normal_time"],
    31: [
        "test_market_state_join::test_invalidation_requires_two_new_observations_after_change",
        "test_market_state_join::test_gap_and_lifecycle_never_reopen_by_timer",
    ],
    32: ["test_market_state_join::test_receipt_content_and_source_ages_stay_separate"],
    33: [
        "test_live_service::test_stop_and_expiry_prevent_further_requests",
        "test_market_state_join::test_binding_starts_waiting",
    ],
    34: [
        "test_workspace_projection::test_actual_chrome_panel_shared_worker_keyboard_and_narrow_layout"
    ],
    35: [
        "test_workspace_projection::test_actual_chrome_panel_shared_worker_keyboard_and_narrow_layout"
    ],
    36: [
        "test_run_intents::test_consumption_burns_intent_and_claim_once_even_after_reload",
        "test_run_intents::test_no_terminal_and_source_config_scope_mismatch_cannot_consume",
    ],
    37: ["test_local_bridge::test_actual_selected_platform_bridge_and_worker_repair"],
    38: [
        "test_live_preflight_batched::test_synthetic_and_truthy_claims_never_admit_live_with_key_present",
        "test_live_security::test_untrusted_review_never_chooses_trust_key_or_grants_live",
    ],
    39: [],  # The two actual Part A processes and their retained case records are required below.
}


def test_existing_descendant_and_immutable_baseline() -> None:
    root = Path(__file__).resolve().parents[2]
    start = "39b92966c2db6694b31507526b339206f4db2b0d"
    for ancestor in (start, "d4055839e596fc52f0e0df175a6733a64b8fffc1"):
        assert (
            subprocess.run(  # noqa: S603 -- fixed local ancestry command.
                ["/usr/bin/git", "merge-base", "--is-ancestor", ancestor, "HEAD"], cwd=root
            ).returncode
            == 0
        )  # noqa: S603 -- local ancestry only.

    def git(*args: str) -> bytes:
        return subprocess.check_output(["/usr/bin/git", *args], cwd=root)  # noqa: S603 -- fixed local identity commands.

    assert git("rev-list", "--max-parents=0", "HEAD") == git("rev-list", "--max-parents=0", start)
    amendment = root / "vendor/hybrid-discovery-v6.3.6/docs/contracts/part-b-one-ready.v1.json"
    if not amendment.exists():
        assert (
            git("diff", start, "--", "vendor", "task-command-registry.json", "schema-lock.json")
            == b""
        )
        return
    # The explicitly adopted descendant permits canonical source-owned rebinding;
    # historical receipts and ancestry keep their original bytes and meaning.
    from tools.full_verifier_config import load_controller_config
    from tools.sync_pack_assets import sync_pack_assets

    contract = json.loads(amendment.read_bytes())
    adopted = contract["adopted_source"]
    assert adopted == {
        "commit": "6d0d1c96bc8b7bddc9651d5bcd5a90b511ba8867",
        "tree": "c73cca5eee550a10bd70cbbecf1819cb08bccc21",
        "qualification": "NOT_INFERRED",
    }
    assert git("rev-parse", adopted["commit"] + "^{tree}").decode().strip() == adopted["tree"]
    assert git("merge-base", "--is-ancestor", adopted["commit"], "HEAD") == b""
    assert (
        git("diff", adopted["commit"], "--", "vendor/hybrid-discovery-v6.3.6/docs/receipts") == b""
    )
    config = load_controller_config(
        root / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"
    )
    assert (
        hashlib.sha256(
            (config.governed_source_pack / "docs/receipts/migration-receipt.v1.json").read_bytes()
        ).hexdigest()
        == contract["historical_migration_sha256"]
    )
    sync_pack_assets(config.governed_source_pack, root, check=True)


def verify_executed_inventory(
    output: Path, tests: dict[str, str], records: list[dict[str, Any]]
) -> list[str]:
    from tools.qualify_live_platform import CHROME

    rows = []
    if (
        set(CASE_TESTS) != set(range(1, 40))
        or not tests
        or any(v != "PASS" for v in tests.values())
    ):
        raise ValueError("E_PART_B_REQUIRED_TESTS")
    commands = {Path(r["log"]).stem: r for r in records}
    if not set(commands) >= {
        "python",
        "compile",
        "node",
        "part-a",
        "part-a-verify",
        "shared-regressions",
        "registry",
        "ruff",
        "mypy",
        "eslint",
        "credential-console",
        "credential-store",
    }:
        raise ValueError("E_PART_B_REQUIRED_COMMANDS")
    for record in records:
        path = output / record["log"]
        if (
            path.parent != output
            or record["exit"] != 0
            or hashlib.sha256(path.read_bytes()).hexdigest() != record["log_sha256"]
        ):
            raise ValueError("E_PART_B_COMMAND_EVIDENCE")
    tap = (output / "node.log").read_text()
    # Seven existing checks plus first-observation and closed-connection regressions.
    if not re.search(r"^# tests 9$", tap, re.M) or not all(
        re.search("^# " + field + " 0$", tap, re.M) for field in ("fail", "cancelled", "skipped")
    ):
        raise ValueError("E_PART_B_NODE_EXECUTION")
    for number, names in CASE_TESTS.items():
        matched = []
        for name in names:
            prefix = "tests.live." + name
            found = [n for n in tests if n == prefix or n.startswith(prefix + "[")]
            if not found:
                raise ValueError("E_PART_B_CASE_NOT_EXECUTED:" + str(number))
            matched.extend(found)
        rows.append({"case_id": f"BCASE-{number:02d}", "executed_tests": matched})
    observations = output / "observations"
    required_browser = [
        "observed-live-bridge.json",
        "observed-capture.json",
        "actual-browser-observations.json",
        "observed-bridge.json",
    ]
    browser_refs = {}
    binary = hashlib.sha256(CHROME.read_bytes()).hexdigest()
    for name in required_browser:
        paths = [p for p in observations.glob("*/" + name) if not p.parent.is_symlink()]
        if len(paths) != 1 or not json.loads(paths[0].read_text()):
            raise ValueError("E_PART_B_BROWSER_OBSERVATION")
        case = paths[0].parent
        identities = [p for p in case.glob("browser*/identity.json") if not p.parent.is_symlink()]
        if name == "observed-bridge.json":
            row = json.loads(paths[0].read_text())
            native = [row["browser_identity"]]
            terminations = [case / "observed-termination.json"]
            if row["platform"] != "WINDOWS_CHROME_WSL2" or row["bound_addresses"] != ["127.0.0.1"]:
                raise ValueError("E_PART_B_PLATFORM")
        else:
            native = [json.loads(p.read_text()) for p in identities]
            terminations = [p.parent / "termination.json" for p in identities]
        if not native or any(
            r.get("system") != "win32" or r["browser"]["sha256"] != binary for r in native
        ):
            raise ValueError("E_PART_B_WRONG_BROWSER_PLATFORM")
        if not all(
            json.loads(p.read_text())["all_observed_handles_signaled"] for p in terminations
        ):
            raise ValueError("E_PART_B_BROWSER_CLEANUP")
        browser_refs[str(paths[0].relative_to(output))] = hashlib.sha256(
            paths[0].read_bytes()
        ).hexdigest()
    part_a = json.loads((output / "part-a/result.json").read_text())
    if (
        part_a["OFFLINE_SLICE_PASS"] != "YES"  # noqa: S105 -- public qualification status.
        or len(part_a["records"]) != 27
        or any(
            r["status"] != "PASS" or r["executed"] is not True or r["command_exit"] != 0
            for r in part_a["records"]
        )
    ):
        raise ValueError("E_PART_B_PART_A_REGRESSION")
    (output / "executed-case-evidence.json").write_text(
        json.dumps(
            {
                "cases": rows,
                "browser_refs": browser_refs,
                "part_a_sha256": hashlib.sha256(
                    (output / "part-a/result.json").read_bytes()
                ).hexdigest(),
                "live_read_only_pass": False,
                "money_ready": False,
            },
            indent=2,
        )
    )
    return [row["case_id"] for row in rows]


def test_every_required_case_has_executed_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        verify_executed_inventory(tmp_path, {}, [{"exit": 0}])
