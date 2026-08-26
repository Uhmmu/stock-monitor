"""Shared proxy/transport policy for every IBKR HTTP client in the project.

Project rule (AGENTS.md): all IBKR network egress must go through the
controlled ``socks5h`` SOCKS5 entrance on the production VPS (Xray/VLESS),
fail-closed, never a direct fallback.

There is exactly one bounded exemption, mirroring the already-deployed
headless Chromium login configuration
(``--proxy-bypass-list=host.docker.internal;127.0.0.1;localhost``):

* Requests to the local Client Portal Gateway origin (loopback / private
  Docker bridge relay on port 5000) do not traverse the SOCKS proxy.
  Reasons:
  1. That hop never leaves the VPS, and the Gateway process itself is
     confined to the ``stock-monitor-ibkr`` network namespace whose only
     egress is the namespace SOCKS relay to host ``127.0.0.1:10808`` —
     IBKR-bound traffic stays proxied at the system level.
  2. Sending the loopback origin through ``socks5h`` would ask Xray (on the
     host) to resolve container-scoped hostnames such as
     ``host.docker.internal``, which do not resolve on the host; making them
     resolve would require weakening the deployment (public binds), which is
     forbidden.

Every other IBKR host (Flex Web Service today, anything added later) gets
the mandatory ``socks5h`` proxy and fails closed when the proxy is missing
or unreachable. Ambient environment proxies are ignored everywhere
(``trust_env=False``) so there is no silent direct path.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from app.config import Settings

from .exceptions import IbkrConfigurationError

#: Hosts that address the local Client Portal Gateway through the loopback /
#: private-bridge relay. These are the only hosts exempt from the proxy.
LOOPBACK_GATEWAY_HOSTS = {"127.0.0.1", "localhost", "host.docker.internal"}

#: The only accepted SOCKS5h entrances (loopback or the private Docker
#: bridge relay to it). Anything else is a configuration error.
_ALLOWED_PROXY_HOSTS = {"127.0.0.1", "localhost", "host.docker.internal"}


def validated_ibkr_proxy_url(settings: Settings) -> str:
    """Return the enforced IBKR proxy URL or raise; never falls back to direct."""
    proxy = urlsplit(settings.ibkr_proxy_url)
    if proxy.scheme != "socks5h" or proxy.hostname not in _ALLOWED_PROXY_HOSTS or proxy.port != 10808:
        raise IbkrConfigurationError("IBKR_PROXY_URL 必须指向受控的本机 10808 SOCKS5h 入口")
    return settings.ibkr_proxy_url


def ibkr_proxy_for_target(settings: Settings, host: str | None) -> str | None:
    """Proxy to use for an IBKR target host: mandatory socks5h unless loopback Gateway."""
    validated_ibkr_proxy_url(settings)  # fail-closed even for exempt targets
    if host in LOOPBACK_GATEWAY_HOSTS:
        return None
    return settings.ibkr_proxy_url


def build_ibkr_http_client(
    settings: Settings,
    *,
    base_url: str = "",
    verify: bool = True,
    timeout: httpx.Timeout,
    headers: dict[str, str] | None = None,
    limits: httpx.Limits | None = None,
) -> httpx.AsyncClient:
    """Construct the one project-sanctioned IBKR HTTP transport.

    Proxy policy is decided here, not by callers; ``trust_env`` is always
    disabled so no ambient proxy or direct fallback can leak in.
    """
    host = urlsplit(base_url).hostname if base_url else None
    kwargs: dict = {
        "proxy": ibkr_proxy_for_target(settings, host),
        "verify": verify,
        "timeout": timeout,
        "trust_env": False,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if headers:
        kwargs["headers"] = headers
    if limits:
        kwargs["limits"] = limits
    return httpx.AsyncClient(**kwargs)
