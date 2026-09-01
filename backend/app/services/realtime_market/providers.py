"""Isolated Alpaca/Tiingo REST and streaming adapters.

Adapters own authentication, provider URLs, rate-limit handling, and wire
schemas.  Callers receive only :mod:`.contracts` values and provider failures
that are safe to route/fallback.  Credentials are never included in errors or
health payloads.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
from dataclasses import replace
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, runtime_checkable

import httpx

from app.config import Settings, get_settings

from .contracts import (
    IntradayBar,
    ProviderError,
    ProviderHealth,
    RealtimeQuote,
    ensure_utc,
    parse_provider_timestamp,
)
from .normalization import (
    normalize_alpaca_bar,
    normalize_alpaca_message,
    normalize_alpaca_rest_quotes,
    normalize_tiingo_message,
    normalize_tiingo_rest_rows,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class RealtimeMarketDataProvider(Protocol):
    name: str

    async def get_quote(self, symbol: str) -> RealtimeQuote:
        ...

    async def get_quotes(self, symbols: list[str]) -> list[RealtimeQuote]:
        ...

    async def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "1m",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[IntradayBar]:
        ...

    async def health_check(self) -> ProviderHealth:
        ...


@runtime_checkable
class StreamingMarketDataProvider(Protocol):
    async def connect(self) -> None:
        ...

    async def subscribe(self, symbols: Sequence[str]) -> None:
        ...

    async def unsubscribe(self, symbols: Sequence[str]) -> None:
        ...

    async def stream(self) -> AsyncIterator[RealtimeQuote | IntradayBar]:
        ...

    async def close(self) -> None:
        ...


def _clean_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not value or len(value) > 32 or any(char in value for char in "\r\n, "):
        raise ValueError("invalid market-data symbol")
    return value


def _symbols(symbols: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(_clean_symbol(value) for value in symbols if value and value.strip()))


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            date_value = parsedate_to_datetime(value)
            if date_value.tzinfo is None:
                date_value = date_value.replace(tzinfo=UTC)
            return max(0.0, (date_value.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _safe_error(response: httpx.Response, provider: str) -> ProviderError:
    status = response.status_code
    if status in {401, 403}:
        return ProviderError(
            f"{provider} authentication or entitlement rejected ({status})",
            provider=provider,
            status_code=status,
            capability_limited=status == 403,
            transient=False,
        )
    if status == 429:
        return ProviderError(
            f"{provider} rate limit exceeded",
            provider=provider,
            status_code=status,
            retry_after=_retry_after(response),
            transient=True,
        )
    return ProviderError(
        f"{provider} HTTP request failed ({status})",
        provider=provider,
        status_code=status,
        transient=status >= 500,
    )


class _ProviderBase(ABC):
    name: str

    def __init__(self, *, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self._connected = False
        self._last_message_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None
        self._error_code: str | None = None
        self._subscriptions: set[str] = set()
        self._reconnect_count = 0
        self._message_count = 0
        self._rate_started_at = datetime.now(UTC)

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _mark_success(self, *, message: bool = False) -> None:
        now = datetime.now(UTC)
        self._last_success_at = now
        self._last_error = None
        self._error_code = None
        if message:
            self._last_message_at = now
            self._message_count += 1

    def _mark_failure(self, error: ProviderError) -> None:
        self._last_error = str(error)
        self._error_code = str(error.status_code) if error.status_code else type(error).__name__
        self._connected = False if not error.capability_limited else self._connected

    def _health(self) -> ProviderHealth:
        elapsed = max(1.0, (datetime.now(UTC) - self._rate_started_at).total_seconds())
        return ProviderHealth(
            provider=self.name,
            connected=self._connected,
            last_message_at=self._last_message_at,
            last_success_at=self._last_success_at,
            last_error=self._last_error,
            error_code=self._error_code,
            subscriptions=tuple(sorted(self._subscriptions)),
            message_rate=self._message_count / elapsed,
            reconnect_count=self._reconnect_count,
            capability_limited=bool(self._error_code == "403"),
        )

    async def _request(self, method: str, url: str, *, provider: str, **kwargs: Any) -> httpx.Response:
        # URLs are generated from validated symbols and static configuration;
        # credentials are headers only and never included in exceptions.
        try:
            response = await self.client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
            error = ProviderError(f"{provider} network request failed: {type(exc).__name__}", provider=provider)
            self._mark_failure(error)
            raise error from exc
        if response.status_code >= 400:
            error = _safe_error(response, provider)
            self._mark_failure(error)
            raise error
        self._mark_success()
        return response

    async def health_check(self) -> ProviderHealth:
        return self._health()


def _iso(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat().replace("+00:00", "Z") if value else None


class AlpacaRealtimeProvider(_ProviderBase):
    name = "alpaca"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        websocket_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(settings=settings, client=client)
        self.feed = str(getattr(self.settings, "alpaca_market_data_feed", "iex") or "iex").strip().lower()
        self.base_url = str(getattr(self.settings, "alpaca_market_data_base_url", "https://data.alpaca.markets")).rstrip("/")
        self.stream_url = str(getattr(self.settings, "alpaca_market_data_stream_url", "wss://stream.data.alpaca.markets")).rstrip("/")
        self.api_key = str(getattr(self.settings, "alpaca_api_key", "") or "")
        self.api_secret = str(getattr(self.settings, "alpaca_api_secret", "") or "")
        self.trading_env = str(getattr(self.settings, "alpaca_trading_env", "paper") or "paper").strip().lower()
        try:
            self.symbol_limit = max(0, int(getattr(self.settings, "alpaca_market_data_symbol_limit", 30) or 0))
        except (TypeError, ValueError):
            self.symbol_limit = 30
        self._websocket_factory = websocket_factory
        self._ws: Any = None
        self._subscribed_types: tuple[str, ...] = ("trades", "quotes", "bars")
        # Alpaca market data is US-equity scoped.  Keep symbols rejected by
        # the REST endpoint out of the shared websocket subscription so one
        # international Yahoo symbol cannot terminate the whole Alpaca feed.
        self._unsupported_symbols: set[str] = set()

    async def _headers(self) -> dict[str, str]:
        if not self.api_key or not self.api_secret:
            raise ProviderError("alpaca credentials are not configured", provider=self.name, transient=False)
        return {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret}

    async def health_check(self) -> ProviderHealth:
        return replace(
            self._health(),
            auth_type="trading_api_key",
            environment=f"{self.trading_env}_credentials",
            market_data_endpoint=self.base_url,
            feed=self.feed,
            stream_endpoint=f"{self.stream_url}/v2/{self.feed}",
        )

    async def get_quote(self, symbol: str) -> RealtimeQuote:
        value = _clean_symbol(symbol)
        try:
            response = await self._request(
                "GET",
                f"{self.base_url}/v2/stocks/{value}/quotes/latest",
                provider=self.name,
                headers=await self._headers(),
                params={"feed": self.feed},
            )
        except ProviderError as exc:
            if exc.status_code in {400, 404}:
                self._unsupported_symbols.add(value)
            raise
        self._unsupported_symbols.discard(value)
        payload = response.json()
        if isinstance(payload, Mapping) and isinstance(payload.get("quote"), Mapping):
            payload = {**payload["quote"], "S": value}
        if not isinstance(payload, Mapping):
            raise ProviderError("alpaca returned an invalid quote payload", provider=self.name, transient=False)
        quote = normalize_alpaca_message({**payload, "S": payload.get("S") or value, "T": "q"}, feed=self.feed)
        if quote is None:
            raise ProviderError("alpaca returned no usable quote", provider=self.name, transient=False)
        self._mark_success(message=True)
        return quote

    async def get_quotes(self, symbols: list[str]) -> list[RealtimeQuote]:
        values = _symbols(symbols)
        if not values:
            return []
        response = await self._request(
            "GET",
            f"{self.base_url}/v2/stocks/quotes/latest",
            provider=self.name,
            headers=await self._headers(),
            params={"symbols": ",".join(values), "feed": self.feed},
        )
        rows = normalize_alpaca_rest_quotes(response.json(), feed=self.feed)
        self._mark_success(message=bool(rows))
        return rows

    async def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "1m",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[IntradayBar]:
        value = _clean_symbol(symbol)
        if interval not in {"1m", "5m", "15m"}:
            raise ValueError("interval must be one of 1m, 5m, or 15m")
        response = await self._request(
            "GET",
            f"{self.base_url}/v2/stocks/{value}/bars",
            provider=self.name,
            headers=await self._headers(),
            params={
                "timeframe": {"1m": "1Min", "5m": "5Min", "15m": "15Min"}[interval],
                "start": _iso(start),
                "end": _iso(end),
                "feed": self.feed,
                "limit": 10000,
            },
        )
        payload = response.json()
        rows = payload.get("bars", []) if isinstance(payload, Mapping) else payload
        output: list[IntradayBar] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                value_row = dict(row)
                value_row.setdefault("S", value)
                bar = normalize_alpaca_bar(value_row, feed=self.feed, interval=interval)
                if bar is not None:
                    output.append(bar)
        self._mark_success(message=bool(output))
        return output

    async def connect(self) -> None:
        if self._ws is not None:
            return
        if not self.api_key or not self.api_secret:
            error = ProviderError("alpaca credentials are not configured", provider=self.name, transient=False)
            self._mark_failure(error)
            raise error
        factory = self._websocket_factory
        if factory is None:
            try:
                import websockets

                factory = websockets.connect
            except ImportError as exc:
                raise ProviderError("websocket transport is unavailable", provider=self.name, transient=False) from exc
        url = f"{self.stream_url}/v2/{self.feed}"
        try:
            # Alpaca's market-data websocket authenticates with the JSON auth
            # message below.  Do not also send REST API-key headers: Alpaca
            # treats that as an already-authenticated connection and rejects
            # the subsequent auth action.
            self._ws = await factory(url, ping_interval=20, ping_timeout=20)
            await self._send({"action": "auth", "key": self.api_key, "secret": self.api_secret})
            # Alpaca rejects a subscription sent before the authenticated
            # control message arrives, so the supervisor must not race the
            # handshake by returning from connect early.
            await self._wait_for_authentication()
            self._connected = True
            self._mark_success()
        except ProviderError:
            ws, self._ws = self._ws, None
            self._connected = False
            if ws is not None:
                result = ws.close()
                if inspect.isawaitable(result):
                    await result
            raise
        except Exception as exc:
            self._ws = None
            error = ProviderError(f"alpaca websocket connection failed: {type(exc).__name__}", provider=self.name)
            self._mark_failure(error)
            raise error from exc

    async def _send(self, payload: Mapping[str, Any]) -> None:
        if self._ws is None:
            raise ProviderError("alpaca websocket is not connected", provider=self.name)
        message = json.dumps(payload, separators=(",", ":"))
        result = self._ws.send(message)
        if inspect.isawaitable(result):
            await result

    async def _wait_for_authentication(self) -> None:
        if self._ws is None:
            raise ProviderError("alpaca websocket is not connected", provider=self.name)
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
            messages = raw if isinstance(raw, list) else json.loads(raw)
            rows = messages if isinstance(messages, list) else [messages]
            for payload in rows:
                if not isinstance(payload, Mapping):
                    continue
                kind = str(payload.get("T") or payload.get("type") or "").lower()
                message = str(payload.get("msg") or payload.get("message") or "").lower()
                if kind in {"success", "authorization"} and message == "authenticated":
                    return
                if kind == "error":
                    raw_code = payload.get("code")
                    try:
                        status_code = int(raw_code) if raw_code is not None else None
                    except (TypeError, ValueError):
                        status_code = None
                    error = ProviderError(
                        f"alpaca websocket authentication rejected ({status_code or 'unknown'})",
                        provider=self.name,
                        status_code=status_code,
                        # Alpaca documents 406 as "connection limit exceeded".
                        # A recently dropped socket can temporarily retain the
                        # account's single stream slot, so retry with bounded
                        # backoff instead of disabling the provider until the
                        # whole process restarts.
                        transient=status_code in {406, 407, 500},
                    )
                    self._mark_failure(error)
                    raise error

    async def subscribe(self, symbols: Sequence[str], *, types: Sequence[str] | None = None) -> None:
        values = [value for value in _symbols(symbols) if value not in self._unsupported_symbols]
        if not values:
            return
        if self._ws is None:
            await self.connect()
        selected = tuple(types or self._subscribed_types)
        payload: dict[str, list[str]] = {}
        limit = self.symbol_limit
        if limit <= 0 or len(values) * len(selected) <= limit:
            payload = {kind: values for kind in selected}
        else:
            # The Basic plan counts each (channel, symbol) pair.  Preserve a
            # quote for every tracked symbol first; it is also sufficient for
            # the local minute aggregator.  Spend the remaining budget on
            # trades and bars for the leading symbols, sharing the remainder
            # so both event types remain available when possible.
            remaining = limit
            if "quotes" in selected:
                payload["quotes"] = values[:min(len(values), remaining)]
                remaining -= len(payload["quotes"])
            secondary = [kind for kind in ("trades", "bars") if kind in selected]
            if secondary and remaining > 0:
                base, extra = divmod(remaining, len(secondary))
                for index, kind in enumerate(secondary):
                    allocation = min(len(values), base + (1 if index < extra else 0))
                    if allocation:
                        payload[kind] = values[:allocation]
                        remaining -= allocation
            for kind in selected:
                if kind not in payload and remaining > 0:
                    allocation = min(len(values), remaining)
                    payload[kind] = values[:allocation]
                    remaining -= allocation
            logger.warning(
                "alpaca_subscription_limit_applied symbols=%d channels=%d limit=%d subscribed=%s",
                len(values), len(selected), limit, {kind: len(items) for kind, items in payload.items()},
            )
        await self._send({"action": "subscribe", **payload})
        self._subscriptions.update({value for items in payload.values() for value in items})
        self._mark_success()

    async def unsubscribe(self, symbols: Sequence[str]) -> None:
        values = _symbols(symbols)
        if not values or self._ws is None:
            return
        await self._send({"action": "unsubscribe", **{kind: values for kind in self._subscribed_types}})
        self._subscriptions.difference_update(values)

    async def stream(self) -> AsyncIterator[RealtimeQuote | IntradayBar]:
        if self._ws is None:
            await self.connect()
        while self._ws is not None:
            try:
                raw = await self._ws.recv()
                received = datetime.now(UTC)
                messages = raw if isinstance(raw, list) else json.loads(raw)
                rows = messages if isinstance(messages, list) else [messages]
                for payload in rows:
                    if not isinstance(payload, Mapping):
                        continue
                    kind = str(payload.get("T") or payload.get("type") or "").lower()
                    if kind in {"error", "subscription", "success", "authorization"}:
                        if kind == "error":
                            error = ProviderError("alpaca websocket provider error", provider=self.name, transient=False)
                            self._mark_failure(error)
                            raise error
                        continue
                    value = normalize_alpaca_message(payload, received_at=received, feed=self.feed)
                    if value is not None:
                        self._mark_success(message=True)
                        yield value
            except ProviderError:
                raise
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as exc:
                self._connected = False
                error = ProviderError(f"alpaca websocket stream failed: {type(exc).__name__}", provider=self.name)
                self._mark_failure(error)
                raise error from exc

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        self._connected = False
        if ws is not None:
            result = ws.close()
            if inspect.isawaitable(result):
                await result
        await self.aclose()


class TiingoRealtimeProvider(_ProviderBase):
    name = "tiingo"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        websocket_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(settings=settings, client=client)
        self.base_url = str(getattr(self.settings, "tiingo_market_data_base_url", "https://api.tiingo.com")).rstrip("/")
        self.stream_url = str(getattr(self.settings, "tiingo_market_data_stream_url", "wss://api.tiingo.com")).rstrip("/")
        self.token = str(getattr(self.settings, "tiingo_api_token", "") or "")
        self.mode = str(getattr(self.settings, "tiingo_realtime_mode", "consolidated") or "consolidated").strip().lower()
        if self.mode not in {"consolidated", "iex", "auto"}:
            self.mode = "consolidated"
        self._websocket_factory = websocket_factory
        self._ws: Any = None

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise ProviderError("tiingo credentials are not configured", provider=self.name, transient=False)
        return {"Authorization": f"Token {self.token}"}

    def _mode_candidates(self) -> list[str]:
        return ["iex", "consolidated"] if self.mode == "auto" else [self.mode]

    def _intraday_path(self, mode: str, symbol: str) -> str:
        return f"{self.base_url}/{'iex' if mode == 'iex' else 'tiingo/equity/intraday'}/{symbol}"

    async def _get_rows(self, symbol: str, *, mode: str, params: Mapping[str, Any] | None = None) -> list[RealtimeQuote | IntradayBar]:
        response = await self._request(
            "GET",
            self._intraday_path(mode, symbol),
            provider=self.name,
            headers=self._headers(),
            params=dict(params or {}),
        )
        payload = response.json()
        rows = normalize_tiingo_rest_rows(payload, mode=mode, feed=mode)
        self._mark_success(message=bool(rows))
        return rows

    async def get_quote(self, symbol: str) -> RealtimeQuote:
        value = _clean_symbol(symbol)
        errors: list[ProviderError] = []
        for mode in self._mode_candidates():
            try:
                rows = await self._get_rows(value, mode=mode)
                quotes = [row for row in rows if isinstance(row, RealtimeQuote)]
                if quotes:
                    return max(quotes, key=lambda row: row.timestamp)
                bars = [row for row in rows if isinstance(row, IntradayBar)]
                if bars:
                    latest = max(bars, key=lambda row: row.timestamp)
                    return RealtimeQuote(
                        symbol=latest.symbol,
                        price=latest.close,
                        timestamp=latest.timestamp,
                        received_at=latest.received_at,
                        provider=self.name,
                        feed=mode,
                        open=latest.open,
                        high=latest.high,
                        low=latest.low,
                        volume=latest.volume,
                        vwap=latest.vwap,
                        market_session=latest.market_session,
                        source_role="reference" if mode == "consolidated" else "primary",
                    )
            except ProviderError as exc:
                errors.append(exc)
                if not exc.capability_limited or self.mode != "auto":
                    raise
        if errors:
            raise errors[-1]
        raise ProviderError("tiingo returned no usable quote", provider=self.name, transient=False)

    async def get_quotes(self, symbols: list[str]) -> list[RealtimeQuote]:
        output: list[RealtimeQuote] = []
        for symbol in _symbols(symbols):
            try:
                output.append(await self.get_quote(symbol))
            except ProviderError:
                # One symbol's entitlement/data gap must not discard others.
                continue
        return output

    async def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "1m",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[IntradayBar]:
        value = _clean_symbol(symbol)
        if interval not in {"1m", "5m", "15m"}:
            raise ValueError("interval must be one of 1m, 5m, or 15m")
        params = {
            "resampleFreq": {"1m": "1min", "5m": "5min", "15m": "15min"}[interval],
            "startDate": _iso(start),
            "endDate": _iso(end),
        }
        errors: list[ProviderError] = []
        for mode in self._mode_candidates():
            try:
                rows = await self._get_rows(value, mode=mode, params=params)
                output = [row for row in rows if isinstance(row, IntradayBar)]
                if output:
                    return output
            except ProviderError as exc:
                errors.append(exc)
                if not exc.capability_limited or self.mode != "auto":
                    raise
        if errors:
            raise errors[-1]
        return []

    async def connect(self) -> None:
        if self._ws is not None:
            return
        if not self.token:
            raise ProviderError("tiingo credentials are not configured", provider=self.name, transient=False)
        factory = self._websocket_factory
        if factory is None:
            try:
                import websockets

                factory = websockets.connect
            except ImportError as exc:
                raise ProviderError("websocket transport is unavailable", provider=self.name, transient=False) from exc
        url = f"{self.stream_url}/{'iex' if self.mode == 'iex' else 'equity/intraday'}"
        try:
            try:
                self._ws = await factory(url, additional_headers=self._headers(), ping_interval=20, ping_timeout=20)
            except TypeError:
                self._ws = await factory(url, extra_headers=self._headers(), ping_interval=20, ping_timeout=20)
            self._connected = True
            self._mark_success()
        except ProviderError:
            raise
        except Exception as exc:
            self._ws = None
            error = ProviderError(f"tiingo websocket connection failed: {type(exc).__name__}", provider=self.name)
            self._mark_failure(error)
            raise error from exc

    async def _send(self, payload: Mapping[str, Any]) -> None:
        if self._ws is None:
            raise ProviderError("tiingo websocket is not connected", provider=self.name)
        result = self._ws.send(json.dumps(payload, separators=(",", ":")))
        if inspect.isawaitable(result):
            await result

    async def subscribe(self, symbols: Sequence[str]) -> None:
        values = _symbols(symbols)
        if not values:
            return
        if self._ws is None:
            await self.connect()
        # Tiingo accepts an authorization subscribe envelope for both IEX and
        # consolidated streams.  The token is sent over TLS but never logged or
        # included in a health/error payload.
        await self._send({
            "eventName": "subscribe",
            "authorization": self.token,
            "eventData": {"tickers": values},
        })
        self._subscriptions.update(values)

    async def unsubscribe(self, symbols: Sequence[str]) -> None:
        values = _symbols(symbols)
        if not values or self._ws is None:
            return
        await self._send({"eventName": "unsubscribe", "eventData": {"tickers": values}})
        self._subscriptions.difference_update(values)

    async def stream(self) -> AsyncIterator[RealtimeQuote | IntradayBar]:
        if self._ws is None:
            await self.connect()
        while self._ws is not None:
            try:
                raw = await self._ws.recv()
                received = datetime.now(UTC)
                messages = raw if isinstance(raw, list) else json.loads(raw)
                rows = messages if isinstance(messages, list) else [messages]
                for payload in rows:
                    if isinstance(payload, Mapping):
                        value = normalize_tiingo_message(payload, received_at=received, mode=self.mode, feed=self.mode)
                        if value is not None:
                            self._mark_success(message=True)
                            yield value
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as exc:
                self._connected = False
                error = ProviderError(f"tiingo websocket stream failed: {type(exc).__name__}", provider=self.name)
                self._mark_failure(error)
                raise error from exc

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        self._connected = False
        if ws is not None:
            result = ws.close()
            if inspect.isawaitable(result):
                await result
        await self.aclose()


class ProviderRegistry:
    """Small explicit registry used by API/worker wiring and tests."""

    def __init__(self, providers: Iterable[RealtimeMarketDataProvider] = ()) -> None:
        self._providers: dict[str, RealtimeMarketDataProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: RealtimeMarketDataProvider) -> None:
        name = str(provider.name).strip().lower()
        if not name:
            raise ValueError("provider name is required")
        self._providers[name] = provider

    def get(self, name: str) -> RealtimeMarketDataProvider | None:
        return self._providers.get(name.strip().lower())

    def require(self, name: str) -> RealtimeMarketDataProvider:
        value = self.get(name)
        if value is None:
            raise KeyError(f"unknown realtime provider: {name}")
        return value

    def names(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def values(self) -> tuple[RealtimeMarketDataProvider, ...]:
        return tuple(self._providers.values())


# Descriptive aliases used by integration code that calls these adapters
# ``MarketDataProvider`` rather than ``RealtimeMarketDataProvider``.
AlpacaMarketDataProvider = AlpacaRealtimeProvider
TiingoMarketDataProvider = TiingoRealtimeProvider
