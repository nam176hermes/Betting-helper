"""Private-pipe access to this application's Windows credential only."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .secrets_local import SecretValue

ROOT = Path(__file__).resolve().parents[2]
SLOT = "Betting-helper/api-football-primary"
NATIVE_PYTHON = Path(
    "/mnt/c/Users/thenam/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
)


def aad(request: dict[str, Any]) -> bytes:
    return json.dumps(
        {k: v for k, v in request.items() if k != "transport_key"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def validate_request(request: dict[str, Any]) -> None:
    try:
        if (
            set(request)
            != {
                "version",
                "slot",
                "action",
                "config_sha256",
                "source_sha256",
                "intent_sha256",
                "generation",
                "run_id",
                "transport_key",
            }
            or type(request["version"]) is not int
            or request["version"] != 1
            or request["slot"] != SLOT
            or request["action"] not in {"probe", "live-readonly"}
            or any(
                not isinstance(request[k], str) or re.fullmatch("[0-9a-f]{64}", request[k]) is None
                for k in ("config_sha256", "source_sha256", "intent_sha256")
            )
            or any(str(UUID(request[k])) != request[k] for k in ("generation", "run_id"))
            or len(base64.b64decode(request["transport_key"], validate=True)) != 32
        ):
            raise ValueError("E_CREDENTIAL_REQUEST")
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("E_CREDENTIAL_REQUEST") from None


def new_request(
    action: str,
    config_hash: str,
    source_hash: str,
    generation: str,
    *,
    run_id: str,
    intent_hash: str,
) -> tuple[dict[str, Any], bytes]:
    key = os.urandom(32)
    request = {
        "version": 1,
        "slot": SLOT,
        "action": action,
        "config_sha256": config_hash,
        "source_sha256": source_hash,
        "generation": generation,
        "run_id": run_id,
        "intent_sha256": intent_hash,
        "transport_key": base64.b64encode(key).decode(),
    }
    validate_request(request)
    return request, key


def decrypt_response(request: dict[str, Any], key: bytes, response: dict[str, Any]) -> SecretValue:
    try:
        validate_request(request)
        if (
            set(response) != {"version", "nonce", "ciphertext"}
            or type(response["version"]) is not int
            or response["version"] != 1
        ):
            raise ValueError()
        nonce = base64.b64decode(response["nonce"], validate=True)
        if len(nonce) != 12:
            raise ValueError()
        raw = AESGCM(key).decrypt(
            nonce, base64.b64decode(response["ciphertext"], validate=True), aad(request)
        )
        value = json.loads(raw)
        if set(value) != {"key", "generation"} or value["generation"] != request["generation"]:
            raise ValueError()
        return SecretValue(value["key"])
    except Exception:
        raise ValueError("E_CREDENTIAL_RESPONSE") from None


def helper_command(action: str, *, native_python_sha256: str) -> list[str]:
    if action not in {"serve", "metadata", "enroll", "delete", "self-test"}:
        raise ValueError("E_CREDENTIAL_ACTION")
    helper = ROOT / "tools/windows_credential_helper.py"
    if helper.resolve() != helper or helper.stat().st_nlink != 1 or not NATIVE_PYTHON.is_file():
        raise ValueError("E_CREDENTIAL_PLATFORM")
    if (
        re.fullmatch("[0-9a-f]{64}", native_python_sha256) is None
        or hashlib.sha256(NATIVE_PYTHON.read_bytes()).hexdigest() != native_python_sha256
    ):
        raise ValueError("E_CREDENTIAL_INTERPRETER")
    # The helper must be the committed candidate, never an arbitrary program.
    git = shutil.which("git")
    if git is None:
        raise ValueError("E_CREDENTIAL_SOURCE")
    frozen = subprocess.run(  # noqa: S603 -- resolved Git, fixed read-only path.
        [git, "-C", str(ROOT), "show", "HEAD:tools/windows_credential_helper.py"],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if frozen.returncode != 0 or frozen.stdout != helper.read_bytes():
        raise ValueError("E_CREDENTIAL_SOURCE")
    path = subprocess.run(  # noqa: S603 -- fixed local path translation, no secret arguments.
        ["/usr/bin/wslpath", "-w", str(helper)], capture_output=True, timeout=5, check=False
    )
    if path.returncode != 0:
        raise ValueError("E_CREDENTIAL_PLATFORM")
    return [str(NATIVE_PYTHON), "-I", "-B", path.stdout.decode().strip(), "--" + action]


@contextmanager
def stored_key(
    action: str,
    config_hash: str,
    source_hash: str,
    generation: str,
    *,
    run_id: str,
    intent_hash: str,
    native_python_sha256: str,
) -> Iterator[SecretValue]:
    request, key = new_request(
        action, config_hash, source_hash, generation, run_id=run_id, intent_hash=intent_hash
    )
    process = subprocess.Popen(  # noqa: S603 -- fixed committed helper, private pipes.
        helper_command("serve", native_python_sha256=native_python_sha256),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={},
        close_fds=True,
    )  # noqa: S603 -- fixed committed helper, secret only in private pipes.
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        process.stdin.flush()
        response = bytearray()
        deadline = time.monotonic() + 15
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while b"\n" not in response:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("E_CREDENTIAL_TIMEOUT")
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk or len(response) + len(chunk) > 8192:
                    raise ValueError("E_CREDENTIAL_RESPONSE")
                response.extend(chunk)
        if response.count(b"\n") != 1 or not response.endswith(b"\n"):
            raise ValueError("E_CREDENTIAL_RESPONSE")
        secret = decrypt_response(request, key, json.loads(response))
        # The helper keeps the native mutex until this context closes. Rotation
        # cannot race a provider session which is using the stored credential.
        yield SecretValue(secret.reveal_for_header(), usable=lambda: process.poll() is None)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()  # Only this owned child; never an image-name/PID search.
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
