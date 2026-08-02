from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.config import Settings, get_settings


class AlphaVantageError(RuntimeError):
    code = "provider_error"


class AlphaVantageAuthenticationError(AlphaVantageError):
    code = "invalid_key"


class AlphaVantageRateLimitError(AlphaVantageError):
    code = "rate_limit"


class AlphaVantagePremiumRequiredError(AlphaVantageError):
    code = "premium_required"


class AlphaVantageSchemaError(AlphaVantageError):
    code = "unexpected_response"


class AlphaVantageTemporaryError(AlphaVantageError):
    code = "temporary_error"


class AlphaVantageUnavailableError(AlphaVantageError):
    code = "provider_information"


def _safe_message(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


class AlphaVantageMacroProvider:
    """Small async client for the official Alpha Vantage REST endpoint.

    The API key is sent as a query parameter to the provider, but it is never
    included in logs or exception messages. Request pacing is instance-local;
    the database usage ledger is responsible for the daily project limit.
    """

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def __aenter__(self) -> "AlphaVantageMacroProvider":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.alpha_vantage_timeout_seconds,
                trust_env=False,
            )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.alpha_vantage_enabled and self.settings.alpha_vantage_api_key.strip())

    async def _wait_for_interval(self) -> None:
        async with self._request_lock:
            interval = max(float(self.settings.alpha_vantage_request_interval_seconds), 0.0)
            if interval:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < interval:
                    await asyncio.sleep(interval - elapsed)
            self._last_request_at = time.monotonic()

    @staticmethod
    def _classify_information(message: str) -> type[AlphaVantageError]:
        lowered = message.lower()
        if any(token in lowered for token in ("invalid api", "invalid key", "apikey", "api key")):
            return AlphaVantageAuthenticationError
        if any(token in lowered for token in ("premium", "premium endpoint", "premium member")):
            return AlphaVantagePremiumRequiredError
        if any(token in lowered for token in ("call frequency", "rate limit", "too many", "per minute", "per day")):
            return AlphaVantageRateLimitError
        return AlphaVantageUnavailableError

    async def _request(self, function: str, **params: str) -> dict[str, Any]:
        if not self.configured:
            raise AlphaVantageAuthenticationError("Alpha Vantage is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.alpha_vantage_timeout_seconds,
                trust_env=False,
            )
        query = {"function": function, **params, "apikey": self.settings.alpha_vantage_api_key.strip()}
        attempts = max(int(self.settings.alpha_vantage_max_retries), 0) + 1
        for attempt in range(attempts):
            try:
                await self._wait_for_interval()
                response = await self._client.get(self.settings.alpha_vantage_base_url, params=query)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt + 1 >= attempts:
                    raise AlphaVantageTemporaryError("Alpha Vantage request timed out or failed") from exc
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            except httpx.HTTPError as exc:
                raise AlphaVantageTemporaryError("Alpha Vantage HTTP client error") from exc

            if response.status_code == 429:
                raise AlphaVantageRateLimitError("Alpha Vantage returned HTTP 429")
            if response.status_code >= 500:
                if attempt + 1 >= attempts:
                    raise AlphaVantageTemporaryError(f"Alpha Vantage returned HTTP {response.status_code}")
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise AlphaVantageTemporaryError(f"Alpha Vantage returned HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise AlphaVantageSchemaError("Alpha Vantage returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise AlphaVantageSchemaError("Alpha Vantage returned a non-object response")
            if payload.get("Error Message"):
                message = _safe_message(payload["Error Message"])
                error_type = self._classify_information(message)
                raise error_type(message)
            for key in ("Note", "Information"):
                if payload.get(key):
                    message = _safe_message(payload[key])
                    raise self._classify_information(message)(message)
            if "data" not in payload:
                raise AlphaVantageSchemaError("Alpha Vantage response did not contain data")
            if not isinstance(payload["data"], list):
                raise AlphaVantageSchemaError("Alpha Vantage data field was not a list")
            return payload
        raise AlphaVantageTemporaryError("Alpha Vantage request exhausted retries")

    async def fetch_series(self, function: str, **params: str) -> dict[str, Any]:
        return await self._request(function, **params)

    async def fetch_real_gdp(self) -> dict[str, Any]:
        return await self.fetch_series("REAL_GDP", interval="quarterly")

    async def fetch_real_gdp_per_capita(self) -> dict[str, Any]:
        return await self.fetch_series("REAL_GDP_PER_CAPITA", interval="quarterly")

    async def fetch_treasury_yield(self, maturity: str) -> dict[str, Any]:
        return await self.fetch_series("TREASURY_YIELD", interval="daily", maturity=maturity)

    async def fetch_federal_funds_rate(self) -> dict[str, Any]:
        return await self.fetch_series("FEDERAL_FUNDS_RATE", interval="daily")

    async def fetch_cpi(self) -> dict[str, Any]:
        return await self.fetch_series("CPI", interval="monthly")

    async def fetch_inflation(self) -> dict[str, Any]:
        return await self.fetch_series("INFLATION")

    async def fetch_retail_sales(self) -> dict[str, Any]:
        return await self.fetch_series("RETAIL_SALES")

    async def fetch_durables(self) -> dict[str, Any]:
        return await self.fetch_series("DURABLES")

    async def fetch_unemployment(self) -> dict[str, Any]:
        return await self.fetch_series("UNEMPLOYMENT")

    async def fetch_nonfarm_payroll(self) -> dict[str, Any]:
        return await self.fetch_series("NONFARM_PAYROLL")

    async def test_connection(self) -> dict[str, Any]:
        payload = await self.fetch_cpi()
        return {"function": "CPI", "data_points": len(payload.get("data", [])), "metadata": payload.get("name") or payload.get("unit")}
