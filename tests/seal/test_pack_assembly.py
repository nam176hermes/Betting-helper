import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import tools.assemble_review_pack as pack_assembly
from tools.assemble_review_pack import assemble_review_pack
from tools.qualify_zero_parent_baseline import _normative_source_set

RUNTIME = Path(__file__).resolve().parents[2]


@pytest.fixture
def current_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Real descendant/candidate binding; full/environment semantics ONLY are fixed.

    All derived paths and inert issuance records are TEST_ONLY_NOT_ISSUED, never
    an actual campaign or receipt qualification. Original source bytes are retained.
    """
    from tests.release import test_descendant_repository_qualification as receipt_tests
    from tools import build_candidate_qualification_receipt as candidate
    from tools import qualify_descendant_repository as descendant
    from tools.full_verifier_config import load_controller_config
    from tools.run_full_repair_qualification import write_closed_inventory
    from tools.verify_proof_coverage import verify_proof_coverage_matrix

    original_config = receipt_tests._config
    write = receipt_tests._write
    source = receipt_tests.SOURCE_CONFIG.parents[2]
    witnesses: dict[str, bytes] = {}
    inert: list[Path] = []

    def sync_fixture(pack: Path, root: Path) -> None:
        receipt_tests._sync_fixture_sources(source, pack, root, monkeypatch, witnesses)

    def configure(directory: Path, root: Path, ancestor: str) -> Any:
        config = original_config(directory, root, ancestor)
        pack = config.governed_source_pack
        config_raw = config.source_path.read_bytes()
        shutil.copytree(source, pack, dirs_exist_ok=True)
        (pack / "docs/configs/full-verifier-controller.v2.json").write_bytes(config_raw)
        # The current source declares this required artifact but has not yet
        # produced it. This disposable factual input is NOT source qualification.
        authority = pack / "docs/contracts/02-authority-graph.md"
        if not authority.exists():
            authority.write_text(
                "# TEST_ONLY authority graph fixture\n\n"
                "Production authority: NONE. Physical power: HOLD.\n"
                "This inert fixture is not an issued source artifact.\n"
            )
            print("TEST_ONLY authority doc added for declared membership; actual source missing")
        delivery = json.loads((pack / "docs/registries/delivery-map.v1.json").read_bytes())
        for entry in delivery["authoring_source_exports"]:
            target = pack.parent / entry["source"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source.parent / entry["source"], target)
        sync_fixture(pack, root)
        return load_controller_config(
            root / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"
        )

    monkeypatch.setattr(receipt_tests, "_config", configure)
    chain = receipt_tests.actual_matrix_candidate_chain.__wrapped__(tmp_path, monkeypatch)
    config = chain["config"]
    pack, root = config.governed_source_pack, chain["root"]
    original = json.loads(receipt_tests.SOURCE_CONFIG.read_bytes())
    derived = json.loads(config.source_path.read_bytes())
    paths = {
        original[section][key]: value
        for section in ("receipts", "qualification_evidence")
        for key, value in derived[section].items()
    }
    for original_row, derived_row in zip(
        chain["source_matrix"]["entries"], chain["matrix"]["entries"], strict=True
    ):
        if original_row["stage"] == "CANDIDATE":
            paths[original_row["evidence_artifact"]] = derived_row["evidence_artifact"]
    manifest_source = json.loads((source / "docs/tasks/task-manifest.v6.3.6.json").read_bytes())
    for task in manifest_source["tasks"]:
        if task["task_id"] not in {
            "V636-BOOT0-T01",
            "V636-BOOT0-T02",
            "V636-BOOT0-T03",
            "V636-P01-T02",
            "V636-MIG0-T08",
        }:
            continue
        for value in task["exact_files"]:
            if not value.startswith("/"):
                continue
            if value not in paths:
                paths[value] = str(tmp_path / "inert" / str(len(inert)) / Path(value).name)
            target = Path(paths[value])
            inert.append(target)
            write(target, {"fixture": "TEST_ONLY_NOT_ISSUED", "recorded_source": value})
    assert len(inert) == 6 and len(set(inert)) == 6
    assert len(set(paths.values())) == len(paths)

    def transport(value: Any, mapping: dict[str, str]) -> Any:
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [transport(item, mapping) for item in value]
        if isinstance(value, dict):
            return {key: transport(item, mapping) for key, item in value.items()}
        return value

    for relative in (
        "docs/tasks/task-manifest.v6.3.6.json",
        "docs/registries/command-io.v1.json",
        "docs/registries/artifact-ownership.v1.json",
    ):
        raw = (source / relative).read_bytes()
        witnesses[relative] = raw
        document = json.loads(raw)
        bound = transport(document, paths)
        assert transport(bound, {v: k for k, v in paths.items()}) == document
        write(pack / relative, bound)
    # Sync ONLY this disposable checkout, through the official copier. Its registry
    # is the actual current source registry; no hand-generated command rows.
    sync_fixture(pack, root)
    qualification = config.qualification_evidence
    for aggregate, inventory in (
        (qualification.full_repair_aggregate, qualification.full_repair_inventory),
        (
            qualification.environment_qualification_aggregate,
            qualification.environment_qualification_inventory,
        ),
    ):
        inventory.unlink()  # Only the earlier dummy file owned by this fixture.
        leaf = aggregate.parent / "owner-boundary.json"
        write(leaf, {"fixture": "TEST_ONLY_NOT_ISSUED", "owner": str(aggregate)})
        write_closed_inventory(
            [
                (aggregate, str(aggregate), str(aggregate.parent)),
                (leaf, str(leaf), str(aggregate.parent)),
            ],
            inventory,
        )
    from tools.verify_full_repair_qualification import verify_full_repair_qualification

    full = verify_full_repair_qualification(
        qualification.full_repair_aggregate,
        qualification.full_repair_inventory,
        config,
    )
    write(
        qualification.p03_proof,
        {
            **full,
            "schema_version": "full-repair-qualification/v1",
            "clock_proof_pending": True,
        },
    )
    write(qualification.p04_proof, full)
    write(
        config.proof_coverage_evidence,
        verify_proof_coverage_matrix(
            chain["matrix"],
            config.evidence_root,
            "CANDIDATE",
            config,
        ),
    )
    # Effective candidate argv are unchanged by these source P09/P10 changes.
    candidate.build_candidate_qualification_receipt(
        root,
        config.candidate_command_evidence,
        config.candidate_qualification_receipt,
        config,
    )
    registry = json.loads((root / "task-command-registry.json").read_bytes())
    issuance = next(
        row for row in registry["commands"] if row["command_id"] == "VERIFY_V636_P07_T03"
    )
    write(
        config.candidate_issuance_evidence,
        {
            "schema_version": "candidate-issuance-result/v1",
            "result": "PASS",
            "production_authority": "NONE",
            "controller_binding": config.binding(),
            "command": {
                "command_id": issuance["command_id"],
                "argv": issuance["argv"],
                "cwd": issuance["cwd"],
                "expected_exit": 0,
                "exit_code": 0,
                "passed": True,
                "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                "stdout_size_bytes": "0",
                "stderr_size_bytes": "0",
            },
            "proof_coverage_sha256": hashlib.sha256(
                config.proof_coverage_evidence.read_bytes()
            ).hexdigest(),
        },
    )
    chain["receipt"] = descendant.issue_descendant_qualification_receipt(
        root,
        config,
        config.descendant_repository_receipt,
    )
    assert load_controller_config(config.source_path) == config
    chain.update(inert=inert, witnesses=witnesses, full=full)
    print("P07 T03 structural invocation fixture: TEST_ONLY_NOT_EXECUTED; no actual issuance")
    print(
        "assembly fixture source witnesses="
        + json.dumps(
            {key: hashlib.sha256(raw).hexdigest() for key, raw in witnesses.items()}, sort_keys=True
        )
    )
    return chain


def _assemble(chain: dict[str, Any], destination: Path) -> dict[str, object]:
    return assemble_review_pack(
        chain["config"].governed_source_pack,
        destination,
        chain["config"],
        retained_manifest=destination / "evidence/retained-artifact-manifest.json",
        retained_root=destination / "evidence/retained",
    )


def _load(chain: dict[str, Any], destination: Path) -> Any:
    return pack_assembly.load_sealed_assembly_context(
        destination,
        destination / "docs/configs/full-verifier-controller.v2.json",
        str(chain["config"].source_path),
        destination / "evidence/retained-artifact-manifest.json",
        destination / "evidence/retained",
    )


def test_current_assembly_rejects_union_missing_extra_duplicate_conflict_and_alias(
    current_chain: dict[str, Any],
) -> None:
    chain = current_chain
    destination = chain["directory"] / "union-damage"
    _assemble(chain, destination)
    manifest_path = destination / "evidence/retained-artifact-manifest.json"
    original = manifest_path.read_bytes()
    root = destination / "evidence/retained"
    for damage in (
        "duplicate",
        "missing",
        "extra",
        "extra-row",
        "boundary",
        "alias",
        "traversal",
        "hash",
        "size",
        "bool-size",
        "symlink",
        "hardlink",
        "invalid-json",
    ):
        manifest = json.loads(original)
        row = next(
            row
            for row in manifest["files"]
            if row["recorded_locator"] == str(chain["config"].source_path)
        )
        target = root / row["copied_relative_path"]
        raw = target.read_bytes()
        extra = root / "files/unexpected.bin"
        if damage == "duplicate":
            manifest["files"].append(dict(row))
        elif damage == "missing":
            manifest["files"].remove(row)
            target.unlink()
        elif damage in {"extra", "extra-row"}:
            extra.write_bytes(b"unexpected")
            if damage == "extra-row":
                manifest["recorded_boundaries"].append("/unrelated")
                manifest["files"].append(
                    {
                        "recorded_locator": "/unrelated/data.json",
                        "recorded_boundary": "/unrelated",
                        "copied_relative_path": "files/unexpected.bin",
                        "size_bytes": 10,
                        "sha256": hashlib.sha256(b"unexpected").hexdigest(),
                    }
                )
        elif damage == "boundary":
            row["recorded_boundary"] = str(Path(row["recorded_boundary"]).parent)
            manifest["recorded_boundaries"].append(row["recorded_boundary"])
        elif damage == "alias":
            row["copied_relative_path"] = manifest["files"][0]["copied_relative_path"]
        elif damage == "traversal":
            row["copied_relative_path"] = "../config.json"
        elif damage == "hash":
            row["sha256"] = "0" * 64
        elif damage == "size":
            row["size_bytes"] += 1
        elif damage == "bool-size":
            row["size_bytes"] = True
        elif damage == "symlink":
            target.unlink()
            target.symlink_to(destination / "docs/configs/full-verifier-controller.v2.json")
        elif damage == "hardlink":
            extra.hardlink_to(target)
        manifest_path.write_bytes(
            b"invalid" if damage == "invalid-json" else json.dumps(manifest).encode()
        )
        try:
            with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
                _load(chain, destination)
        finally:
            if extra.exists():
                extra.unlink()
            if target.is_symlink():
                target.unlink()
            target.write_bytes(raw)
            manifest_path.write_bytes(original)
    _load(chain, destination)


@pytest.mark.parametrize(
    "damage", ["missing-readme", "unbound-membership", "governed", "self-review"]
)
def test_sealed_source_membership_is_independent_of_union(
    current_chain: dict[str, Any],
    damage: str,
) -> None:
    chain = current_chain
    destination = chain["directory"] / "source-membership"
    _assemble(chain, destination)
    source = chain["config"].governed_source_pack
    manifest_path = destination / "evidence/retained-artifact-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    retained = destination / "evidence/retained"
    if damage in {"missing-readme", "unbound-membership"}:
        row = next(
            row for row in manifest["files"] if row["recorded_locator"] == str(source / "README.md")
        )
        manifest["files"].remove(row)
        (retained / row["copied_relative_path"]).unlink()
        (destination / "README.md").unlink()
        if damage == "unbound-membership":
            relative = "docs/registries/artifact-ownership.v1.json"
            ownership = json.loads((destination / relative).read_bytes())
            next(row for row in ownership["entries"] if row["path"] == "pack/README.md")[
                "materialization_required"
            ] = False
            raw = json.dumps(ownership).encode()
            row = next(
                row
                for row in manifest["files"]
                if row["recorded_locator"] == str(source / relative)
            )
            (retained / row["copied_relative_path"]).write_bytes(raw)
            (destination / relative).write_bytes(raw)
            row.update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    else:
        name = "GOVERNED_CONTENT_ROOT.json" if damage == "governed" else "SELF_REVIEW_REPORT.json"
        raw = b'{"fixture":"TEST_ONLY_NOT_ISSUED"}'
        (destination / name).write_bytes(raw)
        (retained / "files/forbidden-future.bin").write_bytes(raw)
        manifest["files"].append(
            {
                "recorded_locator": str(source / name),
                "recorded_boundary": str(source),
                "copied_relative_path": "files/forbidden-future.bin",
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
        _load(chain, destination)


def test_sealed_owner_inventory_metadata_is_still_validated(
    current_chain: dict[str, Any],
) -> None:
    chain = current_chain
    destination = chain["directory"] / "owner-metadata"
    _assemble(chain, destination)
    config, artifacts = _load(chain, destination)
    inventory = config.qualification_evidence.full_repair_inventory
    physical = artifacts.physical_path(str(inventory), recorded_boundary=str(inventory.parent))
    original_inventory = physical.read_bytes()
    manifest_path = destination / "evidence/retained-artifact-manifest.json"
    original_union = manifest_path.read_bytes()
    for damage in ("duplicate-row", "duplicate-boundary", "traversal", "wrong-schema"):
        owner = json.loads(original_inventory)
        if damage == "duplicate-row":
            owner["files"].append(dict(owner["files"][0]))
        elif damage == "duplicate-boundary":
            owner["recorded_boundaries"].append(owner["recorded_boundaries"][0])
        elif damage == "traversal":
            owner["files"][0]["copied_relative_path"] = "../escaped.bin"
        else:
            owner["schema_version"] = "not-a-manifest"
        raw = json.dumps(owner).encode()
        union = json.loads(original_union)
        row = next(row for row in union["files"] if row["recorded_locator"] == str(inventory))
        row.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        physical.write_bytes(raw)
        manifest_path.write_text(json.dumps(union))
        try:
            with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
                _load(chain, destination)
        finally:
            physical.write_bytes(original_inventory)
            manifest_path.write_bytes(original_union)


@pytest.mark.parametrize("damage", ["named-copy", "source-drift", "live-aggregate-drift"])
def test_current_assembly_rejects_named_copy_divergence_and_input_drift(
    current_chain: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    from tools import run_full_repair_qualification as owner

    chain = current_chain
    destination = chain["directory"] / "copy-drift"
    config = chain["config"]
    original_writer = owner.write_closed_inventory

    def changed_after_copy(sources: Any, inventory: Path) -> Any:
        result = original_writer(sources, inventory)
        target = (
            destination / "docs/configs/full-verifier-controller.v2.json"
            if damage == "named-copy"
            else config.governed_source_pack / "docs/registries/delivery-map.v1.json"
            if damage == "source-drift"
            else config.qualification_evidence.full_repair_aggregate
        )
        target.write_bytes(target.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(owner, "write_closed_inventory", changed_after_copy)
    with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
        _assemble(chain, destination)
    assert not destination.exists()


def test_current_destination_is_disjoint_and_has_no_linked_parents(
    current_chain: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = current_chain
    config = chain["config"]
    linked = chain["directory"] / "linked"
    linked.symlink_to(config.evidence_root, target_is_directory=True)
    destinations = (
        config.current_checkout_root / "output",
        config.governed_source_pack / "output",
        config.evidence_root / "output",
        config.source_path.parent / "output",
        chain["directory"],
        linked / "output",
    )
    copied = []
    monkeypatch.setattr(pack_assembly, "_copy", lambda *args: copied.append(args))
    for destination in destinations:
        with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
            _assemble(chain, destination)
    assert copied == []


def test_owner_union_merges_consistent_physical_duplicates_and_rejects_conflicts(
    current_chain: dict[str, Any],
) -> None:
    chain = current_chain
    config = chain["config"]
    qualification = config.qualification_evidence
    full = json.loads(qualification.full_repair_inventory.read_bytes())
    environment = json.loads(qualification.environment_qualification_inventory.read_bytes())
    row = dict(
        next(
            row for row in full["files"] if row["recorded_locator"].endswith("owner-boundary.json")
        )
    )
    raw = (
        qualification.full_repair_inventory.parent / "retained" / row["copied_relative_path"]
    ).read_bytes()
    copy = (
        qualification.environment_qualification_inventory.parent
        / "retained"
        / row["copied_relative_path"]
    )
    copy.write_bytes(raw)
    environment["recorded_boundaries"].append(row["recorded_boundary"])
    environment["files"].append(row)
    qualification.environment_qualification_inventory.write_text(json.dumps(environment))
    entries, _named = pack_assembly._retained_inputs(
        config,
        [str(path) for path in pack_assembly._walk(config.governed_source_pack)],
    )
    assert entries[row["recorded_locator"]][2] == raw
    assert entries[row["recorded_locator"]][0] != copy
    for damage in ("boundary", "bytes"):
        altered = json.loads(json.dumps(environment))
        altered_row = altered["files"][-1]
        if damage == "boundary":
            altered_row["recorded_boundary"] = str(Path(row["recorded_boundary"]).parent)
            altered["recorded_boundaries"].append(altered_row["recorded_boundary"])
        else:
            copy.write_bytes(b"different bytes")
            altered_row.update(size_bytes=15, sha256=hashlib.sha256(b"different bytes").hexdigest())
        qualification.environment_qualification_inventory.write_text(json.dumps(altered))
        with pytest.raises(ValueError, match="E_REVIEW_PACK_ASSEMBLY"):
            pack_assembly._retained_inputs(
                config, [str(path) for path in pack_assembly._walk(config.governed_source_pack)]
            )


def test_current_assembly_rejects_symlink_source_directory(
    current_chain: dict[str, Any],
) -> None:
    chain = current_chain
    (chain["config"].governed_source_pack / "undeclared-link").symlink_to(
        chain["directory"], target_is_directory=True
    )
    destination = chain["directory"] / "linked-source"
    with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
        _assemble(chain, destination)
    assert not destination.exists()


def test_current_assembly_preserves_original_inventory_and_raw_locator_bytes(
    current_chain: dict[str, Any],
) -> None:
    chain = current_chain
    destination = chain["directory"] / "delivered"
    result = _assemble(chain, destination)
    assert result["result"] == "PASS"
    config, artifacts = pack_assembly.load_sealed_assembly_context(
        destination,
        destination / "docs/configs/full-verifier-controller.v2.json",
        str(chain["config"].source_path),
        destination / "evidence/retained-artifact-manifest.json",
        destination / "evidence/retained",
    )
    assert config == chain["config"]
    for path in (
        config.qualification_evidence.full_repair_inventory,
        config.qualification_evidence.environment_qualification_inventory,
        *chain["inert"],
    ):
        assert (
            artifacts.read_bytes(
                str(path), recorded_boundary=artifacts.recorded_boundary(str(path))
            )
            == path.read_bytes()
        )
    assert artifacts.recorded_boundary(
        str(config.governed_source_pack / "docs/configs/full-verifier-controller.v2.json")
    ) == str(config.governed_source_pack)
    assert (
        artifacts.recorded_to_relative[str(config.source_path)]
        != artifacts.recorded_to_relative[
            str(config.governed_source_pack / "docs/configs/full-verifier-controller.v2.json")
        ]
    )


def test_partial_current_assembly_inputs_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="E_REVIEW_PACK_ASSEMBLY"):
        assemble_review_pack(
            tmp_path / "missing", tmp_path / "pack", retained_manifest=tmp_path / "manifest.json"
        )
    assert not (tmp_path / "pack").exists()


def test_current_assembly_rejects_unbound_issuance_before_destination(
    current_chain: dict[str, Any],
) -> None:
    config = current_chain["config"]
    value = json.loads(config.candidate_issuance_evidence.read_bytes())
    value["proof_coverage_sha256"] = "0" * 64
    config.candidate_issuance_evidence.write_text(json.dumps(value))
    destination = current_chain["directory"] / "invalid-issuance"
    with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
        _assemble(current_chain, destination)
    assert not destination.exists()


def test_current_assembly_rejects_receipt_before_destination(
    current_chain: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = current_chain["config"]
    qualification = config.qualification_evidence
    paths = [
        config.descendant_repository_receipt,
        config.candidate_qualification_receipt,
        config.source_path,
        config.governed_source_pack / "docs/configs/full-verifier-controller.v2.json",
        config.candidate_command_evidence,
        config.proof_coverage_evidence,
        qualification.p03_proof,
        qualification.p04_proof,
        qualification.full_repair_aggregate,
        qualification.full_repair_inventory,
        qualification.environment_qualification_aggregate,
        qualification.environment_qualification_inventory,
        config.governed_source_pack / "docs/registries/proof-coverage-matrix.v1.json",
    ]
    copied = []
    monkeypatch.setattr(pack_assembly, "_copy", lambda *args: copied.append(args))
    for index, path in enumerate(paths):
        raw = path.read_bytes()
        path.write_bytes(b"invalid JSON")
        destination = current_chain["directory"] / f"invalid-{index}"
        try:
            with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
                _assemble(current_chain, destination)
            assert not destination.exists() and copied == []
        finally:
            path.write_bytes(raw)
    for index, path in enumerate(current_chain["inert"]):
        raw = path.read_bytes()
        path.unlink()
        try:
            with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
                _assemble(current_chain, current_chain["directory"] / f"missing-inert-{index}")
            assert copied == []
        finally:
            path.write_bytes(raw)


@pytest.mark.parametrize("race", ["exclusive-create", "replace-directory", "owned-failure"])
def test_current_assembly_preserves_competitor_on_exclusive_create_or_replacement(
    current_chain: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    race: str,
) -> None:
    destination = current_chain["directory"] / "raced"
    moved = current_chain["directory"] / "our-moved-directory"
    mkdir, copy = Path.mkdir, pack_assembly._copy

    def raced_mkdir(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == destination:
            mkdir(path)
            (path / "competitor").write_bytes(b"preserve competitor")
            raise FileExistsError(path)
        mkdir(path, *args, **kwargs)

    def raced_copy(source: Path, target: Path) -> None:
        copy(source, target)
        if race == "replace-directory":
            destination.rename(moved)
            mkdir(destination)
            (destination / "competitor").write_bytes(b"preserve competitor")
        raise OSError("controlled copy interruption")

    if race == "exclusive-create":
        monkeypatch.setattr(Path, "mkdir", raced_mkdir)
    else:
        monkeypatch.setattr(pack_assembly, "_copy", raced_copy)
    with pytest.raises(ValueError, match="^E_REVIEW_PACK_ASSEMBLY$"):
        _assemble(current_chain, destination)
    if race == "owned-failure":
        assert not destination.exists()
    else:
        assert (destination / "competitor").read_bytes() == b"preserve competitor"
    if race == "replace-directory":
        assert moved.is_dir()


def test_pack_inventory_has_no_external_review_or_final_seal_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "docs/prompts").mkdir(parents=True)
    (source / "docs/registries").mkdir(parents=True)
    (source / "docs/receipts").mkdir(parents=True)
    (source / "docs/prompts/review.md").write_text("review")
    (source / "docs/registries/normative-source-map.v1.json").write_text(
        """{"schema_version":"normative-source-map/v1","owner_phase":"MIG0","inherited_entries":[],"""
        """"plan_entries":[{"plan_source":"docs/prompts/review.md","vendor_relative":"docs/prompts/review.md"}]}"""
    )
    source_map, source_set, count = _normative_source_set(source)
    (source / "docs/receipts/repo0-baseline-receipt.json").write_text(
        f'{{"schema_version":"repo0-baseline-receipt/v2","normative_source_map_sha256":"{source_map}",'
        f'"normative_source_set_root":"{source_set}","normative_source_set_count":"{count}"}}'
    )
    result = assemble_review_pack(source, tmp_path / "review-pack")
    assert "docs/prompts/review.md" in result["files"]

    completed = subprocess.run(  # noqa: S603 - fixed local interpreter and argv
        [
            "/usr/bin/python3.12",
            "tools/assemble_review_pack.py",
            "--source",
            str(source),
            "--destination",
            str(tmp_path / "cli-review-pack"),
        ],
        cwd=RUNTIME,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode()

    (source / "MANIFEST_SHA256.json").write_text("forbidden")
    with pytest.raises(ValueError, match="E_REVIEW_PACK_ASSEMBLY"):
        assemble_review_pack(source, tmp_path / "second-pack")


def test_pack_copies_only_mapped_candidate_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    (source / "docs/registries").mkdir(parents=True)
    evidence.mkdir()
    (evidence / "proof.json").write_text('{"result":"PASS"}')
    (source / "docs/registries/proof-coverage-matrix.v1.json").write_text(
        '{"entries":[{"stage":"CANDIDATE","evidence_artifact":"'
        + str(evidence / "proof.json")
        + '","sealed_evidence_path":"evidence/proof.json"}]}'
    )
    monkeypatch.setattr(pack_assembly, "EVIDENCE_ROOT", evidence)

    copied = pack_assembly._copy_candidate_evidence(source, tmp_path / "destination")

    assert copied == ["evidence/proof.json"]
