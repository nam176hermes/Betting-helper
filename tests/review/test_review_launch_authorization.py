import base64
import json
import os
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from moj_discovery.review_authorization import (
    sign_review_execution_receipt,
    sign_review_launch_authorization,
    verify_review_execution_receipt,
    verify_review_launch_authorization,
)
from tests.review.test_review_aggregation_and_self_review import signed_current as signed_current
from tools.issue_review_launch_authorization import _mount_roots
from tools.qualify_zero_parent_baseline import _repository_identity

NOW = datetime(2030, 1, 1, tzinfo=UTC)
WORKSPACE = "/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6.3.6/review-a"
PACK_HASH = "a" * 64


def test_current_role_selector_and_transport_reject_unknown_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import issue_review_launch_authorization as launch

    directory = tmp_path / "review-config"
    directory.mkdir()
    for role, name in (
        ("IMPLEMENTATION_READINESS_REVIEWER", "review-a"),
        ("CYBERSECURITY_REVIEWER", "review-b"),
    ):
        for version in (1, 2, 3):
            record = {"schema_version": f"review-config/v{version}", "role": role}
            (directory / f"{name}.v{version}.json").write_text(json.dumps(record))
            assert launch.review_config_for_role(role, version, runtime_root=tmp_path) == record
    with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
        launch.review_config_for_role("CYBERSECURITY_REVIEWER", 4, runtime_root=tmp_path)


def test_scoped_run_copies_exact_inputs_and_rejects_changed_bytes_or_reuse(tmp_path: Path) -> None:
    import os
    import uuid

    from tools.issue_review_launch_authorization import (
        _scope_record,
        prepare_review_scope,
        recheck_review_context,
        resolve_review_run,
        validate_review_scope,
    )

    private = tmp_path / ".local/part-b"
    private.mkdir(parents=True)
    source = private / "synthetic-config.json"
    source.write_text('{"TEST_ONLY":true}')
    prompt = tmp_path / "sealed-prompt.md"
    prompt.write_text("Synthetic scoped review test; no authority.")
    template = {
        "schema_version": "review-config/v3",
        "role": "CYBERSECURITY_REVIEWER",
        "workspace_root": str(tmp_path / "workspaces/review-b"),
        "output_root": str(tmp_path / "results/review-b"),
        "scratch_root": str(tmp_path / "workspaces/review-b/scratch"),
        "authorization_path": str(tmp_path / "authorizations/review-b.json"),
        "scope_input_root": str(private / "review-inputs"),
        "prompt_path": str(prompt),
        "input_roots": [str(tmp_path / "pack"), str(tmp_path)],
    }
    run_id = str(uuid.uuid4())
    config = resolve_review_run(template, run_id)
    assert config["workspace_root"] == template["workspace_root"] + "/" + run_id
    assert config["scratch_root"] == config["workspace_root"] + "/scratch"
    assert resolve_review_run(template, str(uuid.uuid4()))["output_root"] != config["output_root"]
    scope = {
        "kind": "OPERATOR_DISCOVERY_TOOL",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "source_tree_sha256": "a" * 64,
        "capture_source_sha256": "b" * 64,
        "config_sha256": sha256(source.read_bytes()).hexdigest(),
        "fixture_ids": [101],
        "exact_url": "https://miseojeuplus.espacejeux.com/sports/test-only",
        "selectors": {"selection_mode": "USER_SELECTED_REGION_V1"},
        "profile_name": "TEST_ONLY",
        "max_duration_seconds": 600,
        "max_http_attempts": 0,
    }
    prepare_review_scope(config, scope, [source])
    record, snapshots = _scope_record(config)
    assert record["files"][0]["sha256"] == sha256(source.read_bytes()).hexdigest()
    findings = [
        {
            "finding_id": "PART-B-SCOPE",
            "evidence_ids": ["sha256:" + sha256(rfc8785.dumps(scope)).hexdigest()],
            "blocking": False,
        }
    ]
    validate_review_scope(config, {"findings": findings})
    with pytest.raises(ValueError, match="E_REVIEW_SCOPE_INPUT"):
        validate_review_scope(config, {"findings": findings * 2})
    with pytest.raises(FileExistsError):
        prepare_review_scope(config, scope, [source])
    for bad in (run_id + "/..", run_id.upper(), str(uuid.uuid1())):
        with pytest.raises(ValueError):
            resolve_review_run(template, bad)
    copied = Path(config["scope_path"]).parent / "input-00.json"
    before = copied.stat()
    copied.write_text('{"TEST_ONLY":null}')
    os.utime(copied, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError):
        recheck_review_context({"config": config, "snapshots": snapshots})


def test_scoped_inputs_require_complete_role_path_and_hash_mapping() -> None:
    from tools.issue_review_launch_authorization import _scope_finding_id, _validate_scope_inputs

    role = "CYBERSECURITY_REVIEWER"
    profile, sample = b'{ "profile": "TEST_ONLY" }', b'{"sample":"TEST_ONLY"}'
    scope = {
        "kind": "CAPTURE_PROFILE",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "source_tree_sha256": "a" * 64,
        "capture_source_sha256": "b" * 64,
        "profile_sha256": sha256(rfc8785.dumps(json.loads(profile))).hexdigest(),
        "bindings": [],
        "max_matches": 1,
        "sample_refs": {".local/part-b/sample.json": sha256(sample).hexdigest()},
    }
    supplied = {".local/part-b/profile.json": profile, ".local/part-b/sample.json": sample}
    _validate_scope_inputs(role, scope, supplied)
    for bad in (
        {},
        {".local/part-b/profile.json": profile},
        {**supplied, ".local/part-b/extra.json": b"{}"},
        {**supplied, ".local/part-b/sample.json": b"{}"},
    ):
        with pytest.raises(ValueError, match="E_REVIEW_SCOPE_INPUT"):
            _validate_scope_inputs(role, scope, bad)
    candidate = {"kind": "CANDIDATE_READINESS", "expires_at": scope["expires_at"]}
    _validate_scope_inputs(role, candidate, {})
    assert {
        _scope_finding_id(r, candidate) for r in ("IMPLEMENTATION_READINESS_REVIEWER", role)
    } == {"PART-B-CANDIDATE-A", "PART-B-CANDIDATE-B"}
    with pytest.raises(ValueError, match="E_REVIEW_SCOPE_INPUT"):
        _validate_scope_inputs("IMPLEMENTATION_READINESS_REVIEWER", scope, supplied)


def test_scoped_security_inputs_follow_the_exact_configured_artifact_paths() -> None:
    from tools.issue_review_launch_authorization import _validate_scope_inputs

    refs = {
        name: f".local/part-b/{name}.json"
        for name in ("provider", "capture", "profile", "platform", "offline")
    }
    cfg = {
        "gates": {
            "provider_feasibility_path": refs["provider"],
            "capture_review_path": refs["capture"],
            "offline_result_path": refs["offline"],
        },
        "operator": {"capture_profile_path": refs["profile"]},
        "runtime": {"platform_qualification_path": refs["platform"]},
    }
    raw = json.dumps(cfg).encode()
    data = {path: json.dumps({"TEST_ONLY": name}).encode() for name, path in refs.items()}
    data[".local/part-b/config.json"] = raw
    scope = {
        "kind": "LIVE_SECURITY",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "source_tree_sha256": "a" * 64,
        "config_sha256": sha256(raw).hexdigest(),
        "max_matches": 1,
        "previous_scope_refs": {},
        "artifacts": {name: sha256(data[path]).hexdigest() for name, path in refs.items()},
    }
    _validate_scope_inputs("CYBERSECURITY_REVIEWER", scope, data)
    bad = dict(data)
    bad[".local/part-b/wrong-path.json"] = bad.pop(refs["provider"])
    with pytest.raises(ValueError, match="E_REVIEW_SCOPE_INPUT"):
        _validate_scope_inputs("CYBERSECURITY_REVIEWER", scope, bad)


def test_consumed_authority_is_checked_again_after_revocation(tmp_path: Path) -> None:
    import sqlite3

    from tools.issue_review_launch_authorization import validate_review_authority_state

    authority = {"public_key_path": str(tmp_path / "public.json")}
    authorization = {
        "issuer_key_id": "TEST_ONLY",
        "one_use_serial": "test",
        "trust_epoch": 0,
        "authorization_id": "TEST_ONLY_AUTH",
    }
    state = tmp_path / "state.sqlite"
    with sqlite3.connect(state) as db:
        db.execute("CREATE TABLE authority_state(key_id TEXT, trust_epoch INTEGER)")
        db.execute("CREATE TABLE consumed_serials(authority_key_id TEXT, one_use_serial TEXT)")
        db.execute("CREATE TABLE revocations(authorization_id TEXT)")
        db.execute("INSERT INTO authority_state VALUES ('TEST_ONLY',0)")
        db.execute("INSERT INTO consumed_serials VALUES ('TEST_ONLY','test')")
    validate_review_authority_state(authorization, authority)
    with sqlite3.connect(state) as db:
        db.execute("INSERT INTO revocations VALUES ('TEST_ONLY_AUTH')")
    with pytest.raises(ValueError, match="E_REVIEW_AUTHORITY_STATE"):
        validate_review_authority_state(authorization, authority)


def test_review_reuse_detects_changed_installed_compiler_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import issue_review_launch_authorization as launch
    from tools import run_native_ingestor_qualification as native
    from tools import verify_repair_evidence as repair

    executable = tmp_path / "synthetic-executable"
    executable.write_bytes(b"TEST_ONLY")
    # Qualified package managers can hardlink immutable cache payloads.
    os.link(executable, tmp_path / "synthetic-cache-link")
    qualified = tmp_path / ".venv"
    for folder in (
        qualified / "lib",
        tmp_path / "node_modules",
        tmp_path / "extension/node_modules",
    ):
        folder.mkdir(parents=True)
        (folder / "implementation.js").write_bytes(b"TEST_ONLY_V1")
    metadata = {
        "input_roots": [str(tmp_path / "pack"), str(tmp_path)],
        "producer_environment": {
            "python_environment": str(qualified),
            "live_files": [str(executable)],
            "path_translation_executable": str(executable),
            "python_executable": str(executable),
            "node_executable": str(executable),
        },
    }
    monkeypatch.setattr(launch.shutil, "which", lambda name: str(executable))
    monkeypatch.setattr(repair, "capture_binding", lambda: {"environment": "TEST_ONLY"})
    monkeypatch.setattr(repair, "_typescript_compile_binding", lambda current: "TEST_ONLY")
    monkeypatch.setattr(native, "dependency_binding", lambda: {"TEST_ONLY": True})
    context = {
        "snapshots": {},
        "environment_config": metadata,
        "environment_binding": launch._review_environment_binding(metadata),
    }
    launch.recheck_review_context(context)
    compiler = tmp_path / "extension/node_modules/implementation.js"
    before = compiler.stat()
    compiler.write_bytes(b"TEST_ONLY_V2")
    os.utime(compiler, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
        launch.recheck_review_context(context)


@pytest.mark.parametrize(
    "argv",
    [
        ["--root", "/test", "--config", "/test/config", "--preflight"],
        ["--root", "/test", "--config", "/test/config", "--issue", "--receipt", "/test/receipt"],
        [
            "--root",
            "/test",
            "--config",
            "/test/config",
            "--check-only",
            "--receipt",
            "/test/receipt",
            "--pack",
            "/test/pack",
        ],
        [
            "--root",
            "/test",
            "--root",
            "/test",
            "--config",
            "/test/config",
            "--check-only",
            "--receipt",
            "/test/receipt",
        ],
        [
            "--root",
            "/test",
            "--roo",
            "/other",
            "--config",
            "/test/config",
            "--check-only",
            "--receipt",
            "/test/receipt",
        ],
        [
            "--root",
            "/test",
            "--config",
            "/test/config",
            "--check-only",
            "--receipt",
            "/test/receipt",
            "--pack",
            "/test/pack",
            "--recorded-config",
            "/test/original",
            "--retained-root",
            "/test/retained",
            "--retained-manifest",
            "/test/manifest",
            "--retained-man",
            "/test/other",
        ],
    ],
)
def test_descendant_check_only_cli_rejects_incomplete_or_duplicate_before_read(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import assemble_review_pack as assembly
    from tools import qualify_descendant_repository as qualifier

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("invalid CLI reached config or evidence read")

    monkeypatch.setattr(qualifier, "load_controller_config", forbidden)
    monkeypatch.setattr(assembly, "load_sealed_assembly_context", forbidden)
    monkeypatch.setattr("sys.argv", ["qualify_descendant_repository.py", *argv])
    with pytest.raises((SystemExit, ValueError)):
        qualifier.main()


def test_descendant_check_only_cli_optional_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from types import SimpleNamespace

    from tools import qualify_descendant_repository as qualifier

    seen = []
    monkeypatch.setattr(
        "sys.argv",
        [
            "qualify_descendant_repository.py",
            "--root",
            "/test",
            "--config",
            "/test/config",
            "--check-only",
            "--receipt",
            "/test/receipt",
        ],
    )
    monkeypatch.setattr(
        qualifier,
        "load_controller_config",
        lambda path: SimpleNamespace(governed_source_pack=Path("/test/pack")),
    )
    monkeypatch.setattr(
        qualifier,
        "verify_descendant_qualification_receipt",
        lambda *args, **kwargs: (
            seen.append((args, kwargs)) or {"TEST_ONLY_VERIFIER_BOUNDARY": True}
        ),
    )
    qualifier.main()
    assert len(seen) == 1
    assert json.loads(capsys.readouterr().out) == {"TEST_ONLY_VERIFIER_BOUNDARY": True}


def test_current_launch_rejects_unmeasured_pack_before_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import issue_review_launch_authorization as launch

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("unmeasured current pack reached authority bootstrap")

    monkeypatch.setattr(launch, "bootstrap_review_authority", forbidden)
    with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
        launch.issue_review_launch_authorization(
            {
                "schema_version": "review-config/v2",
                "role": "IMPLEMENTATION_READINESS_REVIEWER",
                "network": "DENY",
            },
            {"production_authority": "NONE"},
            tmp_path / "must-not-exist.json",
        )
    assert not (tmp_path / "must-not-exist.json").exists()


@pytest.mark.parametrize("entrypoint", ["finalize_review", "aggregate_reviews"])
def test_current_cli_authentication_precedes_private_state_and_workspace_reads(
    signed_current: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    from cryptography.hazmat.primitives import serialization

    from tools import aggregate_reviews, finalize_review

    module = finalize_review if entrypoint == "finalize_review" else aggregate_reviews
    monkeypatch.setattr(module, "RUNTIME_ROOT", tmp_path)
    directory = tmp_path / "review-config"
    directory.mkdir()
    key = signed_current["private"]
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    public_path = tmp_path / "test-public.json"
    public_path.write_text(
        json.dumps(
            {
                "public_key_b64url": base64.urlsafe_b64encode(public).decode().rstrip("="),
                "trust_epoch": 0,
            }
        )
    )
    (directory / "review-authority.v1.json").write_text(
        json.dumps(
            {
                "public_key_path": str(public_path),
                "private_key_path": str(tmp_path / "must-not-read-private"),
            }
        )
    )
    auth = deepcopy(signed_current["launches"][0])
    auth["repository_identity_kind"] = "WRONG"
    auth = sign_review_launch_authorization(auth, key)
    (directory / "review-a.v2.json").write_text(
        json.dumps(
            {
                "schema_version": "review-config/v2",
                "role": auth["review_role"],
                "workspace_root": auth["workspace_root"],
            }
        )
    )
    authorization_path, result_path = tmp_path / "authorization.json", tmp_path / "result.json"
    authorization_path.write_text(json.dumps(auth))
    result_path.write_text(json.dumps(signed_current["reviews"][0]))
    output = tmp_path / "must-not-write-output.json"
    configured_result = Path(str(auth["allowed_output_root"])) / "result.json"
    original_read = Path.read_text

    def guarded_read(path: Path, *args: Any, **kwargs: Any) -> str:
        if entrypoint == "finalize_review" and path == configured_result:
            pytest.fail("unverified authorization reached configured result")
        if str(path).startswith("/home/thenam176/betting-helper/reviews/"):
            pytest.fail("unverified authorization reached configured human workspace")
        return original_read(path, *args, **kwargs)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("unverified authorization reached private authority/state")

    monkeypatch.setattr(Path, "read_text", guarded_read)
    monkeypatch.setattr(module, "bootstrap_review_authority", forbidden)
    monkeypatch.setattr(module, "_validate_consumed_authorization", forbidden)
    if entrypoint == "finalize_review":
        argv = [
            "finalize_review.py",
            "--authorization",
            str(authorization_path),
            "--result",
            str(configured_result),
            "--receipt",
            str(output),
        ]
    else:
        config_path = directory / "review-aggregation.v2.json"
        config_path.write_text(json.dumps({"schema_version": "review-aggregation-config/v2"}))
        argv = ["aggregate_reviews.py", "--config", str(config_path), "--output", str(output)]
        for flag in (
            "--authorization-a",
            "--authorization-b",
            "--receipt-a",
            "--receipt-b",
            "--review-a",
            "--review-b",
        ):
            argv.extend([flag, str(authorization_path if "authorization" in flag else result_path)])
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(ValueError, match="E_REVIEW_AUTH_SCHEMA"):
        module.main()
    assert not output.exists()


@pytest.fixture
def measured_current_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Real seal/descendant chain; inherited TEST_ONLY full/environment owner seams."""
    from tests.release import test_descendant_repository_qualification as receipt_tests
    from tests.seal.test_deterministic_seal import _current_self_review, _seal_current
    from tests.seal.test_pack_assembly import current_chain
    from tests.seal.test_self_review_binding import descendant_pack
    from tools import issue_review_launch_authorization as launch

    # Same synthetic environment-owner seam as the retained fixture qualification.
    # Production byte projection and its compiler-drift rejection have a separate test above.
    environment = tmp_path / "TEST_ONLY_ENVIRONMENT"
    environment.write_bytes(b"TEST_ONLY_NOT_QUALIFIED")
    monkeypatch.setattr(launch, "_review_environment_binding",
                        lambda config: sha256(environment.read_bytes()).hexdigest())

    original_sync = receipt_tests._sync_fixture_sources
    delivery = tmp_path / "review-pack"

    def transported_sync(
        source: Path,
        pack: Path,
        root: Path,
        patcher: pytest.MonkeyPatch,
        witnesses: dict[str, bytes],
    ) -> None:
        # Transport the current named inputs, not paths from an older checkout.
        # Only configuration locators are read; the host key is never accessed.
        selected = json.loads((source / "docs/configs/review-a.v2.json").read_bytes())
        authority = json.loads((source / "docs/configs/review-authority.v1.json").read_bytes())
        inputs = selected["input_roots"]
        replacements = {
            str(Path(authority["private_key_path"]).parent): str(
                tmp_path / "TEST_ONLY_EPHEMERAL_AUTHORITY"
            ),
            inputs[1]: str(root),
            inputs[0]: str(delivery),
            inputs[3]: str(tmp_path / "current.zip"),
            inputs[4]: str(tmp_path / "current.sha256"),
            inputs[2]: str(tmp_path / "current.json"),
        }

        def transport(value: Any) -> Any:
            if isinstance(value, str):
                for old, new in replacements.items():
                    if value == old or value.startswith(old + "/"):
                        return new + value[len(old) :]
                return value
            if isinstance(value, list):
                return [transport(item) for item in value]
            if isinstance(value, dict):
                return {key: transport(item) for key, item in value.items()}
            return value

        for relative in (
            "docs/configs/review-authority.v1.json",
            "docs/configs/review-a.v2.json",
            "docs/configs/review-b.v2.json",
            "docs/configs/review-aggregation.v2.json",
            "docs/registries/review-command-registry.v1.json",
            "docs/registries/cybersecurity-command-registry.v1.json",
        ):
            raw = (source / relative).read_bytes()
            witnesses[relative] = raw
            receipt_tests._write(pack / relative, transport(json.loads(raw)))
        original_sync(source, pack, root, patcher, witnesses)
        for role in ("a", "b"):
            configured = json.loads((root / f"review-config/review-{role}.v2.json").read_bytes())
            assert all(Path(p).is_relative_to(tmp_path) for p in configured["input_roots"])
            authority_path = Path(configured["authority_config"])
            assert authority_path.is_relative_to(root)
            isolated = json.loads(authority_path.read_bytes())
            assert all(Path(isolated[k]).is_relative_to(tmp_path)
                       for k in ("private_key_path", "public_key_path"))

    monkeypatch.setattr(receipt_tests, "_sync_fixture_sources", transported_sync)
    chain = cast(Any, current_chain).__wrapped__(tmp_path, monkeypatch)
    chain = cast(Any, descendant_pack).__wrapped__(chain)
    _current_self_review(chain)
    seal, paths = _seal_current(chain)
    chain.update(seal=seal, seal_paths=paths)
    return cast(dict[str, Any], chain)


def test_current_both_roles_measure_actual_seal_and_separate_registries(
    measured_current_pack: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from moj_discovery import review_authorization as auth_library
    from tests.review.test_review_aggregation_and_self_review import NOW as fixture_now
    from tests.review.test_review_aggregation_and_self_review import (
        _authorization as launch_fixture,
    )
    from tests.review.test_review_aggregation_and_self_review import _receipt as receipt_fixture
    from tests.review.test_review_aggregation_and_self_review import _review
    from tools import qualify_descendant_repository as qualifier
    from tools.bootstrap_review_authority import bootstrap_review_authority
    from tools.issue_review_launch_authorization import (
        issue_review_launch_authorization,
        measure_review_context,
        recheck_review_context,
        review_config_for_role,
    )

    chain = measured_current_pack
    test_authority_root = chain["directory"] / "TEST_ONLY_EPHEMERAL_AUTHORITY"
    test_authority: dict[str, Any] = {
        "production_authority": "NONE",
        "private_key_path": str(test_authority_root / "private.pem"),
        "public_key_path": str(test_authority_root / "public.json"),
        "private_key_mode": "0600",
        "public_key_mode": "0644",
    }
    bootstrap_review_authority(test_authority, initialize_if_absent=True)
    contexts = []
    configs = []
    issued_records = []
    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(auth_library, "RUNTIME_ROOT", chain["root"])
    for role in ("IMPLEMENTATION_READINESS_REVIEWER", "CYBERSECURITY_REVIEWER"):
        config = review_config_for_role(role, 2, runtime_root=chain["root"])
        context = measure_review_context(config)
        assert context["seal"] == chain["seal"]
        contexts.append(context)
        configs.append(config)
        issued_path = chain["directory"] / f"TEST_ONLY-{len(configs)}-launch.json"
        issued = issue_review_launch_authorization(
            config, test_authority, issued_path, now=fixture_now - timedelta(minutes=1)
        )
        issued_records.append(issued)
        from tools.issue_review_launch_authorization import review_public_key

        issued_public, issued_epoch = review_public_key(test_authority)
        verify_review_launch_authorization(
            issued,
            issued_public,
            role,
            config["workspace_root"],
            chain["seal"]["zip_sha256"],
            expected_trust_epoch=issued_epoch,
            now=fixture_now,
        )
        assert issued["schema_version"] == "review-launch-authorization/v2"
        auth = launch_fixture(
            _review(role), config["workspace_root"], config["output_root"], "1" * 32, private
        )
        auth = {key: value for key, value in auth.items() if not key.startswith("repo0_")}
        auth.update(
            auth_library.review_identity(chain["seal"]),
            schema_version="review-launch-authorization/v2",
            pack_zip_sha256=chain["seal"]["zip_sha256"],
            pack_manifest_sha256=chain["seal"]["manifest_sha256"],
            input_mounts=context["mounts"],
            excluded_roots=config["excluded_roots"],
            prompt_sha256=sha256(Path(config["prompt_path"]).read_bytes()).hexdigest(),
            command_registry_sha256=sha256(
                Path(config["command_registry_path"]).read_bytes()
            ).hexdigest(),
        )
        auth = sign_review_launch_authorization(auth, private)
        verify_review_launch_authorization(
            auth,
            private.public_key(),
            role,
            config["workspace_root"],
            auth["pack_zip_sha256"],
            now=fixture_now,
        )
        assert measure_review_context(config, auth)["seal"] == chain["seal"]
        for field in (
            "command_registry_sha256",
            "prompt_sha256",
            "pack_manifest_sha256",
            "repository_commit_oid",
        ):
            changed = {**auth, field: "f" * len(auth[field])}
            changed = sign_review_launch_authorization(changed, private)
            verify_review_launch_authorization(
                changed,
                private.public_key(),
                role,
                config["workspace_root"],
                changed["pack_zip_sha256"],
                now=fixture_now,
            )
            with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
                measure_review_context(config, changed)
            print("rejected signed binding", role, field)
    assert contexts[0]["transport"] == contexts[1]["transport"]
    assert contexts[0]["mounts"] == contexts[1]["mounts"]
    from cryptography.hazmat.primitives import serialization

    from moj_discovery.review_aggregation import aggregate_independent_reviews, review_content_hash

    test_private = serialization.load_pem_private_key(
        Path(test_authority["private_key_path"]).read_bytes(), password=None
    )
    assert isinstance(test_private, Ed25519PrivateKey)
    reviews, receipts = [], []
    for index, issued in enumerate(issued_records):
        review = _review(issued["review_role"])
        del review["repo0_receipt_sha256"]
        review.update(
            auth_library.review_identity(issued),
            schema_version="independent-review-result/v2",
            pack_zip_sha256=issued["pack_zip_sha256"],
            review_run_id=issued["review_run_id"],
        )
        if index == 0:
            review["verdicts"]["DESCENDANT_REPOSITORY_VALID"] = review["verdicts"].pop(
                "REPO0_BASELINE_VALID"
            )
        else:
            del review["verdicts"]["SAFE_TO_FREEZE_SCOPE0"]
        review["content_hash"] = review_content_hash(review)
        receipt = receipt_fixture(review, issued, test_private)
        receipt.update(
            auth_library.review_identity(issued),
            schema_version="review-execution-receipt/v2",
            host_boot_id=issued["host_boot_id"],
            input_content_roots=[row["content_root_sha256"] for row in issued["input_mounts"]],
        )
        receipts.append(sign_review_execution_receipt(receipt, test_private))
        reviews.append(review)
    aggregate = aggregate_independent_reviews(
        *reviews,
        *receipts,
        *issued_records,
        test_private.public_key(),
        json.loads((chain["root"] / "review-config/review-aggregation.v2.json").read_bytes()),
        expected_host_boot_id=issued_records[0]["host_boot_id"],
        expected_trust_epoch=0,
        now=fixture_now,
        external_seal=contexts[0]["seal"],
    )
    assert aggregate["schema_version"] == "review-aggregate-result/v2"
    assert aggregate["review_outcome"] == "PASS"
    pack = chain["pack"]
    registry_path = pack / "docs/registries/review-command-registry.v1.json"
    original_registry = registry_path.read_bytes()
    manifest_path = pack / "MANIFEST_SHA256.json"
    original_manifest = manifest_path.read_bytes()
    for mutation in (
        "missing",
        "duplicate",
        "cwd",
        "access",
        "repeated-option",
        "recorded-config",
        "other-row",
    ):
        registry = json.loads(original_registry)
        row = next(row for row in registry["commands"] if row["command_id"] == "A_CHECK_DESCENDANT")
        if mutation == "missing":
            registry["commands"].remove(row)
        elif mutation == "duplicate":
            registry["commands"].append(deepcopy(row))
        elif mutation == "cwd":
            row["cwd"] = "/test/wrong"
        elif mutation == "access":
            row["network"] = "ALLOW"
        elif mutation == "repeated-option":
            row["argv"].extend(["--pack", str(pack)])
        elif mutation == "recorded-config":
            row["argv"][row["argv"].index("--recorded-config") + 1] = "/test/wrong/config.json"
        else:
            registry["commands"][0]["purpose"] += "-substituted"
        raw = json.dumps(registry, sort_keys=True).encode()
        manifest = json.loads(original_manifest)
        entry = next(
            row
            for row in manifest["entries"]
            if row["path"] == "docs/registries/review-command-registry.v1.json"
        )
        entry.update(size=str(len(raw)), sha256=sha256(raw).hexdigest())
        try:
            registry_path.write_bytes(raw)
            manifest_path.write_text(json.dumps(manifest))
            for config in configs:
                with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
                    measure_review_context(config)
            print("rejected coherent transport", mutation)
        finally:
            registry_path.write_bytes(original_registry)
            manifest_path.write_bytes(original_manifest)
    materialized = chain["root"] / "review-config/review-a.v2.json"
    original = materialized.read_bytes()
    try:
        materialized.write_bytes(original + b" ")
        with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
            measure_review_context(configs[1])
        with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
            recheck_review_context(contexts[1])
    finally:
        materialized.write_bytes(original)
    # Actual check-only adapter + real descendant verifier; no operation output.
    monkeypatch.setattr("sys.argv", contexts[0]["transport"]["argv"][5:])
    qualifier.main()
    output = capsys.readouterr().out
    assert (
        json.loads(output.splitlines()[-1])["schema_version"]
        == "descendant-repository-qualification-receipt/v1"
    )


def test_current_finalizer_cli_confines_delivery_after_real_authentication(
    measured_current_pack: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real crypto/context/state; only exact configured delivery IO is virtualized."""
    from cryptography.hazmat.primitives import serialization

    from moj_discovery import review_authorization as auth_library
    from moj_discovery.review_aggregation import review_content_hash
    from tests.review.test_review_aggregation_and_self_review import _review
    from tools import finalize_review as finalizer
    from tools import prepare_review_workspace as preparation
    from tools.bootstrap_review_authority import bootstrap_review_authority
    from tools.issue_review_launch_authorization import (
        issue_review_launch_authorization,
        review_config_for_role,
    )

    chain = measured_current_pack
    root, directory = chain["root"], chain["directory"]
    monkeypatch.setattr(auth_library, "RUNTIME_ROOT", root)
    monkeypatch.setattr(finalizer, "RUNTIME_ROOT", root)
    monkeypatch.setattr(preparation, "RUNTIME_ROOT", root)
    config = review_config_for_role("IMPLEMENTATION_READINESS_REVIEWER", 2, runtime_root=root)
    authority = json.loads(Path(config["authority_config"]).read_bytes())
    assert Path(authority["private_key_path"]).is_relative_to(directory)
    bootstrap_review_authority(authority, initialize_if_absent=True)
    auth_path = directory / "TEST_ONLY-current-launch.json"
    auth = issue_review_launch_authorization(config, authority, auth_path)
    private = serialization.load_pem_private_key(
        Path(authority["private_key_path"]).read_bytes(), password=None
    )
    assert isinstance(private, Ed25519PrivateKey)
    logical_output, logical_workspace = (
        Path(auth["allowed_output_root"]),
        Path(auth["workspace_root"]),
    )
    output, workspace = directory / "delivery-output", directory / "delivery-workspace"
    mapping = {logical_output: output, logical_workspace: workspace}
    original_open, original_stat, original_lstat = Path.open, Path.stat, Path.lstat
    original_mkdir, original_resolve = Path.mkdir, Path.resolve

    def mapped(path: Path) -> Path:
        for logical, physical in mapping.items():
            if path == logical or path.is_relative_to(logical):
                return physical / path.relative_to(logical)
        return path

    def resolved(path: Path, *args: Any, **kwargs: Any) -> Path:
        physical = original_resolve(mapped(path), *args, **kwargs)
        for logical, backing in mapping.items():
            if (path == logical or path.is_relative_to(logical)) and physical.is_relative_to(
                backing
            ):
                return logical / physical.relative_to(backing)
        return physical

    monkeypatch.setattr(
        Path, "open", lambda path, *args, **kwargs: original_open(mapped(path), *args, **kwargs)
    )
    monkeypatch.setattr(
        Path, "stat", lambda path, *args, **kwargs: original_stat(mapped(path), *args, **kwargs)
    )
    monkeypatch.setattr(
        Path, "lstat", lambda path, *args, **kwargs: original_lstat(mapped(path), *args, **kwargs)
    )
    monkeypatch.setattr(
        Path, "mkdir", lambda path, *args, **kwargs: original_mkdir(mapped(path), *args, **kwargs)
    )
    monkeypatch.setattr(Path, "resolve", resolved)
    records = [
        {
            "command_id": command_id,
            "argv": argv,
            "cwd": str(root),
            "environment": {},
            "exit_code": 0,
            "stdout_sha256": "0" * 64,
            "stderr_sha256": "0" * 64,
        }
        for command_id, argv in (
            ("A_INSTALL_PYTHON", ["uv", "sync", "--frozen", "--offline"]),
            (
                "A_INSTALL_NODE",
                ["pnpm", "install", "--frozen-lockfile", "--offline", "--ignore-scripts"],
            ),
        )
    ]
    # Install/namespace execution are separate TEST_ONLY boundaries, not actual reviews.
    monkeypatch.setattr(preparation, "_preparation_commands", lambda *_: [])
    def fixture_preparation(*_args: object, log_root: Path) -> list[dict[str, object]]:
        # This auth/delivery test substitutes installs, with explicitly TEST_ONLY
        # observations retained through the same host custody path as real installs.
        for index, record in enumerate(records):
            for stream in ("stdout", "stderr"):
                raw = b"TEST_ONLY simulated preparation output"
                (log_root / f"{index:02d}.{stream}").write_bytes(raw)
                record[stream + "_sha256"] = sha256(raw).hexdigest()
        return records

    monkeypatch.setattr(preparation, "_run_preparation", fixture_preparation)
    monkeypatch.setattr(
        preparation, "_start_namespace", lambda *_: {"TEST_ONLY_NOT_EXECUTED": True}
    )
    assert preparation._consume(config, auth, execute=False)["result"] == "PASS"
    assert output.is_dir() and workspace.is_dir()
    result = _review(auth["review_role"])
    del result["repo0_receipt_sha256"]
    result.update(
        auth_library.review_identity(auth),
        schema_version="independent-review-result/v2",
        review_run_id=auth["review_run_id"],
        pack_zip_sha256=auth["pack_zip_sha256"],
    )
    result["verdicts"]["DESCENDANT_REPOSITORY_VALID"] = result["verdicts"].pop(
        "REPO0_BASELINE_VALID"
    )
    result["content_hash"] = review_content_hash(result)
    (output / "result.json").write_text(json.dumps(result))
    attestation_path = output / "workspace-attestation.json"
    attestation = json.loads(attestation_path.read_bytes())
    now = datetime.now(UTC).isoformat()
    attestation.update(
        finished_at=now,
        fresh_session_attestation={
            "attestation_type": "HUMAN_FRESH_CODEX_SESSION",
            "attested": True,
            "attested_by": "TEST_ONLY_PROCEDURAL_RECORD",
            "attested_at": now,
            "procedural_not_cryptographic": True,
        },
    )
    attestation_path.write_text(json.dumps(attestation))
    sentinel = directory / "outside-sentinel.json"
    sentinel.write_bytes(b"outside preserved")
    original_sign = finalizer.sign_review_execution_receipt
    forbidden_signing = True

    def sign(value: dict[str, object], key: Ed25519PrivateKey) -> dict[str, object]:
        if forbidden_signing:
            pytest.fail("invalid current delivery reached signing")
        return original_sign(value, key)

    monkeypatch.setattr(finalizer, "sign_review_execution_receipt", sign)
    receipt = output / "execution-receipt.json"
    for damage in ("outside", "parent-symlink", "hardlink", "existing", "result-outside"):
        supplied_result, supplied_receipt = (
            logical_output / "result.json",
            logical_output / "execution-receipt.json",
        )
        saved_output = directory / "saved-output"
        if damage == "outside":
            supplied_receipt = sentinel
        elif damage == "parent-symlink":
            output.rename(saved_output)
            output.symlink_to(saved_output, target_is_directory=True)
        elif damage == "hardlink":
            os.link(sentinel, receipt)
        elif damage == "existing":
            receipt.write_bytes(b"existing preserved")
        else:
            supplied_result = sentinel
        monkeypatch.setattr(
            "sys.argv",
            [
                "finalize_review.py",
                "--authorization",
                str(auth_path),
                "--result",
                str(supplied_result),
                "--receipt",
                str(supplied_receipt),
            ],
        )
        try:
            with pytest.raises(ValueError, match="E_REVIEW_FINALIZE_BINDING"):
                finalizer.main()
            assert sentinel.read_bytes() == b"outside preserved"
            if damage == "existing":
                assert receipt.read_bytes() == b"existing preserved"
        finally:
            if damage == "parent-symlink":
                output.unlink()
                saved_output.rename(output)
            elif damage in {"hardlink", "existing"}:
                receipt.unlink()
    forbidden_signing = False
    monkeypatch.setattr(
        "sys.argv",
        [
            "finalize_review.py",
            "--authorization",
            str(auth_path),
            "--result",
            str(logical_output / "result.json"),
            "--receipt",
            str(logical_output / "execution-receipt.json"),
        ],
    )
    with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
        finalizer.main()
    # Delivery-only positive seam; no real leaf execution or host receipt is claimed.
    # Actual closed host logs and tamper rejection are covered in workspace-isolation tests.
    monkeypatch.setattr(finalizer, "validate_host_execution", lambda *_: None)
    finalizer.main()
    emitted = json.loads(receipt.read_bytes())
    auth_library.verify_review_execution_receipt(
        emitted, auth, private.public_key(), result_sha256=emitted["result_sha256"]
    )
    assert emitted["schema_version"] == "review-execution-receipt/v2"


def test_mount_roots_read_governed_root_schema(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    runtime = tmp_path / "runtime"
    (pack / "docs/receipts").mkdir(parents=True)
    runtime.mkdir()
    (runtime / "source.txt").write_text("source")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=runtime, check=True)  # noqa: S607 - disposable fixture Git.
    subprocess.run(["git", "add", "source.txt"], cwd=runtime, check=True)  # noqa: S607 - disposable fixture Git.
    subprocess.run(
        [  # noqa: S607 - disposable fixture Git.
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "-m",
            "baseline",
        ],
        cwd=runtime,
        check=True,
    )
    commit, tree, file_root = _repository_identity(runtime)
    (pack / "GOVERNED_CONTENT_ROOT.json").write_text(json.dumps({"root_sha256": "a" * 64}))
    (pack / "docs/receipts/repo0-baseline-receipt.json").write_text(
        json.dumps(
            {
                "baseline_commit": commit,
                "baseline_tree": tree,
                "baseline_file_root_sha256": file_root,
            }
        )
    )
    inputs = [pack, runtime]
    for name in ("attestation.json", "pack.zip", "pack.zip.sha256"):
        path = tmp_path / name
        path.write_text(name)
        inputs.append(path)
    roots = _mount_roots(
        {
            "input_roots": [str(path) for path in inputs],
            "input_mounts": [
                {"source_root": str(path), "workspace_mount": str(path), "mode": "READ_ONLY"}
                for path in inputs
            ],
        }
    )

    assert roots[0]["content_root_sha256"] == "a" * 64
    assert roots[1]["content_root_sha256"] == file_root


def _authorization(private: Ed25519PrivateKey) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "review-launch-authorization/v1",
        "issuer_role": "HOST_REVIEW_AUTHORITY",
        "audience": "hybrid-discovery:independent-review-launcher:v1",
        "review_role": "IMPLEMENTATION_READINESS_REVIEWER",
        "review_run_id": "11111111-1111-4111-8111-111111111111",
        "pack_zip_sha256": PACK_HASH,
        "pack_manifest_sha256": "b" * 64,
        "repo0_receipt_sha256": "c" * 64,
        "repo0_commit_oid": "d" * 40,
        "repo0_tree_oid": "e" * 40,
        "repo0_file_tree_root_sha256": "f" * 64,
        "workspace_root": WORKSPACE,
        "input_mounts": [
            {
                "source_root": f"/sealed/input-{index}",
                "workspace_mount": f"/sealed/input-{index}",
                "mode": "READ_ONLY",
                "content_root_sha256": sha256(f"input-{index}".encode()).hexdigest(),
            }
            for index in range(5)
        ],
        "excluded_roots": ["/authoring", "/peer"],
        "allowed_output_root": (
            "/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a"
        ),
        "prompt_sha256": "1" * 64,
        "command_registry_sha256": "2" * 64,
        "issued_at": NOW.isoformat(),
        "not_before": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=14400)).isoformat(),
        "maximum_duration_seconds": 14400,
        "one_use_serial": "3" * 32,
        "nonce": "A" * 43,
        "fresh_session_required": True,
        "production_authority": "NONE",
        "signature_algorithm": "Ed25519",
        "host_boot_id": "00000000-0000-0000-0000-000000000000",
        "trust_epoch": 0,
    }
    return sign_review_launch_authorization(value, private)


def _receipt(authorization: dict[str, object], private: Ed25519PrivateKey) -> dict[str, object]:
    result = {"result": "PASS"}
    value: dict[str, object] = {
        "schema_version": "review-execution-receipt/v1",
        "authorization_id": authorization["authorization_id"],
        "issuer_role": "HOST_REVIEW_AUTHORITY",
        "review_role": authorization["review_role"],
        "review_run_id": authorization["review_run_id"],
        "workspace_root": authorization["workspace_root"],
        "workspace_attestation_sha256": "4" * 64,
        "input_content_roots": [
            item["content_root_sha256"]
            for item in cast(list[dict[str, object]], authorization["input_mounts"])
        ],
        "result_sha256": sha256(rfc8785.dumps(result)).hexdigest(),
        "commands_executed_root": "5" * 64,
        "allowed_changed_paths": ["result.json"],
        "unexpected_changed_paths": [],
        "started_at": (NOW + timedelta(seconds=1)).isoformat(),
        "finished_at": (NOW + timedelta(seconds=2)).isoformat(),
        "authorization_consumed_at": NOW.isoformat(),
        "fresh_session_attestation": {
            "attestation_type": "HUMAN_FRESH_CODEX_SESSION",
            "attested": True,
            "attested_by": "reviewer",
            "attested_at": NOW.isoformat(),
            "procedural_not_cryptographic": True,
        },
        "production_authority": "NONE",
        "signature_algorithm": "Ed25519",
        "host_boot_id": authorization["host_boot_id"],
        "trust_epoch": authorization["trust_epoch"],
        "preparation_commands_root": "6" * 64,
    }
    return sign_review_execution_receipt(value, private)


def test_wrong_role_workspace_pack_or_expiry_is_rejected() -> None:
    private = Ed25519PrivateKey.generate()
    authorization = _authorization(private)
    assert (
        verify_review_launch_authorization(
            authorization,
            private.public_key(),
            "IMPLEMENTATION_READINESS_REVIEWER",
            WORKSPACE,
            PACK_HASH,
            now=NOW,
        )["result"]
        == "PASS"
    )
    for field, value in (
        ("review_role", "CYBERSECURITY_REVIEWER"),
        ("workspace_root", "/wrong"),
        ("pack_zip_sha256", "b" * 64),
        ("expires_at", (NOW + timedelta(seconds=1)).isoformat()),
    ):
        changed = deepcopy(authorization)
        changed[field] = value
        with pytest.raises(ValueError):
            verify_review_launch_authorization(
                changed,
                private.public_key(),
                "IMPLEMENTATION_READINESS_REVIEWER",
                WORKSPACE,
                PACK_HASH,
                now=NOW,
            )


def test_receipt_has_a_separate_domain_and_exact_launch_binding() -> None:
    private = Ed25519PrivateKey.generate()
    authorization = _authorization(private)
    receipt = _receipt(authorization, private)
    result_hash = cast(str, receipt["result_sha256"])
    assert (
        verify_review_execution_receipt(
            receipt,
            authorization,
            private.public_key(),
            result_sha256=result_hash,
            now=NOW + timedelta(seconds=3),
        )["result"]
        == "PASS"
    )
    changed = deepcopy(receipt)
    cast(list[str], changed["input_content_roots"]).reverse()
    with pytest.raises(ValueError):
        verify_review_execution_receipt(
            changed,
            authorization,
            private.public_key(),
            result_sha256=result_hash,
            now=NOW + timedelta(seconds=3),
        )
    with pytest.raises(ValueError, match="E_REVIEW_AUTH_BINDING"):
        verify_review_execution_receipt(
            receipt,
            authorization,
            private.public_key(),
            result_sha256=result_hash,
            expected_host_boot_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
            expected_trust_epoch=0,
            now=NOW + timedelta(seconds=3),
        )


@pytest.mark.parametrize("seconds", [14400, 28800])
def test_current_signed_review_lifetime_and_expiry(
    signed_current: dict[str, Any], seconds: int
) -> None:
    private = signed_current["private"]
    launch = dict(signed_current["launches"][0])
    issued = datetime.fromisoformat(launch["issued_at"])
    launch.update(
        maximum_duration_seconds=seconds,
        expires_at=(issued + timedelta(seconds=seconds)).isoformat(),
    )
    launch = sign_review_launch_authorization(launch, private)
    args = (
        launch,
        private.public_key(),
        launch["review_role"],
        launch["workspace_root"],
        launch["pack_zip_sha256"],
    )
    verify_review_launch_authorization(*args, now=issued + timedelta(seconds=seconds - 1))
    with pytest.raises(ValueError, match="E_REVIEW_AUTH_BINDING"):
        verify_review_launch_authorization(*args, now=issued + timedelta(seconds=seconds))
    # A caller cannot extend an already issued launch by editing its timestamp.
    launch["expires_at"] = (issued + timedelta(seconds=seconds + 1)).isoformat()
    with pytest.raises(ValueError):
        verify_review_launch_authorization(*args, now=issued + timedelta(seconds=1))
    # Even a new signature cannot introduce an undeclared lifetime.
    launch["maximum_duration_seconds"] = seconds + 1
    bad = sign_review_launch_authorization(launch, private)
    with pytest.raises(ValueError):
        verify_review_launch_authorization(bad, *args[1:], now=issued + timedelta(seconds=1))


def test_eight_hour_receipt_accepts_seven_hours_and_rejects_late_finish(
    signed_current: dict[str, Any],
) -> None:
    private = signed_current["private"]
    launch = dict(signed_current["launches"][0])
    issued = datetime.fromisoformat(launch["issued_at"])
    launch.update(maximum_duration_seconds=28800,
                  expires_at=(issued + timedelta(hours=8)).isoformat())
    launch = sign_review_launch_authorization(launch, private)
    receipt = dict(signed_current["receipts"][0])
    receipt.update(authorization_id=launch["authorization_id"],
                   finished_at=(issued + timedelta(hours=7)).isoformat())
    receipt = sign_review_execution_receipt(receipt, private)
    verify_review_execution_receipt(receipt, launch, private.public_key(),
        result_sha256=receipt["result_sha256"], now=issued + timedelta(hours=7, minutes=1))
    receipt["finished_at"] = (issued + timedelta(hours=8, seconds=1)).isoformat()
    receipt = sign_review_execution_receipt(receipt, private)
    with pytest.raises(ValueError):
        verify_review_execution_receipt(receipt, launch, private.public_key(),
            result_sha256=receipt["result_sha256"], now=issued + timedelta(hours=8, seconds=2))
