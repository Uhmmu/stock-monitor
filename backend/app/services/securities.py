from __future__ import annotations

import json
import re
import threading
import time
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

import httpx
import yfinance as yf
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Security
from app.services.market_data import fetch_stock_profile

_CACHE_TTL = 15 * 60
_CACHE_LIMIT = 256
_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()
_redis_client = None
_redis_disabled = False

_EXCHANGE_META = {
    "NMS": ("NASDAQ", "US", "US"), "NGM": ("NASDAQ", "US", "US"),
    "NCM": ("NASDAQ", "US", "US"), "NYQ": ("NYSE", "US", "US"),
    "ASE": ("NYSE American", "US", "US"), "PCX": ("NYSE Arca", "US", "US"),
    "JPX": ("Tokyo", "JP", "JP"), "HKG": ("Hong Kong", "HK", "HK"),
}
_TYPE_MAP = {
    "EQUITY": "EQUITY", "ETF": "ETF", "INDEX": "INDEX", "MUTUALFUND": "MUTUALFUND",
    "CRYPTOCURRENCY": "CRYPTOCURRENCY", "FUTURE": "FUTURE", "OPTION": "OPTION",
}


class SecuritySearchUnavailable(RuntimeError):
    pass


def _redis() -> Any | None:
    global _redis_client, _redis_disabled
    if _redis_disabled:
        return None
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(get_settings().redis_url, socket_connect_timeout=.2, socket_timeout=.2)
        except Exception:
            _redis_disabled = True
            return None
    return _redis_client


def _redis_get(key: str) -> list[dict] | None:
    client = _redis()
    if not client:
        return None
    try:
        payload = client.get(key)
        return json.loads(payload) if payload else None
    except Exception:
        return None


def _redis_set(key: str, rows: list[dict]) -> None:
    client = _redis()
    if not client:
        return
    try:
        client.setex(key, _CACHE_TTL, json.dumps(rows, ensure_ascii=False))
    except Exception:
        pass


def normalize_query(value: str) -> str:
    return " ".join((value or "").strip().split())[:80]


def _local_symbol(symbol: str) -> str:
    return symbol.rsplit(".", 1)[0] if "." in symbol else symbol


def _country_from_symbol(symbol: str) -> tuple[str | None, str | None]:
    suffix = symbol.rsplit(".", 1)[1].upper() if "." in symbol else ""
    return {"T": ("JP", "JP"), "HK": ("HK", "HK"), "L": ("GB", "GB"),
            "TO": ("CA", "CA"), "AX": ("AU", "AU"), "PA": ("FR", "FR"),
            "DE": ("DE", "DE")}.get(suffix, (None, None))


def yahoo_result(item: dict[str, Any]) -> dict | None:
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    exchange_code = str(item.get("exchange") or "").strip().upper() or None
    exchange_meta = _EXCHANGE_META.get(exchange_code or "", (item.get("exchDisp"), None, None))
    suffix_market, suffix_country = _country_from_symbol(symbol)
    quote_type = str(item.get("quoteType") or "EQUITY").upper()
    name = item.get("longname") or item.get("shortname") or item.get("name") or symbol
    if quote_type == "EQUITY" and re.search(r"\bADR\b", str(name), re.IGNORECASE):
        quote_type = "ADR"
    market = suffix_market or exchange_meta[1]
    country = suffix_country or exchange_meta[2]
    currency = item.get("currency") or {"US": "USD", "JP": "JPY", "HK": "HKD"}.get(country or "")
    return {
        "provider_key": f"yahoo:{symbol}", "security_id": None,
        "display_symbol": symbol, "display_name": str(name), "local_symbol": _local_symbol(symbol),
        "exchange": exchange_meta[0] or exchange_code, "exchange_code": exchange_code,
        "market": market, "country_code": country,
        "currency": currency, "instrument_type": _TYPE_MAP.get(quote_type, quote_type),
        "yahoo_symbol": symbol, "finnhub_symbol": None, "source": "yahoo", "is_local": False,
    }


def finnhub_search(query: str, limit: int) -> list[dict]:
    token = get_settings().finnhub_api_key
    if not token:
        return []
    response = httpx.get("https://finnhub.io/api/v1/search", params={"q": query, "token": token}, timeout=5.0)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("result", []) if isinstance(payload, dict) else []
    output = []
    for item in rows[:limit]:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        output.append({
            "provider_key": f"finnhub:{symbol}", "security_id": None,
            "display_symbol": symbol, "display_name": item.get("description") or symbol,
            "local_symbol": _local_symbol(symbol), "exchange": item.get("displaySymbol"),
            "exchange_code": None, "market": None, "country_code": None, "currency": None,
            "instrument_type": str(item.get("type") or "EQUITY").upper(),
            "yahoo_symbol": None, "finnhub_symbol": symbol, "source": "finnhub", "is_local": False,
        })
    return output


def yahoo_search(query: str, limit: int) -> list[dict]:
    search = yf.Search(query, max_results=max(limit * 2, 12), news_count=0, enable_fuzzy_query=True, timeout=6)
    rows = getattr(search, "quotes", None) or []
    return [parsed for item in rows if isinstance(item, dict) and (parsed := yahoo_result(item))]


def _rank(item: dict, query: str) -> tuple:
    q = query.casefold()
    symbol = str(item.get("display_symbol") or "").casefold()
    name = str(item.get("display_name") or "").casefold()
    if symbol == q: match = 0
    elif symbol.startswith(q): match = 1
    elif q in symbol: match = 2
    elif name == q: match = 3
    elif name.startswith(q): match = 4
    elif q in name: match = 5
    else: match = 6
    similarity = max(SequenceMatcher(None, q, symbol).ratio(), SequenceMatcher(None, q, name).ratio())
    us = 0 if item.get("country_code") == "US" else 1
    local = 0 if item.get("is_local") else 1
    return match, local, us, -similarity, symbol


def dedupe_and_sort(items: list[dict], query: str, limit: int) -> list[dict]:
    unique: dict[tuple, dict] = {}
    for item in items:
        key = (("yahoo", item.get("yahoo_symbol")) if item.get("yahoo_symbol") else
               ("finnhub", item.get("finnhub_symbol"), item.get("exchange_code"), item.get("instrument_type")))
        existing = unique.get(key)
        if existing is None or (item.get("is_local") and not existing.get("is_local")):
            unique[key] = item
    return sorted(unique.values(), key=lambda row: _rank(row, query))[:limit]


def _local_results(db: Session, query: str, limit: int) -> list[dict]:
    pattern = f"%{query}%"
    rows = db.scalars(select(Security).where(or_(
        Security.display_symbol.ilike(pattern), Security.display_name.ilike(pattern),
        Security.local_symbol.ilike(pattern), Security.yahoo_symbol.ilike(pattern),
        Security.finnhub_symbol.ilike(pattern),
    )).limit(limit)).all()
    return [{
        "provider_key": f"security:{row.id}", "security_id": row.id,
        "display_symbol": row.display_symbol, "display_name": row.display_name or row.display_symbol,
        "local_symbol": row.local_symbol, "exchange": row.exchange_name, "exchange_code": row.exchange_code,
        "market": row.market, "country_code": row.country_code, "currency": row.currency,
        "instrument_type": row.instrument_type, "yahoo_symbol": row.yahoo_symbol,
        "finnhub_symbol": row.finnhub_symbol, "source": "local", "is_local": True,
    } for row in rows]


def search_securities(db: Session, raw_query: str, limit: int = 12) -> list[dict]:
    query = normalize_query(raw_query)
    if not query:
        return []
    limit = min(max(limit, 1), 20)
    local = _local_results(db, query, limit)
    cache_key = (query.casefold(), limit)
    redis_key = f"security-search:v1:{limit}:{query.casefold()}"
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
    redis_cached = _redis_get(redis_key)
    if redis_cached is not None:
        remote = redis_cached
    elif cached and cached[0] > now:
        remote = [dict(item) for item in cached[1]]
    else:
        yahoo_failed = False
        try:
            remote = yahoo_search(query, limit)
        except Exception:
            yahoo_failed = True
            try:
                remote = finnhub_search(query, limit)
            except Exception:
                remote = []
        if yahoo_failed and not remote and not local:
            raise SecuritySearchUnavailable("暂时无法连接搜索服务，请稍后重试")
        with _cache_lock:
            if len(_cache) >= _CACHE_LIMIT:
                oldest = min(_cache, key=lambda key: _cache[key][0])
                _cache.pop(oldest, None)
            _cache[cache_key] = (now + _CACHE_TTL, [dict(item) for item in remote])
        _redis_set(redis_key, remote)
    return dedupe_and_sort(local + remote, query, limit)


def resolve_security(db: Session, *, security_id: int | None = None, source: str | None = None,
                     yahoo_symbol: str | None = None, finnhub_symbol: str | None = None) -> Security:
    existing = None
    if security_id:
        existing = db.get(Security, security_id)
        if not existing:
            raise ValueError("候选证券已失效，请重新搜索")
        yahoo_symbol, finnhub_symbol = existing.yahoo_symbol, existing.finnhub_symbol
    yahoo = (yahoo_symbol or "").strip().upper() or None
    finnhub = (finnhub_symbol or "").strip().upper() or None
    if not yahoo and not finnhub:
        raise ValueError("缺少可验证的数据源标识")
    if source == "yahoo" and not yahoo or source == "finnhub" and not finnhub:
        raise ValueError("缺少可验证的数据源标识")
    if not existing and yahoo:
        existing = db.scalar(select(Security).where(Security.yahoo_symbol == yahoo))
    if not existing and finnhub:
        existing = db.scalar(select(Security).where(Security.finnhub_symbol == finnhub))
    profile = fetch_stock_profile(yahoo) if yahoo else None
    if yahoo and not profile:
        raise ValueError("该证券暂时无法通过 Yahoo 验证")
    if finnhub and not yahoo:
        try:
            if not any(item.get("finnhub_symbol") == finnhub for item in finnhub_search(finnhub, 8)):
                raise ValueError("该证券暂时无法通过 Finnhub 验证")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("暂时无法连接 Finnhub 验证证券") from exc
    if existing:
        if profile:
            existing.display_name = profile.get("longName") or profile.get("shortName") or existing.display_name
            existing.currency = profile.get("currency") or existing.currency
            existing.instrument_type = str(profile.get("quoteType") or existing.instrument_type or "EQUITY").upper()
            refreshed = yahoo_result({"symbol": yahoo, "longname": existing.display_name,
                                      "exchange": profile.get("exchange"), "quoteType": profile.get("quoteType"),
                                      "currency": profile.get("currency")})
            existing.exchange_code = profile.get("exchange") or existing.exchange_code
            existing.exchange_name = (refreshed or {}).get("exchange") or existing.exchange_name
            existing.market = (refreshed or {}).get("market") or existing.market
            existing.country_code = (refreshed or {}).get("country_code") or existing.country_code
            if not existing.finnhub_symbol and yahoo and "." not in yahoo and (refreshed or {}).get("country_code") == "US":
                try:
                    matches = finnhub_search(yahoo, 8)
                    exact = next((item for item in matches if item["finnhub_symbol"] == yahoo), None)
                    mapped = db.scalar(select(Security).where(Security.finnhub_symbol == yahoo))
                    if exact and (not mapped or mapped.id == existing.id) and SequenceMatcher(None, str(existing.display_name).casefold(), str(exact["display_name"]).casefold()).ratio() >= .55:
                        existing.finnhub_symbol = yahoo
                        existing.finnhub_status = "available"
                        existing.mapping_method = "exchange_local_symbol"
                        existing.mapping_confidence = .9
                    else:
                        existing.finnhub_status = "unsupported"
                except Exception:
                    existing.finnhub_status = "unknown"
        existing.last_verified_at = datetime.now(UTC)
        existing.yahoo_status = "available" if yahoo else existing.yahoo_status
        return existing
    name = (profile or {}).get("longName") or (profile or {}).get("shortName") or yahoo or finnhub
    exchange_code = (profile or {}).get("exchange")
    parsed = yahoo_result({"symbol": yahoo, "longname": name, "exchange": exchange_code,
                           "quoteType": (profile or {}).get("quoteType"), "currency": (profile or {}).get("currency")}) if yahoo else None
    # Never infer non-US Finnhub symbols by stripping a Yahoo suffix.
    mapped_finnhub = finnhub
    mapping_method, confidence = ("unresolved", None)
    if yahoo and "." not in yahoo and (parsed or {}).get("country_code") == "US":
        try:
            matches = finnhub_search(yahoo, 8)
            exact = next((item for item in matches if item["finnhub_symbol"] == yahoo), None)
            mapped = db.scalar(select(Security).where(Security.finnhub_symbol == yahoo))
            if exact and not mapped and SequenceMatcher(None, str(name).casefold(), str(exact["display_name"]).casefold()).ratio() >= .55:
                mapped_finnhub, mapping_method, confidence = yahoo, "exchange_local_symbol", .9
        except Exception:
            pass
    row = Security(
        display_symbol=(parsed or {}).get("display_symbol") or finnhub,
        display_name=name, local_symbol=(parsed or {}).get("local_symbol") or _local_symbol(finnhub or ""),
        exchange_code=exchange_code, exchange_name=(parsed or {}).get("exchange"),
        market=(parsed or {}).get("market"), country_code=(parsed or {}).get("country_code"),
        currency=(profile or {}).get("currency"), instrument_type=((profile or {}).get("quoteType") or "EQUITY").upper(),
        yahoo_symbol=yahoo, finnhub_symbol=mapped_finnhub,
        yahoo_status="available" if yahoo else "unsupported",
        finnhub_status="available" if mapped_finnhub else "unsupported",
        mapping_method=mapping_method, mapping_confidence=confidence, last_verified_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def clear_search_cache() -> None:
    with _cache_lock:
        _cache.clear()


def provider_symbol(db: Session, ticker: str, provider: str) -> str | None:
    """Resolve a legacy Yahoo-facing ticker without guessing provider suffix rules."""
    row = db.scalar(select(Security).where(or_(Security.yahoo_symbol == ticker, Security.display_symbol == ticker)))
    if not row:
        return ticker if provider == "yahoo" else None
    return row.yahoo_symbol if provider == "yahoo" else row.finnhub_symbol
