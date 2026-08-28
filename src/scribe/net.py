"""Offline enforcement (PRD 13).

Two layers:

1. `assert_offline()` -- a startup check that fails loudly if the environment
   points at a cloud endpoint (proxy vars, cloud API keys, a non-loopback
   engine URL).
2. `no_outbound_network()` -- a context manager that patches
   `socket.socket.connect` so any attempt to reach a non-allowed host raises.
   This is what makes "no outbound network calls during run" a verified
   property rather than a claim.

Layer 2 is deliberately blunt: it blocks the whole process, so `scribe run`
cannot silently phone home even through a dependency.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from contextlib import contextmanager
from typing import Iterable
from urllib.parse import urlparse

PROXY_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)

CLOUD_KEY_VARS = (
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_ENDPOINT", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "AWS_BEDROCK_ENDPOINT", "MISTRAL_API_KEY", "COHERE_API_KEY",
)


class OutboundNetworkBlocked(RuntimeError):
    """Raised when code inside the offline guard tries to leave the machine."""


class OfflineAssertionError(RuntimeError):
    """Raised at startup when the environment suggests a cloud endpoint."""


def _is_local(host: str) -> bool:
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def assert_offline(server_url: str, allow_hosts: Iterable[str] = ()) -> None:
    """Fail if the environment looks like it routes to a cloud service."""
    problems: list[str] = []

    for var in PROXY_VARS:
        val = os.environ.get(var)
        if val and not _is_local(urlparse(val).hostname or ""):
            problems.append(f"{var}={val} routes through a non-local proxy")

    for var in CLOUD_KEY_VARS:
        if os.environ.get(var):
            problems.append(
                f"{var} is set; unset it before running the pipeline on real data"
            )

    host = urlparse(server_url).hostname or ""
    allowed = set(allow_hosts)
    if not (_is_local(host) or host in allowed):
        problems.append(
            f"extraction_engine.server_url points at '{host}', which is neither "
            f"loopback nor in security.allow_hosts"
        )

    if problems:
        raise OfflineAssertionError(
            "Refusing to start -- environment suggests a cloud endpoint:\n  - "
            + "\n  - ".join(problems)
        )


@contextmanager
def no_outbound_network(allow_hosts: Iterable[str] = ()):
    """Block every socket connection to a non-loopback, non-allowed host."""
    allowed = {h.lower() for h in allow_hosts}
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(address) -> None:
        # Unix sockets and anything not (host, port) are local by construction.
        if not isinstance(address, tuple) or not address:
            return
        host = str(address[0])
        if _is_local(host) or host.lower() in allowed:
            return
        raise OutboundNetworkBlocked(
            f"Blocked outbound connection to {host}. The pipeline runs fully "
            f"local (PRD 13); no document image or extracted value leaves this "
            f"machine."
        )

    def guarded_connect(self, address):
        _check(address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        _check(address)
        return real_connect_ex(self, address)

    socket.socket.connect = guarded_connect          # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex    # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect          # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex    # type: ignore[method-assign]
