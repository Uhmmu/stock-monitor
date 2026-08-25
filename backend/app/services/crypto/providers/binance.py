"""Server-only Binance public market-data client (crypto/quant program WP 2.1).

Public endpoints only: no API key can be configured, no auth header is ever
sent, and every request/response is shaped by the WP 0.2 fixtures. Errors are
normalized (rate limited / ip banned / retryable / timeout / permanent) with
bounded retries that respect ``Retry-After``. Request weights from response
headers are observable for budget accounting.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

DEFAULT_SPOT_BASE_URL = "https://api.binance.com"
DEFAULT_USDM_BASE_URL = "https://fapi.binance.com"

MARKETS = ("spot", "usdm")

_MARKET_PATHS: dict[str, dict[str, str]] = {
    "spot": {
        "time": "/api/v3/time",
        "exchange_info": "/api/v3/exchangeInfo",
        "klines": "/api/v3/klines",
        "ticker_24h": "/api/v3/ticker/24hr",
        "book_ticker": "/api/v3/ticker/bookTicker",
    },
    "usdm": {
        "time": "/fapi/v1/time",
        "exchange_info": "/fapi/v1/exchangeInfo",
        "klines": "/fapi/v1/klines",
        "ticker_24h": "/fapi/v1/ticker/24hr",
        "book_ticker": "/fapi/v1/ticker/bookTicker",
    },
}

_STATUS_NORMALIZATION = {
    "TRADING": "trading",
    "BREAK": "halted",
    "PENDING_TRADING": "halted",
    "SETTLING": "halted",
    "DELIVERING": "halted",
    "CLOSE": "delisted",
    "DELISTED": "delisted",
}


class BinancePublicError(Exception):
    """Normalized public-endpoint error; no URL, key or raw body is embedded."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status_code: int | None = None,
        provider_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.kind = kind  # rate_limited | ip_banned | timeout | retryable | permanent
        self.message = message
        self.status_code = status_code
        self.provider_code = provider_code
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in ("rate_limited", "retryable", "timeout")


@dataclass(frozen=True)
class WeightObservation:
    market: str
    used_weight: int | None
    used_weight_1m: int | None
    observed_at: str  # ISO-UTC receive time

    @property
    def max_weight(self) -> int | None:
        values = [v for v in (self.used_weight, self.used_weight_1m) if v is not None]
        return max(values) if values else None


@dataclass(frozen=True)
class ServerTime:
    market: str
    server_time_ms: int
    received_at: str


@dataclass(frozen=True)
class Kline:
    market: str
    symbol: str  # raw provider venue symbol
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_volume: Decimal
    quote_volume: Decimal
    trades: int
    taker_buy_base_volume: Decimal
    taker_buy_quote_volume: Decimal
    received_at: str

    @property
    def closed(self) -> bool:
        """A candle is final only when its close time is strictly past."""
        received_ms = int(datetime.fromisoformat(self.received_at).timestamp() * 1000)
        return self.close_time_ms < received_ms


@dataclass(frozen=True)
class Ticker24h:
    market: str
    symbol: str
    last_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    high_price: Decimal
    low_price: Decimal
    base_volume: Decimal  # rolling 24h cumulative; never sum across polls
    quote_volume: Decimal
    open_time_ms: int | None = None
    close_time_ms: int | None = None
    received_at: str = ""


@dataclass(frozen=True)
class BookTicker:
    market: str
    symbol: str
    bid_price: Decimal
    bid_qty: Decimal
    ask_price: Decimal
    ask_qty: Decimal
    received_at: str = ""


@dataclass(frozen=True)
class ExchangeInfoSymbol:
    market: str
    provider_symbol: str
    status: str  # normalized: trading | halted | delisted
    base_asset: str
    quote_asset: str
    margin_asset: str | None = None
    kind: str = "spot"  # spot | perpetual | future
    base_asset_precision: int | None = None
    quote_asset_precision: int | None = None
    price_precision: int | None = None
    quantity_precision: int | None = None
    onboard_date_ms: int | None = None
    delivery_date_ms: int | None = None
    contract_type: str | None = None
    filters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangeInfo:
    market: str
    timezone: str
    symbols: list[ExchangeInfoSymbol]
    rate_limits: list[dict]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any, field_name: str) -> Decimal:
    if value is None:
        raise BinancePublicError("permanent", f"missing decimal field {field_name!r} in provider payload")
    return Decimal(str(value))


def _int_ms(value: Any, field_name: str) -> int:
    if value is None:
        raise BinancePublicError("permanent", f"missing timestamp field {field_name!r} in provider payload")
    return int(value)


def parse_kline_row(market: str, symbol: str, interval: str, row: list, received_at: str | None = None) -> Kline:
    """Parse one 12-column kline row (shape frozen by the WP 0.2 fixtures)."""
    if not isinstance(row, list) or len(row) < 12:
        raise BinancePublicError("permanent", "kline row does not match the documented 12-column shape")
    return Kline(
        market=market,
        symbol=symbol,
        interval=interval,
        open_time_ms=_int_ms(row[0], "openTime"),
        close_time_ms=_int_ms(row[6], "closeTime"),
        open=_decimal(row[1], "open"),
        high=_decimal(row[2], "high"),
        low=_decimal(row[3], "low"),
        close=_decimal(row[4], "close"),
        base_volume=_decimal(row[5], "volume"),
        quote_volume=_decimal(row[7], "quoteVolume"),
        trades=_int_ms(row[8], "numberOfTrades"),
        taker_buy_base_volume=_decimal(row[9], "takerBuyBaseVolume"),
        taker_buy_quote_volume=_decimal(row[10], "takerBuyQuoteVolume"),
        received_at=received_at or _utcnow_iso(),
    )


def parse_exchange_info(market: str, payload: dict) -> ExchangeInfo:
    symbols: list[ExchangeInfoSymbol] = []
    for raw in payload.get("symbols", []):
        contract_type = raw.get("contractType")
        if market == "spot":
            kind = "spot"
        elif contract_type == "PERPETUAL":
            kind = "perpetual"
        else:
            kind = "future"
        symbols.append(
            ExchangeInfoSymbol(
                market=market,
                provider_symbol=raw["symbol"],
                status=_STATUS_NORMALIZATION.get(raw.get("status", ""), "inactive"),
                base_asset=raw["baseAsset"],
                quote_asset=raw["quoteAsset"],
                margin_asset=raw.get("marginAsset"),
                kind=kind,
                base_asset_precision=raw.get("baseAssetPrecision"),
                quote_asset_precision=raw.get("quoteAssetPrecision") or raw.get("quotePrecision"),
                price_precision=raw.get("pricePrecision"),
                quantity_precision=raw.get("quantityPrecision"),
                onboard_date_ms=raw.get("onboardDate"),
                delivery_date_ms=raw.get("deliveryDate"),
                contract_type=contract_type,
                filters={f["filterType"]: {k: v for k, v in f.items() if k != "filterType"} for f in raw.get("filters", [])},
            )
        )
    return ExchangeInfo(
        market=market,
        timezone=payload.get("timezone", ""),
        symbols=symbols,
        rate_limits=payload.get("rateLimits", []),
    )


class BinancePublicClient:
    """Minimal typed public client. Never sends credentials."""

    def __init__(
        self,
        *,
        spot_base_url: str = DEFAULT_SPOT_BASE_URL,
        usdm_base_url: str = DEFAULT_USDM_BASE_URL,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_urls = {"spot": spot_base_url.rstrip("/"), "usdm": usdm_base_url.rstrip("/")}
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._transport = transport
        self.last_weight: WeightObservation | None = None

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, transport=self._transport)

    def _record_weight(self, market: str, headers: httpx.Headers) -> None:
        def _parse(name: str) -> int | None:
            raw = headers.get(name)
            if raw is None or raw == "":
                return None
            try:
                return int(raw)
            except ValueError:
                return None

        self.last_weight = WeightObservation(
            market=market,
            used_weight=_parse("x-mbx-used-weight"),
            used_weight_1m=_parse("x-mbx-used-weight-1m"),
            observed_at=_utcnow_iso(),
        )

    def _request(self, market: str, endpoint: str, params: dict | None = None) -> Any:
        if market not in MARKETS:
            raise ValueError(f"unsupported market {market!r}; expected one of {MARKETS}")
        url = self._base_urls[market] + _MARKET_PATHS[market][endpoint]
        attempt = 0
        last_error: BinancePublicError | None = None
        while attempt <= self._max_retries:
            if last_error is not None:
                sleep_for = last_error.retry_after if last_error.retry_after is not None else self._backoff * (2 ** (attempt - 1))
                time.sleep(min(sleep_for, 30.0))
            try:
                with self._client() as client:
                    response = client.get(url, params=params)
            except httpx.TimeoutException as exc:
                last_error = BinancePublicError("timeout", f"public request timed out: {type(exc).__name__}")
                attempt += 1
                continue
            except httpx.TransportError as exc:
                last_error = BinancePublicError("retryable", f"network error: {type(exc).__name__}")
                attempt += 1
                continue
            self._record_weight(market, response.headers)
            if response.status_code == 200:
                return response.json()
            provider_code: int | None = None
            message = f"http {response.status_code}"
            try:
                body = response.json()
                provider_code = body.get("code")
                message = body.get("msg") or message
            except ValueError:
                pass
            retry_after: float | None = None
            raw_retry = response.headers.get("retry-after")
            if raw_retry:
                try:
                    retry_after = float(raw_retry)
                except ValueError:
                    retry_after = None
            if response.status_code == 429:
                last_error = BinancePublicError(
                    "rate_limited", message, status_code=429, provider_code=provider_code, retry_after=retry_after
                )
                attempt += 1
                continue
            if response.status_code == 418:
                raise BinancePublicError(
                    "ip_banned", message, status_code=418, provider_code=provider_code, retry_after=retry_after
                )
            if 500 <= response.status_code < 600:
                last_error = BinancePublicError(
                    "retryable", message, status_code=response.status_code, provider_code=provider_code
                )
                attempt += 1
                continue
            raise BinancePublicError(
                "permanent", message, status_code=response.status_code, provider_code=provider_code
            )
        raise last_error or BinancePublicError("retryable", "request failed")

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------

    def server_time(self, market: str = "spot") -> ServerTime:
        payload = self._request(market, "time")
        return ServerTime(
            market=market,
            server_time_ms=_int_ms(payload.get("serverTime"), "serverTime"),
            received_at=_utcnow_iso(),
        )

    def exchange_info(self, market: str = "spot", symbol: str | None = None) -> ExchangeInfo:
        params = {"symbol": symbol} if symbol else None
        return parse_exchange_info(market, self._request(market, "exchange_info", params))

    def klines(
        self,
        market: str,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
    ) -> list[Kline]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        received_at = _utcnow_iso()
        payload = self._request(market, "klines", params)
        if not isinstance(payload, list):
            raise BinancePublicError("permanent", "klines payload is not a list")
        return [parse_kline_row(market, symbol, interval, row, received_at) for row in payload]

    def ticker_24h(self, market: str, symbol: str) -> Ticker24h:
        payload = self._request(market, "ticker_24h", {"symbol": symbol})
        return Ticker24h(
            market=market,
            symbol=payload["symbol"],
            last_price=_decimal(payload.get("lastPrice"), "lastPrice"),
            bid_price=_decimal(payload.get("bidPrice"), "bidPrice"),
            ask_price=_decimal(payload.get("askPrice"), "askPrice"),
            high_price=_decimal(payload.get("highPrice"), "highPrice"),
            low_price=_decimal(payload.get("lowPrice"), "lowPrice"),
            base_volume=_decimal(payload.get("volume"), "volume"),
            quote_volume=_decimal(payload.get("quoteVolume"), "quoteVolume"),
            open_time_ms=payload.get("openTime"),
            close_time_ms=payload.get("closeTime"),
            received_at=_utcnow_iso(),
        )

    def book_ticker(self, market: str, symbol: str) -> BookTicker:
        payload = self._request(market, "book_ticker", {"symbol": symbol})
        return BookTicker(
            market=market,
            symbol=payload["symbol"],
            bid_price=_decimal(payload.get("bidPrice"), "bidPrice"),
            bid_qty=_decimal(payload.get("bidQty"), "bidQty"),
            ask_price=_decimal(payload.get("askPrice"), "askPrice"),
            ask_qty=_decimal(payload.get("askQty"), "askQty"),
            received_at=_utcnow_iso(),
        )
