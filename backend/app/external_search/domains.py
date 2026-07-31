from __future__ import annotations

from urllib.parse import urlsplit

from app.config import get_settings

OFFICIAL_SUFFIXES = (
    ".gov", ".gov.uk", ".gc.ca", ".europa.eu", "sec.gov", "federalreserve.gov",
    "nyse.com", "nasdaq.com",
)


def authority_tier(url: str, *, official_domains: list[str] | None = None) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    official = [value.lower().lstrip("*.") for value in (official_domains or [])]
    if any(host == item or host.endswith("." + item) for item in official) or any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in OFFICIAL_SUFFIXES):
        return "official"
    trusted = [item.strip().lower().lstrip("*.") for item in get_settings().exa_trusted_media_domains.split(",") if item.strip()]
    if any(host == item or host.endswith("." + item) for item in trusted):
        return "trusted_media"
    if host.endswith((".edu", ".ac.uk")) or host in {"arxiv.org", "ssrn.com", "nature.com", "science.org"}:
        return "specialist"
    return "general_web" if host else "unknown"


def blocked_domains() -> list[str]:
    return [item.strip().lower() for item in get_settings().exa_blocked_domains.split(",") if item.strip()]
