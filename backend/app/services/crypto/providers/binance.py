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
        "mark_klines": "/fapi/v1/markPriceKlines",
        "index_klines": "/fapi/v1/indexPriceKlines",
        "premium_klines": "/fapi/v1/premiumIndexKlines",
        "ticker_24h": "/fapi/v1/ticker/24hr",
        "book_ticker": "/fapi/v1/ticker/bookTicker",
        "premium_index": "/fapi/v1/premiumIndex",
        "funding_rate": "/fapi/v1/fundingRate",
        "open_interest": "/fapi/v1/openInterest",
        "open_interest_hist": "/futures/data/openInterestHist",
        "global_long_short_ratio": "/futures/data/globalLongShortAccountRatio",
        "taker_long_short_ratio": "/futures/data/takerlongshortRatio",
    },
}

_STATUS_NORMALIZATION = {
    "TRADING": "trading",
    "BREAK": "halted",
    "PENDING_TRADING": "halted",
    "PRE_DELIVERING": "halted",
    "SETTLING": "halted",
    "DELIVERING": "halted",
    "PRE_SETTLE": "halted",
    "ENACTING": "halted",
    "ADJUST": "halted",
    "DELIVERED": "delisted",
    "EXPIRED": "delisted",
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
    price_type: str = "trade"

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
    bid_price: Decimal | None
    ask_price: Decimal | None
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
    contract_size: Decimal | None = None
    filters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangeInfo:
    market: str
    timezone: str
    symbols: list[ExchangeInfoSymbol]
    rate_limits: list[dict]


@dataclass(frozen=True)
class PremiumIndex:
    market: str
    symbol: str
    mark_price: Decimal
    index_price: Decimal
    estimated_settle_price: Decimal | None
    last_funding_rate: Decimal | None
    interest_rate: Decimal | None
    next_funding_time_ms: int | None
    event_time_ms: int | None
    received_at: str


@dataclass(frozen=True)
class FundingRate:
    market: str
    symbol: str
    funding_time_ms: int
    funding_rate: Decimal
    mark_price: Decimal | None
    rate_type: str | None
    received_at: str


@dataclass(frozen=True)
class OpenInterest:
    market: str
    symbol: str
    open_interest: Decimal
    event_time_ms: int
    received_at: str


@dataclass(frozen=True)
class OpenInterestHistory:
    market: str
    symbol: str
    sum_open_interest: Decimal
    sum_open_interest_value: Decimal
    circulating_supply: Decimal | None
    event_time_ms: int
    received_at: str


@dataclass(frozen=True)
class GlobalLongShortRatio:
    market: str
    symbol: str
    period: str
    long_short_ratio: Decimal
    long_account: Decimal
    short_account: Decimal
    event_time_ms: int
    received_at: str


@dataclass(frozen=True)
class TakerBuySellVolume:
    market: str
    symbol: str
    period: str
    buy_volume: Decimal
    sell_volume: Decimal
    buy_sell_ratio: Decimal | None
    event_time_ms: int
    pair: str | None
    contract_type: str | None
    received_at: str


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any, field_name: str) -> Decimal:
    if value is None:
        raise BinancePublicError("permanent", f"missing decimal field {field_name!r} in provider payload")
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _int_ms(value: Any, field_name: str) -> int:
    if value is None:
        raise BinancePublicError("permanent", f"missing timestamp field {field_name!r} in provider payload")
    return int(value)


def parse_kline_row(
    market: str,
    symbol: str,
    interval: str,
    row: list,
    received_at: str | None = None,
    *,
    price_type: str = "trade",
) -> Kline:
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
        price_type=price_type,
    )


def parse_exchange_info(market: str, payload: dict) -> ExchangeInfo:
    symbols: list[ExchangeInfoSymbol] = []
    for raw in payload.get("symbols", []):
        contract_type = raw.get("contractType")
        normalized_contract_type = str(contract_type or "").upper()
        if market == "spot":
            kind = "spot"
        elif normalized_contract_type == "PERPETUAL":
            kind = "perpetual"
        else:
            kind = "future"
        symbols.append(
            ExchangeInfoSymbol(
                market=market,
                provider_symbol=raw["symbol"],
                status=_STATUS_NORMALIZATION.get(str(raw.get("status", "")).upper(), "inactive"),
                base_asset=raw["baseAsset"],
                quote_asset=raw["quoteAsset"],
                margin_asset=raw.get("marginAsset") or raw.get("settlementAsset"),
                kind=kind,
                base_asset_precision=raw.get("baseAssetPrecision"),
                quote_asset_precision=raw.get("quoteAssetPrecision") or raw.get("quotePrecision"),
                price_precision=raw.get("pricePrecision"),
                quantity_precision=raw.get("quantityPrecision"),
                onboard_date_ms=raw.get("onboardDate"),
                delivery_date_ms=raw.get("deliveryDate"),
                contract_type=contract_type,
                contract_size=_optional_decimal(raw.get("contractSize")),
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

    @staticmethod
    def _time_params(
        symbol: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol, **extra}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        if limit is not None:
            params["limit"] = limit
        return params

    def _kline_endpoint(
        self,
        market: str,
        symbol: str,
        interval: str,
        *,
        endpoint: str,
        price_type: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
    ) -> list[Kline]:
        params = self._time_params(
            symbol,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
            interval=interval,
        )
        if endpoint == "index_klines":
            params["pair"] = params.pop("symbol")
        received_at = _utcnow_iso()
        payload = self._request(market, endpoint, params)
        if not isinstance(payload, list):
            raise BinancePublicError("permanent", "klines payload is not a list")
        return [
            parse_kline_row(market, symbol, interval, row, received_at, price_type=price_type)
            for row in payload
        ]

    def klines(
        self,
        market: str,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
        price_type: str = "trade",
    ) -> list[Kline]:
        endpoint_by_price_type = {
            "trade": "klines",
            "mark": "mark_klines",
            "index": "index_klines",
            "premium": "premium_klines",
        }
        if price_type not in endpoint_by_price_type:
            raise ValueError("price_type must be trade, mark, index or premium")
        if market == "spot" and price_type != "trade":
            raise ValueError("spot market only supports trade klines")
        return self._kline_endpoint(
            market,
            symbol,
            interval,
            endpoint=endpoint_by_price_type[price_type],
            price_type=price_type,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
        )

    def mark_price_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
        market: str = "usdm",
    ) -> list[Kline]:
        self._require_usdm(market)
        return self.klines(
            market,
            symbol,
            interval,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
            price_type="mark",
        )

    def index_price_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
        market: str = "usdm",
    ) -> list[Kline]:
        self._require_usdm(market)
        return self.klines(
            market,
            symbol,
            interval,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
            price_type="index",
        )

    def premium_index_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
        market: str = "usdm",
    ) -> list[Kline]:
        self._require_usdm(market)
        return self.klines(
            market,
            symbol,
            interval,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
            price_type="premium",
        )

    @staticmethod
    def _require_usdm(market: str) -> None:
        if market != "usdm":
            raise ValueError("USD-M derivative endpoint requires market='usdm'")

    def premium_index(self, symbol: str, *, market: str = "usdm") -> PremiumIndex:
        self._require_usdm(market)
        payload = self._request(market, "premium_index", {"symbol": symbol})
        return PremiumIndex(
            market=market,
            symbol=payload["symbol"],
            mark_price=_decimal(payload.get("markPrice"), "markPrice"),
            index_price=_decimal(payload.get("indexPrice"), "indexPrice"),
            estimated_settle_price=_optional_decimal(payload.get("estimatedSettlePrice")),
            last_funding_rate=_optional_decimal(payload.get("lastFundingRate")),
            interest_rate=_optional_decimal(payload.get("interestRate")),
            next_funding_time_ms=_optional_int(payload.get("nextFundingTime")),
            event_time_ms=_optional_int(payload.get("time")),
            received_at=_utcnow_iso(),
        )

    def funding_rate_history(
        self,
        symbol: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
        market: str = "usdm",
    ) -> list[FundingRate]:
        self._require_usdm(market)
        payload = self._request(
            market,
            "funding_rate",
            self._time_params(symbol, start_time_ms=start_time_ms, end_time_ms=end_time_ms, limit=limit),
        )
        if not isinstance(payload, list):
            raise BinancePublicError("permanent", "funding rate payload is not a list")
        received_at = _utcnow_iso()
        return [
            FundingRate(
                market=market,
                symbol=row["symbol"],
                funding_time_ms=_int_ms(row.get("fundingTime"), "fundingTime"),
                funding_rate=_decimal(row.get("fundingRate"), "fundingRate"),
                mark_price=_optional_decimal(row.get("markPrice")),
                rate_type=row.get("rateType"),
                received_at=received_at,
            )
            for row in payload
        ]

    def open_interest(self, symbol: str, *, market: str = "usdm") -> OpenInterest:
        self._require_usdm(market)
        payload = self._request(market, "open_interest", {"symbol": symbol})
        return OpenInterest(
            market=market,
            symbol=payload["symbol"],
            open_interest=_decimal(payload.get("openInterest"), "openInterest"),
            event_time_ms=_int_ms(payload.get("time"), "time"),
            received_at=_utcnow_iso(),
        )

    def open_interest_history(
        self,
        symbol: str,
        *,
        period: str = "1h",
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
        market: str = "usdm",
    ) -> list[OpenInterestHistory]:
        self._require_usdm(market)
        payload = self._request(
            market,
            "open_interest_hist",
            self._time_params(
                symbol,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                limit=limit,
                period=period,
            ),
        )
        if not isinstance(payload, list):
            raise BinancePublicError("permanent", "open interest history payload is not a list")
        received_at = _utcnow_iso()
        return [
            OpenInterestHistory(
                market=market,
                symbol=row["symbol"],
                sum_open_interest=_decimal(row.get("sumOpenInterest"), "sumOpenInterest"),
                sum_open_interest_value=_decimal(
                    row.get("sumOpenInterestValue"), "sumOpenInterestValue"
                ),
                circulating_supply=_optional_decimal(row.get("CMCCirculatingSupply")),
                event_time_ms=_int_ms(row.get("timestamp"), "timestamp"),
                received_at=received_at,
            )
            for row in payload
        ]

    def global_long_short_ratio(
        self,
        symbol: str,
        *,
        period: str = "1h",
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
        market: str = "usdm",
    ) -> list[GlobalLongShortRatio]:
        self._require_usdm(market)
        payload = self._request(
            market,
            "global_long_short_ratio",
            self._time_params(
                symbol,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                limit=limit,
                period=period,
            ),
        )
        if not isinstance(payload, list):
            raise BinancePublicError("permanent", "global long-short payload is not a list")
        received_at = _utcnow_iso()
        return [
            GlobalLongShortRatio(
                market=market,
                symbol=row["symbol"],
                period=row.get("period", period),
                long_short_ratio=_decimal(row.get("longShortRatio"), "longShortRatio"),
                long_account=_decimal(row.get("longAccount"), "longAccount"),
                short_account=_decimal(row.get("shortAccount"), "shortAccount"),
                event_time_ms=_int_ms(row.get("timestamp"), "timestamp"),
                received_at=received_at,
            )
            for row in payload
        ]

    def taker_buy_sell_volume(
        self,
        symbol: str,
        *,
        period: str = "1h",
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
        market: str = "usdm",
    ) -> list[TakerBuySellVolume]:
        self._require_usdm(market)
        payload = self._request(
            market,
            "taker_long_short_ratio",
            self._time_params(
                symbol,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                limit=limit,
                period=period,
            ),
        )
        if not isinstance(payload, list):
            raise BinancePublicError("permanent", "taker buy/sell payload is not a list")
        received_at = _utcnow_iso()
        rows: list[TakerBuySellVolume] = []
        for row in payload:
            buy = _decimal(row.get("buyVol", row.get("takerBuyVol")), "buyVol")
            sell = _decimal(row.get("sellVol", row.get("takerSellVol")), "sellVol")
            ratio = _optional_decimal(row.get("buySellRatio"))
            rows.append(
                TakerBuySellVolume(
                    market=market,
                    symbol=row.get("symbol", symbol),
                    period=row.get("period", period),
                    buy_volume=buy,
                    sell_volume=sell,
                    buy_sell_ratio=ratio,
                    event_time_ms=_int_ms(row.get("timestamp"), "timestamp"),
                    pair=row.get("pair"),
                    contract_type=row.get("contractType"),
                    received_at=received_at,
                )
            )
        return rows

    def ticker_24h(self, market: str, symbol: str) -> Ticker24h:
        payload = self._request(market, "ticker_24h", {"symbol": symbol})
        return Ticker24h(
            market=market,
            symbol=payload["symbol"],
            last_price=_decimal(payload.get("lastPrice"), "lastPrice"),
            bid_price=_optional_decimal(payload.get("bidPrice")),
            ask_price=_optional_decimal(payload.get("askPrice")),
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
