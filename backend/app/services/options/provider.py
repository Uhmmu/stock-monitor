"""Defensive yfinance options-chain adapter.

Yahoo's schema is not a contract.  All provider values are normalized here so
analytics and persistence never need to understand pandas or yfinance objects.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import UTC, date, datetime, timedelta
import json
import logging
import math
import re
import time
from typing import Any, Callable, Mapping, Protocol

import yfinance as yf

logger = logging.getLogger(__name__)

MAX_EXPIRATIONS = 2
MAX_EXPIRATION_CANDIDATES = 12
MAX_CONTRACTS_PER_EXPIRATION = 300
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRIES = 2
STALE_DAYS = 7
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,31}$")


class UnderlyingQuoteValidator(Protocol):
    def __call__(self, symbol: str) -> Mapping[str, Any] | None: ...


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _int_nonnegative(value: Any) -> int | None:
    number = _finite(value)
    if number is None or number < 0:
        return None
    return int(number)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromtimestamp(float(text), UTC).date()
        except (TypeError, ValueError, OverflowError, OSError):
            return None


def _json_value(value: Any) -> Any:
    """Convert pandas/numpy/provider values to finite JSON-safe primitives."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return _iso(value)
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except Exception:
            return None
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return str(value)


def _records(table: Any) -> list[dict[str, Any]]:
    if table is None:
        return []
    if isinstance(table, Mapping):
        table = table.get("data", table.get("rows", table))
        if isinstance(table, Mapping):
            table = [table]
    if hasattr(table, "to_dict"):
        try:
            table = table.to_dict("records")
        except (TypeError, ValueError):
            table = []
    return [dict(row) for row in (table or []) if isinstance(row, Mapping)]


def _contract(row: Mapping[str, Any]) -> dict[str, Any] | None:
    lowered = {str(key).casefold().replace(" ", ""): value for key, value in row.items()}
    strike = _positive(lowered.get("strike"))
    if strike is None:
        return None
    iv_raw = lowered.get("impliedvolatility") if "impliedvolatility" in lowered else lowered.get("iv")
    oi_raw = lowered.get("openinterest") if "openinterest" in lowered else lowered.get("open_interest")
    trade_raw = lowered.get("lasttradedate") if "lasttradedate" in lowered else lowered.get("lasttrade")
    iv = _finite(iv_raw)
    # Yahoo occasionally emits 0, NaN, or absurd sentinels.  Retain the row,
    # but preserve the IV as missing rather than fabricating a useful number.
    if iv is not None and not 0 < iv <= 5:
        iv = None
    last_trade = _iso(trade_raw)
    result = {
        "contract_symbol": str(lowered.get("contractsymbol") or "") or None,
        "strike": strike,
        "last_price": _positive(lowered.get("lastprice")),
        "bid": _positive(lowered.get("bid")),
        "ask": _positive(lowered.get("ask")),
        "volume": _int_nonnegative(lowered.get("volume")),
        "open_interest": _int_nonnegative(oi_raw),
        "implied_volatility": iv,
        "in_the_money": bool(lowered.get("inthemoney")) if lowered.get("inthemoney") is not None else None,
        "last_trade_date": last_trade,
    }
    return _json_value(result)


def _contract_rank(row: dict[str, Any], underlying_price: float | None) -> tuple[float, float, str]:
    strike = float(row.get("strike") or 0)
    distance = abs(strike - underlying_price) if underlying_price else strike
    liquidity = float(row.get("volume") or 0) + float(row.get("open_interest") or 0) * 0.01
    return (distance, -liquidity, str(row.get("contract_symbol") or ""))


def _bounded_contracts(rows: Any, underlying_price: float | None, limit: int) -> list[dict[str, Any]]:
    normalized = [item for row in _records(rows) if (item := _contract(row)) is not None]
    normalized.sort(key=lambda item: _contract_rank(item, underlying_price))
    return normalized[: max(0, limit)]


def _call_with_timeout(fn: Callable[[], Any], timeout: float) -> Any:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="options-provider")
    future = executor.submit(fn)
    try:
        return future.result(timeout=max(0.1, float(timeout)))
    except FutureTimeout as exc:
        future.cancel()
        raise TimeoutError("options provider request timed out") from exc
    finally:
        # Do not wait for a stuck network worker; the caller's timeout must be real.
        executor.shutdown(wait=False, cancel_futures=True)


def _ticker_call(ticker: Any, method: str, *args: Any, timeout: float, **kwargs: Any) -> Any:
    return _call_with_timeout(lambda: getattr(ticker, method)(*args, **kwargs), timeout)


def _underlying_price(ticker: Any, timeout: float) -> float | None:
    for source in ("fast_info", "info"):
        try:
            value = _call_with_timeout(lambda: getattr(ticker, source), timeout)
            if callable(value):
                value = _call_with_timeout(value, timeout)
            if isinstance(value, Mapping):
                for key in ("lastPrice", "last_price", "regularMarketPrice", "currentPrice", "previousClose"):
                    if (number := _positive(value.get(key))) is not None:
                        return number
        except Exception:
            continue
    try:
        frame = _ticker_call(ticker, "history", period="1d", interval="1m", timeout=timeout)
        records = _records(frame)
        for row in reversed(records):
            if (number := _positive(row.get("Close") or row.get("close"))) is not None:
                return number
    except Exception:
        pass
    return None


def _meaningful_expirations(value: Any, today: date) -> list[str]:
    candidates: list[tuple[date, str]] = []
    for raw in value or ():
        day = _date(raw)
        if day and day >= today:
            candidates.append((day, day.isoformat()))
    return [text for _, text in sorted(set(candidates))[:MAX_EXPIRATION_CANDIDATES]]


def normalize_options_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a provider-like payload without making network calls."""
    result = {str(key): _json_value(value) for key, value in dict(payload).items()}
    result.setdefault("provider", "yfinance")
    result.setdefault("fetched_at", datetime.now(UTC).isoformat())
    return result


def fetch_options_chain(
    symbol: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    timeout: float | None = None,
    retries: int = DEFAULT_RETRIES,
    max_expirations: int = MAX_EXPIRATIONS,
    max_contracts: int = MAX_CONTRACTS_PER_EXPIRATION,
    quote_validator: UnderlyingQuoteValidator | None = None,
    ticker_factory: Callable[[str], Any] = yf.Ticker,
) -> dict[str, Any]:
    """Fetch at most two meaningful expirations and bounded filtered contracts."""
    value = str(symbol or "").strip().upper()
    if not value or not _SYMBOL_RE.fullmatch(value):
        raise ValueError(f"invalid options symbol: {symbol!r}")
    if timeout is not None:
        timeout_seconds = float(timeout)
    contract_limit = max(1, min(MAX_CONTRACTS_PER_EXPIRATION, int(max_contracts)))
    started = time.monotonic()
    fetched_at = datetime.now(UTC)
    base: dict[str, Any] = {
        "symbol": value,
        "provider": "yfinance",
        "fetched_at": fetched_at.isoformat(),
        "underlying_price": None,
        "expirations": [],
        "warnings": [],
    }
    try:
        ticker = _call_with_timeout(lambda: ticker_factory(value), timeout_seconds)
        price = _underlying_price(ticker, timeout_seconds)
        base["underlying_price"] = price
        expiration_value = None
        for attempt in range(max(1, int(retries) + 1)):
            try:
                expiration_value = _call_with_timeout(lambda: ticker.options, timeout_seconds)
                break
            except Exception:
                if attempt >= int(retries):
                    raise
                time.sleep(min(0.5 * (2 ** attempt), 2.0))
        candidates = _meaningful_expirations(expiration_value, fetched_at.date())
        if not candidates:
            base["status"] = "NO_OPTIONS" if not expiration_value else "NO_VALID_EXPIRATION"
            base["warnings"].append("no_future_expiration")
            return base
        chain_errors = 0
        for expiration in candidates:
            if len(base["expirations"]) >= max(1, min(MAX_EXPIRATIONS, int(max_expirations))):
                break
            chain = None
            for attempt in range(max(1, int(retries) + 1)):
                try:
                    chain = _ticker_call(ticker, "option_chain", expiration, timeout=timeout_seconds)
                    break
                except Exception as exc:
                    if attempt >= int(retries):
                        chain_errors += 1
                        logger.warning("options_chain_fetch_failed symbol=%s expiration=%s error=%s", value, expiration, type(exc).__name__)
                    else:
                        time.sleep(min(0.5 * (2 ** attempt), 2.0))
            if chain is None:
                continue
            if isinstance(chain, Mapping):
                calls_raw = chain.get("calls")
                puts_raw = chain.get("puts")
            elif isinstance(chain, (tuple, list)) and len(chain) >= 2:
                calls_raw, puts_raw = chain[0], chain[1]
            else:
                calls_raw = getattr(chain, "calls", None)
                puts_raw = getattr(chain, "puts", None)
            # A full expiration is capped at 300 rows total; favor contracts
            # closest to spot and then liquid contracts on each side.
            calls = _bounded_contracts(calls_raw, price, contract_limit // 2)
            puts = _bounded_contracts(puts_raw, price, contract_limit - len(calls))
            if not calls and not puts:
                continue
            base["expirations"].append({
                "expiration": expiration,
                "days_to_expiration": max(0, (_date(expiration) - fetched_at.date()).days),
                "calls": calls,
                "puts": puts,
                "contract_count": len(calls) + len(puts),
            })
        if not base["expirations"]:
            base["status"] = "PROVIDER_ERROR" if chain_errors >= len(candidates) else "NO_VALID_EXPIRATION"
            base["warnings"].append("provider_chain_error" if base["status"] == "PROVIDER_ERROR" else "empty_or_malformed_option_chain")
            return base
        base["nearest_expiration"] = base["expirations"][0]["expiration"]
        base["next_expiration"] = (base["expirations"][1]["expiration"] if len(base["expirations"]) > 1 else None)
        base["calls"] = base["expirations"][0]["calls"]
        base["puts"] = base["expirations"][0]["puts"]
        all_contracts = [contract for item in base["expirations"] for side in ("calls", "puts") for contract in item[side]]
        trade_dates = [_date(item.get("last_trade_date")) for item in all_contracts]
        trade_dates = [item for item in trade_dates if item is not None]
        latest_trade = max(trade_dates, default=None)
        base["status"] = "STALE_DATA" if latest_trade and latest_trade < fetched_at.date() - timedelta(days=STALE_DAYS) else "OK"
        if base["status"] == "STALE_DATA":
            base["warnings"].append("all_quotes_are_stale")
        if quote_validator is not None:
            try:
                validation = quote_validator(value)
                base["underlying_quote_validation"] = _json_value(dict(validation or {}))
            except Exception as exc:
                base["warnings"].append("underlying_quote_validation_failed")
                base["underlying_quote_validation"] = {"status": "error", "error": type(exc).__name__}
        return base
    except TimeoutError:
        base["status"] = "PROVIDER_ERROR"
        base["error_code"] = "TIMEOUT"
        base["warnings"].append("provider_timeout")
        return base
    except Exception as exc:
        logger.warning("options_provider_error symbol=%s error=%s", value, type(exc).__name__)
        base["status"] = "PROVIDER_ERROR"
        base["error_code"] = type(exc).__name__
        base["warnings"].append("provider_error")
        return base
    finally:
        logger.info(
            "options_refresh_completed symbol=%s elapsed_ms=%d",
            value,
            int((time.monotonic() - started) * 1000),
        )


fetch_yfinance_options = fetch_options_chain
fetch_yahoo_options = fetch_options_chain
fetch_yfinance_option_chain = fetch_options_chain
get_options_chain = fetch_options_chain

__all__ = [
    "UnderlyingQuoteValidator", "fetch_options_chain", "fetch_yahoo_options", "fetch_yfinance_option_chain", "fetch_yfinance_options", "get_options_chain",
    "normalize_options_payload",
]
