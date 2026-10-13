"""Regression tests for SSRF-resistant webfetch behavior."""
import socket
import urllib.request
from types import SimpleNamespace

import pytest

from alberto.runtime import function_caller


def test_url_validator_rejects_local_and_non_http_targets():
    for url in (
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "file:///etc/passwd",
        "http://localhost/",
        "http://user:password@example.com/",
        "https://example.com:8443/",
    ):
        with pytest.raises(ValueError):
            function_caller._validate_public_web_url(url)


def test_url_validator_rejects_hostname_resolving_to_private_ip(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 80))
        ],
    )

    with pytest.raises(ValueError, match="non-public"):
        function_caller._validate_public_web_url("http://internal-looking.example/")


def test_url_validator_accepts_public_hostname(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ],
    )

    parsed = function_caller._validate_public_web_url("http://example.com/path")

    assert parsed.hostname == "example.com"
    assert parsed.path == "/path"


def test_redirect_handler_rejects_redirect_to_loopback():
    handler = function_caller._SafeWebRedirectHandler()
    request = urllib.request.Request("https://example.com/start")

    with pytest.raises(ValueError, match="non-public"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1/admin",
        )


def test_webfetch_rejects_private_url_before_opening(monkeypatch):
    monkeypatch.setattr(
        function_caller.urllib.request,
        "build_opener",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network opener must not be built")),
    )

    output, is_error = function_caller.tool_webfetch(
        None, {"url": "http://169.254.169.254/latest/meta-data/"}
    )

    assert is_error is True
    assert "non-public" in output


def test_webfetch_bounds_response_read_and_output(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            self.requested_size = size
            return b"x" * size

    class FakeOpener:
        def __init__(self):
            self.response = FakeResponse()

        def open(self, request, timeout):
            return self.response

    opener = FakeOpener()
    monkeypatch.setattr(function_caller, "_validate_public_web_url", lambda url: None)
    monkeypatch.setattr(function_caller.urllib.request, "build_opener", lambda handler: opener)

    output, is_error = function_caller.tool_webfetch(
        None, {"url": "https://example.com/", "max_length": 10}
    )

    assert is_error is False
    assert output == "x" * 10
    assert opener.response.requested_size == 41
