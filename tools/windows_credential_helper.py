"""Windows backend helper. Never put the provider key on stdout or in argv."""

# ruff: noqa: E402
from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from moj_discovery.secrets_local import SecretValue
from moj_discovery.windows_credential_store import SLOT, aad, validate_request


def encrypt_response(request: dict[str, Any], secret: str, generation: str) -> dict[str, Any]:
    validate_request(request)
    if request["generation"] != generation:
        raise ValueError("E_CREDENTIAL_ROTATED")
    value = SecretValue(secret)
    nonce = os.urandom(12)
    raw = json.dumps(
        {"key": value.reveal_for_header(), "generation": generation}, separators=(",", ":")
    ).encode()
    encrypted = AESGCM(base64.b64decode(request["transport_key"], validate=True)).encrypt(
        nonce, raw, aad(request)
    )
    return {
        "version": 1,
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(encrypted).decode(),
    }


def native_api() -> tuple[Any, Any]:
    if sys.platform != "win32":
        raise ValueError("E_CREDENTIAL_PLATFORM")
    from ctypes import wintypes as w

    class Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", w.DWORD),
            ("Type", w.DWORD),
            ("TargetName", w.LPWSTR),
            ("Comment", w.LPWSTR),
            ("LastWritten", w.FILETIME),
            ("CredentialBlobSize", w.DWORD),
            ("CredentialBlob", ctypes.POINTER(w.BYTE)),
            ("Persist", w.DWORD),
            ("AttributeCount", w.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", w.LPWSTR),
            ("UserName", w.LPWSTR),
        ]

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredReadW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        w.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    api.CredReadW.restype = w.BOOL
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), w.DWORD]
    api.CredWriteW.restype = w.BOOL
    api.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
    api.CredDeleteW.restype = w.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    return api, Credential


@contextmanager
def credential_lock(slot: str) -> Iterator[None]:
    if sys.platform != "win32":
        raise ValueError("E_CREDENTIAL_PLATFORM")
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    kernel.CreateMutexW.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.ReleaseMutex.argtypes = [w.HANDLE]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateMutexW(None, False, "Local\\" + slot.replace("/", "."))
    if not handle:
        raise ValueError("E_CREDENTIAL_LOCK")
    owned = False
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        # An abandoned owner is recoverable: CredWrite is atomic and each blob
        # is validated in full before use. No mutable session state lives here.
        if status not in (0, 0x80):
            raise ValueError("E_CREDENTIAL_IN_USE")
        owned = True
        yield
    finally:
        if owned:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def read_credential(slot: str) -> dict[str, str] | None:
    api, credential = native_api()
    pointer = ctypes.POINTER(credential)()
    if not api.CredReadW(slot, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # type: ignore[attr-defined]
            return None
        raise ValueError("E_CREDENTIAL_READ")
    try:
        item = pointer.contents
        if item.Type != 1 or item.TargetName != slot or not 1 <= item.CredentialBlobSize <= 2560:
            raise ValueError("E_CREDENTIAL_FORMAT")
        value = json.loads(ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize))
        if (
            set(value) != {"key", "generation"}
            or str(UUID(value["generation"])) != value["generation"]
        ):
            raise ValueError("E_CREDENTIAL_FORMAT")
        SecretValue(value["key"])
        return cast(dict[str, str], value)
    finally:
        api.CredFree(pointer)


def write_credential(slot: str, secret: SecretValue) -> str:
    api, credential = native_api()
    generation = str(uuid4())  # Identity is random, never a key fingerprint.
    raw = json.dumps(
        {"key": secret.reveal_for_header(), "generation": generation}, separators=(",", ":")
    ).encode()
    if len(raw) > 2560:
        raise ValueError("E_CREDENTIAL_FORMAT")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    item = credential(
        Type=1,
        TargetName=slot,
        CredentialBlobSize=len(raw),
        CredentialBlob=blob,
        Persist=2,
        UserName="Betting-helper",
    )
    if not api.CredWriteW(ctypes.byref(item), 0):
        raise ValueError("E_CREDENTIAL_WRITE")
    return generation


def console_secret() -> SecretValue:
    if sys.platform != "win32" or not sys.stdin.isatty():
        raise ValueError("E_CREDENTIAL_NO_CONSOLE")
    import msvcrt
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleMode.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.SetConsoleMode.argtypes = [w.HANDLE, w.DWORD]
    kernel.FlushConsoleInputBuffer.argtypes = [w.HANDLE]
    kernel.FlushConsoleInputBuffer.restype = w.BOOL
    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    original = w.DWORD()
    if not kernel.GetConsoleMode(handle, ctypes.byref(original)) or not kernel.SetConsoleMode(
        handle, original.value & ~0x4
    ):
        raise ValueError("E_CREDENTIAL_NO_CONSOLE")
    verified = w.DWORD()
    try:
        if not kernel.GetConsoleMode(handle, ctypes.byref(verified)) or verified.value & 0x4:
            raise ValueError("E_CREDENTIAL_NO_CONSOLE")
        sys.stdout.write("API_FOOTBALL_KEY (ẩn, chỉ nhập trong terminal này): ")
        sys.stdout.flush()
        chars: list[str] = []
        while True:
            c = msvcrt.getwch()  # Native no-echo console read, never input().
            if c == "\r":
                break
            if c in {"\x03", "\x1a", "\x00", "\xe0"}:
                raise ValueError("E_CREDENTIAL_CANCELLED")
            if c == "\b":
                chars = chars[:-1]
            elif len(chars) < 512:
                chars.append(c)
            else:
                raise ValueError("E_CREDENTIAL_FORMAT")
        sys.stdout.write("\n")
        return SecretValue("".join(chars))
    finally:
        # A cancelled/oversized paste must not reach the next echo-enabled prompt.
        if not kernel.FlushConsoleInputBuffer(handle):
            raise ValueError("E_CREDENTIAL_CONSOLE_CLEANUP")
        if not kernel.SetConsoleMode(handle, original.value):
            raise ValueError("E_CREDENTIAL_CONSOLE_CLEANUP")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in {
        "--serve",
        "--metadata",
        "--enroll",
        "--delete",
        "--self-test",
    }:
        return 2
    try:
        if args == ["--self-test"]:
            slot = "Betting-helper/TEST_ONLY/" + str(uuid4())
            with credential_lock(slot):
                if read_credential(slot) is not None:
                    raise ValueError("E_CREDENTIAL_TEST_COLLISION")
                try:
                    generation = write_credential(slot, SecretValue("TEST_ONLY_NATIVE_CHECK"))
                    value = read_credential(slot)
                    if value != {"key": "TEST_ONLY_NATIVE_CHECK", "generation": generation}:
                        raise ValueError("E_CREDENTIAL_TEST")
                finally:
                    api, _ = native_api()
                    if not api.CredDeleteW(slot, 1, 0):
                        raise ValueError("E_CREDENTIAL_TEST_CLEANUP")
                if read_credential(slot) is not None:
                    raise ValueError("E_CREDENTIAL_TEST_CLEANUP")
            print('{"result":"PASS","data":"TEST_ONLY","primary_slot_accessed":false}')
            return 0
        with credential_lock(SLOT):
            if args == ["--enroll"]:
                generation = write_credential(SLOT, console_secret())
                print(json.dumps({"state": "STORED", "generation": generation}))
            elif args == ["--delete"]:
                if not sys.stdin.isatty():
                    raise ValueError("E_CREDENTIAL_NO_CONSOLE")
                print("Gõ DELETE API KEY để xóa key đã lưu:", flush=True)
                if sys.stdin.readline(32).rstrip("\r\n") != "DELETE API KEY":
                    raise ValueError("E_CREDENTIAL_CANCELLED")
                api, _ = native_api()
                if not api.CredDeleteW(SLOT, 1, 0) and ctypes.get_last_error() != 1168:  # type: ignore[attr-defined]
                    raise ValueError("E_CREDENTIAL_DELETE")
                print('{"state":"ABSENT"}')
            elif args == ["--metadata"]:
                value = read_credential(SLOT)
                print(
                    json.dumps(
                        {
                            "state": "STORED" if value else "ABSENT",
                            "generation": value["generation"] if value else None,
                        }
                    )
                )
            else:
                request = json.loads(sys.stdin.buffer.readline(8193))
                validate_request(request)
                value = read_credential(SLOT)
                if value is None:
                    raise ValueError("E_CREDENTIAL_ABSENT")
                print(
                    json.dumps(encrypt_response(request, value["key"], value["generation"])),
                    flush=True,
                )
                sys.stdin.buffer.read(1)  # Private parent EOF releases the lease.
        return 0
    except (Exception, KeyboardInterrupt) as error:
        if args == ["--metadata"] and str(error) == "E_CREDENTIAL_IN_USE":
            print('{"state":"IN_USE","generation":null}', flush=True)
            return 2
        print('{"error":"E_CREDENTIAL_UNAVAILABLE"}', flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
