"""Supplemental retained closure must work without its original owned stores."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from tools import run_environment_qualification as environment
from tools.retained_artifact_io import RetainedArtifactIO
from tools.run_full_repair_qualification import collect_retained_sources, write_closed_inventory
from tools.run_indexeddb_crash_matrix import ROOT


def test_native_config_workspace_is_a_retained_boundary(tmp_path: Path) -> None:
    report = {
        "reports": {
            "native_ingestor": {
                "config": {"workspace": str(environment.WINDOWS_PARENT / "native-ingestor-test")}
            },
            "native_commit_io": {
                "config": {"workspace": str(environment.WINDOWS_PARENT / "native-ingestor-io")}
            },
        }
    }
    roots = environment.environment_retained_boundaries(report, tmp_path)
    assert set(roots) == {
        tmp_path,
        environment.WINDOWS_PARENT / "native-ingestor-test",
        environment.WINDOWS_PARENT / "native-ingestor-io",
    }


def test_live_prerequisites_do_not_exclude_sibling_owned_evidence(tmp_path: Path) -> None:
    roots = environment.environment_live_roots()
    assert environment.WINDOWS_PARENT not in roots
    assert Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe") in roots
    evidence = tmp_path / "input.json"
    evidence.write_text('{"retained":true}')
    assert collect_retained_sources(
        environment.artifact(evidence), retained_boundaries=(tmp_path,), live_roots=roots
    ) == [(evidence, str(evidence), str(tmp_path))]


@pytest.mark.parametrize("path", ["native-ingestor-sibling/../dependencies", "dependencies"])
def test_native_retained_boundary_rejects_shared_parent_escape(tmp_path: Path, path: str) -> None:
    report = {
        "reports": {
            "native_ingestor": {
                "config": {
                    "workspace": str(environment.WINDOWS_PARENT / path),
                }
            }
        }
    }
    with pytest.raises(ValueError, match="E_ENV_ARTIFACT_BOUNDARY"):
        environment.environment_retained_boundaries(report, tmp_path)


@pytest.fixture(scope="module")
def native_browser(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return environment.run_windows_browser(tmp_path_factory.mktemp("supplemental-native"))


def test_actual_native_browser_copied_closure_survives_original_unavailability(
    native_browser: dict[str, Any], tmp_path: Path
) -> None:
    report = native_browser
    owned = Path(report["owned_workspace"])
    controller = Path(report["input"]["path"]).parent
    inventory = write_closed_inventory(
        collect_retained_sources(
            report,
            retained_boundaries=(owned, controller),
            live_roots=(
                ROOT,
                environment.NATIVE.parent.parent,
                Path(report["browser_binary"]["path"]),
            ),
        ),
        tmp_path / "inventory.json",
    )
    artifacts = RetainedArtifactIO.from_manifest(inventory, tmp_path / "retained")
    hidden = owned.with_name(owned.name + "-hidden")
    owned.rename(hidden)
    try:
        environment.verify_windows_browser(report, artifacts=artifacts)
    finally:
        hidden.rename(owned)


def test_browser_closure_requires_captured_assets(
    native_browser: dict[str, Any], tmp_path: Path
) -> None:
    report = native_browser
    owned = Path(report["owned_workspace"])
    sources = collect_retained_sources(
        report,
        retained_boundaries=(owned, Path(report["input"]["path"]).parent),
        live_roots=(
            ROOT,
            environment.NATIVE.parent.parent,
            Path(report["browser_binary"]["path"]),
        ),
    )
    locators = {locator for _, locator, _ in sources}
    for name in ("manifest.json", "repair-probe.html", "src/spool.js"):
        assert str(owned / "test-extension" / name) in locators
    assert str(owned / "profile/environment-profile.json") in locators
    manifest = write_closed_inventory(sources, tmp_path / "inventory.json")
    row = next(
        row
        for row in cast(list[dict[str, Any]], manifest["files"])
        if row["recorded_locator"].endswith("src/spool.js")
    )
    (tmp_path / "retained" / row["copied_relative_path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="E_RETAINED_ARTIFACT"):
        RetainedArtifactIO.from_manifest(manifest, tmp_path / "retained")


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_hash", "binary_copy"])
def test_browser_retained_declarations_and_live_binary_cannot_be_substituted(
    native_browser: dict[str, Any], tmp_path: Path, mutation: str
) -> None:
    report = copy.deepcopy(native_browser)
    if mutation == "missing":
        report["retained_browser_files"].pop()
    elif mutation == "duplicate":
        report["retained_browser_files"].append(report["retained_browser_files"][0])
    elif mutation == "wrong_hash":
        report["retained_browser_files"][0]["sha256"] = "0" * 64
    else:
        target = tmp_path / "chrome.exe"
        shutil.copyfile(report["browser_binary"]["path"], target)
        report["browser_binary"] = environment.artifact(target)
    with pytest.raises(ValueError, match="E_ENV_WINDOWS_BROWSER_EVIDENCE") as rejected:
        environment.verify_windows_browser(report)
    assert str(rejected.value.__cause__) == (
        "E_ENV_ARTIFACT_HASH"
        if mutation == "wrong_hash"
        else "binding"
        if mutation == "binary_copy"
        else "browser files"
    )
