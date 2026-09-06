import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
from copy import copy, deepcopy
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

import moj_discovery.pack_verifier as pack_verifier
from moj_discovery.pack_verifier import (
    compute_command_result_root,
    compute_independent_file_tree_root,
    verify_pack_archive,
    verify_repository_baseline,
    write_pack_manifest,
)

PACK_NAME = "hybrid-discovery-v6.2"
ARCHIVE_NAME = f"{PACK_NAME}.zip"
RUNTIME_ROOT = Path(__file__).resolve().parents[2]
VENDOR = RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6"


def _fixture_pack(tmp_path: Path) -> Path:
    pack = tmp_path / PACK_NAME
    pack.mkdir(parents=True)
    (pack / "README.md").write_bytes(b"fixture\n")
    _write_manifest(pack)
    return pack


def _write_manifest(pack: Path, *, pack_hash: str | None = None) -> None:
    files: list[dict[str, object]] = []
    tree_items: list[bytes] = []
    for path in sorted(pack.rglob("*"), key=lambda value: value.as_posix().encode("utf-8")):
        if path.is_file() and path.name != "MANIFEST_SHA256.json":
            content = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(pack).as_posix(),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            )
            tree_items.append(
                path.relative_to(pack).as_posix().encode("utf-8")
                + b"\0"
                + str(len(content)).encode("ascii")
                + b"\0"
                + hashlib.sha256(content).hexdigest().encode("ascii")
                + b"\n"
            )
    tree_preimage = b"".join(tree_items)
    manifest = {
        "files": files,
        "implementation_baseline_hash": "a" * 64,
        "pack_hash": pack_hash or hashlib.sha256(tree_preimage).hexdigest(),
        "pack_version": "6.2",
        "production_authority": "NONE",
        "schema_version": "pack-manifest/v1",
        "self_excluded_path": "MANIFEST_SHA256.json",
    }
    (pack / "MANIFEST_SHA256.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_sidecar(archive: Path) -> None:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_bytes(
        f"{digest}  {archive.name}\n".encode("ascii")
    )


def test_manifest_writer_binds_baseline_tree_and_is_self_excluding(tmp_path: Path) -> None:
    pack = tmp_path / PACK_NAME
    receipt = pack / "docs/receipts/repo0-baseline-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "repo0-baseline-receipt/v1",
                "independent_file_tree_root_sha256": "b" * 64,
                "production_authority": "NONE",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (pack / "README.md").write_text("sealed fixture\n", encoding="utf-8")

    write_pack_manifest(pack, receipt)

    manifest = json.loads((pack / "MANIFEST_SHA256.json").read_text(encoding="utf-8"))
    assert manifest["implementation_baseline_hash"] == "b" * 64
    assert "MANIFEST_SHA256.json" not in {item["path"] for item in manifest["files"]}


def test_plan_manifest_authoring_and_sealing_authority_are_fail_closed() -> None:
    schema = json.loads((VENDOR / "schemas/meta-records.schema.json").read_text())
    plan = json.loads(
        (VENDOR / "docs/fixtures/inherited/v6.2/plan-manifest.json").read_text()
    )
    validator = Draft202012Validator(schema).evolve(schema={"$ref": "#/$defs/PlanManifest"})
    assert not list(validator.iter_errors(plan))

    draft = deepcopy(plan)
    draft["sealed"] = False
    draft["artifact_status"] = "AUTHORING_DRAFT_NOT_SEALED"
    draft["authority"]["READY_FOR_CODEX_REVIEW"] = "NO"
    assert not list(validator.iter_errors(draft))

    sealed = deepcopy(plan)
    sealed["sealed"] = True
    sealed["artifact_status"] = "SEALED_READY_FOR_INDEPENDENT_REVIEW"
    sealed["authority"]["READY_FOR_CODEX_REVIEW"] = "YES"
    assert not list(validator.iter_errors(sealed))

    draft_claims_review = deepcopy(draft)
    draft_claims_review["authority"]["READY_FOR_CODEX_REVIEW"] = "YES"
    sealed_denies_review = deepcopy(sealed)
    sealed_denies_review["authority"]["READY_FOR_CODEX_REVIEW"] = "NO"
    sealed_claims_implementation = deepcopy(sealed)
    sealed_claims_implementation["authority"]["READY_TO_IMPLEMENT_DISCOVERY_PACK"] = "YES"
    for mutation in (
        draft_claims_review,
        sealed_denies_review,
        sealed_claims_implementation,
    ):
        assert list(validator.iter_errors(mutation))


def _rewrite_archive(
    archive: Path,
    *,
    mutate_first: str | None = None,
    archive_comment: bytes = b"",
    add_directory: bool = False,
    add_path: str | None = None,
) -> None:
    with ZipFile(archive) as source:
        entries = [(copy(info), source.read(info)) for info in source.infolist()]
    temporary = archive.with_suffix(".rewrite")
    with ZipFile(temporary, "w", compression=ZIP_STORED, allowZip64=False) as output:
        output.comment = archive_comment
        for index, (info, content) in enumerate(entries):
            if index == 0:
                if mutate_first == "timestamp":
                    info.date_time = (1981, 1, 1, 0, 0, 0)
                elif mutate_first == "compression":
                    info.compress_type = ZIP_DEFLATED
                elif mutate_first == "creator":
                    info.create_system = 0
                elif mutate_first == "version":
                    info.create_version = 10
                elif mutate_first == "permissions":
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                elif mutate_first == "extra":
                    info.extra = b"\xfe\xca\x00\x00"
                elif mutate_first == "comment":
                    info.comment = b"comment"
                elif mutate_first == "internal":
                    info.internal_attr = 1
            output.writestr(info, content)
        if add_directory:
            directory = ZipInfo(f"{PACK_NAME}/", (1980, 1, 1, 0, 0, 0))
            directory.create_system = 3
            directory.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
            output.writestr(directory, b"")
        if add_path is not None:
            output.writestr(add_path, b"escape")
    os.replace(temporary, archive)
    _write_sidecar(archive)


def test_builder_is_byte_deterministic_and_writes_exact_sidecar(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / ARCHIVE_NAME
    second = second_dir / ARCHIVE_NAME

    pack_verifier.build_pack_archive(pack, first)
    pack_verifier.build_pack_archive(pack, second)

    assert first.read_bytes() == second.read_bytes()
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    assert digest == "8dad90d03be6e4f433d1049c82766c7b091ced9db0aed47ef3172b084e84f952"
    assert first.with_name(first.name + ".sha256").read_bytes() == (
        f"{digest}  {ARCHIVE_NAME}\n".encode("ascii")
    )
    verify_pack_archive(pack, first)


def test_vendored_archive_contract_reproduces_exact_golden_bytes(tmp_path: Path) -> None:
    schema = json.loads((VENDOR / "schemas/pack-archive.schema.json").read_text())
    profile = json.loads(
        (VENDOR / "registries/pack-archive-profile.v1.json").read_text()
    )
    vectors = json.loads((VENDOR / "vectors/pack-archive-v1.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(profile)
    validator.validate(vectors)
    assert profile["profile_id"] == vectors["profile_id"] == "HD-PACK-ZIP-STORED-v1"

    golden = vectors["golden_vectors"][0]
    pack = tmp_path / PACK_NAME
    pack.mkdir()
    for source in golden["source_files"]:
        content = base64.b64decode(source["content_base64"], validate=True)
        assert len(content) == source["size_bytes"]
        assert hashlib.sha256(content).hexdigest() == source["sha256"]
        target = pack / source["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (pack / "MANIFEST_SHA256.json").write_bytes(
        base64.b64decode(golden["manifest_content_base64"], validate=True)
    )
    archive = tmp_path / ARCHIVE_NAME

    digest = pack_verifier.build_pack_archive(pack, archive)

    expected_archive = base64.b64decode(golden["expected_archive_base64"], validate=True)
    expected_sidecar = base64.b64decode(golden["expected_sidecar_base64"], validate=True)
    assert len(expected_archive) == golden["expected_archive_size_bytes"] == 760
    assert digest == golden["expected_archive_sha256"]
    assert digest == "8dad90d03be6e4f433d1049c82766c7b091ced9db0aed47ef3172b084e84f952"
    assert hashlib.sha256(expected_archive).hexdigest() == digest
    assert archive.read_bytes() == expected_archive
    assert archive.with_name(archive.name + ".sha256").read_bytes() == expected_sidecar
    with ZipFile(archive) as zipped:
        assert zipped.namelist() == golden["expected_member_names"]
    negative_ids = [item["vector_id"] for item in vectors["negative_vectors"]]
    assert len(negative_ids) == len(set(negative_ids)) == 36
    verify_pack_archive(pack, archive)


def test_manifest_tree_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    _write_manifest(pack, pack_hash="0" * 64)

    with pytest.raises(ValueError, match="E_PACK:MANIFEST_HASH"):
        pack_verifier.build_pack_archive(pack, tmp_path / ARCHIVE_NAME)


def test_manifest_noncanonical_serialization_is_rejected(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    manifest_path = pack / "MANIFEST_SHA256.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="E_PACK:MANIFEST_SERIALIZATION"):
        pack_verifier.build_pack_archive(pack, tmp_path / ARCHIVE_NAME)


@pytest.mark.parametrize(
    "invalid_size",
    ["8", -1, 1.5, 9_007_199_254_740_992],
)
def test_manifest_size_bytes_requires_bounded_json_integer(
    tmp_path: Path, invalid_size: object
) -> None:
    pack = _fixture_pack(tmp_path)
    manifest_path = pack / "MANIFEST_SHA256.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["size_bytes"] = invalid_size
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="E_PACK:MANIFEST$"):
        pack_verifier.build_pack_archive(pack, tmp_path / ARCHIVE_NAME)


def test_builder_rejects_output_inside_pack(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)

    with pytest.raises(ValueError, match="E_PACK:ARCHIVE_PATH"):
        pack_verifier.build_pack_archive(pack, pack / ARCHIVE_NAME)


def test_build_cli_uses_the_normative_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = _fixture_pack(tmp_path)
    archive = tmp_path / ARCHIVE_NAME
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pack_verifier",
            "build",
            "--pack",
            str(pack),
            "--archive",
            str(archive),
        ],
    )

    assert pack_verifier.main() == 0
    verify_pack_archive(pack, archive)


def test_builder_rejects_source_symlinks_hardlinks_and_special_files(
    tmp_path: Path,
) -> None:
    for source_kind in ("symlink", "hardlink", "fifo"):
        case_root = tmp_path / source_kind
        pack = _fixture_pack(case_root)
        if source_kind == "symlink":
            (pack / "linked.md").symlink_to("README.md")
            _write_manifest(pack)
            expected = "E_PACK:SOURCE_TYPE"
        elif source_kind == "hardlink":
            os.link(pack / "README.md", pack / "linked.md")
            _write_manifest(pack)
            expected = "E_PACK:SOURCE_HARDLINK"
        else:
            os.mkfifo(pack / "special")
            expected = "E_PACK:SOURCE_TYPE"
        with pytest.raises(ValueError, match=expected):
            pack_verifier.build_pack_archive(pack, case_root / ARCHIVE_NAME)


def test_builder_rejects_non_nfc_source_path(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    (pack / "Cafe\u0301.md").write_bytes(b"unsafe path")
    _write_manifest(pack)

    with pytest.raises(ValueError, match="E_PACK:ARCHIVE_PATH"):
        pack_verifier.build_pack_archive(pack, tmp_path / ARCHIVE_NAME)


@pytest.mark.parametrize("name", ["\ufeffbom.md", "embedded\ufeffbom.md"])
def test_pack_archive_rejects_bom_path(tmp_path: Path, name: str) -> None:
    pack = _fixture_pack(tmp_path)
    (pack / name).write_bytes(b"unsafe path")
    _write_manifest(pack)

    with pytest.raises(ValueError, match="E_PACK:ARCHIVE_PATH"):
        pack_verifier.build_pack_archive(pack, tmp_path / ARCHIVE_NAME)


def test_verifier_requires_exact_sidecar(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    archive = tmp_path / ARCHIVE_NAME
    pack_verifier.build_pack_archive(pack, archive)
    archive.with_name(archive.name + ".sha256").unlink()

    with pytest.raises(ValueError, match="E_PACK:SIDECAR"):
        verify_pack_archive(pack, archive)


@pytest.mark.parametrize(
    "mutation",
    [
        "timestamp",
        "compression",
        "creator",
        "version",
        "permissions",
        "extra",
        "comment",
        "internal",
    ],
)
def test_verifier_rejects_noncanonical_member_metadata(
    tmp_path: Path, mutation: str
) -> None:
    pack = _fixture_pack(tmp_path)
    archive = tmp_path / ARCHIVE_NAME
    pack_verifier.build_pack_archive(pack, archive)
    _rewrite_archive(archive, mutate_first=mutation)

    with pytest.raises(ValueError, match="E_PACK:ARCHIVE_METADATA"):
        verify_pack_archive(pack, archive)


def test_verifier_rejects_comments_and_directory_entries(tmp_path: Path) -> None:
    for mutation in ("archive_comment", "directory_entry"):
        case_root = tmp_path / mutation
        pack = _fixture_pack(case_root)
        archive = case_root / ARCHIVE_NAME
        pack_verifier.build_pack_archive(pack, archive)
        _rewrite_archive(
            archive,
            archive_comment=b"comment" if mutation == "archive_comment" else b"",
            add_directory=mutation == "directory_entry",
        )
        expected = (
            "E_PACK:ARCHIVE_METADATA"
            if mutation == "archive_comment"
            else "E_PACK:ARCHIVE_FILE_SET"
        )
        with pytest.raises(ValueError, match=expected):
            verify_pack_archive(pack, archive)


def test_verifier_rejects_archive_bytes_that_do_not_match_rebuild(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    archive = tmp_path / ARCHIVE_NAME
    pack_verifier.build_pack_archive(pack, archive)
    content = bytearray(archive.read_bytes())
    content[-1] ^= 1
    archive.write_bytes(content)
    _write_sidecar(archive)

    with pytest.raises(ValueError, match="E_PACK:ARCHIVE"):
        verify_pack_archive(pack, archive)


def test_unsealed_directory_is_not_a_repository_baseline(tmp_path: Path) -> None:
    assert verify_repository_baseline(tmp_path) == ["E_BASELINE:NO_GIT"]


def test_independent_file_and_command_roots_match_canonical_golden_vectors() -> None:
    vector_path = VENDOR / "vectors/repo0-baseline-roots-v1.json"
    vectors = json.loads(vector_path.read_text())["valid_vectors"]
    file_vector, command_vector = vectors

    assert compute_independent_file_tree_root(file_vector["input"]) == file_vector["sha256"]
    assert compute_command_result_root(command_vector["input"]) == command_vector["sha256"]


def _git(root: Path, *argv: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed absolute Git executable in tmp_path only
        ["/usr/bin/git", "-C", str(root), *argv],
        check=True,
        capture_output=True,
        env={
            "HOME": str(root),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
        },
        text=True,
    ).stdout.strip()


def test_repository_verifier_rejects_ambient_parent_git(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    runtime = parent / "runtime"
    runtime.mkdir(parents=True)
    _git(parent, "init", "--initial-branch=main")

    assert verify_repository_baseline(runtime) == ["E_REPO0_AMBIENT_GIT"]


def _sealed_repository_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "runtime"
    root.mkdir(parents=True)
    (root / ".gitignore").write_text(".venv/\nnode_modules/\n")
    for filename in ("pnpm-lock.yaml", "uv.lock"):
        (root / filename).write_bytes(Path(filename).read_bytes())
    vendor = root / "vendor/hybrid-discovery-v6.3.6"
    vendor.mkdir(parents=True)
    (vendor / "payload.json").write_bytes(b"{}\n")
    (root / "same-a.txt").write_bytes(b"same\n")
    (root / "same-b.txt").write_bytes(b"same\n")

    _git(root, "init", "--initial-branch=main")
    _git(root, "add", "--all")
    _git(
        root,
        "-c",
        "user.name=Repo0 Test",
        "-c",
        "user.email=repo0@example.invalid",
        "commit",
        "-m",
        "Repo0 baseline test",
    )
    pack = tmp_path / "pack"
    (pack / "docs/registries").mkdir(parents=True)
    (pack / "docs/receipts").mkdir(parents=True)
    (pack / "docs/normative.json").write_bytes(b"{}\n")
    source_map = pack / "docs/registries/normative-source-map.v1.json"
    source_map.write_text(
        """{"schema_version":"normative-source-map/v1","owner_phase":"MIG0","inherited_entries":[],"""
        """"plan_entries":[{"plan_source":"docs/normative.json","vendor_relative":"docs/normative.json"}]}"""
    )
    from moj_discovery.pack_verifier import compute_vendor_tree_root
    from tools.qualify_zero_parent_baseline import _normative_source_set, _repository_identity
    from tools.verify_toolchains import EXPECTED, dependency_lock_hashes

    commit, tree, file_root = _repository_identity(root)
    map_hash, source_set_root, source_set_count = _normative_source_set(pack)
    receipt_path = pack / "docs/receipts/repo0-baseline-receipt.json"
    receipt_path.write_text(json.dumps({
        "schema_version": "repo0-baseline-receipt/v2", "production_authority": "NONE",
        "baseline_commit": commit, "baseline_tree": tree, "baseline_file_root_sha256": file_root,
        "candidate_qualification_sha256": "a" * 64,
        "candidate_command_evidence_sha256": "b" * 64,
        "command_result_root": "c" * 64, "baseline_registry_sha256": "d" * 64,
        "toolchain_versions": EXPECTED, "lockfile_hashes": dependency_lock_hashes(root),
        "vendor_root_sha256": compute_vendor_tree_root(vendor),
        "normative_source_map_sha256": map_hash, "normative_source_set_root": source_set_root,
        "normative_source_set_count": source_set_count,
    }, sort_keys=True, separators=(",", ":")) + "\n")
    return root, pack, receipt_path


def test_repository_verifier_accepts_current_postcommit_receipt(
    tmp_path: Path,
) -> None:
    root, _pack, receipt_path = _sealed_repository_fixture(tmp_path)
    assert verify_repository_baseline(root, receipt_path=receipt_path) == []


def test_repository_verifier_rejects_tampered_receipt_or_mapped_normative_set(
    tmp_path: Path,
) -> None:
    root, pack, receipt_path = _sealed_repository_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text())
    receipt["baseline_tree"] = "0" * 40
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
    assert verify_repository_baseline(root, receipt_path=receipt_path) == ["E_ZERO_PARENT_BASELINE"]

    root, pack, receipt_path = _sealed_repository_fixture(tmp_path / "mapped")
    (pack / "docs/normative.json").write_bytes(b"changed\n")
    assert verify_repository_baseline(root, receipt_path=receipt_path) == ["E_ZERO_PARENT_BASELINE"]


def test_repository_verifier_rejects_same_bytes_hardlinked_worktree(
    tmp_path: Path,
) -> None:
    root, _pack, receipt_path = _sealed_repository_fixture(tmp_path)
    (root / "same-b.txt").unlink()
    os.link(root / "same-a.txt", root / "same-b.txt")

    assert verify_repository_baseline(root, receipt_path=receipt_path) == [
        "E_REPO0_FILE_TREE_ENTRY"
    ]


@pytest.mark.parametrize("path", ["\ufeffbom.txt", "embedded\ufeffbom.txt"])
def test_independent_file_tree_rejects_bom_path(path: str) -> None:
    tree = {
        "schema_version": "repo0-independent-file-tree/v1",
        "entries": [
            {
                "entry_kind": "REGULAR_FILE",
                "file_sha256": hashlib.sha256(b"payload").hexdigest(),
                "git_mode": "100644",
                "gitlink": False,
                "hardlink": False,
                "path": path,
                "size_bytes": "7",
                "symlink": False,
            }
        ],
    }

    with pytest.raises(ValueError, match="E_REPO0_FILE_TREE_ENTRY"):
        compute_independent_file_tree_root(tree)


def test_public_receipt_symbols_reject_noncanonical_paths_without_mutation(
    tmp_path: Path,
) -> None:
    result = tmp_path / "repo0-command-results.json"
    result.write_text("keep")
    receipt_path = tmp_path / "repo0-baseline-receipt.json"

    with pytest.raises(ValueError, match="E_REPO0_RECEIPT_PATH"):
        pack_verifier.build_repo0_baseline_receipt(tmp_path, result)
    with pytest.raises(ValueError, match="E_REPO0_RECEIPT_PATH"):
        pack_verifier.write_repo0_baseline_receipt(receipt_path, {})

    assert result.read_text() == "keep"
    assert not receipt_path.exists()


def test_archive_path_traversal_is_rejected(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    archive = tmp_path / ARCHIVE_NAME
    pack_verifier.build_pack_archive(pack, archive)
    _rewrite_archive(archive, add_path="../escape.txt")
    with pytest.raises(ValueError, match="E_PACK:ARCHIVE_PATH"):
        verify_pack_archive(pack, archive)


def test_archive_file_set_precedes_untrusted_member_metadata(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    archive = tmp_path / ARCHIVE_NAME
    pack_verifier.build_pack_archive(pack, archive)
    _rewrite_archive(archive, add_path=f"{PACK_NAME}/extra.txt")

    with pytest.raises(ValueError, match="E_PACK:ARCHIVE_FILE_SET"):
        verify_pack_archive(pack, archive)


def test_exact_pack_archive_is_accepted(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    archive = tmp_path / ARCHIVE_NAME
    pack_verifier.build_pack_archive(pack, archive)
    verify_pack_archive(pack, archive)


def test_nested_source_walk_does_not_change_global_member_order(tmp_path: Path) -> None:
    pack = _fixture_pack(tmp_path)
    (pack / "a.").mkdir()
    (pack / "a." / "child").write_bytes(b"nested")
    (pack / "a.-").write_bytes(b"sibling")
    _write_manifest(pack)
    archive = tmp_path / ARCHIVE_NAME

    pack_verifier.build_pack_archive(pack, archive)

    with ZipFile(archive) as zipped:
        names = zipped.namelist()
    assert names == sorted(names, key=lambda value: value.encode("utf-8"))
    verify_pack_archive(pack, archive)
