"""Validate the deduplicated canonical seed universe without importing it."""

import json
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "app/services/industry_pulse/data/leaf_industry_seed_registry.v1.json"
BATCH_SIZE = 50


def ticker_frame(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if frame.empty or not isinstance(frame.columns, pd.MultiIndex):
        return frame
    if ticker in frame.columns.get_level_values(0):
        return frame[ticker]
    if ticker in frame.columns.get_level_values(1):
        return frame.xs(ticker, axis=1, level=1)
    return pd.DataFrame()


def download(symbols: list[str]) -> pd.DataFrame:
    for attempt in range(2):
        frame = yf.download(symbols, period="2mo", interval="1d", group_by="ticker", auto_adjust=False, actions=False, threads=4, progress=False, timeout=25)
        if not frame.empty:
            return frame
        if attempt == 0:
            time.sleep(random.uniform(3, 6))
    return pd.DataFrame()


def main() -> None:
    registry = json.loads(REGISTRY.read_text())
    active = [row for row in registry["unique_universe"] if row.get("enabled", True)]
    symbols = [row["ticker"] for row in active]
    results = {}
    latest_seen = None

    for offset in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[offset:offset + BATCH_SIZE]
        frame = download(batch)
        for ticker in batch:
            raw = ticker_frame(frame, ticker).dropna(how="all")
            if len(raw):
                latest = pd.Timestamp(raw.index.max()).date()
                latest_seen = max(latest_seen, latest) if latest_seen else latest
                rows = raw.tail(30)
                ohlc = bool(all(column in rows and rows[column].notna().any() for column in ("Open", "High", "Low", "Close")))
                adjusted = bool("Adj Close" in rows and rows["Adj Close"].notna().any())
                volume = bool("Volume" in rows and rows["Volume"].notna().any())
                results[ticker] = {"rows": len(rows), "ohlc": ohlc, "adjusted": adjusted, "volume": volume, "latest": latest}
            else:
                results[ticker] = {"rows": 0, "error": "empty_response"}
        if offset + BATCH_SIZE < len(symbols):
            time.sleep(random.uniform(.8, 1.8))

    failed = [ticker for ticker, row in results.items() if not row["rows"]]
    sys.path.insert(0, str(ROOT))
    from app.services.industry_pulse.provider import fetch_finnhub_history
    fallback = {ticker: fetch_finnhub_history(ticker, days=30) for ticker in failed}
    now = datetime.now(UTC).isoformat()

    for row in active:
        ticker = row["ticker"]
        result = results[ticker]
        previous = row.get("market_data_validation") or {}
        if result["rows"]:
            if not previous:
                try:
                    metadata = yf.Ticker(ticker).get_history_metadata()
                    previous = {"currency": metadata.get("currency"), "exchange": metadata.get("exchangeName") or metadata.get("exchange")}
                except Exception:
                    previous = {}
            stale = latest_seen is not None and result["latest"] < latest_seen - timedelta(days=1)
            foreign = row.get("symbol_type") == "FOREIGN" or (previous.get("currency") not in (None, "USD"))
            incomplete = result["rows"] < 20 or not all((result["ohlc"], result["adjusted"], result["volume"]))
            status = "STALE" if stale else "INSUFFICIENT_HISTORY" if incomplete else "FOREIGN_MARKET" if foreign else "VALID"
            row["market_data_status"] = status
            row["market_data_validation"] = {
                "validated_at": now, "provider": "yfinance", "yfinance_status": status,
                "finnhub_status": None, "finnhub_recovered": False, "history_rows": result["rows"],
                "ohlc_available": result["ohlc"], "adjusted_close_available": result["adjusted"],
                "volume_available": result["volume"], "latest_market_date": result["latest"].isoformat(),
                "currency": previous.get("currency"), "exchange": previous.get("exchange"), "error": None,
            }
        else:
            alternate = fallback[ticker]
            recovered = bool(alternate.bars)
            row["market_data_status"] = "VALID" if recovered else "TEMPORARY_FAILURE"
            row["market_data_validation"] = {
                "validated_at": now, "provider": "finnhub" if recovered else "yfinance",
                "yfinance_status": "TEMPORARY_FAILURE", "finnhub_status": "VALID" if recovered else alternate.error_code,
                "finnhub_recovered": recovered, "history_rows": len(alternate.bars), "ohlc_available": recovered,
                "adjusted_close_available": False, "volume_available": alternate.volume_available,
                "latest_market_date": alternate.bars[-1].date.isoformat() if recovered else None,
                "currency": previous.get("currency"), "exchange": previous.get("exchange"), "error": result["error"],
            }

    registry["market_data_validation"] = {
        "validated_at": now,
        "lookback": "approximately_30_trading_days",
        "active_total": len(active),
        "yfinance_valid": sum(row["market_data_validation"]["provider"] == "yfinance" and row["market_data_status"] in {"VALID", "FOREIGN_MARKET"} for row in active),
        "yfinance_failed": len(failed),
        "finnhub_recovered": sum(bool(row["market_data_validation"]["finnhub_recovered"]) for row in active),
        "temporary_failures": sum(row["market_data_status"] == "TEMPORARY_FAILURE" for row in active),
        "history_anomalies": sum(row["market_data_status"] in {"STALE", "INSUFFICIENT_HISTORY"} for row in active),
        "foreign": sum(row["market_data_status"] == "FOREIGN_MARKET" for row in active),
        "replacement_required": registry["statistics"]["replacement_required_unique_ticker_count"],
    }
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(registry["market_data_validation"], indent=2))
    if failed:
        print("failed:", ", ".join(failed))


if __name__ == "__main__":
    main()
