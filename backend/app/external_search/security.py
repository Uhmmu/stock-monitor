from __future__ import annotations

import ipaddress
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from .exceptions import ExternalSearchError

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}
INTERNAL_HOSTS = {
    "localhost", "postgres", "redis", "api", "frontend", "caddy", "finnhub-mcp",
    "metadata.google.internal", "metadata.azure.internal", "instance-data.ec2.internal",
}


def _public_host(hostname: str) -> str:
    try:
        host = hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise ExternalSearchError("WEB_SEARCH_UNSAFE_URL", "Search result URL has an invalid host.", status_code=422) from exc
    if not host or host in INTERNAL_HOSTS or host.endswith((".internal", ".local", ".localhost")):
        raise ExternalSearchError("WEB_SEARCH_UNSAFE_URL", "Search result URL is not public.", status_code=422)
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host
    if not address.is_global:
        raise ExternalSearchError("WEB_SEARCH_UNSAFE_URL", "Search result URL is not public.", status_code=422)
    return host


def normalize_public_url(value: str, *, max_length: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise ExternalSearchError("WEB_SEARCH_UNSAFE_URL", "Search result URL is invalid.", status_code=422)
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ExternalSearchError("WEB_SEARCH_UNSAFE_URL", "Search result URL is unsafe.", status_code=422)
    host = _public_host(parsed.hostname)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExternalSearchError("WEB_SEARCH_UNSAFE_URL", "Search result URL has an invalid port.", status_code=422) from exc
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = urlencode(
        [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
         if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS],
        doseq=True,
    )
    normalized = urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))
    if len(normalized) > max_length:
        raise ExternalSearchError("WEB_SEARCH_UNSAFE_URL", "Search result URL is too long.", status_code=422)
    return normalized


def normalize_domain_filter(value: str) -> str:
    raw = value.strip().lower()
    if not raw or len(raw) > 253 or "://" in raw or any(char in raw for char in "?#@"):
        raise ExternalSearchError("WEB_SEARCH_INVALID_REQUEST", "Domain filter is invalid.", status_code=422)
    wildcard = raw.startswith("*.")
    domain_path = raw[2:] if wildcard else raw
    host, slash, path = domain_path.partition("/")
    safe_host = _public_host(host)
    result = ("*." if wildcard else "") + safe_host
    if slash:
        result += "/" + quote(path.strip("/"), safe="/-._~")
    return result
