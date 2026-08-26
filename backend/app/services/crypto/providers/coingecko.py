"""Server-only CoinGecko reference and market-data client.

CoinGecko responses enrich canonical crypto identity; this client never
resolves symbols and never exposes credentials to callers outside the server.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_BASE_URL = "https://api.coingecko.com/api/v3"
PROVIDER = "coingecko"


class CoinGeckoError(Exception):
    """Normalized provider error without URL, key or raw response leakage."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in {"rate_limited", "retryable", "timeout"}


@dataclass(frozen=True)
class CoinGeckoMarket:
    provider_id: str
    symbol: str | None
    name: str | None
    payload: dict[str, Any]


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class CoinGeckoClient:
    """Small bounded HTTP client for the public CoinGecko v3 endpoints."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._backoff = max(0.0, backoff_seconds)
        self._transport = transport
        self.last_request_at: str | None = None

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, transport=self._transport)

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        headers = {"accept": "application/json"}
        if self._api_key:
            headers["x-cg-demo-api-key"] = self._api_key
        url = f"{self._base_url}/{path.lstrip('/')}"
        attempt = 0
        last_error: CoinGeckoError | None = None
        while attempt <= self._max_retries:
            if last_error is not None:
                delay = last_error.retry_after if last_error.retry_after is not None else self._backoff * (2 ** (attempt - 1))
                time.sleep(min(delay, 30.0))
            try:
                with self._client() as client:
                    response = client.get(url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = CoinGeckoError("timeout", f"public request timed out: {type(exc).__name__}")
                attempt += 1
                continue
            except httpx.TransportError as exc:
                last_error = CoinGeckoError("retryable", f"network error: {type(exc).__name__}")
                attempt += 1
                continue
            self.last_request_at = _utcnow_iso()
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise CoinGeckoError("permanent", "provider returned invalid JSON", status_code=200) from exc
            retry_after: float | None = None
            raw_retry = response.headers.get("retry-after")
            if raw_retry:
                try:
                    retry_after = float(raw_retry)
                except ValueError:
                    retry_after = None
            message = f"http {response.status_code}"
            if response.status_code in {401, 403}:
                raise CoinGeckoError("permanent", "provider authentication or entitlement failed", status_code=response.status_code)
            if response.status_code == 429:
                last_error = CoinGeckoError("rate_limited", message, status_code=429, retry_after=retry_after)
                attempt += 1
                continue
            if 500 <= response.status_code < 600:
                last_error = CoinGeckoError("retryable", message, status_code=response.status_code)
                attempt += 1
                continue
            raise CoinGeckoError("permanent", message, status_code=response.status_code)
        raise last_error or CoinGeckoError("retryable", "provider request failed")

    def markets(self, ids: list[str], *, vs_currency: str = "usd") -> list[CoinGeckoMarket]:
        clean = list(dict.fromkeys(str(value).strip() for value in ids if str(value).strip()))[:50]
        if not clean:
            return []
        payload = self._request(
            "coins/markets",
            {"vs_currency": vs_currency, "ids": ",".join(clean), "order": "market_cap_desc", "per_page": len(clean), "page": 1, "sparkline": "false"},
        )
        if not isinstance(payload, list):
            raise CoinGeckoError("permanent", "markets payload is not a list", status_code=200)
        result = []
        for row in payload:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            result.append(CoinGeckoMarket(
                provider_id=str(row["id"]),
                symbol=str(row["symbol"]).upper() if row.get("symbol") else None,
                name=str(row["name"]) if row.get("name") else None,
                payload=row,
            ))
        return result

    def asset_detail(self, provider_id: str) -> dict[str, Any]:
        clean = str(provider_id).strip()
        if not clean:
            raise ValueError("provider_id is required")
        payload = self._request(
            f"coins/{quote(clean, safe='')}",
            {"localization": "false", "tickers": "false", "market_data": "true", "community_data": "false", "developer_data": "false"},
        )
        if not isinstance(payload, dict) or not payload.get("id"):
            raise CoinGeckoError("permanent", "asset detail payload is not an object", status_code=200)
        return payload
