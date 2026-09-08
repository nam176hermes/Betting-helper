import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.seal.test_self_review_binding import current_chain as current_chain
from tests.seal.test_self_review_binding import descendant_pack as descendant_pack
from tools.build_self_review import build_runtime_self_review
from tools.compute_governed_content_root import compute_governed_content_root
from tools.seal_review_pack import seal_review_pack
from tools.verify_proof_coverage import _verify_sealed_inputs


def _current_self_review(chain: dict[str, Any]) -> dict[str, object]:
    pack = chain["pack"]
    return build_runtime_self_review(
        pack / "GOVERNED_CONTENT_ROOT.json",
        pack / "docs/receipts/descendant-repository-qualification-receipt.json",
        pack,
        config=chain["copied_config"],
        artifacts=chain["artifacts"],
    )


def _seal_current(
    chain: dict[str, Any], label: str = "current"
) -> tuple[dict[str, object], list[Path]]:
    paths = [chain["directory"] / (label + suffix) for suffix in (".zip", ".sha256", ".json")]
    result = seal_review_pack(
        chain["pack"],
        *paths,
        config=chain["copied_config"],
        artifacts=chain["artifacts"],
    )
    return result, paths


def _verify_current(chain: dict[str, Any], pack: Path, paths: list[Path]) -> dict[str, object]:
    from tools.seal_review_pack import verify_sealed_review_pack

    return verify_sealed_review_pack(
        pack,
        *paths,
        config_path=pack / "docs/configs/full-verifier-controller.v2.json",
        recorded_config_locator=str(chain["config"].source_path),
        retained_manifest=pack / "evidence/retained-artifact-manifest.json",
        retained_root=pack / "evidence/retained",
    )


def test_registered_descendant_sealer_argv_emits_v7(
    descendant_pack: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import seal_review_pack as sealing

    chain, pack = descendant_pack, descendant_pack["pack"]
    _current_self_review(chain)
    registry = json.loads((pack / "docs/registries/task-command-registry.v1.json").read_bytes())
    row = next(row for row in registry["commands"] if row["command_id"] == "VERIFY_V636_P09_T04")
    argv = row["argv"][2:]
    values = {
        "--pack": pack,
        "--config": pack / "docs/configs/full-verifier-controller.v2.json",
        "--recorded-config": chain["config"].source_path,
        "--retained-manifest": pack / "evidence/retained-artifact-manifest.json",
        "--retained-root": pack / "evidence/retained",
        "--zip": chain["directory"] / "cli.zip",
        "--sidecar": chain["directory"] / "cli.sha256",
        "--attestation": chain["directory"] / "cli.json",
    }
    for flag, value in values.items():
        argv[argv.index(flag) + 1] = str(value)
    monkeypatch.setattr("sys.argv", argv)
    sealing.main()
    assert (
        json.loads(values["--attestation"].read_bytes())["schema_version"]
        == "external-seal-attestation/v7"
    )


def test_descendant_seal_verifies_from_closed_copy_without_original_roots(
    descendant_pack: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import compute_governed_content_root as governing
    from tools import seal_review_pack as sealing

    chain, pack = descendant_pack, descendant_pack["pack"]
    review = _current_self_review(chain)
    attestation, paths = _seal_current(chain)
    assert set(attestation) == {
        "schema_version",
        "artifact_type",
        "artifact",
        "authorized_production_phases",
        "created_at",
        "zip_sha256",
        "manifest_sha256",
        "governed_content_root",
        "self_review_markdown_sha256",
        "self_review_json_sha256",
        "task_manifest_sha256",
        "candidate_receipt_sha256",
        "repository_qualification_receipt_sha256",
        "repository_identity_kind",
        "repository_commit_oid",
        "repository_tree_oid",
        "repository_file_tree_root_sha256",
    }
    assert attestation["schema_version"] == "external-seal-attestation/v7"
    assert attestation["artifact_type"] == "RUNTIME_PACK"
    assert attestation["authorized_production_phases"] == "NONE"
    for key in (
        "repository_qualification_receipt_sha256",
        "repository_identity_kind",
        "repository_commit_oid",
        "repository_tree_oid",
        "repository_file_tree_root_sha256",
        "governed_content_root",
        "task_manifest_sha256",
    ):
        assert attestation[key] == review[key]
    assert attestation["candidate_receipt_sha256"] == review["candidate_qualification_sha256"]
    closed = chain["directory"] / "closed" / pack.name
    shutil.copytree(pack, closed)
    for original in (
        pack,
        chain["config"].governed_source_pack.parent,
        chain["config"].evidence_root,
        chain["directory"] / "inert",
    ):
        shutil.rmtree(original)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in closed.rglob("*")
        if path.is_file()
    }
    before.update({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths})
    seal, compute = sealing.seal_review_pack, governing.compute_governed_content_root
    observed = []

    def temporary_seal(rebuilt: Path, *args: Any, **kwargs: Any) -> Any:
        assert rebuilt != closed and not rebuilt.is_relative_to(closed)
        assert kwargs["artifacts"].physical_root == rebuilt / "evidence/retained"
        assert kwargs["config"].source_path == chain["config"].source_path
        observed.append(rebuilt)
        return seal(rebuilt, *args, **kwargs)

    def temporary_root(rebuilt: Path, *args: Any) -> Any:
        assert rebuilt != closed and not rebuilt.is_relative_to(closed)
        return compute(rebuilt, *args)

    monkeypatch.setattr(sealing, "seal_review_pack", temporary_seal)
    monkeypatch.setattr(governing, "compute_governed_content_root", temporary_root)
    assert _verify_current(chain, closed, paths) == attestation
    assert observed
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before} == before


def test_self_review_rejects_cross_object_hash_and_identity_substitution(
    descendant_pack: dict[str, Any],
) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    record = _current_self_review(chain)
    path = pack / "SELF_REVIEW_REPORT.json"
    original = path.read_bytes()
    substitutions = {
        "schema_version": "runtime-self-review/v1",
        "governed_content_root": "a" * 64,
        "repository_qualification_receipt_sha256": "b" * 64,
        "candidate_qualification_sha256": "c" * 64,
        "task_manifest_sha256": "d" * 64,
        "command_result_root": "e" * 64,
        "repository_identity_kind": "ZERO_PARENT_BASELINE",
        "repository_commit_oid": "f" * 40,
        "repository_tree_oid": "0" * 40,
        "repository_file_tree_root_sha256": "1" * 64,
        "checks": [],
        "authority_granted": "LIVE",
    }
    assert set(substitutions) == set(record)
    for field, replacement in substitutions.items():
        for damage in ("different", "missing"):
            changed = copy.deepcopy(record)
            if damage == "different":
                changed[field] = replacement
            else:
                del changed[field]
            path.write_text(json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n")
            try:
                with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                    _seal_current(chain, "rejected")
                assert not (pack / "MANIFEST_SHA256.json").exists()
                assert not any(
                    (chain["directory"] / ("rejected" + suffix)).exists()
                    for suffix in (".zip", ".sha256", ".json")
                )
            finally:
                path.write_bytes(original)
    for field in (
        "repo0_receipt_sha256",
        "manifest_sha256",
        "zip_sha256",
        "sidecar_sha256",
        "extra",
    ):
        path.write_text(json.dumps({**record, field: "a" * 64}))
        try:
            with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                _seal_current(chain, "rejected")
        finally:
            path.write_bytes(original)


def test_v7_two_builds_and_independent_reconstruction_are_identical(
    descendant_pack: dict[str, Any],
) -> None:
    from tests.seal.test_pack_assembly import _load

    chain, pack = descendant_pack, descendant_pack["pack"]
    second = chain["directory"] / "independent" / pack.name
    shutil.copytree(pack, second)  # Both copies still have no self-review or manifest.
    assert not (second / "SELF_REVIEW_REPORT.json").exists()
    results = []
    for current in (pack, second):
        config, artifacts = _load(chain, current)
        compute_governed_content_root(current, current / "docs/registries/seal-exclusions.v1.json")
        local = {
            **chain,
            "pack": current,
            "copied_config": config,
            "artifacts": artifacts,
            "directory": current.parent,
        }
        _current_self_review(local)
        attestation, paths = _seal_current(local, "same")
        assert _verify_current(local, current, paths) == attestation
        results.append((attestation, paths))
    for name in (
        "GOVERNED_CONTENT_ROOT.json",
        "SELF_REVIEW_REPORT.json",
        "SELF_REVIEW_REPORT.md",
        "MANIFEST_SHA256.json",
    ):
        assert (pack / name).read_bytes() == (second / name).read_bytes()
    first, next_result = results
    assert first[1][0].read_bytes() == next_result[1][0].read_bytes()
    assert first[1][1].read_bytes() == next_result[1][1].read_bytes()
    next_result[0]["created_at"] = first[0]["created_at"]
    assert first[0] == next_result[0]


def test_v7_attestation_rejects_every_external_binding_mutation(
    descendant_pack: dict[str, Any],
) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    _current_self_review(chain)
    record, paths = _seal_current(chain)
    original = paths[2].read_bytes()
    substitutions = {key: "0" * 64 for key in record if key.endswith("sha256")}
    substitutions.update(
        schema_version="external-seal-attestation/v6",
        artifact_type="PLAN",
        artifact="other",
        authorized_production_phases="LIVE",
        created_at="2026-09-08T00:00:00",
        governed_content_root="1" * 64,
        repository_identity_kind="ZERO_PARENT_BASELINE",
        repository_commit_oid="2" * 40,
        repository_tree_oid="3" * 40,
    )
    assert set(substitutions) == set(record)
    for field, replacement in substitutions.items():
        for damage in ("different", "missing"):
            changed = dict(record)
            if damage == "different":
                changed[field] = replacement
            else:
                del changed[field]
            paths[2].write_text(json.dumps(changed))
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
            try:
                with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                    _verify_current(chain, pack, paths)
                assert {
                    path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
                } == before
            finally:
                paths[2].write_bytes(original)
    for field in ("repo0_receipt_sha256", "baseline_commit", "extra"):
        paths[2].write_text(json.dumps({**record, field: "a" * 64}))
        try:
            with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                _verify_current(chain, pack, paths)
        finally:
            paths[2].write_bytes(original)


def test_v7_created_at_is_a_valid_external_rfc3339_value(
    descendant_pack: dict[str, Any],
) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    _current_self_review(chain)
    record, paths = _seal_current(chain)
    for timestamp in ("20260908T000000+0000", "2026-09-08 00:00:00+00:00", "2026-09-08"):
        paths[2].write_text(json.dumps({**record, "created_at": timestamp}))
        with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
            _verify_current(chain, pack, paths)
    record["created_at"] = "2026-09-08T01:02:03.123456-04:00"
    paths[2].write_text(json.dumps(record))
    assert _verify_current(chain, pack, paths) == record


def test_current_and_legacy_outputs_match_the_governed_schema_arms(
    descendant_pack: dict[str, Any],
) -> None:
    from jsonschema import Draft202012Validator

    chain, pack = descendant_pack, descendant_pack["pack"]
    _current_self_review(chain)
    current, _paths = _seal_current(chain)
    schema = json.loads((pack / "docs/schemas/external-seal-attestation.schema.json").read_bytes())
    validator = Draft202012Validator(
        {"$ref": "#/$defs/ExternalSealAttestation", "$defs": schema["$defs"]}
    )
    assert list(validator.iter_errors(current)) == []
    legacy_root = chain["directory"] / "legacy-schema"
    legacy_pack, _matrix = _legacy_pack(legacy_root)
    legacy = seal_review_pack(
        legacy_pack,
        legacy_root / "seal.zip",
        legacy_root / "seal.sha256",
        legacy_root / "seal.json",
    )
    assert list(validator.iter_errors(legacy)) == []
    plan = {
        key: value
        for key, value in legacy.items()
        if key
        not in {
            "repo0_receipt_sha256",
            "baseline_file_root_sha256",
            "candidate_receipt_sha256",
            "baseline_commit",
            "baseline_tree",
        }
    }
    plan["artifact_type"] = "PLAN"
    assert list(validator.iter_errors(plan)) == []
    assert list(validator.iter_errors({**current, "artifact_type": "PLAN"}))


def test_sealed_verifier_rejects_changed_pack_and_external_bytes_without_writes(
    descendant_pack: dict[str, Any],
) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    _current_self_review(chain)
    _record, paths = _seal_current(chain)
    targets = [
        *paths[:2],
        *(
            pack / name
            for name in (
                "MANIFEST_SHA256.json",
                "GOVERNED_CONTENT_ROOT.json",
                "SELF_REVIEW_REPORT.json",
                "SELF_REVIEW_REPORT.md",
                "docs/tasks/task-manifest.v6.3.6.json",
                "docs/receipts/descendant-repository-qualification-receipt.json",
            )
        ),
    ]
    for target in targets:
        original = target.read_bytes()
        target.write_bytes(original + b" ")
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in targets}
        try:
            with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                _verify_current(chain, pack, paths)
            assert {
                path: (path.read_bytes(), path.stat().st_mtime_ns) for path in targets
            } == before
        finally:
            target.write_bytes(original)


def test_current_public_sealers_reject_incomplete_or_stale_context_and_in_pack_outputs(
    descendant_pack: dict[str, Any],
) -> None:
    from tools.seal_review_pack import verify_sealed_review_pack

    chain, pack = descendant_pack, descendant_pack["pack"]
    _current_self_review(chain)
    _record, paths = _seal_current(chain)
    for context in ({}, {"config": chain["copied_config"]}, {"artifacts": chain["artifacts"]}):
        before = {path: path.read_bytes() for path in (*paths, pack / "MANIFEST_SHA256.json")}
        with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
            seal_review_pack(pack, *paths, **context)
        assert {path: path.read_bytes() for path in before} == before
    complete = {
        "config_path": pack / "docs/configs/full-verifier-controller.v2.json",
        "recorded_config_locator": str(chain["config"].source_path),
        "retained_manifest": pack / "evidence/retained-artifact-manifest.json",
        "retained_root": pack / "evidence/retained",
    }
    for field in complete:
        for value in (
            None,
            "wrong-recorded" if field == "recorded_config_locator" else pack / "wrong",
        ):
            with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                verify_sealed_review_pack(pack, *paths, **{**complete, field: value})
    for index in range(3):
        invalid = list(paths)
        invalid[index] = pack / paths[index].name
        before = {path: path.read_bytes() for path in (*paths, pack / "MANIFEST_SHA256.json")}
        with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
            seal_review_pack(
                pack, *invalid, config=chain["copied_config"], artifacts=chain["artifacts"]
            )
        assert {path: path.read_bytes() for path in before} == before
        assert not invalid[index].exists()


def test_descendant_public_sealers_reject_retained_member_damage(
    descendant_pack: dict[str, Any],
) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    _current_self_review(chain)
    _record, paths = _seal_current(chain)
    manifest_path = pack / "evidence/retained-artifact-manifest.json"
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    row = next(
        row
        for row in manifest["files"]
        if row["recorded_locator"] == str(chain["config"].descendant_repository_receipt)
    )
    target = pack / "evidence/retained" / row["copied_relative_path"]
    raw = target.read_bytes()
    outside = chain["directory"] / "same-retained-bytes"
    outside.write_bytes(raw)
    extra = pack / "evidence/retained/files/unlisted.bin"
    for damage in ("missing", "extra", "alias", "hardlink", "symlink", "stale-hash"):
        changed = copy.deepcopy(manifest)
        if damage == "missing":
            target.unlink()
        elif damage == "extra":
            extra.write_bytes(b"unlisted")
        elif damage == "alias":
            changed["files"].append({**row, "recorded_locator": row["recorded_locator"] + ".alias"})
            manifest_path.write_text(json.dumps(changed))
        elif damage in {"hardlink", "symlink"}:
            target.unlink()
            if damage == "hardlink":
                target.hardlink_to(outside)
            else:
                target.symlink_to(outside)
        else:
            target.write_bytes(raw + b"\n")
        before = {path: path.read_bytes() for path in (*paths, pack / "MANIFEST_SHA256.json")}
        try:
            with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                _seal_current(chain)
            with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                _verify_current(chain, pack, paths)
            assert {path: path.read_bytes() for path in before} == before
        finally:
            if target.exists() or target.is_symlink():
                target.unlink()
            target.write_bytes(raw)
            extra.unlink(missing_ok=True)
            manifest_path.write_bytes(original)


def test_descendant_seal_rejects_coherently_rehashed_retained_tamper(
    descendant_pack: dict[str, Any],
) -> None:
    """Real candidate/P07/receipt binding; full/env are only the named fixed seams.

    Negative fixture repair makes transport, named copies, governed/manifest/ZIP
    and self-review/v7 byte hashes coherent. It does not invent executed evidence.
    """
    from tools.retained_artifact_io import RetainedArtifactIO
    from tools.seal_review_pack import _write_manifest, _write_zip

    chain, pack = descendant_pack, descendant_pack["pack"]
    config = chain["copied_config"]
    qualification = config.qualification_evidence
    review = _current_self_review(chain)
    attestation, paths = _seal_current(chain)
    union_path = pack / "evidence/retained-artifact-manifest.json"
    original = {path: path.read_bytes() for path in pack.rglob("*") if path.is_file()}
    original.update({path: path.read_bytes() for path in paths})
    matrix = json.loads((pack / "docs/registries/proof-coverage-matrix.v1.json").read_bytes())
    names = {
        str(path): "evidence/" + path.name
        for path in (
            config.candidate_qualification_receipt,
            config.candidate_issuance_evidence,
            config.proof_coverage_evidence,
            config.candidate_command_evidence,
        )
    }
    names.update(
        {
            entry["evidence_artifact"]: entry["sealed_evidence_path"]
            for entry in matrix["entries"]
            if entry["stage"] == "CANDIDATE"
        }
    )
    names[str(config.descendant_repository_receipt)] = (
        "docs/receipts/descendant-repository-qualification-receipt.json"
    )
    for damage, locator in (
        ("candidate", config.candidate_qualification_receipt),
        ("p07", config.candidate_issuance_evidence),
        ("receipt", config.descendant_repository_receipt),
        ("p03", qualification.p03_proof),
        ("full-aggregate", qualification.full_repair_aggregate),
        ("full-inventory", qualification.full_repair_inventory),
        ("environment-aggregate", qualification.environment_qualification_aggregate),
        ("environment-inventory", qualification.environment_qualification_inventory),
    ):
        union = json.loads(original[union_path])

        def replace(recorded: Path, value: Any, union: dict[str, Any] = union) -> bytes:
            raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
            row = next(row for row in union["files"] if row["recorded_locator"] == str(recorded))
            (pack / "evidence/retained" / row["copied_relative_path"]).write_bytes(raw)
            row.update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            if str(recorded) in names:
                (pack / names[str(recorded)]).write_bytes(raw)
            return raw

        physical = chain["artifacts"].physical_path(
            str(locator),
            recorded_boundary=chain["artifacts"].recorded_boundary(str(locator)),
        )
        value = json.loads(original[physical])
        if damage == "candidate":
            value["command_result_root"] = "a" * 64
        elif damage == "p07":
            value["command"]["command_id"] = "VERIFY_V636_P07_T02"
        elif damage == "receipt":
            value["repository_commit"] = "b" * 40
        elif damage == "p03":
            value["mutation_count"] = 104
        elif damage.endswith("aggregate"):
            value["changed_negative_fixture"] = True
        else:
            value["files"][0]["copied_relative_path"] = "files/renamed-negative-fixture.bin"
        changed_raw = replace(locator, value)
        if damage.endswith("aggregate"):
            inventory = (
                qualification.full_repair_inventory
                if damage.startswith("full")
                else qualification.environment_qualification_inventory
            )
            inventory_path = chain["artifacts"].physical_path(
                str(inventory),
                recorded_boundary=chain["artifacts"].recorded_boundary(str(inventory)),
            )
            owner = json.loads(original[inventory_path])
            row = next(row for row in owner["files"] if row["recorded_locator"] == str(locator))
            row.update(size_bytes=len(changed_raw), sha256=hashlib.sha256(changed_raw).hexdigest())
            replace(inventory, owner)
        receipt = json.loads((pack / names[str(config.descendant_repository_receipt)]).read_bytes())
        if damage == "candidate":
            receipt["candidate_qualification_sha256"] = hashlib.sha256(changed_raw).hexdigest()
            replace(config.descendant_repository_receipt, receipt)
        union_path.write_text(json.dumps(union))
        # Prove raw transport itself is valid, before entering semantic guards.
        artifacts = RetainedArtifactIO.from_manifest(union, pack / "evidence/retained")
        root = compute_governed_content_root(pack, pack / "docs/registries/seal-exclusions.v1.json")
        changed_review = {
            **review,
            "governed_content_root": root["root_sha256"],
            "repository_qualification_receipt_sha256": hashlib.sha256(
                (pack / names[str(config.descendant_repository_receipt)]).read_bytes()
            ).hexdigest(),
            "candidate_qualification_sha256": receipt["candidate_qualification_sha256"],
            "repository_commit_oid": receipt["repository_commit"],
        }
        (pack / "SELF_REVIEW_REPORT.json").write_text(
            json.dumps(changed_review, sort_keys=True, separators=(",", ":")) + "\n"
        )
        (pack / "SELF_REVIEW_REPORT.md").write_text(
            "# Runtime self-review\n\n"
            f"Governed content root: `{root['root_sha256']}`.\n\nAuthority granted: NONE.\n"
        )
        manifest = _write_manifest(pack)
        _write_zip(pack, paths[0])
        changed_attestation = {
            **attestation,
            **{
                key: changed_review[key]
                for key in (
                    "governed_content_root",
                    "repository_qualification_receipt_sha256",
                    "repository_commit_oid",
                )
            },
            "candidate_receipt_sha256": receipt["candidate_qualification_sha256"],
        }
        for field, path in (
            ("manifest_sha256", manifest),
            ("zip_sha256", paths[0]),
            ("self_review_json_sha256", pack / "SELF_REVIEW_REPORT.json"),
            ("self_review_markdown_sha256", pack / "SELF_REVIEW_REPORT.md"),
        ):
            changed_attestation[field] = hashlib.sha256(path.read_bytes()).hexdigest()
        paths[1].write_text(f"{changed_attestation['zip_sha256']}  {paths[0].name}\n")
        paths[2].write_text(json.dumps(changed_attestation))
        before = {path: path.read_bytes() for path in original}
        try:
            with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                seal_review_pack(pack, *paths, config=config, artifacts=artifacts)
            with pytest.raises(ValueError, match="^E_SEAL_PACK$"):
                _verify_current(chain, pack, paths)
            assert {path: path.read_bytes() for path in original} == before
        finally:
            for path, raw in original.items():
                path.write_bytes(raw)


def _legacy_pack(tmp_path: Path) -> tuple[Path, Path]:
    pack = tmp_path / "pack"
    (pack / "docs/registries").mkdir(parents=True)
    (pack / "docs/receipts").mkdir(parents=True)
    (pack / "docs/tasks").mkdir(parents=True)
    (pack / "docs/tasks/task-manifest.v6.3.6.json").write_text("{}\n")
    registry = pack / "docs/registries/seal-exclusions.v1.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "seal-exclusions/v2",
                "governed_root_exclusions": [
                    "GOVERNED_CONTENT_ROOT.json",
                    "SELF_REVIEW_REPORT.md",
                    "SELF_REVIEW_REPORT.json",
                    "MANIFEST_SHA256.json",
                ],
                "external_outputs_must_be_outside_root": True,
            }
        )
    )
    matrix = pack / "docs/registries/proof-coverage-matrix.v1.json"
    matrix.write_text("{}\n")
    receipt = pack / "docs/receipts/repo0-baseline-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "repo0-baseline-receipt/v2",
                "production_authority": "NONE",
                "baseline_commit": "a" * 40,
                "baseline_tree": "b" * 40,
                "baseline_file_root_sha256": "c" * 64,
                "candidate_qualification_sha256": "d" * 64,
                "command_result_root": "e" * 64,
                "candidate_command_evidence_sha256": "f" * 64,
                "baseline_registry_sha256": "0" * 64,
                "toolchain_versions": {"node": "v22.23.0"},
                "lockfile_hashes": {"uv_lock_sha256": "1" * 64},
                "vendor_root_sha256": "2" * 64,
                "normative_source_map_sha256": "3" * 64,
                "normative_source_set_root": "4" * 64,
                "normative_source_set_count": "106",
            }
        )
    )
    root = compute_governed_content_root(pack, registry)
    assert root["file_count"] == 4
    build_runtime_self_review(pack / "GOVERNED_CONTENT_ROOT.json", receipt, pack)
    return pack, matrix


def test_independent_rebuild_is_byte_identical_and_external_attestation_matches(
    tmp_path: Path,
) -> None:
    pack, matrix = _legacy_pack(tmp_path)

    first = seal_review_pack(
        pack, tmp_path / "one.zip", tmp_path / "one.sha256", tmp_path / "one.json"
    )
    second = seal_review_pack(
        pack, tmp_path / "two.zip", tmp_path / "two.sha256", tmp_path / "two.json"
    )

    assert (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()
    assert first["zip_sha256"] == hashlib.sha256((tmp_path / "one.zip").read_bytes()).hexdigest()
    assert second["manifest_sha256"] == first["manifest_sha256"]
    _verify_sealed_inputs(
        matrix, tmp_path / "one.json", tmp_path / "one.zip", tmp_path / "one.sha256"
    )


def test_sealer_rejects_descendant_review_with_legacy_receipt(tmp_path: Path) -> None:
    pack, _matrix = _legacy_pack(tmp_path)
    path = pack / "SELF_REVIEW_REPORT.json"
    value = json.loads(path.read_bytes())
    value["schema_version"] = "runtime-self-review/v2"
    value["repository_qualification_receipt_sha256"] = value.pop("repo0_receipt_sha256")
    value.update(
        repository_identity_kind="DESCENDANT",
        repository_commit_oid="a" * 40,
        repository_tree_oid="b" * 40,
        repository_file_tree_root_sha256="c" * 64,
    )
    path.write_text(json.dumps(value))
    outputs = [tmp_path / "wrong.zip", tmp_path / "wrong.sha256", tmp_path / "wrong.json"]
    with pytest.raises(ValueError, match="E_SEAL_PACK"):
        seal_review_pack(pack, *outputs)
    assert not (pack / "MANIFEST_SHA256.json").exists()
    assert not any(path.exists() for path in outputs)


@pytest.mark.parametrize("kind", ["file-symlink", "directory-symlink", "hardlink"])
def test_reconstruction_rejects_original_links_before_copy(tmp_path: Path, kind: str) -> None:
    pack, matrix = _legacy_pack(tmp_path)
    paths = [tmp_path / "seal.zip", tmp_path / "seal.sha256", tmp_path / "seal.json"]
    seal_review_pack(pack, *paths)
    original = pack / "docs/tasks/task-manifest.v6.3.6.json"
    if kind == "directory-symlink":
        directory = original.parent
        outside = tmp_path / "moved-tasks"
        directory.rename(outside)
        directory.symlink_to(outside, target_is_directory=True)
    else:
        outside = tmp_path / "same-task-bytes.json"
        original.rename(outside)
        if kind == "file-symlink":
            original.symlink_to(outside)
        else:
            original.hardlink_to(outside)
    with pytest.raises(ValueError, match="E_PROOF_COVERAGE"):
        _verify_sealed_inputs(matrix, paths[2], paths[0], paths[1])
