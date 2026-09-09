import io
import json
import ssl
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request

import pytest
from test_api_football import STATUS, Reply, make_client

from moj_discovery.errors import ContractNotImplementedError
from moj_discovery.provider_protocol import verify_probe_protocol
from moj_discovery.providers import api_football
from moj_discovery.providers.api_football import ApiFootballClient, ProviderError
from moj_discovery.secrets_local import SecretValue


def test_legacy_stub_remains_closed():
    with pytest.raises(ContractNotImplementedError):
        verify_probe_protocol()


def test_mock_key_cannot_open_real_transport(tmp_path, fake_clock):
    client, q, _ = make_client(tmp_path, fake_clock, [])
    with q, client, pytest.raises(ProviderError):
        ApiFootballClient(SecretValue("TEST_ONLY_HTTP_KEY"), q, client.scope)


@pytest.mark.parametrize(
    "reply",
    [
        lambda: Reply({}, status=302, headers={"Location": "https://untrusted.invalid/"}),
        lambda: Reply(STATUS, url="https://untrusted.invalid/"),
        lambda: Reply(b"x" * (8 * 1024 * 1024 + 1)),
        lambda: Reply(b'{"errors":[],"errors":[]}'),
        lambda: Reply(STATUS, headers={"Content-Encoding": "gzip"}),
    ],
)
def test_transport_bounds_and_redirects(tmp_path, fake_clock, reply):
    client, q, http = make_client(tmp_path, fake_clock, [reply()])
    with q, client:
        with pytest.raises(ProviderError):
            client.get_status()
        assert len(http.calls) == q.count_attempts() == 1


def test_exception_and_echo_never_escape(tmp_path, fake_clock, capsys):
    client, q, http = make_client(
        tmp_path,
        fake_clock,
        [
            HTTPError(
                "https://v3.football.api-sports.io/status",
                401,
                "TEST_ONLY_HTTP_KEY",
                {},
                io.BytesIO(b"TEST_ONLY_HTTP_KEY"),
            )
        ],
    )
    with q, client:
        with pytest.raises(ProviderError) as caught:
            client.get_status()
        print(caught.value, repr(caught.value))
        assert "TEST_ONLY_HTTP_KEY" not in capsys.readouterr().out
        assert len(http.calls) == 1


def test_default_opener_disables_proxy_redirect_and_keeps_tls():
    opener = api_football.build_fixed_opener()
    proxy = (
        next(h for h in opener.handlers if isinstance(h, ProxyHandler))
        if any(isinstance(h, ProxyHandler) for h in opener.handlers)
        else None
    )
    assert proxy is None or proxy.proxies == {}
    redirect = next(h for h in opener.handlers if isinstance(h, HTTPRedirectHandler))
    assert (
        redirect.redirect_request(
            Request("https://v3.football.api-sports.io/status"),
            None,
            302,
            "ignored",
            {},
            "https://untrusted.invalid/",
        )
        is None
    )
    handler = next(h for h in opener.handlers if hasattr(h, "_context"))
    assert handler._context.verify_mode == ssl.CERT_REQUIRED
    assert handler._context.check_hostname is True


def test_retry_after_date_and_invalid_fallback(fake_clock):
    from datetime import timedelta
    from email.utils import format_datetime

    future = format_datetime(fake_clock.utc + timedelta(seconds=90), usegmt=True)
    assert api_football.retry_after_seconds(future, fake_clock.utc) == 90
    assert api_football.retry_after_seconds("bad", fake_clock.utc) == 60


def test_private_request_is_not_a_generic_proxy(tmp_path, fake_clock):
    client, q, http = make_client(tmp_path, fake_clock, [])
    with q, client:
        for path in ["@untrusted.invalid/status", "/predictions", "/odds", "/status?secret=x"]:
            with pytest.raises(ProviderError):
                client._request("STATUS", path)
        assert not http.calls and q.count_attempts() == 0


def test_decoded_secret_echo_is_rejected(tmp_path, fake_clock):
    body = json.dumps({**STATUS, "echo": "TEST_ONLY_HTTP_KEY"}).encode()
    body = body.replace(b"TEST_ONLY_HTTP_KEY", b"\\u0054EST_ONLY_HTTP_KEY")
    client, q, _ = make_client(tmp_path, fake_clock, [Reply(body)])
    with q, client, pytest.raises(ProviderError, match="SECRET_ECHO"):
        client.get_status()


def test_three_attempt_ceiling_and_run_deadline(tmp_path, fake_clock):
    client, q, http = make_client(
        tmp_path,
        fake_clock,
        [Reply(STATUS), Reply({}, status=500), Reply({}, status=500), Reply({}, status=500)],
    )
    with q, client:
        client.get_status()
        with pytest.raises(ProviderError, match="HTTP_5XX"):
            client.get_fixture_bundle([101])
        assert len(http.calls) == q.count_attempts() == 4
        fake_clock.advance(300)
        with pytest.raises(ProviderError, match="DEADLINE"):
            client.get_fixture_bundle([101])
        assert len(http.calls) == 4


def test_pinned_httpresponse_eof_and_content_length(tmp_path, fake_clock):
    import http.client
    import socket

    client, q, _ = make_client(tmp_path, fake_clock, [])
    left, right = socket.socketpair()
    payload = json.dumps(STATUS).encode()
    try:
        right.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\n\r\n"
            + payload
        )
        response = http.client.HTTPResponse(left)
        response.begin()
        response.geturl = lambda: "https://v3.football.api-sports.io/status"
        client._real = True
        request = Request("https://v3.football.api-sports.io/status")
        assert client._read(response, request, 10) == payload
        assert response.isclosed()
    finally:
        left.close()
        right.close()
        client.close()
        q.close()
