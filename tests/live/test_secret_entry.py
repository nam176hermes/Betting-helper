import contextlib
import getpass
import io
import os
import pty
import select
import time
import warnings
from typing import Any

import pytest

from moj_discovery import secrets_local
from moj_discovery.secrets_local import SecretValue, obtain_api_football_key
from tools import run_with_api_football_key as launcher


@pytest.mark.parametrize("value", ["", "  ", "x\ny", "x\ry", "x\x00y", "x\x7fy", "x" * 513])
def test_invalid_secret(value: Any) -> None:
    with pytest.raises(ValueError, match="E_SECRET"):
        SecretValue(value)


def test_secret_shape_is_not_guessed() -> None:
    assert SecretValue("TEST_ONLY_not-32-hex").reveal_for_header() == "TEST_ONLY_not-32-hex"


def test_getpass_noecho_and_prompt_wins(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        secrets_local, "controlling_tty", lambda: contextlib.nullcontext(io.StringIO())
    )
    monkeypatch.setenv("API_FOOTBALL_KEY", "TEST_ONLY_ENVIRONMENT")
    monkeypatch.setattr(getpass, "getpass", lambda *a, **k: "TEST_ONLY_PROMPT")
    assert obtain_api_football_key(True).reveal_for_header() == "TEST_ONLY_PROMPT"
    assert obtain_api_football_key(False).reveal_for_header() == "TEST_ONLY_ENVIRONMENT"


def test_no_tty_prevents_secret_read(monkeypatch: Any) -> None:
    def deny() -> Any:
        raise ValueError("E_SECRET_NO_TTY")

    monkeypatch.setattr(secrets_local, "controlling_tty", deny)
    monkeypatch.setattr(getpass, "getpass", lambda *a, **k: pytest.fail("read attempted"))
    for interactive in [True, False]:
        with pytest.raises(ValueError, match="E_SECRET"):
            obtain_api_football_key(interactive)


def test_getpass_warning_never_falls_back(monkeypatch: Any) -> None:
    def warning(*args: Any, **kwargs: Any) -> Any:
        warnings.warn("TEST_ONLY_NO_ECHO", getpass.GetPassWarning, stacklevel=1)
        pytest.fail("echo fallback continued")

    monkeypatch.setattr(
        secrets_local, "controlling_tty", lambda: contextlib.nullcontext(io.StringIO())
    )
    monkeypatch.setattr(getpass, "getpass", warning)
    with pytest.raises(ValueError, match="E_SECRET_NO_ECHO"):
        obtain_api_football_key(True)


def test_launcher_missing_owner_does_not_read_key(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(launcher, "obtain_api_football_key", lambda *a: pytest.fail("key read"))
    assert (
        launcher.main(
            [
                "--action",
                "probe",
                "--config",
                "config/live-batched.example.json",
                "--intent",
                ".local/part-b/absent-intent.json",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert "KEY_CHECK: NOT_CHECKED" in output
    assert "REQUEST_ATTEMPTS: 0" in output


def test_declined_confirmation_zero_requests(monkeypatch: Any, capsys: Any) -> None:
    calls = []
    intent = type(
        "SyntheticIntent",
        (),
        {
            "public": {
                "fixture_ids": [101],
                "max_duration_seconds": 300,
                "max_http_attempts": 20,
                "stage": "PROVIDER_PROBE",
            }
        },
    )()
    monkeypatch.setattr(
        launcher,
        "_load_action",
        lambda *a: (intent, lambda *a: calls.append("consume"), lambda *a: calls.append("http")),
    )
    monkeypatch.setattr(
        launcher, "controlling_tty", lambda: contextlib.nullcontext(io.StringIO("NO\n"))
    )
    monkeypatch.setattr(launcher, "obtain_api_football_key", lambda *a: pytest.fail("key read"))
    assert (
        launcher.main(
            [
                "--action",
                "probe",
                "--config",
                "config/live-batched.example.json",
                "--intent",
                ".local/part-b/absent-intent.json",
            ]
        )
        == 2
    )
    assert calls == []
    assert "REQUEST_ATTEMPTS: 0" in capsys.readouterr().out


def test_real_pseudoterminal_noecho() -> None:
    """Real Linux terminal discipline, synthetic credential, no HTTP implementation."""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            secret = obtain_api_football_key(True)
            assert secret.reveal_for_header() == "TEST_ONLY_PTY_SECRET"
            os.write(1, b"KEY_LOCAL_TEST: OK [REDACTED]\n")
            os._exit(0)
        except BaseException:
            os._exit(2)
    output = b""
    sent = False
    reaped = False
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                output += chunk
                if b"(hidden): " in output and not sent:
                    os.write(fd, b"TEST_ONLY_PTY_SECRET\n")
                    sent = True
            found, status = os.waitpid(pid, os.WNOHANG)
            if found:
                reaped = True
                assert os.waitstatus_to_exitcode(status) == 0
                break
        assert sent and b"KEY_LOCAL_TEST: OK" in output
        assert b"TEST_ONLY_PTY_SECRET" not in output
    finally:
        os.close(fd)
        if not reaped:
            found, status = os.waitpid(pid, os.WNOHANG)
            if not found:
                import signal

                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)


@pytest.mark.parametrize("vault_fails", [False, True])
def test_stored_key_is_read_only_after_consumption_without_fallback(
    monkeypatch: Any,
    capsys: Any,
    vault_fails: bool,
) -> None:
    from types import SimpleNamespace

    from moj_discovery import windows_credential_store

    calls = []
    config = SimpleNamespace(
        sha256="a" * 64,
        public={
            "credentials": {"generation": "TEST_ONLY_GENERATION", "native_python_sha256": "b" * 64}
        },
    )
    intent = SimpleNamespace(
        sha256="c" * 64,
        public={
            "fixture_ids": [101],
            "max_duration_seconds": 300,
            "max_http_attempts": 20,
            "source_tree_sha256": "d" * 64,
        },
    )

    def consume(*args: Any) -> Any:
        calls.append("consume")
        return SimpleNamespace(run_id="TEST_ONLY_RUN")

    @contextlib.contextmanager
    def key(*args: Any, **kwargs: Any) -> Any:
        calls.append("key")
        assert "API_FOOTBALL_KEY" not in os.environ
        if vault_fails:
            raise ValueError("E_CREDENTIAL_ROTATED")
        yield SecretValue("TEST_ONLY_VAULT")

    def dispatch(*args: Any) -> Any:
        calls.append("dispatch")
        return {
            "KEY_CHECK": "AUTHENTICATED",
            "SUBSCRIPTION_CHECK": "CONFIRMED",
            "PROBE_RESULT": "PASS",
            "REQUEST_ATTEMPTS": 4,
            "MISSING_CAPABILITIES": [],
            "PROVIDER_DIAGNOSTIC": "NONE",
        }

    monkeypatch.setattr(launcher, "load_live_config", lambda *a, **k: config)
    monkeypatch.setattr(launcher, "_load_action", lambda *a: (intent, consume, dispatch))
    monkeypatch.setattr(
        launcher,
        "controlling_tty",
        lambda: contextlib.nullcontext(io.StringIO("ALLOW PROVIDER PROBE\n")),
    )
    monkeypatch.setattr(windows_credential_store, "stored_key", key)
    monkeypatch.setattr(
        launcher, "obtain_api_football_key", lambda *a, **k: pytest.fail("fallback")
    )
    monkeypatch.setenv("API_FOOTBALL_KEY", "TEST_ONLY_ENV_MUST_NOT_PROPAGATE")
    exit_code = launcher.main(
        ["--action", "probe", "--config", "TEST_ONLY.json", "--intent", "TEST_ONLY.json"]
    )
    assert exit_code == (2 if vault_fails else 0)
    assert calls == (["consume", "key"] if vault_fails else ["consume", "key", "dispatch"])
    output = capsys.readouterr().out
    assert "TEST_ONLY_VAULT" not in output and "TEST_ONLY_ENV_MUST_NOT_PROPAGATE" not in output
