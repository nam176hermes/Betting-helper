import base64
import json
import socket
import subprocess
import sys
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import tools.prepare_review_workspace as review_workspace
from tests.review.test_review_aggregation_and_self_review import signed_current as signed_current
from tools.finalize_review import finalize_review, review_content_hash
from tools.prepare_review_workspace import (
    NAMESPACE_SOCKET,
    RUNTIME_ROOT,
    _environment,
    _namespace_request,
    _preparation_commands,
    _preparation_environment,
    _preparation_root,
    _start_namespace,
    _tool_mounts,
    build_bubblewrap_argv,
    prepare_review_workspace,
)


def test_pnpm_preparation_uses_host_store_and_pinned_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "store/v10"
    node = tmp_path / "node/bin/node"
    store.mkdir(parents=True)
    node.parent.mkdir(parents=True)
    node.write_text("node")
    monkeypatch.setattr(review_workspace, "HOST_PNPM_STORE", store)
    monkeypatch.setattr(review_workspace, "_node_binary", lambda: node)

    environment = _preparation_environment({"argv": ["pnpm"]}, {"PATH": "/usr/bin"})

    assert environment["npm_config_store_dir"] == str(store)
    assert environment["PATH"].startswith(f"{node.parent}:")


def test_uv_preparation_uses_host_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "uv-cache"
    cache.mkdir()
    monkeypatch.setattr(review_workspace, "HOST_UV_CACHE", cache)

    environment = _preparation_environment({"argv": ["uv"]}, {"PATH": "/usr/bin"})

    assert environment["UV_CACHE_DIR"] == str(cache)


def test_broker_environment_accepts_only_mounted_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "tools.prepare_review_workspace.shutil.which",
        lambda command: "/review-bin/uv" if command == "uv" else None,
    )

    environment = _environment({"scratch_root": str(tmp_path), "environment": {}})

    assert environment["PATH"] == "/bin:/review-bin:/usr/bin"


@pytest.mark.parametrize("leaf", ["A_CHECK_BASELINE", "A_CHECK_DESCENDANT"])
def test_baseline_check_mounts_transitive_node_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leaf: str
) -> None:
    uv = tmp_path / "uv"
    node = tmp_path / "node"
    pnpm = tmp_path / "pnpm/package/bin/pnpm"
    for path in (uv, node, pnpm):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    monkeypatch.setattr(review_workspace, "_node_binary", lambda: node)
    monkeypatch.setattr(
        "tools.prepare_review_workspace.shutil.which",
        lambda command: str(uv if command == "uv" else pnpm),
    )

    mounts, _links = _tool_mounts([{"command_id": leaf, "argv": ["uv"]}])

    assert {target.name for _source, target in mounts} == {"node", "pnpm", "uv"}


@pytest.mark.parametrize("version", [1, 2])
def test_namespace_reuses_home_created_by_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int
) -> None:
    scratch = tmp_path / "scratch"
    (scratch / "home").mkdir(parents=True)
    python = scratch / "python-env/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    socket_path = scratch / "tmp/namespace.sock"

    class Process:
        pid = 123

        def poll(self) -> None:
            return None

    monkeypatch.setattr(review_workspace, "_registered_leaf_commands", lambda *_: [])
    monkeypatch.setattr(
        review_workspace, "_prepared_python_environment", lambda _: python.parent.parent
    )
    brokers = []
    monkeypatch.setattr(
        review_workspace,
        "build_bubblewrap_argv",
        lambda _config, broker, **_kwargs: brokers.append(broker) or [],
    )
    monkeypatch.setattr(
        "tools.prepare_review_workspace.subprocess.Popen",
        lambda *_args, **_kwargs: socket_path.write_text("") or Process(),
    )
    monkeypatch.setattr(
        review_workspace,
        "_namespace_facts",
        lambda _pid: {"pid": 123, "start_ticks": "1", "namespaces": {}},
    )

    config: dict[str, Any] = {
        "scratch_root": str(scratch),
        "role": "IMPLEMENTATION_READINESS_REVIEWER",
        "schema_version": f"review-config/v{version}",
    }
    directory = tmp_path / "review-config"
    directory.mkdir()
    (directory / f"review-a.v{version}.json").write_text(json.dumps(config))
    monkeypatch.setattr(review_workspace, "RUNTIME_ROOT", tmp_path)
    launch: dict[str, Any] = {
        "schema_version": f"review-launch-authorization/v{version}",
        "authorization_id": "REVIEW-LAUNCH:" + "a" * 64,
        "command_registry_sha256": "b" * 64,
        "expires_at": "2030-01-01T00:00:00+00:00",
    }
    if version == 2:
        with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
            _start_namespace({**config, "schema_version": "review-config/v1"}, launch)
        assert not (scratch / "control").exists()
    result = _start_namespace(config, launch)

    assert result["pid"] == 123
    assert (scratch / "tmp").is_dir()
    assert str(directory / f"review-a.v{version}.json") in brokers[0]["argv"]


def test_namespace_client_uses_short_proc_fd_socket_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / ("long-" * 20)
    parent.mkdir()
    observed: list[str] = []

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def settimeout(self, _timeout: int) -> None:
            return None

        def connect(self, endpoint: str) -> None:
            observed.append(endpoint)

        def sendall(self, _payload: bytes) -> None:
            return None

        def recv(self, _size: int) -> bytes:
            return b'{"exit_code":0,"stdout":"","stderr":""}'

    monkeypatch.setattr("tools.prepare_review_workspace.socket.socket", lambda *_args: Connection())

    result = _namespace_request(parent / "namespace.sock", {})

    assert result.returncode == 0
    assert observed[0].startswith("/proc/self/fd/") and len(observed[0]) < 108


def test_authoring_tree_and_peer_review_output_are_not_mounted(tmp_path: Path) -> None:
    config: dict[str, object] = {
        "workspace_root": str(tmp_path / "review-a"),
        "output_root": str(tmp_path / "out-a"),
        "excluded_roots": [str(tmp_path / "authoring"), str(tmp_path / "out-b")],
        "input_mounts": [
            {
                "source_root": str(tmp_path / "pack"),
                "workspace_mount": str(tmp_path / "pack"),
                "mode": "READ_ONLY",
            }
        ],
        "network": "DENY",
    }
    assert prepare_review_workspace(config)["result"] == "PASS"
    changed = dict(config)
    changed["input_mounts"] = [
        {
            "source_root": str(tmp_path / "authoring"),
            "workspace_mount": str(tmp_path / "authoring"),
            "mode": "READ_ONLY",
        }
    ]
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        prepare_review_workspace(changed)


def test_review_b_preparation_uses_the_sibling_operations_registry(tmp_path: Path) -> None:
    leaf = tmp_path / "cybersecurity-command-registry.v1.json"
    leaf.write_text('{"schema_version":"cybersecurity-command-registry/v1","commands":[]}')
    operations = tmp_path / "review-command-registry.v1.json"
    operations.write_text(
        """{"schema_version":"review-command-registry/v1","commands":[
        {"command_id":"B_INSTALL_PYTHON","argv":["uv","sync","--frozen","--offline"],"cwd":"/tmp","expected_exit":0,"kind":"review-operation","network":"DENY","authenticated_operator_access":"DENY","provider_access":"DENY"},
        {"command_id":"B_INSTALL_NODE","argv":["pnpm","install","--frozen-lockfile","--offline","--ignore-scripts"],"cwd":"/tmp","expected_exit":0,"kind":"review-operation","network":"DENY","authenticated_operator_access":"DENY","provider_access":"DENY"}
        ]}"""
    )
    config: dict[str, object] = {
        "command_registry_path": str(leaf),
        "preparation_command_ids": ["B_INSTALL_PYTHON", "B_INSTALL_NODE"],
    }
    assert [row["command_id"] for row in _preparation_commands(config)] == [
        "B_INSTALL_PYTHON",
        "B_INSTALL_NODE",
    ]
    operations.unlink()
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        _preparation_commands(config)


def test_bubblewrap_mounts_only_signed_inputs_and_role_scratch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    scratch = workspace / "scratch"
    output = tmp_path / "output"
    runtime = tmp_path / "runtime"
    pack = tmp_path / "pack"
    runtime.mkdir(parents=True)
    pack.mkdir()
    scratch.mkdir(parents=True)
    output.mkdir()
    for name in ("control", "home", "tmp"):
        (scratch / name).mkdir()
    (scratch / "node-project/node_modules").mkdir(parents=True)
    (scratch / "node-project/extension/node_modules").mkdir(parents=True)
    seal = tmp_path / "seal.json"
    archive = tmp_path / "pack.zip"
    sidecar = tmp_path / "pack.zip.sha256"
    for path in (seal, archive, sidecar):
        path.write_text(path.name)
    config: dict[str, object] = {
        "environment": {"UV_OFFLINE": "1"},
        "excluded_roots": [str(tmp_path / "authoring"), str(tmp_path / "peer")],
        "input_mounts": [
            {"source_root": str(pack), "workspace_mount": str(pack), "mode": "READ_ONLY"},
            {"source_root": str(runtime), "workspace_mount": str(runtime), "mode": "READ_ONLY"},
            *[
                {"source_root": str(path), "workspace_mount": str(path), "mode": "READ_ONLY"}
                for path in (seal, archive, sidecar)
            ],
        ],
        "node_environment": {
            "dependency_mounts": [
                {
                    "source_root": str(scratch / "node-project/node_modules"),
                    "workspace_mount": str(runtime / "node_modules"),
                    "mode": "READ_ONLY",
                },
                {
                    "source_root": str(scratch / "node-project/extension/node_modules"),
                    "workspace_mount": str(runtime / "extension/node_modules"),
                    "mode": "READ_ONLY",
                },
            ]
        },
        "scratch_root": str(scratch),
        "output_root": str(output),
    }
    argv = build_bubblewrap_argv(config, {"argv": ["python", "-c", "pass"], "cwd": str(runtime)})
    assert {"--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-uts"} <= set(argv)
    assert str(tmp_path / "authoring") not in argv and str(tmp_path / "peer") not in argv
    pairs = [argv[index : index + 2] for index in range(len(argv) - 1)]
    assert "--die-with-parent" not in argv
    assert ["/bin", "/bin"] in pairs
    assert [str(scratch), str(scratch)] not in pairs
    assert [str(scratch / "tmp"), str(Path("/") / "tmp")] in pairs


def _broker_process(config: Path, endpoint: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - local test fixture executes the checked-in broker
        [
            sys.executable,
            str(RUNTIME_ROOT / "tools/prepare_review_workspace.py"),
            "--namespace-broker",
            "--config",
            str(config),
            "--authorization-id",
            "REVIEW-LAUNCH:" + "a" * 64,
            "--registry-sha256",
            sha256(
                Path(json.loads(config.read_text())["command_registry_path"]).read_bytes()
            ).hexdigest(),
            "--socket",
            str(endpoint),
            "--expires-at",
            "2030-01-01T01:00:00+00:00",
        ],
        cwd=RUNTIME_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _broker_request(endpoint: Path, request: dict[str, object]) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(endpoint))
        connection.sendall(json.dumps(request, sort_keys=True).encode())
        return connection.recv(4096)


def test_broker_reuses_one_namespace_and_rejects_client_command_injection(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    for name in ("control", "home", "tmp"):
        (scratch / name).mkdir(parents=True, exist_ok=True)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "commands": [
                    {
                        "command_id": "ONE",
                        "kind": "review-leaf",
                        "argv": ["/usr/bin/python3", "-c", "print('one')"],
                        "cwd": str(tmp_path),
                    },
                    {
                        "command_id": "TWO",
                        "kind": "review-leaf",
                        "argv": ["/usr/bin/python3", "-c", "print('two')"],
                        "cwd": str(tmp_path),
                    },
                ]
            }
        )
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "network": "DENY",
                "scratch_root": str(scratch),
                "command_registry_path": str(registry),
                "mechanical_command_ids": ["ONE", "TWO"],
                "environment": {"UV_OFFLINE": "1"},
            }
        )
    )
    endpoint = NAMESPACE_SOCKET
    endpoint.unlink(missing_ok=True)
    process = _broker_process(config, endpoint)
    for _ in range(100):
        if endpoint.exists():
            break
        time.sleep(0.01)
    stderr = process.stderr
    assert endpoint.exists(), stderr.read().decode() if stderr is not None else ""
    launch = "REVIEW-LAUNCH:" + "a" * 64
    first = json.loads(
        _broker_request(endpoint, {"authorization_id": launch, "sequence": 0, "command_id": "ONE"})
    )
    assert process.poll() is None and first["stdout"]
    second = json.loads(
        _broker_request(endpoint, {"authorization_id": launch, "sequence": 1, "command_id": "TWO"})
    )
    assert second["stdout"] and process.wait(timeout=5) == 0

    for request in (
        {"authorization_id": launch, "sequence": 0, "command_id": "TWO"},
        {"authorization_id": launch, "sequence": 0, "command_id": "ONE", "argv": ["sh"]},
    ):
        endpoint.unlink(missing_ok=True)
        process = _broker_process(config, endpoint)
        for _ in range(100):
            if endpoint.exists():
                break
            time.sleep(0.01)
        stderr = process.stderr
        assert endpoint.exists(), stderr.read().decode() if stderr is not None else ""
        assert _broker_request(endpoint, request) == b""
        assert process.wait(timeout=5) != 0


def test_finalizer_uses_jcs_hashes_for_the_bound_human_result() -> None:
    authorization: dict[str, object] = {
        "authorization_id": "REVIEW-LAUNCH:" + "a" * 64,
        "review_role": "IMPLEMENTATION_READINESS_REVIEWER",
        "review_run_id": "review-a",
        "pack_zip_sha256": "b" * 64,
        "repo0_receipt_sha256": "c" * 64,
        "workspace_root": "/workspace/a",
        "input_mounts": [
            {"content_root_sha256": sha256(f"input-{index}".encode()).hexdigest()}
            for index in range(5)
        ],
        "host_boot_id": "00000000-0000-0000-0000-000000000000",
        "trust_epoch": 0,
    }
    result: dict[str, object] = {
        "schema_version": "independent-review-result/v1",
        "review_role": "IMPLEMENTATION_READINESS_REVIEWER",
        "review_outcome": "HOLD",
        "findings": [],
        "pack_zip_sha256": authorization["pack_zip_sha256"],
        "repo0_receipt_sha256": authorization["repo0_receipt_sha256"],
        "review_run_id": authorization["review_run_id"],
        "verdicts": {
            "REPO0_BASELINE_VALID": "NO",
            "READY_TO_IMPLEMENT_DISCOVERY_PACK": "NO",
            "SAFE_TO_IMPLEMENT_R0": "NO",
            "SAFE_TO_IMPLEMENT_F0A": "NO",
            "SAFE_TO_IMPLEMENT_SEC0": "NO",
            "SAFE_TO_IMPLEMENT_E0": "NO",
            "SAFE_TO_IMPLEMENT_D0": "NO",
            "SAFE_TO_FREEZE_SCOPE0": "NO",
            "AUTHORIZED_PRODUCTION_PHASES": "NONE",
        },
        "authorized_production_phases": "NONE",
    }
    result["content_hash"] = review_content_hash(result)
    attestation: dict[str, object] = {
        "workspace_root": authorization["workspace_root"],
        "allowed_changed_paths": ["result.json"],
        "unexpected_changed_paths": [],
        "commands_executed_root": "d" * 64,
        "preparation_commands": [
            {
                "command_id": "A_INSTALL_PYTHON",
                "argv": ["uv", "sync", "--frozen", "--offline"],
                "cwd": "/runtime",
                "environment": {"HOME": "/scratch/home"},
                "exit_code": 0,
                "stdout_sha256": "e" * 64,
                "stderr_sha256": "f" * 64,
            },
            {
                "command_id": "A_INSTALL_NODE",
                "argv": [
                    "pnpm",
                    "install",
                    "--frozen-lockfile",
                    "--offline",
                    "--ignore-scripts",
                ],
                "cwd": "/scratch/node-project",
                "environment": {"HOME": "/scratch/home"},
                "exit_code": 0,
                "stdout_sha256": "0" * 64,
                "stderr_sha256": "1" * 64,
            },
        ],
        "started_at": "2030-01-01T00:00:00+00:00",
        "finished_at": "2030-01-01T00:01:00+00:00",
        "authorization_consumed_at": "2030-01-01T00:00:00+00:00",
        "fresh_session_attestation": {
            "attestation_type": "HUMAN_FRESH_CODEX_SESSION",
            "attested": True,
            "attested_by": "reviewer",
            "attested_at": "2030-01-01T00:00:00+00:00",
            "procedural_not_cryptographic": True,
        },
    }
    attestation["preparation_commands_root"] = _preparation_root(
        cast(list[dict[str, object]], attestation["preparation_commands"])
    )
    receipt = finalize_review(authorization, result, attestation, Ed25519PrivateKey.generate())
    assert receipt["result_sha256"] == sha256(rfc8785.dumps(cast(Any, result))).hexdigest()
    cast(list[dict[str, object]], attestation["preparation_commands"])[1]["argv"] = ["pnpm"]
    with pytest.raises(ValueError, match="E_REVIEW_FINALIZE_BINDING"):
        finalize_review(authorization, result, attestation, Ed25519PrivateKey.generate())


def test_current_finalizer_binds_external_seal_and_human_workspace(
    signed_current: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from moj_discovery import review_authorization as auth_library
    from tests.review.test_review_aggregation_and_self_review import IDENTITY, NOW
    from tools import finalize_review as finalizer

    monkeypatch.setattr(finalizer, "RUNTIME_ROOT", auth_library.RUNTIME_ROOT)
    launch, result = signed_current["launches"][0], signed_current["reviews"][0]
    template = signed_current["receipts"][0]
    attestation = {
        key: template[key]
        for key in (
            "workspace_root",
            "allowed_changed_paths",
            "unexpected_changed_paths",
            "commands_executed_root",
            "started_at",
            "finished_at",
            "authorization_consumed_at",
            "fresh_session_attestation",
        )
    }
    attestation["preparation_commands"] = [
        {
            "command_id": command_id,
            "argv": argv,
            "cwd": "/test-only/preparation",
            "environment": {},
            "exit_code": 0,
            "stdout_sha256": "a" * 64,
            "stderr_sha256": "b" * 64,
        }
        for command_id, argv in (
            ("A_INSTALL_PYTHON", ["uv", "sync", "--frozen", "--offline"]),
            (
                "A_INSTALL_NODE",
                ["pnpm", "install", "--frozen-lockfile", "--offline", "--ignore-scripts"],
            ),
        )
    ]
    attestation["preparation_commands_root"] = _preparation_root(
        attestation["preparation_commands"]
    )
    seal = {
        **IDENTITY,
        "schema_version": "external-seal-attestation/v7",
        "artifact_type": "RUNTIME_PACK",
        "zip_sha256": launch["pack_zip_sha256"],
        "manifest_sha256": launch["pack_manifest_sha256"],
    }
    receipt = finalize_review(
        launch, result, attestation, signed_current["private"], now=NOW, external_seal=seal
    )
    assert receipt["schema_version"] == "review-execution-receipt/v2"
    auth_library.verify_review_execution_receipt(
        receipt,
        launch,
        signed_current["private"].public_key(),
        result_sha256=receipt["result_sha256"],
        now=NOW,
    )
    for mutation in (
        "absent-seal",
        "workspace-as-seal",
        "seal-identity",
        "workspace",
        "false-human",
        "missing-human",
    ):
        changed, changed_seal = deepcopy(attestation), deepcopy(seal)
        if mutation == "absent-seal":
            changed_seal = None
        elif mutation == "workspace-as-seal":
            changed_seal = deepcopy(attestation)
        elif mutation == "seal-identity":
            changed_seal["repository_commit_oid"] = "f" * 40
        elif mutation == "workspace":
            changed["workspace_root"] = "/test-only/wrong-workspace"
        elif mutation == "false-human":
            changed["fresh_session_attestation"]["attested"] = False
        else:
            del changed["fresh_session_attestation"]
        with pytest.raises(ValueError, match="E_REVIEW_FINALIZE_BINDING"):
            finalize_review(
                launch,
                result,
                changed,
                signed_current["private"],
                now=NOW,
                external_seal=changed_seal,
            )


@pytest.mark.parametrize("execute", [False, True])
def test_current_consume_rejects_unmeasured_inputs_before_state(
    signed_current: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, execute: bool
) -> None:
    from cryptography.hazmat.primitives import serialization

    from moj_discovery.review_authorization import sign_review_launch_authorization

    private = signed_current["private"]
    public_path = tmp_path / "test-only-public.json"
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    public_path.write_text(
        json.dumps(
            {
                "public_key_b64url": base64.urlsafe_b64encode(raw).decode().rstrip("="),
                "trust_epoch": 0,
            }
        )
    )
    authority = tmp_path / "test-only-authority.json"
    authority.write_text(json.dumps({"public_key_path": str(public_path)}))
    launch = deepcopy(signed_current["launches"][0])
    now = datetime.now(UTC)
    launch.update(
        issued_at=now.isoformat(),
        not_before=now.isoformat(),
        expires_at=(now + timedelta(seconds=14400)).isoformat(),
        host_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    )
    launch = sign_review_launch_authorization(launch, private)
    config: dict[str, Any] = {
        "schema_version": "review-config/v2",
        "authority_config": str(authority),
        "role": launch["review_role"],
        "workspace_root": launch["workspace_root"],
    }

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("unmeasured current input reached serial/state/preparation")

    monkeypatch.setattr(review_workspace, "_authority_state", forbidden)
    monkeypatch.setattr(review_workspace, "prepare_review_workspace", forbidden)
    with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_INPUT"):
        review_workspace._consume(config, launch, execute=execute)


@pytest.mark.parametrize("plausible", [False, True])
@pytest.mark.parametrize("entrypoint", ["direct", "cli"])
def test_current_config_only_preparation_rejects_before_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plausible: bool, entrypoint: str
) -> None:
    from tests.release.test_descendant_repository_qualification import SOURCE_CONFIG

    config = (
        json.loads((SOURCE_CONFIG.parents[2] / "docs/configs/review-a.v2.json").read_bytes())
        if plausible
        else {
            "schema_version": "review-config/v2",
            "network": "DENY",
            "excluded_roots": [str(tmp_path / "excluded")],
            "input_mounts": [],
        }
    )
    config.update(workspace_root=str(tmp_path / "workspace"), output_root=str(tmp_path / "output"))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("unauthorized current config-only preparation reached mkdir")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        if entrypoint == "direct":
            prepare_review_workspace(config)
        else:
            monkeypatch.setattr(
                "sys.argv", ["prepare_review_workspace.py", "--config", str(config_path)]
            )
            review_workspace.main()
