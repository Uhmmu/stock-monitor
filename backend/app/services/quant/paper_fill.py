"""Pure quote-driven PAPER fill decisions; no provider or credential imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP


BPS = Decimal("10000")


@dataclass(frozen=True)
class PaperQuote:
    bid: Decimal
    ask: Decimal
    observed_at: datetime
    mark: Decimal | None = None

    def validate(self, *, now: datetime, max_age: timedelta) -> None:
        observed = self.observed_at.astimezone(UTC) if self.observed_at.tzinfo else self.observed_at.replace(tzinfo=UTC)
        if self.bid <= 0 or self.ask <= 0 or self.bid > self.ask:
            raise ValueError("invalid paper market quote")
        if observed > now + timedelta(seconds=5) or now - observed > max_age:
            raise ValueError("paper market quote is stale")


@dataclass(frozen=True)
class PaperFillDecision:
    price: Decimal
    liquidity: str
    reference_price: Decimal
    slippage_cost_per_unit: Decimal


class PaperFillSimulator:
    """Market-at-touch plus adverse BPS slippage; limits fill only on crossing."""

    def __init__(self, *, slippage_bps: Decimal, max_quote_age_seconds: int = 30) -> None:
        if slippage_bps < 0 or slippage_bps > 200:
            raise ValueError("paper slippage is outside supported bounds")
        self.slippage_bps = slippage_bps
        self.max_age = timedelta(seconds=max_quote_age_seconds)

    @staticmethod
    def _tick(price: Decimal, tick_size: Decimal, *, buy: bool) -> Decimal:
        if tick_size <= 0:
            return price
        units = (price / tick_size).to_integral_value(rounding=ROUND_UP if buy else ROUND_DOWN)
        return units * tick_size

    def decide(
        self,
        quote: PaperQuote,
        *,
        side: str,
        order_type: str,
        tick_size: Decimal,
        limit_price: Decimal | None = None,
        now: datetime | None = None,
    ) -> PaperFillDecision | None:
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        quote.validate(now=moment, max_age=self.max_age)
        if side not in {"buy", "sell"} or order_type not in {"market", "limit"}:
            raise ValueError("unsupported paper order")
        buy = side == "buy"
        touch = quote.ask if buy else quote.bid
        if order_type == "limit":
            if limit_price is None or limit_price <= 0:
                raise ValueError("positive limit price is required")
            if (buy and quote.ask > limit_price) or (not buy and quote.bid < limit_price):
                return None
            price = min(quote.ask, limit_price) if buy else max(quote.bid, limit_price)
            return PaperFillDecision(self._tick(price, tick_size, buy=buy), "maker", touch, Decimal("0"))
        slip = touch * self.slippage_bps / BPS
        price = touch + slip if buy else touch - slip
        return PaperFillDecision(self._tick(price, tick_size, buy=buy), "taker", touch, slip)
