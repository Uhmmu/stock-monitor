from datetime import date, timedelta

from app.services.technical_analysis_engine import (
    aggregate_weekly,
    bollinger,
    build_analysis,
    build_weekly_chart_data,
    macd,
    render_chart,
    rsi,
    sma,
)


def candles(count=420):
    start = date(2024, 1, 1)
    rows = []
    price = 100.0
    for index in range(count):
        day = start + timedelta(days=index)
        if day.weekday() >= 5:
            continue
        drift = 0.35 + (index % 23 - 11) * 0.08
        opening = price
        close = max(10, price + drift)
        rows.append(
            {
                "date": day,
                "open": opening,
                "high": max(opening, close) + 1.2,
                "low": min(opening, close) - 1.1,
                "close": close,
                "volume": 1_000_000 + index * 100,
                "vwap": (opening + close) / 2,
            }
        )
        price = close
    return rows


def test_daily_to_weekly_includes_partial_week_and_uses_real_dates():
    rows = candles(11)
    weekly = aggregate_weekly(rows)
    assert len(weekly) == 2
    assert weekly[0]["open"] == rows[0]["open"]
    assert weekly[-1]["close"] == rows[-1]["close"]
    assert weekly[-1]["data_through"] == rows[-1]["date"]


def test_core_indicators_are_deterministic():
    values = [float(x) for x in range(1, 80)]
    assert sma(values, 20)[18] is None and sma(values, 20)[19] == 10.5
    assert rsi(values)[-1] == 100
    line, signal, histogram = macd(values)
    assert len(line) == len(signal) == len(histogram) == len(values)
    low, middle, high = bollinger(values)
    assert low[-1] < middle[-1] < high[-1]


def test_structured_analysis_truncates_to_156_real_weeks():
    result, weekly = build_analysis("TEST", candles(1400))
    assert len(weekly) <= 156
    assert result["dataThrough"] == weekly[-1]["data_through"].isoformat()
    assert result["latestClose"] == weekly[-1]["close"]
    assert result["weeklyTrend"] in {"bullish", "bearish", "neutral"}
    assert set(result["indicators"]) >= {
        "rsi14",
        "macd",
        "ma20",
        "ma60",
        "ema20",
        "atr14",
    }


def test_insufficient_history_records_omissions():
    result, weekly = build_analysis("SHORT", candles(30))
    assert weekly
    assert "Insufficient data for weekly MA50" in result["omittedReasons"]
    assert result["fibonacci"]["available"] is False


def test_weekly_chart_data_uses_business_days_and_backend_ma_values():
    payload = build_weekly_chart_data(candles(420), "fmp")
    assert payload["chart_data_status"] == "ready"
    assert payload["chart_data_source"] == "fmp"
    assert payload["weekly"]
    assert set(payload["weekly"][0]) == {
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    assert len(payload["weekly"][0]["time"]) == 10
    assert payload["moving_averages"]["ma20"][0]["time"] == payload["weekly"][19]["time"]
    assert payload["moving_averages"]["ma20"][0]["value"] == sma(
        [row["close"] for row in payload["weekly"]], 20
    )[19]
    assert set(payload["chart_series"]) == {"day", "week", "month"}
    assert payload["chart_series"]["week"]["candles"] == payload["weekly"]
    assert payload["chart_series"]["day"]["candles"]
    assert payload["chart_series"]["month"]["candles"]


def test_weekly_chart_data_explicitly_reports_missing_history():
    payload = build_weekly_chart_data([], None)
    assert payload["chart_data_status"] == "insufficient"
    assert payload["chart_data_reason"] == "historical_data_unavailable"
    assert payload["weekly"] == []
    assert all(
        not item["candles"] for item in payload["chart_series"].values()
    )


def test_static_webp_chart_generation(tmp_path):
    result, weekly = build_analysis("CHART", candles(700))
    target = tmp_path / "chart.webp"
    render_chart("CHART", weekly, result, str(target))
    assert target.read_bytes()[:4] == b"RIFF"
    assert target.stat().st_size > 1_000
