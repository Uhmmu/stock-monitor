import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,16}$")


def _safe_ticker(ticker: str) -> str:
    value = ticker.strip().upper()
    if not _TICKER_RE.match(value):
        raise ValueError("非法股票代码")
    return value


def _root() -> Path:
    from app.config import get_settings

    return Path(get_settings().archive_dir)


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def news_dir(ticker: str, market_date: date) -> Path:
    return _root() / _safe_ticker(ticker) / "news" / market_date.isoformat()


def append_raw_news(ticker: str, market_date: date, records: list[dict]) -> Path:
    directory = news_dir(ticker, market_date)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "raw.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path


def write_daily_archive(ticker: str, market_date: date, content: str, manifest: dict) -> str:
    directory = news_dir(ticker, market_date)
    daily_path = directory / "daily.md"
    _atomic_write(daily_path, content)
    _atomic_write(directory / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return str(daily_path)


def weekly_dir(ticker: str, iso_year: int, iso_week: int) -> Path:
    return _root() / _safe_ticker(ticker) / "news_weekly" / f"{iso_year}-W{iso_week:02d}"


def write_weekly_archive(ticker: str, iso_year: int, iso_week: int, content: str, manifest: dict) -> str:
    directory = weekly_dir(ticker, iso_year, iso_week)
    weekly_path = directory / "weekly.md"
    _atomic_write(weekly_path, content)
    _atomic_write(directory / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return str(weekly_path)


def earnings_dir(ticker: str) -> Path:
    return _root() / _safe_ticker(ticker) / "earnings"


def write_quarter(ticker: str, label: str, payload: dict) -> None:
    directory = earnings_dir(ticker)
    _atomic_write(directory / f"{label}.json", json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def prune_quarters(ticker: str, keep_labels: list[str]) -> None:
    directory = earnings_dir(ticker)
    if not directory.exists():
        return
    keep = set(keep_labels)
    for file in directory.glob("*.json"):
        if file.stem == "index" or file.stem in keep:
            continue
        file.unlink()
    _atomic_write(directory / "index.json", json.dumps({"quarters": keep_labels}, ensure_ascii=False, indent=2))
