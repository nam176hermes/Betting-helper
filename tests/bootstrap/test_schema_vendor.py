import json
import os
from pathlib import Path

import pytest

from moj_discovery.vendor import pack_root, verify_vendored_assets
from tools.sync_pack_assets import sync_pack_assets
from tools.verify_normative_bundle import verify_normative_bundle

ROOT = Path(__file__).parents[2]
PACK = pack_root(ROOT)


def test_vendor_sync_is_exact_and_registry_is_not_reauthored(tmp_path: Path) -> None:
    if PACK == ROOT / "vendor/hybrid-discovery-v6.3.6":
        assert verify_vendored_assets(ROOT)
        return
    sync_pack_assets(PACK, tmp_path)
    vendor = tmp_path / "vendor/hybrid-discovery-v6.3.6"
    assert not (tmp_path / "task-command-registry.json").exists()
    assert (vendor / "docs/registries/task-command-registry.v1.json").read_bytes() == (
        PACK / "docs/registries/task-command-registry.v1.json"
    ).read_bytes()
    assert len(json.loads((vendor / "SCHEMA_SHA256.json").read_text())["files"]) == 106
    _stage_root_registry(tmp_path)
    before = _snapshot(tmp_path)
    sync_pack_assets(PACK, tmp_path, check=True)
    assert _snapshot(tmp_path) == before


def test_normative_bundle_uses_the_explicit_runtime_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        verify_normative_bundle(PACK, tmp_path / "wrong-runtime")


def _minimal_pack(root: Path) -> Path:
    pack = root / "pack"
    for path in ("graphs", "registries", "schemas"):
        (pack / "docs" / path).mkdir(parents=True)
    (pack / "docs/graphs/graph.json").write_text("{}")
    (pack / "docs/registries/task-command-registry.v1.json").write_text("{}")
    _write_mapping(
        pack,
        [
            ("docs/graphs/graph.json", "docs/graphs/graph.json"),
            (
                "docs/registries/task-command-registry.v1.json",
                "docs/registries/task-command-registry.v1.json",
            ),
            (
                "docs/registries/normative-source-map.v1.json",
                "docs/registries/normative-source-map.v1.json",
            ),
        ],
    )
    return pack


def _write_mapping(pack: Path, entries: list[tuple[str, str]]) -> None:
    (pack / "docs/registries/normative-source-map.v1.json").write_text(
        json.dumps(
            {
                "schema_version": "normative-source-map/v1",
                "owner_phase": "MIG0",
                "vendor_prefix": "runtime/vendor/hybrid-discovery-v6.3.6/",
                "plan_namespace": "docs/",
                "inherited_entries": [],
                "plan_entries": [
                    {"plan_source": source, "vendor_relative": destination}
                    for source, destination in entries
                ],
                "graph_overrides": [],
            }
        )
    )


def _add_mapping(pack: Path, source: str, destination: str) -> None:
    mapping_path = pack / "docs/registries/normative-source-map.v1.json"
    mapping = json.loads(mapping_path.read_text())
    entries = [
        (entry["plan_source"], entry["vendor_relative"]) for entry in mapping["plan_entries"]
    ]
    _write_mapping(pack, [*entries, (source, destination)])


def _stage_root_registry(runtime: Path) -> None:
    vendor = runtime / "vendor/hybrid-discovery-v6.3.6"
    (runtime / "task-command-registry.json").write_bytes(
        (vendor / "docs/registries/task-command-registry.v1.json").read_bytes()
    )


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode & 0o777)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("link_kind", ["file", "directory"])
def test_sync_rejects_source_symlinks(tmp_path: Path, link_kind: str) -> None:
    pack = _minimal_pack(tmp_path)
    outside = tmp_path / "outside"
    if link_kind == "file":
        outside.write_text("escape")
        source = pack / "docs/graphs/graph.json"
        source.unlink()
        source.symlink_to(outside)
    else:
        outside.mkdir()
        (outside / "escape.json").write_text("escape")
        source = pack / "docs/graphs/graph.json"
        source.unlink()
        source.parent.rmdir()
        (pack / "docs/graphs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="E_VENDOR:SYMLINK"):
        sync_pack_assets(pack, tmp_path / "runtime")


def test_sync_rejects_destination_symlinks(tmp_path: Path) -> None:
    pack = _minimal_pack(tmp_path)
    runtime = tmp_path / "runtime"
    outside = tmp_path / "outside"
    outside.mkdir()
    vendor = runtime / "vendor/hybrid-discovery-v6.3.6"
    vendor.mkdir(parents=True)
    (vendor / "docs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="E_VENDOR:SYMLINK"):
        sync_pack_assets(pack, runtime)


def test_copy_removes_stale_destination_extra_and_check_rejects_it(tmp_path: Path) -> None:
    pack = _minimal_pack(tmp_path)
    runtime = tmp_path / "runtime"
    sync_pack_assets(pack, runtime)
    stale = runtime / "vendor/hybrid-discovery-v6.3.6/stale.json"
    stale.write_text("stale")
    before = _snapshot(runtime)

    with pytest.raises(ValueError, match="E_VENDOR:FILE_SET"):
        sync_pack_assets(pack, runtime, check=True)
    assert _snapshot(runtime) == before

    with pytest.raises(ValueError, match="E_VENDOR:FILE_SET"):
        sync_pack_assets(pack, runtime)
    assert stale.exists() and _snapshot(runtime) == before


def test_nested_manifest_name_is_payload_not_self_exclusion(tmp_path: Path) -> None:
    pack = _minimal_pack(tmp_path)
    nested = pack / "docs/schemas/nested/SCHEMA_SHA256.json"
    nested.parent.mkdir()
    nested.write_text("nested payload")
    _add_mapping(
        pack,
        "docs/schemas/nested/SCHEMA_SHA256.json",
        "docs/schemas/nested/SCHEMA_SHA256.json",
    )
    runtime = tmp_path / "runtime"

    sync_pack_assets(pack, runtime)

    manifest = json.loads(
        (runtime / "vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json").read_text()
    )
    assert "docs/schemas/nested/SCHEMA_SHA256.json" in {item["path"] for item in manifest["files"]}


@pytest.mark.parametrize("location", ["source", "vendor"])
def test_sync_rejects_fifo_special_entries(tmp_path: Path, location: str) -> None:
    pack = _minimal_pack(tmp_path)
    runtime = tmp_path / "runtime"
    if location == "source":
        source = pack / "docs/graphs/graph.json"
        source.unlink()
        os.mkfifo(source)
    else:
        sync_pack_assets(pack, runtime)
        os.mkfifo(runtime / "vendor/hybrid-discovery-v6.3.6/pipe")

    with pytest.raises(ValueError, match="E_VENDOR:ENTRY"):
        sync_pack_assets(pack, runtime, check=location == "vendor")


def test_sync_rejects_hardlinked_source_file(tmp_path: Path) -> None:
    pack = _minimal_pack(tmp_path)
    source = pack / "docs/graphs/graph.json"
    os.link(source, pack / "docs/graphs/alias.json")

    with pytest.raises(ValueError, match="E_VENDOR:HARDLINK"):
        sync_pack_assets(pack, tmp_path / "runtime")


def test_sync_rejects_non_nfc_paths(tmp_path: Path) -> None:
    pack = _minimal_pack(tmp_path)
    source = "docs/schemas/e\N{COMBINING ACUTE ACCENT}.json"
    (pack / source).parent.mkdir(parents=True, exist_ok=True)
    (pack / source).write_text("{}")
    _add_mapping(pack, source, source)

    with pytest.raises(ValueError, match="E_VENDOR:PATH"):
        sync_pack_assets(pack, tmp_path / "runtime")


def test_sync_rejects_noncanonical_source_and_vendor_modes(tmp_path: Path) -> None:
    pack = _minimal_pack(tmp_path)
    source = pack / "docs/schemas/schema.json"
    source.parent.mkdir(exist_ok=True)
    source.write_text("{}")
    _add_mapping(pack, "docs/schemas/schema.json", "docs/schemas/schema.json")
    source.chmod(0o600)

    with pytest.raises(ValueError, match="E_VENDOR:MODE"):
        sync_pack_assets(pack, tmp_path / "runtime")

    source.chmod(0o644)
    runtime = tmp_path / "runtime"
    sync_pack_assets(pack, runtime)
    (runtime / "vendor/hybrid-discovery-v6.3.6/docs/schemas/schema.json").chmod(0o600)
    with pytest.raises(ValueError, match="E_VENDOR:MODE"):
        sync_pack_assets(pack, runtime, check=True)


def test_sync_rejects_hardlinked_vendor_and_generated_files(tmp_path: Path) -> None:
    pack = _minimal_pack(tmp_path)
    runtime = tmp_path / "runtime"
    sync_pack_assets(pack, runtime)
    vendor_file = runtime / "vendor/hybrid-discovery-v6.3.6/docs/graphs/graph.json"
    os.link(vendor_file, runtime / "vendor/hybrid-discovery-v6.3.6/docs/graphs/alias.json")
    with pytest.raises(ValueError, match="E_VENDOR:HARDLINK"):
        sync_pack_assets(pack, runtime, check=True)

    vendor_file.unlink()
    (runtime / "vendor/hybrid-discovery-v6.3.6/docs/graphs/alias.json").unlink()
    sync_pack_assets(pack, runtime)
    _stage_root_registry(runtime)
    outside = tmp_path / "registry-alias.json"
    os.link(runtime / "task-command-registry.json", outside)
    with pytest.raises(ValueError, match="E_VENDOR:TASK_REGISTRY"):
        sync_pack_assets(pack, runtime, check=True)
