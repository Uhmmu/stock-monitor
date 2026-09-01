from datetime import UTC, datetime, timedelta
from decimal import Decimal
import inspect
import builtins

import pytest

from app.services.execution import backends
from app.services.quant.paper_fill import PaperFillSimulator, PaperQuote


def test_paper_backend_has_no_authenticated_binance_path(monkeypatch):
    source = inspect.getsource(backends)
    assert "BinanceClient" not in source
    assert "api_key" not in source and "api_secret" not in source
    with pytest.raises(backends.ExecutionModeBlocked):
        backends.backend_for(backends.ExecutionMode.BINANCE_DEMO)
    with pytest.raises(backends.ExecutionModeBlocked):
        backends.backend_for(backends.ExecutionMode.BINANCE_LIVE)
    real_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.startswith("execution_agent"):
            raise AssertionError("PAPER attempted to import the authenticated Binance execution client")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    from app.services.quant import paper
    monkeypatch.setattr(paper, "submit_manual_order", lambda db, account, **order: order)
    backend = backends.backend_for(backends.ExecutionMode.PAPER, db=object(), account=object())
    assert backend.submit_order(instrument_id=1) == {"instrument_id": 1}


def test_quote_driven_market_and_limit_fills_are_defensible():
    now = datetime.now(UTC)
    quote = PaperQuote(Decimal("99"), Decimal("101"), now, Decimal("100"))
    simulator = PaperFillSimulator(slippage_bps=Decimal("10"))
    buy = simulator.decide(quote, side="buy", order_type="market", tick_size=Decimal("0.01"), now=now)
    assert buy and buy.price == Decimal("101.11") and buy.liquidity == "taker"
    assert simulator.decide(
        quote, side="buy", order_type="limit", limit_price=Decimal("100"),
        tick_size=Decimal("0.01"), now=now,
    ) is None
    crossed = simulator.decide(
        quote, side="sell", order_type="limit", limit_price=Decimal("98"),
        tick_size=Decimal("0.01"), now=now,
    )
    assert crossed and crossed.price == Decimal("99") and crossed.liquidity == "maker"
    with pytest.raises(ValueError, match="stale"):
        simulator.decide(
            PaperQuote(Decimal("99"), Decimal("101"), now - timedelta(minutes=1)),
            side="buy", order_type="market", tick_size=Decimal("0.01"), now=now,
        )
