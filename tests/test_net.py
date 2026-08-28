"""The offline guard is a security control (PRD 13), so it gets real tests.

These assert the guard actually blocks sockets rather than merely warning, and
that it restores the interpreter afterwards.
"""

from __future__ import annotations

import socket

import pytest

from scribe.net import (
    OfflineAssertionError,
    OutboundNetworkBlocked,
    assert_offline,
    no_outbound_network,
)

LOCAL = ["127.0.0.1", "localhost"]


# -- assert_offline ------------------------------------------------------


def test_loopback_url_passes(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert_offline("http://127.0.0.1:8081/v1", LOCAL)
    assert_offline("http://localhost:8081/v1", LOCAL)


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1",
    "https://generativelanguage.googleapis.com/v1",
    "http://10.0.0.5:8000/v1",
])
def test_non_local_engine_url_is_rejected(url, monkeypatch):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    with pytest.raises(OfflineAssertionError, match="allow_hosts"):
        assert_offline(url, LOCAL)


def test_explicitly_allowed_host_passes(monkeypatch):
    """The Lusaka GPU box will be a non-loopback host; allow_hosts is how it is
    opted into, deliberately and in config."""
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    assert_offline("http://10.0.0.5:8000/v1", ["10.0.0.5"])


def test_cloud_api_key_in_env_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-whatever")
    with pytest.raises(OfflineAssertionError, match="ANTHROPIC_API_KEY"):
        assert_offline("http://127.0.0.1:8081/v1", LOCAL)


def test_remote_proxy_is_rejected(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy.example.com:3128")
    with pytest.raises(OfflineAssertionError, match="proxy"):
        assert_offline("http://127.0.0.1:8081/v1", LOCAL)


def test_local_proxy_is_tolerated(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    assert_offline("http://127.0.0.1:8081/v1", LOCAL)


# -- no_outbound_network -------------------------------------------------


def test_guard_blocks_outbound_connect():
    with no_outbound_network(LOCAL):
        with pytest.raises(OutboundNetworkBlocked):
            socket.create_connection(("huggingface.co", 443), timeout=5)


def test_guard_blocks_connect_ex():
    """connect_ex returns an error code instead of raising, so it would be an
    easy way around a guard that only patched connect."""
    with no_outbound_network(LOCAL):
        s = socket.socket()
        try:
            with pytest.raises(OutboundNetworkBlocked):
                s.connect_ex(("1.1.1.1", 80))
        finally:
            s.close()


def test_guard_allows_loopback():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        with no_outbound_network(LOCAL):
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                pass
    finally:
        srv.close()


def test_guard_is_removed_on_exit():
    before = socket.socket.connect
    with no_outbound_network(LOCAL):
        assert socket.socket.connect is not before
    assert socket.socket.connect is before


def test_guard_is_removed_even_after_an_exception():
    before = socket.socket.connect
    with pytest.raises(ValueError):
        with no_outbound_network(LOCAL):
            raise ValueError("boom")
    assert socket.socket.connect is before
