from app.api.routes import _yahoo_metric
from app.services import market_data


class _Frame:
    empty = False

    def to_dict(self, orient):
        assert orient == "records"
        return [{"period": "0m", "strongBuy": 3, "buy": 7, "hold": 2, "sell": 1, "strongSell": 0}]


class _Ticker:
    recommendations_summary = _Frame()

    def get_info(self):
        return {
            "trailingPE": 21.5,
            "grossMargins": 0.42,
            "marketCap": 12_500_000_000,
            "beta": 1.2,
            "ignored": "value",
        }


def test_yahoo_fundamentals_are_normalized(monkeypatch):
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: _Ticker())
    info = market_data.fetch_yf_info_metrics("TEST")

    assert info["trailingPE"] == 21.5
    assert _yahoo_metric(info, "P/E") == 21.5
    assert _yahoo_metric(info, "毛利率 %") == 42
    assert _yahoo_metric(info, "市值(百万)") == 12_500
    assert "ignored" not in info


def test_yahoo_recommendations_are_available_without_finnhub(monkeypatch):
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: _Ticker())

    assert market_data.fetch_yf_recommendations("TEST") == [{
        "period": "0m", "strongBuy": 3, "buy": 7, "hold": 2, "sell": 1, "strongSell": 0,
    }]
