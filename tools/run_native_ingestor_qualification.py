"""Supplemental native Ingestor/COMMIT-I/O boundaries; no physical loss proof."""

from __future__ import annotations

import json
import subprocess
import tomllib
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from tools.native_ingestor_probe import COMMIT_PHASE, PHASES, dependency_payload
from tools.run_environment_qualification import (
    NATIVE,
    WINDOWS_PARENT,
    _verify_native_observation,
    artifact,
    checked,
    localpath,
    save,
    winpath,
)
from tools.run_indexeddb_crash_matrix import ROOT, _observations
from tools.verify_repair_evidence import _validate_sqlite_state, capture_binding

if TYPE_CHECKING:
    from tools.retained_artifact_io import RetainedArtifactIO

DEPENDENCIES = WINDOWS_PARENT / "native-dependency-closure-ab0f612d-1f27-4349-921a-76f05780578a"
SCRIPT = ROOT / "tools/native_ingestor_probe.py"
MODES = ("setup", "write", "reopen", "read", "replay", "replay-again", "final-read")


def dependency_binding() -> dict[str, Any]:
    files = dependency_payload(DEPENDENCIES)
    preparation = DEPENDENCIES / "preparation.json"
    prepared = json.loads(preparation.read_text())
    lock = artifact(ROOT / "uv.lock")
    if lock["sha256"] != prepared["lock_sha256"]:
        raise ValueError("E_NATIVE_DEPENDENCY_LOCK")
    packages = {
        row["name"]: row for row in tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    }
    wheels = []
    for wheel in prepared["wheels"]:
        source = Path(wheel["source"])
        descriptor = artifact(source)
        package = packages[wheel["name"]]
        if (
            descriptor["sha256"] != wheel["sha256"]
            or package["version"] != wheel["version"]
            or wheel["locked_wheel"] not in package["wheels"]
            or wheel["locked_wheel"]["hash"] != "sha256:" + descriptor["sha256"]
        ):
            raise ValueError("E_NATIVE_DEPENDENCY_WHEEL")
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                if (
                    not member.is_dir()
                    and archive.read(member)
                    != (DEPENDENCIES / "site-packages" / member.filename).read_bytes()
                ):
                    raise ValueError("E_NATIVE_DEPENDENCY_WHEEL_PAYLOAD")
        wheels.append(descriptor)
    for item in prepared["rfc8785"]["files"]:
        copied = (DEPENDENCIES / "site-packages" / item["path"]).read_bytes()
        if copied != Path(item["independent_source"]).read_bytes():
            raise ValueError("E_NATIVE_DEPENDENCY_RFC_PAYLOAD")
        if (
            not item["path"].endswith("/RECORD")
            and copied != Path(item["installed_source"]).read_bytes()
        ):
            raise ValueError("E_NATIVE_DEPENDENCY_RFC_PAYLOAD")
    return {
        "preparation": artifact(preparation),
        "files": files,
        "wheels": wheels,
        "lock": lock,
        "rfc_provenance": prepared["rfc8785"]["provenance"],
        "native_pyd": artifact(DEPENDENCIES / "site-packages/rpds/rpds.cp312-win_amd64.pyd"),
    }


def verify_loaded_dependencies(value: dict[str, Any], dependency: dict[str, Any]) -> None:
    imported = json.loads((DEPENDENCIES / "native-import.json").read_text())
    if (
        artifact(DEPENDENCIES / "native-import.json")["sha256"]
        != "7f33919edbec6678ecf6ef7c7f4f9c97176aa78627d0673fe227e341227749a6"
    ):
        raise ValueError("E_NATIVE_DEPENDENCY_IMPORT_REFERENCE")
    expected = {
        "modules": {
            item["distribution"]: {key: item[key] for key in ("path", "sha256", "version")}
            for item in imported["dependencies"]
        },
        "native_rpds": imported["native_rpds"],
    }
    if value != expected or value["native_rpds"]["sha256"] != dependency["native_pyd"]["sha256"]:
        raise ValueError("E_NATIVE_DEPENDENCY_IMPORT")


def _execute_native_ingestor(workspace: Path, *, commit_io: str | None = None) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    dependency = dependency_binding()
    owned = WINDOWS_PARENT / ("native-ingestor-" + str(uuid4()))
    owned.mkdir(exist_ok=False)
    delivery = _observations(str(uuid4()))[0]
    config = {
        "workspace": winpath(owned),
        "root": winpath(ROOT),
        "dependency_root": winpath(DEPENDENCIES),
        "delivery": delivery,
    }
    if commit_io is not None:
        config["commit_io"] = commit_io
    input_path = workspace / "owner-input.json"
    save(input_path, config)
    command = [str(NATIVE), "-I", "-B", winpath(SCRIPT), "owner", winpath(input_path)]
    process = subprocess.run(command, capture_output=True, timeout=180)  # noqa: S603
    (workspace / "owner.stdout").write_bytes(process.stdout)
    (workspace / "owner.stderr").write_bytes(process.stderr)
    if process.returncode or process.stderr:
        raise ValueError("E_NATIVE_INGESTOR_OWNER:" + process.stderr.decode())
    report = {
        **json.loads(process.stdout),
        "result": "PASS",
        "binding": capture_binding(),
        "dependency": dependency,
        "input": artifact(input_path),
        "config": config,
        "command": command,
        "exit": process.returncode,
        "stdout": artifact(workspace / "owner.stdout"),
        "stderr": artifact(workspace / "owner.stderr"),
        "scope": "NATIVE_SQLITE_COMMIT_IO_ONLY"
        if commit_io is not None
        else "NATIVE_INGESTOR_TEST_OWNER_BOUNDARIES_ONLY",
        "native_sql06": "PASS" if commit_io is not None else "HOLD_UNSUPPORTED",
        "physical_power_loss": "HOLD_NOT_EXECUTED",
        "tcp_ack_publication": "NOT_EXECUTED",
        "production_authority": "NONE",
    }
    try:
        verify_native_ingestor(report)
    except ValueError:
        save(workspace / "native-ingestor-candidate.json", {**report, "result": "UNVERIFIED"})
        raise
    save(workspace / "native-ingestor-terminal.json", report)
    return report


def run_native_ingestor(workspace: Path) -> dict[str, Any]:
    return _execute_native_ingestor(workspace)


def run_native_commit_io(workspace: Path, *, mode: str = "armed") -> dict[str, Any]:
    return _execute_native_ingestor(workspace, commit_io=mode)


def verify_native_commit_io(
    report: dict[str, Any], *, artifacts: RetainedArtifactIO | None = None
) -> None:
    verify_native_ingestor(report, artifacts=artifacts)
    if report["native_sql06"] != "PASS" or report["scope"] != "NATIVE_SQLITE_COMMIT_IO_ONLY":
        raise ValueError("E_NATIVE_COMMIT_IO_CALLBACK")


def verify_native_ingestor(
    report: dict[str, Any], *, artifacts: RetainedArtifactIO | None = None
) -> None:
    def retained(descriptor: dict[str, str]) -> bytes:
        boundary = artifacts.recorded_boundary(descriptor["path"]) if artifacts else None
        return checked(descriptor, artifacts=artifacts, recorded_boundary=boundary)

    try:
        io = "commit_io" in report["config"]
        if (
            report["result"] != "PASS"
            or report["binding"] != capture_binding()
            or report["dependency"] != dependency_binding()
            or report["exit"] != 0
            or retained(report["stderr"])
            or report["scope"]
            != (
                "NATIVE_SQLITE_COMMIT_IO_ONLY"
                if io
                else "NATIVE_INGESTOR_TEST_OWNER_BOUNDARIES_ONLY"
            )
            or report["native_sql06"] != ("PASS" if io else "HOLD_UNSUPPORTED")
            or report["physical_power_loss"] != "HOLD_NOT_EXECUTED"
            or report["tcp_ack_publication"] != "NOT_EXECUTED"
            or report["production_authority"] != "NONE"
        ):
            raise ValueError("binding")
        raw = json.loads(retained(report["stdout"]))
        if set(raw) != {
            "cases",
            "controller",
            "system",
            "python_version",
            "runtime_files",
        } or raw != {key: report[key] for key in raw}:
            raise ValueError("raw owner")
        runtime = [
            NATIVE,
            NATIVE.parent / "python312.dll",
            NATIVE.parent / "DLLs/_sqlite3.pyd",
            NATIVE.parent / "DLLs/sqlite3.dll",
        ]
        if report["system"] != "nt" or not report["python_version"].startswith("3.12.14 "):
            raise ValueError("native runtime")
        if len(report["runtime_files"]) != len(runtime):
            raise ValueError("native runtime files")
        for descriptor, path in zip(report["runtime_files"], runtime, strict=True):
            if localpath(descriptor["path"]) != path or checked(descriptor) != path.read_bytes():
                raise ValueError("native runtime files")
        cfg = json.loads(retained(report["input"]))
        if cfg != report["config"] or set(cfg) != {
            "workspace",
            "root",
            "dependency_root",
            "delivery",
        } | ({"commit_io"} if io else set()):
            raise ValueError("input")
        if io and cfg["commit_io"] not in {"armed", "bypass", "unarmed", "postcommit"}:
            raise ValueError("E_NATIVE_COMMIT_IO_MODE")
        from moj_discovery.canonical import verify_canonical_content_hash
        from moj_discovery.schema_registry import validate_artifact
        from moj_discovery.store import VENDOR

        delivery = cfg["delivery"]
        validate_artifact(
            delivery, "raw-observation.schema.json", bootstrap_only=True, vendor=VENDOR
        )
        verify_canonical_content_hash(
            "RawObservation",
            delivery,
            delivery["content_hash"],
            registry_path=VENDOR / "registries/canonical-hash-domains.v1.json",
        )
        run_id = delivery["discovery_run_id"]
        if delivery != _observations(run_id)[0]:
            raise ValueError("ordinary delivery")
        owned = localpath(cfg["workspace"])
        if owned.parent != WINDOWS_PARENT or not owned.name.startswith("native-ingestor-"):
            raise ValueError("owned workspace")
        if cfg["root"] != winpath(ROOT) or cfg["dependency_root"] != winpath(DEPENDENCIES):
            raise ValueError("input paths")
        command = [
            str(NATIVE),
            "-I",
            "-B",
            winpath(SCRIPT),
            "owner",
            winpath(Path(report["input"]["path"])),
        ]
        if report["command"] != command:
            raise ValueError("command")
        controller_identity = _verify_native_observation(
            report["controller"],
            [winpath(NATIVE), *command[1:]],
            report["controller"]["cim"]["ParentProcessId"],
            wsl_entry=True,
        )
        phases = (COMMIT_PHASE,) if io else PHASES
        if [row["case_id"] for row in report["cases"]] != list(phases):
            raise ValueError("case set")
        identities = {controller_identity}
        for ordinal, row in enumerate(report["cases"]):
            phase = phases[ordinal]
            committed_after = ordinal if not io else int(cfg["commit_io"] != "armed")
            case = owned / phase
            identity = {"run_id": run_id, "case_id": phase, "checkpoint_id": phase}
            base = {
                "root": cfg["root"],
                "dependency_root": cfg["dependency_root"],
                "run_dir": winpath(case / run_id),
                "identity": identity,
            }
            if set(row["inputs"]) != set(MODES):
                raise ValueError("inputs")
            for mode in MODES:
                value = {
                    **base,
                    **(
                        {"delivery": delivery}
                        if mode in {"setup", "write", "replay", "replay-again"}
                        else {}
                    ),
                }
                if io and mode == "write":
                    value["commit_io"] = cfg["commit_io"]
                item = row["inputs"][mode]
                if (
                    item["value"] != value
                    or json.loads(retained(item["artifact"])) != value
                    or localpath(item["artifact"]["path"]) != case / f"{mode}.input.json"
                ):
                    raise ValueError("oracle-free child input")
            if row["writer"] != row["writer_start"]:
                raise ValueError("writer replacement")
            writer_identity = _verify_native_observation(
                row["writer"],
                [
                    winpath(NATIVE),
                    "-I",
                    "-B",
                    winpath(SCRIPT),
                    "write",
                    winpath(case / "write.input.json"),
                ],
                report["controller"]["pid"],
            )
            identities.add(writer_identity)
            if row["termination"] != {
                "mechanism": "WINDOWS_TERMINATE_PROCESS_OWNED_HANDLE",
                "exit": 1,
                "pid": row["writer"]["pid"],
                "graceful": False,
            }:
                raise ValueError("termination")
            for key, filename in [
                ("writer_stdout", "write.stdout"),
                ("writer_stderr", "write.stderr"),
            ]:
                if localpath(row[key]["path"]) != case / filename or retained(row[key]):
                    raise ValueError("writer output")
            checkpoint = row["checkpoint"]
            if (
                checkpoint != json.loads(retained(row["checkpoint_artifact"]))
                or localpath(row["checkpoint_artifact"]["path"]) != case / "checkpoint.json"
                or set(checkpoint)
                != {
                    "identity",
                    "in_transaction",
                    "tables",
                    "ingest_ack",
                    "owner_ack_published",
                    "loaded_dependencies",
                }
                | ({"commit_io"} if io else set())
                or checkpoint["identity"] != {**identity, "pid": row["writer"]["pid"]}
                or checkpoint["in_transaction"] != (committed_after == 0)
                or checkpoint["owner_ack_published"] is not False
            ):
                raise ValueError("checkpoint")
            verify_loaded_dependencies(checkpoint["loaded_dependencies"], report["dependency"])
            names = ["before", "reopened", "after", "replayed", "replayed_again", "final"]
            if [process["mode"] for process in row["processes"]] != [
                mode for mode in MODES if mode != "write"
            ]:
                raise ValueError("reader set")
            for name, process in zip(names, row["processes"], strict=True):
                mode = process["mode"]
                process_identity = _verify_native_observation(
                    process["observed"],
                    [
                        winpath(NATIVE),
                        "-I",
                        "-B",
                        winpath(SCRIPT),
                        mode,
                        winpath(case / f"{mode}.input.json"),
                    ],
                    report["controller"]["pid"],
                )
                identities.add(process_identity)
                value = process["value"]
                if (
                    process["exit"] != 0
                    or retained(process["stderr"])
                    or localpath(process["stdout"]["path"]) != case / f"{mode}.stdout"
                    or localpath(process["stderr"]["path"]) != case / f"{mode}.stderr"
                    or value != json.loads(retained(process["stdout"]))
                    or set(value) != {"pid", "identity", "state", "ack", "loaded_dependencies"}
                    or value["pid"] != process["observed"]["pid"]
                    or value["identity"] != identity
                    or value["state"] != row[name]
                ):
                    raise ValueError("reader success")
                verify_loaded_dependencies(value["loaded_dependencies"], report["dependency"])
                committed = (
                    0
                    if name == "before"
                    else committed_after
                    if name in {"reopened", "after"}
                    else 1
                )
                _validate_sqlite_state(row[name], {"observation": delivery}, committed)
                expected_ack = (
                    row[name]["tables"]["ack_outbox"][0]
                    if mode in {"replay", "replay-again"}
                    else None
                )
                if value["ack"] != expected_ack:
                    raise ValueError("ack")
            _validate_sqlite_state(
                {**row["before"], "tables": checkpoint["tables"]}, {"observation": delivery}, 1
            )
            if (
                checkpoint["ingest_ack"]
                != (None if committed_after == 0 else row["after"]["tables"]["ack_outbox"][0])
                or row["after"] != row["reopened"]
                or row["replayed"] != row["replayed_again"]
                or row["replayed_again"] != row["final"]
                or (committed_after == 0 and row["after"] != row["before"])
                or (committed_after == 1 and row["after"] != row["replayed"])
            ):
                raise ValueError("atomic/replay state")
        if len(identities) != 1 + 7 * len(phases):
            raise ValueError("independent process identity")
        if io:
            from tools.native_sqlite_commit_io import verify_commit_callback

            verify_commit_callback(
                report["cases"][0],
                owned / COMMIT_PHASE,
                cfg["commit_io"],
                artifacts=artifacts,
            )
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise ValueError("E_NATIVE_INGESTOR_EVIDENCE") from error
