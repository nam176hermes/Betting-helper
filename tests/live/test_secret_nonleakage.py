import copy
import hashlib
import json
import pickle
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import pytest

from moj_discovery.secrets_local import SecretValue
from tools import run_with_api_football_key as launcher

TEST_SECRET = "TEST_ONLY_secret+/%_never_real"  # noqa: S105 -- synthetic leak sentinel


def test_repr_and_serialization_are_closed(capsys: Any) -> None:
    secret = SecretValue(TEST_SECRET)
    assert repr(secret) == str(secret) == format(secret) == "[REDACTED]"
    serializers: list[Callable[[Any], Any]] = [
        json.dumps,
        pickle.dumps,
        copy.copy,
        copy.deepcopy,
        hash,
    ]
    for serialize in serializers:
        with pytest.raises(TypeError) as caught:
            serialize(secret)
        print(caught.value)
    print(secret, repr(secret), f"{secret}")
    text = capsys.readouterr().out
    assert TEST_SECRET not in text
    assert quote(TEST_SECRET, safe="") not in text
    assert hashlib.sha256(TEST_SECRET.encode()).hexdigest() not in text


def test_invalid_argv_never_echoes_a_secret(capsys: Any) -> None:
    assert launcher.main(["--api-key", TEST_SECRET]) == 2
    output = capsys.readouterr()
    assert TEST_SECRET not in output.out + output.err
    assert "REQUEST_ATTEMPTS: 0" in output.out


def test_key_removed_from_child_environment_before_dispatch(monkeypatch: Any, capsys: Any) -> None:
    import contextlib
    import io
    import os

    intent = type(
        "SyntheticIntent",
        (),
        {"public": {"fixture_ids": [101], "max_duration_seconds": 300, "max_http_attempts": 20}},
    )()

    def dispatch(config: Any, secret: Any, receipt: Any) -> Any:
        assert os.environ.get("API_FOOTBALL_KEY") is None
        assert secret.reveal_for_header() == TEST_SECRET
        return {
            "KEY_CHECK": "NOT_CHECKED",
            "SUBSCRIPTION_CHECK": "UNKNOWN",
            "PROBE_RESULT": "PARTIAL",
            "REQUEST_ATTEMPTS": 0,
            "MISSING_CAPABILITIES": ["REVIEW_REQUIRED"],
        }

    monkeypatch.setenv("API_FOOTBALL_KEY", "TEST_ONLY_ENVIRONMENT")
    monkeypatch.setattr(
        launcher, "_load_action", lambda *a: (intent, lambda *a: object(), dispatch)
    )
    monkeypatch.setattr(
        launcher,
        "controlling_tty",
        lambda: contextlib.nullcontext(io.StringIO("ALLOW PROVIDER PROBE\n")),
    )
    monkeypatch.setattr(
        launcher, "obtain_api_football_key", lambda *a, **k: SecretValue(TEST_SECRET)
    )
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
    output = capsys.readouterr()
    assert TEST_SECRET not in output.out + output.err


def test_dispatch_error_is_finite(monkeypatch: Any, capsys: Any) -> None:
    import contextlib
    import io

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

    def explode(*args: Any) -> Any:
        raise ValueError(TEST_SECRET)

    monkeypatch.setattr(launcher, "_load_action", lambda *a: (intent, lambda *a: object(), explode))
    monkeypatch.setattr(
        launcher,
        "controlling_tty",
        lambda: contextlib.nullcontext(io.StringIO("ALLOW PROVIDER PROBE\n")),
    )
    monkeypatch.setattr(
        launcher, "obtain_api_football_key", lambda *a, **k: SecretValue(TEST_SECRET)
    )
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
    output = capsys.readouterr()
    assert TEST_SECRET not in output.out + output.err
    assert "REQUEST_ATTEMPTS: UNKNOWN" in output.out
