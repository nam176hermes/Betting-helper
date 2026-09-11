from __future__ import annotations

import base64
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

if __name__ != "__main__":
    import pytest


def test_transport_is_authenticated_bound_and_never_echoes_plaintext() -> None:
    from moj_discovery.windows_credential_store import decrypt_response, new_request
    from tools.windows_credential_helper import encrypt_response

    secret = "TEST_ONLY_CREDENTIAL_VALUE"  # noqa: S105 -- synthetic nonleakage sentinel.
    generation = str(uuid4())
    request, transport_key = new_request(
        "probe", "a" * 64, "b" * 64, generation, run_id=str(uuid4()), intent_hash="c" * 64
    )
    assert secret not in json.dumps(request)
    response = encrypt_response(request, secret, generation)
    assert secret not in json.dumps(response)
    value = decrypt_response(request, transport_key, response)
    assert value.reveal_for_header() == secret and str(value) == "[REDACTED]"
    changed = {**request, "run_id": str(uuid4())}
    with pytest.raises(ValueError, match="E_CREDENTIAL"):
        decrypt_response(changed, transport_key, response)
    response["ciphertext"] = base64.b64encode(b"tampered").decode()
    with pytest.raises(ValueError, match="E_CREDENTIAL"):
        decrypt_response(request, transport_key, response)


def test_generation_mismatch_and_wrong_request_fail_closed() -> None:
    from moj_discovery.windows_credential_store import new_request
    from tools.windows_credential_helper import encrypt_response

    request, _ = new_request(
        "probe", "a" * 64, "b" * 64, str(uuid4()), run_id=str(uuid4()), intent_hash="c" * 64
    )
    with pytest.raises(ValueError, match="E_CREDENTIAL"):
        encrypt_response(request, "TEST_ONLY", str(uuid4()))
    for action in ("GET_URL", "live", "", "enroll"):
        with pytest.raises(ValueError, match="E_CREDENTIAL"):
            new_request(
                action, "a" * 64, "b" * 64, str(uuid4()), run_id=str(uuid4()), intent_hash="c" * 64
            )


def test_windows_enrollment_without_console_has_no_prompt_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.windows_credential_helper import console_secret

    if os.name != "nt":
        with pytest.raises(ValueError, match="E_CREDENTIAL_NO_CONSOLE"):
            console_secret()


def test_helper_exit_revokes_secret_before_another_provider_attempt(
    tmp_path: Path,
    fake_clock: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    from moj_discovery import windows_credential_store as store
    from moj_discovery.providers.api_football import ProviderError
    from tests.live.test_api_football import make_client

    helper = tmp_path / "TEST_ONLY_helper.py"
    helper.write_text(
        "import json,sys\n"
        "sys.path[:0]=[sys.argv[1],sys.argv[1]+'/src']\n"
        "from tools.windows_credential_helper import encrypt_response\n"
        "r=json.loads(sys.stdin.readline())\n"
        "print(json.dumps(encrypt_response(r,'TEST_ONLY',r['generation'])),flush=True)\n"
    )
    monkeypatch.setattr(
        store,
        "helper_command",
        lambda *args, **kwargs: [sys.executable, "-B", str(helper), str(store.ROOT)],
    )
    with store.stored_key(
        "probe",
        "a" * 64,
        "b" * 64,
        str(uuid4()),
        run_id=str(uuid4()),
        intent_hash="c" * 64,
        native_python_sha256="d" * 64,
    ) as secret:
        for _ in range(100):
            try:
                secret.check_usable()
            except ValueError:
                break
            time.sleep(0.01)
        else:
            pytest.fail("exited helper still trusted")
        with pytest.raises(ValueError, match="E_SECRET_LEASE_LOST"):
            secret.reveal_for_header()
        client, quota, http = make_client(tmp_path, fake_clock, [])
        client._secret = secret
        with quota, client, pytest.raises(ProviderError, match="AUTH_FAILED"):
            client.get_status()
        assert http.calls == []


def test_native_console_flushes_pending_input_before_restoring_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes
    import io
    from types import SimpleNamespace

    from tools import windows_credential_helper as helper

    events: list[str] = []
    mode = 7

    class Function:
        def __init__(self, call: Any) -> None:
            self.call = call

        def __call__(self, *args: Any) -> Any:
            return self.call(*args)

    def get_mode(handle: Any, pointer: Any) -> bool:
        pointer._obj.value = mode
        return True

    def set_mode(handle: Any, value: int) -> bool:
        nonlocal mode
        events.append("echo_on" if value & 4 else "echo_off")
        mode = value
        return True

    def flush(handle: Any) -> bool:
        events.append("flush")
        return True

    kernel = SimpleNamespace(
        GetConsoleMode=Function(get_mode),
        SetConsoleMode=Function(set_mode),
        FlushConsoleInputBuffer=Function(flush),
    )
    terminal = io.StringIO()
    monkeypatch.setattr(terminal, "isatty", lambda: True)
    monkeypatch.setattr(terminal, "fileno", lambda: 0)
    monkeypatch.setattr(sys, "stdin", terminal)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    for data in ("TEST_ONLY" + "x" * 520 + "\r", "TEST_ONLY\x03PENDING_TAIL\r", "TEST_ONLY\r"):
        chars = iter(data)
        monkeypatch.setitem(
            sys.modules,
            "msvcrt",
            SimpleNamespace(get_osfhandle=lambda fd: fd, getwch=lambda chars=chars: next(chars)),
        )
        events.clear()
        with suppress(ValueError):
            helper.console_secret()
        assert events == ["echo_off", "flush", "echo_on"]


def native_console_check() -> None:
    """Real isolated Windows console, synthetic input only; never the primary slot."""
    if sys.platform != "win32":
        raise ValueError("TEST_ONLY_NATIVE_WINDOWS_REQUIRED")
    import ctypes
    import msvcrt
    import threading
    import time
    from ctypes import wintypes as w

    from tools.windows_credential_helper import console_secret

    class Key(ctypes.Structure):
        _fields_ = [
            ("down", w.BOOL),
            ("repeat", w.WORD),
            ("code", w.WORD),
            ("scan", w.WORD),
            ("char", w.WCHAR),
            ("state", w.DWORD),
        ]

    class Event(ctypes.Structure):
        _fields_ = [("kind", w.WORD), ("key", Key)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [w.DWORD]
    kernel.GetStdHandle.restype = w.HANDLE
    kernel.GetConsoleMode.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.WriteConsoleInputW.argtypes = [
        w.HANDLE,
        ctypes.POINTER(Event),
        w.DWORD,
        ctypes.POINTER(w.DWORD),
    ]
    kernel.GetNumberOfConsoleInputEvents.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.FreeConsole()  # Detach this test process only, then allocate its own console.
    assert kernel.AllocConsole(), "TEST_ONLY console allocation failed"
    sys.stdout.reconfigure(encoding="utf-8")
    before = sys.stdin
    try:
        with open("CONIN$", encoding="utf-8") as terminal:
            sys.stdin = terminal
            handle = msvcrt.get_osfhandle(terminal.fileno())
            for data, rejected in (
                ("TEST_ONLY\r", False),
                ("TEST_ONLY" + "x" * 600 + "\r", True),
                ("TEST_ONLY\x03PENDING_TAIL\r", True),
            ):
                checked: list[bool] = []

                def inject(data: str = data, checked: list[bool] = checked) -> None:
                    mode = w.DWORD()
                    end = time.monotonic() + 5
                    while time.monotonic() < end:
                        assert kernel.GetConsoleMode(handle, ctypes.byref(mode))
                        if not mode.value & 4:
                            records = (Event * len(data))(
                                *(Event(1, Key(True, 1, 0, 0, char, 0)) for char in data)
                            )
                            written = w.DWORD()
                            assert kernel.WriteConsoleInputW(
                                handle, records, len(data), ctypes.byref(written)
                            )
                            checked.append(written.value == len(data))
                            return
                        time.sleep(0.01)
                    checked.append(False)

                worker = threading.Thread(target=inject, daemon=True)
                worker.start()
                try:
                    result = console_secret()
                    assert not rejected and result.reveal_for_header() == "TEST_ONLY"
                except ValueError:
                    assert rejected
                worker.join(6)
                count = w.DWORD()
                assert kernel.GetNumberOfConsoleInputEvents(handle, ctypes.byref(count))
                assert checked == [True] and count.value == 0
    finally:
        sys.stdin = before
        kernel.FreeConsole()
    print("NATIVE_CONSOLE_TEST_ONLY: PASS; PRIMARY_SLOT_ACCESSED: false")


def native_lock_check() -> None:
    import subprocess

    from tools.windows_credential_helper import credential_lock

    slot = "Betting-helper/TEST_ONLY/" + str(uuid4())
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--lock-child", slot]
    with credential_lock(slot):
        denied = subprocess.run(command, capture_output=True, env={}, timeout=10, check=False)  # noqa: S603 -- owned TEST_ONLY child.
        assert denied.returncode == 2 and denied.stdout.strip() == b"TEST_ONLY_IN_USE"
    for crash in (False, True):
        child = subprocess.Popen(  # noqa: S603 -- owned TEST_ONLY child.
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={}
        )  # noqa: S603 -- owned TEST_ONLY child.
        try:
            assert child.stdout is not None and child.stdin is not None
            assert child.stdout.readline().strip() == b"TEST_ONLY_LOCKED"
            try:
                with credential_lock(slot):
                    raise AssertionError("concurrent owner admitted")
            except ValueError as error:
                assert str(error) == "E_CREDENTIAL_IN_USE"
            if crash:
                child.kill()
            child.stdin.close()
            child.wait(timeout=10)
            with credential_lock(slot):
                pass
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            if child.stdout is not None:
                child.stdout.close()
            if child.stderr is not None:
                child.stderr.close()
    print("NATIVE_MUTEX_TEST_ONLY: PASS; EOF_AND_CRASH_RELEASE: PASS")


if __name__ == "__main__":
    sys.path[:0] = [
        str(Path(__file__).resolve().parents[2]),
        str(Path(__file__).resolve().parents[2] / "src"),
    ]
    if len(sys.argv) == 3 and sys.argv[1] == "--lock-child":
        from tools.windows_credential_helper import credential_lock

        assert sys.argv[2].startswith("Betting-helper/TEST_ONLY/")
        try:
            with credential_lock(sys.argv[2]):
                print("TEST_ONLY_LOCKED", flush=True)
                sys.stdin.buffer.read(1)
        except ValueError:
            print("TEST_ONLY_IN_USE", flush=True)
            raise SystemExit(2) from None
    else:
        native_console_check()
        native_lock_check()
