"""Issue one host-authority review launch authorization after all bindings are measured."""

# ruff: noqa: E402, I001, E501
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import shutil
import sqlite3
import stat
import sys
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
import rfc8785
from moj_discovery.canonical import parse_strict_json

from tools.bootstrap_review_authority import bootstrap_review_authority
from moj_discovery.review_authorization import (
    review_identity,
    sign_review_launch_authorization,
    verify_review_launch_authorization,
)


def review_public_key(authority_config: dict[str, object]) -> tuple[Ed25519PublicKey, int]:
    record_path = Path(cast(str, authority_config["public_key_path"]))
    _regular_hash(record_path)
    record = json.loads(record_path.read_text())
    encoded = record.get("public_key_b64url") if isinstance(record, dict) else None
    epoch = record.get("trust_epoch") if isinstance(record, dict) else None
    if not isinstance(encoded, str) or type(epoch) is not int or epoch < 0:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != encoded:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return Ed25519PublicKey.from_public_bytes(raw), epoch


def authorized_review_context(
    authorization: dict[str, object],
    authority: dict[str, object],
    *,
    runtime_root: Path = RUNTIME_ROOT,
) -> dict[str, object]:
    config = review_config_for_authorization(authorization, runtime_root=runtime_root)
    public, epoch = review_public_key(authority)
    verify_review_launch_authorization(
        authorization,
        public,
        cast(str, config["role"]),
        cast(str, config["workspace_root"]),
        cast(str, authorization["pack_zip_sha256"]),
        expected_host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        expected_trust_epoch=epoch,
    )
    return measure_review_context(config, authorization)


def review_config_for_role(
    role: str, version: int, *, runtime_root: Path = RUNTIME_ROOT
) -> dict[str, object]:
    names = {"IMPLEMENTATION_READINESS_REVIEWER": "review-a", "CYBERSECURITY_REVIEWER": "review-b"}
    if role not in names or type(version) is not int or version not in {1, 2, 3}:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    path = runtime_root / "review-config" / f"{names[role]}.v{version}.json"
    _regular_hash(path)
    config = json.loads(path.read_bytes())
    if (
        not isinstance(config, dict)
        or config.get("role") != role
        or config.get("schema_version") != f"review-config/v{version}"
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return cast(dict[str, object], config)


def resolve_review_run(template: dict[str, object], run_id: str) -> dict[str, object]:
    """Resolve only the frozen role's output/scratch prefixes with a canonical UUID."""
    if template.get("schema_version") != "review-config/v3":
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    parsed = uuid.UUID(run_id)
    if str(parsed) != run_id or parsed.version != 4:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    workspace = cast(str, template["workspace_root"])
    output = cast(str, template["output_root"])

    def resolve(value: Any) -> Any:
        if isinstance(value, str):
            for prefix in (workspace, output):
                if value == prefix or value.startswith(prefix + "/"):
                    return prefix + "/" + run_id + value[len(prefix) :]
        elif isinstance(value, list):
            return [resolve(item) for item in value]
        elif isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    config = cast(dict[str, object], resolve(template))
    input_root = Path(cast(str, template["scope_input_root"])) / run_id
    config.update(
        review_run_id=run_id,
        prompt_template_path=template["prompt_path"],
        prompt_path=str(input_root / "prompt.md"),
        scope_path=str(input_root / "scope.json"),
    )
    launch_path = Path(cast(str, template["authorization_path"]))
    config["authorization_path"] = str(launch_path.with_name(run_id + ".json"))
    return config


def review_config_for_authorization(
    authorization: dict[str, object],
    *,
    runtime_root: Path = RUNTIME_ROOT,
) -> dict[str, object]:
    role = cast(str, authorization["review_role"])
    if authorization.get("schema_version") != "review-launch-authorization/v2":
        return review_config_for_role(role, 1, runtime_root=runtime_root)
    label = "a" if role == "IMPLEMENTATION_READINESS_REVIEWER" else "b"
    if (runtime_root / f"review-config/review-{label}.v3.json").exists():
        template = review_config_for_role(role, 3, runtime_root=runtime_root)
        resolved = resolve_review_run(template, cast(str, authorization["review_run_id"]))
        if authorization["workspace_root"] == resolved["workspace_root"]:
            return resolved
    return review_config_for_role(role, 2, runtime_root=runtime_root)


def _scope_finding_id(role: object, scope: dict[str, Any]) -> str:
    if scope.get("kind") == "CANDIDATE_READINESS":
        suffix = {"IMPLEMENTATION_READINESS_REVIEWER": "A", "CYBERSECURITY_REVIEWER": "B"}.get(
            cast(str, role)
        )
        if suffix is not None:
            return "PART-B-CANDIDATE-" + suffix
    elif role == "CYBERSECURITY_REVIEWER" and scope.get("kind") in {
        "OPERATOR_DISCOVERY_TOOL",
        "CAPTURE_PROFILE",
        "LIVE_SECURITY",
    }:
        return "PART-B-SCOPE"
    raise ValueError("E_REVIEW_SCOPE_INPUT")


def _scope_prompt(template: bytes, record: dict[str, Any], role: object) -> bytes:
    return (
        template
        + b"\n\n## Exact review scope\n\n"
        + rfc8785.dumps(record)
        + (
            b"\n\nReview the named bytes. Include exactly one non-blocking "
            + _scope_finding_id(role, record["scope"]).encode()
            + b" finding "
            b"whose sole evidence ID is sha256: followed by the SHA-256 of the canonical scope. "
            b"Missing observations remain HOLD. Production authority is NONE.\n"
        )
    )


def _validate_scope_inputs(
    role: object,
    scope: dict[str, Any],
    contents: dict[str, bytes],
) -> None:
    """Require the complete named scope, including raw versus canonical hash semantics."""
    _scope_finding_id(role, scope)
    kind = scope["kind"]
    fields = {
        "CANDIDATE_READINESS": {"kind", "expires_at"},
        "OPERATOR_DISCOVERY_TOOL": {
            "kind",
            "expires_at",
            "source_tree_sha256",
            "capture_source_sha256",
            "config_sha256",
            "fixture_ids",
            "exact_url",
            "selectors",
            "profile_name",
            "max_duration_seconds",
            "max_http_attempts",
        },
        "CAPTURE_PROFILE": {
            "kind",
            "expires_at",
            "source_tree_sha256",
            "capture_source_sha256",
            "profile_sha256",
            "bindings",
            "sample_refs",
            "max_matches",
        },
        "LIVE_SECURITY": {
            "kind",
            "expires_at",
            "source_tree_sha256",
            "config_sha256",
            "artifacts",
            "max_matches",
            "previous_scope_refs",
        },
    }
    if set(scope) != fields[kind]:
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()}
    expected: dict[str, str] = {}
    if kind in {"OPERATOR_DISCOVERY_TOOL", "LIVE_SECURITY"}:
        matches = [name for name, digest in hashes.items() if digest == scope["config_sha256"]]
        if len(matches) != 1:
            raise ValueError("E_REVIEW_SCOPE_INPUT")
        config_name = matches[0]
        expected[config_name] = scope["config_sha256"]
        if kind == "LIVE_SECURITY":
            cfg = cast(dict[str, Any], parse_strict_json(contents[config_name]))
            refs = {
                "provider": cfg["gates"]["provider_feasibility_path"],
                "capture": cfg["gates"]["capture_review_path"],
                "profile": cfg["operator"]["capture_profile_path"],
                "platform": cfg["runtime"]["platform_qualification_path"],
                "offline": cfg["gates"]["offline_result_path"],
            }
            if set(scope["artifacts"]) != set(refs) or len(set(refs.values())) != len(refs):
                raise ValueError("E_REVIEW_SCOPE_INPUT")
            expected.update({path: scope["artifacts"][name] for name, path in refs.items()})
            for ref in scope["previous_scope_refs"].values():
                if set(ref) != {"path", "sha256"} or ref["path"] in expected:
                    raise ValueError("E_REVIEW_SCOPE_INPUT")
                expected[ref["path"]] = ref["sha256"]
    elif kind == "CAPTURE_PROFILE":
        expected.update(scope["sample_refs"])
        profiles = [
            name
            for name, raw in contents.items()
            if name not in expected
            and hashlib.sha256(rfc8785.dumps(cast(Any, parse_strict_json(raw)))).hexdigest()
            == scope["profile_sha256"]
        ]
        if len(profiles) != 1 or not expected:
            raise ValueError("E_REVIEW_SCOPE_INPUT")
        expected[profiles[0]] = hashes[profiles[0]]
    if hashes != expected:
        raise ValueError("E_REVIEW_SCOPE_INPUT")


def _scope_record(config: dict[str, object]) -> tuple[dict[str, Any], dict[str, str]]:
    path = Path(cast(str, config["scope_path"]))
    snapshots = {str(path): _regular_hash(path)}
    raw = path.read_bytes()
    if len(raw) > 65536:
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    value = parse_strict_json(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "scope", "files"}
        or value["schema_version"] != "part-b-review-inputs/v1"
        or not isinstance(value["scope"], dict)
        or not isinstance(value["files"], list)
        or len(value["files"]) > 32
    ):
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    expires = datetime.fromisoformat(str(value["scope"].get("expires_at")))
    if expires.tzinfo is None or expires <= datetime.now(UTC):
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    expected_names = {"scope.json", "prompt.md"}
    contents = {}
    for index, row in enumerate(value["files"]):
        name = f"input-{index:02d}.json"
        if (
            not isinstance(row, dict)
            or set(row) != {"name", "path", "sha256"}
            or row["name"] != name
            or not isinstance(row["path"], str)
            or not row["path"].startswith(".local/part-b/")
            or ".." in Path(row["path"]).parts
            or row["path"] in contents
        ):
            raise ValueError("E_REVIEW_SCOPE_INPUT")
        selected = path.parent / name
        if selected.stat().st_size > 1048576 or _regular_hash(selected) != row["sha256"]:
            raise ValueError("E_REVIEW_SCOPE_INPUT")
        snapshots[str(selected)] = row["sha256"]
        contents[row["path"]] = selected.read_bytes()
        expected_names.add(name)
    _validate_scope_inputs(config["role"], value["scope"], contents)
    if {item.name for item in path.parent.iterdir()} != expected_names:
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    template = Path(cast(str, config["prompt_template_path"]))
    prompt = Path(cast(str, config["prompt_path"]))
    snapshots[str(template)] = _regular_hash(template)
    snapshots[str(prompt)] = _regular_hash(prompt)
    if prompt.read_bytes() != _scope_prompt(template.read_bytes(), value, config["role"]):
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    return cast(dict[str, Any], value), snapshots


def prepare_review_scope(
    config: dict[str, object],
    scope: dict[str, Any],
    inputs: list[Path],
) -> None:
    """Copy only explicitly named non-secret local JSON; never discover credentials."""
    boundary = Path(cast(list[str], config["input_roots"])[1]) / ".local/part-b"
    if len(inputs) > 32 or len(set(inputs)) != len(inputs):
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    contents = {}
    for path in inputs:
        if (
            not path.is_relative_to(boundary)
            or path.suffix != ".json"
            or path != path.resolve(strict=True)
            or path.stat().st_size > 1048576
        ):
            raise ValueError("E_REVIEW_SCOPE_INPUT")
        before = _regular_hash(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != before:
            raise ValueError("E_REVIEW_SCOPE_INPUT")
        contents[str(path.relative_to(boundary.parents[1]))] = raw
    _validate_scope_inputs(config["role"], scope, contents)
    folder = Path(cast(str, config["scope_path"])).parent
    if folder != folder.resolve():
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = []
    for index, (source, raw) in enumerate(contents.items()):
        name = f"input-{index:02d}.json"
        with (folder / name).open("xb") as stream:
            stream.write(raw)
        rows.append({"name": name, "path": source, "sha256": hashlib.sha256(raw).hexdigest()})
    record: dict[str, Any] = {
        "schema_version": "part-b-review-inputs/v1",
        "scope": scope,
        "files": rows,
    }
    with (folder / "scope.json").open("xb") as stream:
        stream.write(rfc8785.dumps(record) + b"\n")
    template = Path(cast(str, config["prompt_template_path"]))
    _regular_hash(template)
    with (folder / "prompt.md").open("xb") as stream:
        stream.write(_scope_prompt(template.read_bytes(), record, config["role"]))
    _scope_record(config)


def validate_review_scope(config: dict[str, object], result: dict[str, Any]) -> None:
    if config.get("schema_version") != "review-config/v3":
        return
    record, _ = _scope_record(config)
    finding_id = _scope_finding_id(config["role"], record["scope"])
    findings = [row for row in result["findings"] if row["finding_id"] == finding_id]
    if len(findings) != 1 or findings[0]["evidence_ids"] != [
        "sha256:" + hashlib.sha256(rfc8785.dumps(record["scope"])).hexdigest()
    ]:
        raise ValueError("E_REVIEW_SCOPE_INPUT")


def validate_review_authority_state(
    authorization: dict[str, object],
    authority: dict[str, object],
) -> None:
    # Public trust metadata determines the state location; no signing key is read.
    path = Path(cast(str, authority["public_key_path"])).parent / "state.sqlite"
    _regular_hash(path)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        epoch = connection.execute(
            "SELECT trust_epoch FROM authority_state WHERE key_id = ?",
            (authorization["issuer_key_id"],),
        ).fetchone()
        consumed = connection.execute(
            "SELECT 1 FROM consumed_serials WHERE authority_key_id = ? AND one_use_serial = ?",
            (authorization["issuer_key_id"], authorization["one_use_serial"]),
        ).fetchone()
        revoked = connection.execute(
            "SELECT 1 FROM revocations WHERE authorization_id = ?",
            (authorization["authorization_id"],),
        ).fetchone()
    if epoch != (authorization["trust_epoch"],) or consumed is None or revoked is not None:
        raise ValueError("E_REVIEW_AUTHORITY_STATE")


def review_execution_root(authorization: dict[str, object], authority: dict[str, object]) -> Path:
    run_id = cast(str, authorization["review_run_id"])
    parsed = uuid.UUID(run_id)
    if str(parsed) != run_id or parsed.version != 4:
        raise ValueError("E_REVIEW_EXECUTION")
    public = Path(cast(str, authority["public_key_path"]))
    _regular_hash(public)
    root = public.parent / "executions" / run_id
    if root != root.resolve() or any(
        root.is_relative_to(Path(cast(str, row["source_root"])))
        for row in cast(list[dict[str, object]], authorization["input_mounts"])
    ):
        raise ValueError("E_REVIEW_EXECUTION")
    return root


def _regular_hash(path: Path) -> str:
    if (
        path.is_symlink()
        or not path.is_file()
        or stat.S_ISLNK(path.lstat().st_mode)
        or path.stat().st_nlink != 1
        or path != path.resolve(strict=True)
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review_environment_binding(metadata: dict[str, object]) -> str:
    """Reuse the qualified byte projections, never executable names or stat caches."""
    from tools.prepare_review_workspace import _dependency_projection, _sha256
    from tools.run_native_ingestor_qualification import dependency_binding
    from tools.verify_repair_evidence import capture_binding, _typescript_compile_binding

    declaration = cast(dict[str, Any], metadata["producer_environment"])
    runtime = Path(cast(list[str], metadata["input_roots"])[1])
    qualified = Path(declaration["python_environment"])
    current = capture_binding()
    executables = {}
    for name in ("uv", "pnpm", "node", "bwrap"):
        selected = shutil.which(name)
        if selected is None:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        resolved = Path(selected).resolve(strict=True)
        executables[name] = {
            "path": selected,
            "resolved": str(resolved),
            "sha256": _sha256(resolved),
        }
    paths = [
        *declaration["live_files"],
        declaration["path_translation_executable"],
        declaration["python_executable"],
        declaration["node_executable"],
    ]
    payload = {
        "environment": current["environment"],
        "compiler": _typescript_compile_binding(current),
        "executables": executables,
        "live_files": {name: _sha256(Path(name).resolve(strict=True)) for name in paths},
        "python": _dependency_projection(qualified / "lib", qualified, python=True),
        "node": _dependency_projection(runtime / "node_modules", runtime, python=False),
        "extension": _dependency_projection(
            runtime / "extension/node_modules", runtime, python=False
        ),
        "native": dependency_binding(),
    }
    return hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def recheck_review_context(context: dict[str, object]) -> None:
    for name, expected in cast(dict[str, str], context["snapshots"]).items():
        if _regular_hash(Path(name)) != expected:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
    if "pack_files" in context:
        from tools.seal_review_pack import _safe_files

        pack = Path(cast(str, context["pack"]))
        if [
            name for name, _ in _safe_files(pack, include_manifest=True, strict_directories=True)
        ] != context["pack_files"]:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
    if "inventory" in context:
        from tools.build_candidate_qualification_receipt import _inventory
        from tools.run_command_registry import collect_generated_outputs

        runtime = Path(cast(str, context["runtime"]))
        if _inventory(runtime, collect_generated_outputs(runtime)) != context["inventory"]:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
    if (
        "environment_binding" in context
        and _review_environment_binding(cast(dict[str, object], context["environment_config"]))
        != context["environment_binding"]
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    config = cast(dict[str, object], context.get("config", {}))
    if config.get("schema_version") == "review-config/v3":
        _scope_record(config)


def measure_review_context(
    config: dict[str, object], authorization: dict[str, object] | None = None
) -> dict[str, object]:
    """Bounded locator extraction, then actual sealed verification, before authority."""
    from tools.build_candidate_qualification_receipt import _read_bytes
    from tools.seal_review_pack import verify_sealed_review_pack

    try:
        if config.get("schema_version") not in {"review-config/v2", "review-config/v3"}:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        version = 3 if config["schema_version"] == "review-config/v3" else 2
        inputs = cast(list[str], config["input_roots"])
        if not isinstance(inputs, list) or len(inputs) != 5:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        pack, runtime = Path(inputs[0]), Path(inputs[1])
        if pack != pack.resolve(strict=True) or runtime != runtime.resolve(strict=True):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        manifest_path = pack / "MANIFEST_SHA256.json"
        snapshots = {str(manifest_path): _regular_hash(manifest_path)}
        manifest = json.loads(manifest_path.read_bytes())
        entries = manifest["entries"]
        if manifest.get("schema_version") != "manifest-sha256/v1" or not isinstance(entries, list):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")

        def member(path: Path) -> bytes:
            relative = path.relative_to(pack).as_posix()
            if path != path.resolve(strict=True):
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            digest = _regular_hash(path)
            raw = path.read_bytes()
            rows = [row for row in entries if isinstance(row, dict) and row.get("path") == relative]
            if rows != [{"path": relative, "size": str(len(raw)), "sha256": digest}]:
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            snapshots[str(path)] = digest
            return raw

        metadata = review_config_for_role(
            "IMPLEMENTATION_READINESS_REVIEWER", version, runtime_root=runtime
        )
        if version == 3:
            metadata = resolve_review_run(metadata, cast(str, config["review_run_id"]))
        used: dict[str, bytes] = {}
        for selected in (config, metadata):
            role = cast(str, selected["role"])
            template = review_config_for_role(role, version, runtime_root=runtime)
            expected = (
                resolve_review_run(template, cast(str, config["review_run_id"]))
                if version == 3
                else template
            )
            if selected != expected:
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            label = "a" if role == "IMPLEMENTATION_READINESS_REVIEWER" else "b"
            relative = f"docs/configs/review-{label}.v{version}.json"
            raw = member(pack / relative)
            materialized = runtime / f"review-config/review-{label}.v{version}.json"
            snapshots[str(materialized)] = _regular_hash(materialized)
            if materialized.read_bytes() != raw or json.loads(raw) != template:
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            used[relative] = raw
            registry_relative = "docs/registries/" + (
                "review-command-registry.v1.json"
                if label == "a"
                else "cybersecurity-command-registry.v1.json"
            )
            if selected["command_registry_path"] != str(pack / registry_relative):
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
            used[registry_relative] = member(pack / registry_relative)
        if any(
            config[key] != metadata[key]
            for key in ("input_roots", "input_mounts", "seal_inputs", "repository_identity")
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        registry = json.loads(used["docs/registries/review-command-registry.v1.json"])
        if (
            set(registry) != {"schema_version", "commands"}
            or registry["schema_version"] != "review-command-registry/v1"
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        rows = registry["commands"]
        if not isinstance(rows, list) or len({row["command_id"] for row in rows}) != len(rows):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        leaf = [row for row in rows if row.get("command_id") == "A_CHECK_DESCENDANT"]
        if (
            len(leaf) != 1
            or not isinstance(leaf[0].get("argv"), list)
            or len(leaf[0]["argv"]) != 21
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        recorded = leaf[0]["argv"][16]
        if recorded != str(
            runtime / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        named_config = pack / "docs/configs/full-verifier-controller.v2.json"
        named_receipt = pack / "docs/receipts/descendant-repository-qualification-receipt.json"
        retained_manifest, retained_root = (
            pack / "evidence/retained-artifact-manifest.json",
            pack / "evidence/retained",
        )
        argv = [
            "uv",
            "run",
            "--frozen",
            "--offline",
            "python",
            "tools/qualify_descendant_repository.py",
            "--root",
            str(runtime),
            "--config",
            str(named_config),
            "--check-only",
            "--receipt",
            str(named_receipt),
            "--pack",
            str(pack),
            "--recorded-config",
            recorded,
            "--retained-manifest",
            str(retained_manifest),
            "--retained-root",
            str(retained_root),
        ]
        expected_row = {
            "command_id": "A_CHECK_DESCENDANT",
            "purpose": "A_CHECK_DESCENDANT",
            "cwd": str(runtime),
            "argv": argv,
            "expected_exit": 0,
            "kind": "review-leaf",
            "available_at": "SEALED",
            "network": "DENY",
            "authenticated_operator_access": "DENY",
            "provider_access": "DENY",
        }
        if leaf != [expected_row] or config["repository_identity"] != {
            "kind": "DESCENDANT",
            "receipt": str(named_receipt),
        }:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        seal_inputs = cast(dict[str, str], config["seal_inputs"])
        if seal_inputs != {"attestation": inputs[2], "zip": inputs[3], "sidecar": inputs[4]}:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        for path in (
            named_config,
            named_receipt,
            retained_manifest,
            Path(cast(str, config["prompt_template_path" if version == 3 else "prompt_path"])),
        ):
            member(path)
        if version == 3:
            _scope, scope_snapshots = _scope_record(config)
            snapshots.update(scope_snapshots)
        for locator in inputs[2:]:
            snapshots[locator] = _regular_hash(Path(locator))
        mounts = cast(list[dict[str, object]], config["input_mounts"])
        if mounts != [
            {"source_root": value, "workspace_mount": value, "mode": "READ_ONLY"}
            for value in inputs
        ]:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        if authorization is not None and (
            authorization.get("schema_version") != "review-launch-authorization/v2"
            or authorization.get("review_role") != config["role"]
            or authorization.get("workspace_root") != config["workspace_root"]
            or authorization.get("allowed_output_root") != config["output_root"]
            or authorization.get("excluded_roots") != config["excluded_roots"]
            or authorization.get("pack_manifest_sha256") != snapshots[str(manifest_path)]
            or authorization.get("command_registry_sha256")
            != snapshots[cast(str, config["command_registry_path"])]
            or authorization.get("prompt_sha256") != snapshots[cast(str, config["prompt_path"])]
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        from tools.build_candidate_qualification_receipt import _inventory
        from tools.run_command_registry import collect_generated_outputs
        from tools.seal_review_pack import _safe_files

        pack_files = _safe_files(pack, include_manifest=True, strict_directories=True)
        snapshots.update({str(path): _regular_hash(path) for _, path in pack_files})
        inventory = _inventory(runtime, collect_generated_outputs(runtime))
        environment_binding = _review_environment_binding(metadata)
        measured: dict[str, Any] = {}
        seal = verify_sealed_review_pack(
            pack,
            Path(inputs[3]),
            Path(inputs[4]),
            Path(inputs[2]),
            config_path=named_config,
            recorded_config_locator=recorded,
            retained_manifest=retained_manifest,
            retained_root=retained_root,
            context_out=measured,
        )
        controller, artifacts = measured["controller"], measured["artifacts"]
        if (
            controller.current_checkout_root != runtime
            or controller.descendant_repository_receipt is None
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        for relative, raw in used.items():
            if raw != _read_bytes(controller.governed_source_pack / relative, artifacts):
                raise ValueError("E_REVIEW_LAUNCH_INPUT")
        if named_receipt.read_bytes() != _read_bytes(
            controller.descendant_repository_receipt, artifacts
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        identity = review_identity(seal)
        roots = [
            seal["governed_content_root"],
            identity["repository_file_tree_root_sha256"],
            *[snapshots[path] for path in inputs[2:]],
        ]
        measured_mounts = [
            {**mount, "content_root_sha256": root}
            for mount, root in zip(mounts, roots, strict=True)
        ]
        if (
            seal["schema_version"] != "external-seal-attestation/v7"
            or seal["artifact_type"] != "RUNTIME_PACK"
            or seal["zip_sha256"] != snapshots[inputs[3]]
            or seal["manifest_sha256"] != snapshots[str(manifest_path)]
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        if authorization is not None and (
            review_identity(authorization) != identity
            or authorization["input_mounts"] != measured_mounts
            or authorization["pack_zip_sha256"] != seal["zip_sha256"]
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        context: dict[str, object] = {
            "seal": seal,
            "mounts": measured_mounts,
            "snapshots": snapshots,
            "transport": expected_row,
            "controller": controller,
            "artifacts": artifacts,
            "config": config,
        }
        # All sealed members and the current inventory are checked at reuse points;
        # a caller-supplied PASS or unchanged stat metadata is never sufficient.
        context.update(
            pack=str(pack),
            pack_files=[name for name, _ in pack_files],
            runtime=str(runtime),
            inventory=inventory,
            environment_binding=environment_binding,
            environment_config=metadata,
        )
        recheck_review_context(context)
        return context
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("E_REVIEW_LAUNCH_INPUT") from error


def _directory_root(path: Path, record: str, field: str) -> str:
    if path.is_symlink() or not path.is_dir() or stat.S_ISLNK(path.lstat().st_mode):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    value = json.loads((path / record).read_text())
    root = value.get(field) if isinstance(value, dict) else None
    if not isinstance(root, str) or len(root) != 64:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return root


def _runtime_root(path: Path, receipt_path: Path) -> str:
    from tools.qualify_zero_parent_baseline import _repository_identity

    receipt = json.loads(receipt_path.read_text())
    commit, tree, root = _repository_identity(path)
    if not isinstance(receipt, dict) or (
        receipt.get("baseline_commit"),
        receipt.get("baseline_tree"),
        receipt.get("baseline_file_root_sha256"),
    ) != (commit, tree, root):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return root


def _mount_roots(config: dict[str, object]) -> list[dict[str, object]]:
    if config.get("schema_version") == "review-config/v2":
        return cast(list[dict[str, object]], measure_review_context(config)["mounts"])
    mounts = config.get("input_mounts")
    inputs = config.get("input_roots")
    if (
        not isinstance(mounts, list)
        or not isinstance(inputs, list)
        or len(mounts) != 5
        or len(inputs) != 5
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    result: list[dict[str, object]] = []
    for index, mount in enumerate(mounts):
        if not isinstance(mount, dict) or mount.get("mode") != "READ_ONLY":
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        source = mount.get("source_root")
        if (
            source != mount.get("workspace_mount")
            or source != inputs[index]
            or not isinstance(source, str)
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        path = Path(source)
        if index == 0:
            root = _directory_root(path, "GOVERNED_CONTENT_ROOT.json", "root_sha256")
        elif index == 1:
            root = _runtime_root(
                path,
                Path(cast(str, inputs[0])) / "docs/receipts/repo0-baseline-receipt.json",
            )
        else:
            root = _regular_hash(path)
        result.append({**mount, "content_root_sha256": root})
    if len({cast(str, item["source_root"]) for item in result}) != 5:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    return result


def issue_review_launch_authorization(
    config: dict[str, object],
    authority_config: dict[str, object],
    output: Path,
    *,
    now: datetime | None = None,
    scope: dict[str, Any] | None = None,
    scope_inputs: list[Path] | None = None,
) -> dict[str, object]:
    if (
        config.get("network") != "DENY"
        or config.get("role") not in {"IMPLEMENTATION_READINESS_REVIEWER", "CYBERSECURITY_REVIEWER"}
        or authority_config.get("production_authority") != "NONE"
    ):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    if config.get("schema_version") not in {
        "review-config/v1",
        "review-config/v2",
        "review-config/v3",
    }:
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    trusted_now = (now or datetime.now(UTC)).astimezone(UTC)
    run_id = str(uuid.uuid4())
    if config.get("schema_version") == "review-config/v3":
        if config != review_config_for_role(
            cast(str, config["role"]), 3, runtime_root=RUNTIME_ROOT
        ):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        if config.get("scope_input_root") != str(RUNTIME_ROOT / ".local/part-b/review-inputs"):
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        config = resolve_review_run(config, run_id)
        if output != Path(cast(str, config["authorization_path"])).parent:
            raise ValueError("E_REVIEW_LAUNCH_INPUT")
        prepare_review_scope(
            config,
            scope
            if scope is not None
            else {
                "kind": "CANDIDATE_READINESS",
                "expires_at": (trusted_now + timedelta(seconds=14400)).isoformat(),
            },
            scope_inputs or [],
        )
        output = Path(cast(str, config["authorization_path"]))
    elif scope is not None or scope_inputs:
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    current = config.get("schema_version") in {"review-config/v2", "review-config/v3"}
    context = measure_review_context(config) if current else None
    if context is not None:
        recheck_review_context(context)
    bootstrap_review_authority(authority_config, initialize_if_absent=False)
    private_path = Path(cast(str, authority_config["private_key_path"]))
    public = json.loads(Path(cast(str, authority_config["public_key_path"])).read_text())
    private = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey) or not isinstance(public, dict):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    seal_inputs = config.get("seal_inputs")
    if not isinstance(seal_inputs, dict):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    attestation_path = Path(cast(str, seal_inputs["attestation"]))
    attestation = json.loads(attestation_path.read_text())
    if not isinstance(attestation, dict):
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    mounts = (
        cast(list[dict[str, object]], context["mounts"])
        if context is not None
        else _mount_roots(config)
    )
    serial = secrets.token_hex(16)
    input_roots = cast(list[str], config["input_roots"])
    runtime_receipt = (
        {}
        if current
        else json.loads(
            (Path(input_roots[0]) / "docs/receipts/repo0-baseline-receipt.json").read_text()
        )
    )
    value: dict[str, object] = {
        "schema_version": "review-launch-authorization/v2"
        if current
        else "review-launch-authorization/v1",
        "issuer_role": "HOST_REVIEW_AUTHORITY",
        "audience": "hybrid-discovery:independent-review-launcher:v1",
        "review_role": config["role"],
        "review_run_id": run_id,
        "pack_zip_sha256": _regular_hash(Path(cast(str, seal_inputs["zip"]))),
        "pack_manifest_sha256": attestation["manifest_sha256"],
        **(
            review_identity(attestation)
            if current
            else {
                "repo0_receipt_sha256": attestation["repo0_receipt_sha256"],
                "repo0_commit_oid": runtime_receipt["baseline_commit"],
                "repo0_tree_oid": runtime_receipt["baseline_tree"],
                "repo0_file_tree_root_sha256": mounts[1]["content_root_sha256"],
            }
        ),
        "workspace_root": config["workspace_root"],
        "input_mounts": mounts,
        "excluded_roots": config["excluded_roots"],
        "allowed_output_root": config["output_root"],
        "prompt_sha256": _regular_hash(Path(cast(str, config["prompt_path"]))),
        "command_registry_sha256": _regular_hash(Path(cast(str, config["command_registry_path"]))),
        "issued_at": trusted_now.isoformat(),
        "not_before": trusted_now.isoformat(),
        "expires_at": (trusted_now + timedelta(seconds=14400)).isoformat(),
        "maximum_duration_seconds": 14400,
        "one_use_serial": serial,
        "nonce": secrets.token_urlsafe(32),
        "fresh_session_required": True,
        "production_authority": "NONE",
        "signature_algorithm": "Ed25519",
        "host_boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "trust_epoch": public["trust_epoch"],
    }
    if context is not None:
        recheck_review_context(context)
    signed = sign_review_launch_authorization(value, private)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output != output.resolve():
        raise ValueError("E_REVIEW_LAUNCH_INPUT")
    with output.open("x") as stream:
        stream.write(json.dumps(signed, sort_keys=True, separators=(",", ":")) + "\n")
    return signed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scope", type=Path)
    parser.add_argument("--scope-input", type=Path, action="append", default=[])
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    scope = parse_strict_json(args.scope.read_bytes()) if args.scope is not None else None
    if scope is not None and not isinstance(scope, dict):
        raise ValueError("E_REVIEW_SCOPE_INPUT")
    authority_path = Path(cast(str, config["authority_config"]))
    print(
        json.dumps(
            issue_review_launch_authorization(
                config,
                json.loads(authority_path.read_text()),
                args.output,
                scope=scope,
                scope_inputs=args.scope_input,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
