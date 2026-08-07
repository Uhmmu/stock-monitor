"""Reconnect-gap detection and provider-priority intraday backfill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

from .contracts import IntradayBar, ProviderError, ensure_utc
from .providers import RealtimeMarketDataProvider


@dataclass(frozen=True, slots=True)
class BackfillGap:
    symbol: str
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return max(0, int((self.end - self.start).total_seconds() // 60))


@dataclass(frozen=True, slots=True)
class BackfillResult:
    symbol: str
    start: datetime | None
    end: datetime | None
    bars: tuple[IntradayBar, ...]
    provider: str | None
    attempted_providers: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.bars)


def detect_reconnect_gap(
    last_valid_market_timestamp: datetime | None,
    reconnect_at: datetime,
    *,
    minimum_gap_seconds: float = 60.0,
    symbol: str = "",
) -> BackfillGap | None:
    if last_valid_market_timestamp is None:
        return None
    start = ensure_utc(last_valid_market_timestamp)
    end = ensure_utc(reconnect_at)
    if (end - start).total_seconds() < max(0.0, minimum_gap_seconds):
        return None
    # Start at the next minute so a provider replay of the last valid minute is
    # harmless and database uniqueness remains deterministic.
    first = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return BackfillGap(symbol=symbol.strip().upper(), start=first, end=end)


def _dedupe_bars(rows: Iterable[IntradayBar], gap: BackfillGap) -> tuple[IntradayBar, ...]:
    values: dict[tuple[str, datetime, str, str], IntradayBar] = {}
    for row in rows:
        if row.symbol != gap.symbol or row.interval != "1m":
            continue
        stamp = ensure_utc(row.timestamp).replace(second=0, microsecond=0)
        if stamp < gap.start or stamp > gap.end:
            continue
        key = (row.symbol, stamp, row.provider, row.feed or "unknown")
        values.setdefault(key, row)
    return tuple(sorted(values.values(), key=lambda value: (value.timestamp, value.provider, value.feed or "")))


class BackfillCoordinator:
    """Fetch missing 1m bars after reconnect without coupling to persistence."""

    def __init__(self, providers: Iterable[RealtimeMarketDataProvider]) -> None:
        self.providers = tuple(providers)

    async def backfill(
        self,
        symbol: str,
        *,
        last_valid_market_timestamp: datetime | None,
        reconnect_at: datetime | None = None,
    ) -> BackfillResult:
        now = ensure_utc(reconnect_at)
        gap = detect_reconnect_gap(last_valid_market_timestamp, now, symbol=symbol)
        if gap is None:
            return BackfillResult(symbol=symbol.strip().upper(), start=None, end=None, bars=(), provider=None, attempted_providers=())
        attempted: list[str] = []
        warnings: list[str] = []
        for provider in self.providers:
            attempted.append(provider.name)
            try:
                rows = await provider.get_intraday_bars(gap.symbol, "1m", gap.start, gap.end)
                bars = _dedupe_bars(rows, gap)
                if bars:
                    return BackfillResult(
                        symbol=gap.symbol,
                        start=gap.start,
                        end=gap.end,
                        bars=bars,
                        provider=provider.name,
                        attempted_providers=tuple(attempted),
                        warnings=tuple(warnings),
                    )
                warnings.append(f"{provider.name}:no_bars")
            except ProviderError as exc:
                warnings.append(f"{provider.name}:{type(exc).__name__}")
            except Exception as exc:
                warnings.append(f"{provider.name}:{type(exc).__name__}")
        return BackfillResult(
            symbol=gap.symbol,
            start=gap.start,
            end=gap.end,
            bars=(),
            provider=None,
            attempted_providers=tuple(attempted),
            warnings=tuple(warnings),
        )


async def backfill_missing_bars(
    symbol: str,
    providers: Iterable[RealtimeMarketDataProvider],
    *,
    last_valid_market_timestamp: datetime | None,
    reconnect_at: datetime | None = None,
) -> BackfillResult:
    return await BackfillCoordinator(providers).backfill(
        symbol,
        last_valid_market_timestamp=last_valid_market_timestamp,
        reconnect_at=reconnect_at,
    )
