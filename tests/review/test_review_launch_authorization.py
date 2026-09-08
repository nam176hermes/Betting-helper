import base64
import json
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
        for version in (1, 2):
            record = {"schema_version": f"review-config/v{version}", "role": role}
            (directory / f"{name}.v{version}.json").write_text(json.dumps(record))
            assert launch.review_config_for_role(role, version, runtime_root=tmp_path) == record
    with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
        launch.review_config_for_role("CYBERSECURITY_REVIEWER", 3, runtime_root=tmp_path)


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
    original_read = Path.read_text

    def guarded_read(path: Path, *args: Any, **kwargs: Any) -> str:
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
            str(result_path),
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

    original_sync = receipt_tests._sync_fixture_sources
    delivery = tmp_path / "review-pack"

    def transported_sync(
        source: Path,
        pack: Path,
        root: Path,
        patcher: pytest.MonkeyPatch,
        witnesses: dict[str, bytes],
    ) -> None:
        replacements = {
            "/home/thenam176/betting-helper/discovery-runtime-v6.3.6": str(root),
            "/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6": str(delivery),
            "/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6.zip": str(
                tmp_path / "current.zip"
            ),
            "/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6.zip.sha256": str(
                tmp_path / "current.sha256"
            ),
            (
                "/home/thenam176/betting-helper/review-packs/"
                "hybrid-discovery-v6.3.6.seal-attestation.json"
            ): str(tmp_path / "current.json"),
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
