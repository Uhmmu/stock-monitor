import sys
import types
from datetime import date

import pandas as pd
import pytest

from app.services import sec_extract


@pytest.fixture(autouse=True)
def _reset_identity():
    sec_extract._identity_ready = False
    yield
    sec_extract._identity_ready = False


# ---------------------------------------------------------------- 假 edgar 模块

class _FakeFiling:
    def __init__(self, obj):
        self._obj = obj

    def obj(self):
        return self._obj


class _Fake8K:
    """模拟 CurrentReport：.items 列 + __getitem__ 取正文。"""
    def __init__(self, mapping):
        self._m = mapping
        self.items = list(mapping.keys())

    def __getitem__(self, key):
        return self._m[key]


class _FakeForm4:
    def __init__(self, df):
        self._df = df

    def to_dataframe(self, detailed=False, include_metadata=False):
        return self._df


def _install_fake_edgar(monkeypatch, *, by_accession=None, company=None):
    fake = types.ModuleType("edgar")
    captured = {"identity": None}

    def set_identity(value):
        captured["identity"] = value

    fake.set_identity = set_identity
    fake.use_local_storage = lambda *a, **k: None
    fake.get_by_accession_number = lambda acc: (by_accession or {}).get(acc)
    fake.Company = lambda ticker: company
    monkeypatch.setitem(sys.modules, "edgar", fake)
    return captured


# ---------------------------------------------------------------- 8-K/6-K 正文

def test_extract_events_maps_items_and_priority(monkeypatch):
    obj = _Fake8K({
        "Item 2.02": "Item 2.02 Results of Operations...",
        "Item 5.02": "Item 5.02 Departure of Directors...",
    })
    cap = _install_fake_edgar(monkeypatch, by_accession={"acc-1": _FakeFiling(obj)})

    rows = [("acc-1", "8-K", date(2026, 4, 30), "http://x/8k")]
    events = sec_extract.extract_events("aapl", "0000320193", rows)

    # UA 硬约束：必须通过 set_identity 传入
    assert cap["identity"] == "stockMonitor/1.0 self-hosted@example.com"
    assert [e.item_code for e in events] == ["2.02", "5.02"]
    assert events[0].priority == "urgent" and events[0].item_label == "业绩公告（财报）"
    assert events[1].priority == "important" and events[1].item_label == "高管/董事变动"
    assert events[0].ticker == "AAPL" and events[0].text.startswith("Item 2.02")


def test_extract_events_unknown_item_defaults_normal(monkeypatch):
    obj = _Fake8K({"Item 9.99": "mystery"})
    _install_fake_edgar(monkeypatch, by_accession={"a": _FakeFiling(obj)})
    events = sec_extract.extract_events("X", "1", [("a", "8-K", None, "u")])
    assert events[0].priority == "normal" and events[0].item_label == "Item 9.99"


def test_extract_events_skips_missing_filing(monkeypatch):
    _install_fake_edgar(monkeypatch, by_accession={})  # get_by_accession_number -> None
    assert sec_extract.extract_events("X", "1", [("gone", "8-K", None, "u")]) == []


# ---------------------------------------------------------------- 财务大表

def _fake_financials():
    inc = pd.DataFrame([
        {"concept": "us-gaap_RevenueFromContract", "standard_concept": "Revenue",
         "label": "Net sales", "2025-09-27 (FY)": 416161000000.0},
        {"concept": "us-gaap_GrossProfit", "standard_concept": "GrossProfit",
         "label": "Gross margin", "2025-09-27 (FY)": 195201000000.0},
        {"concept": "us-gaap_EarningsPerShareBasic", "standard_concept": float("nan"),
         "label": "Basic", "2025-09-27 (FY)": 7.49},
        {"concept": "us-gaap_EarningsPerShareDiluted", "standard_concept": float("nan"),
         "label": "Diluted", "2025-09-27 (FY)": 7.46},
    ])
    bs = pd.DataFrame([
        {"concept": "us-gaap_Cash", "standard_concept": "CashAndMarketableSecurities",
         "label": "Cash and cash equivalents", "2025-09-27": 35934000000.0},
        {"concept": "us-gaap_LongTermDebtNoncurrent", "standard_concept": "LongTermDebt",
         "label": "Term debt", "2025-09-27": 78328000000.0},
        {"concept": "us-gaap_LongTermDebtCurrent", "standard_concept": "CurrentPortionOfLongTermDebt",
         "label": "Term debt", "2025-09-27": 12350000000.0},
        {"concept": "us-gaap_CommercialPaper", "standard_concept": "ShortTermDebt",
         "label": "Commercial paper", "2025-09-27": 7979000000.0},
    ])
    cf = pd.DataFrame([
        {"concept": "us-gaap_NetCashProvidedByUsedInOperatingActivities",
         "standard_concept": "NetCashFromOperatingActivities",
         "label": "Cash from ops", "2025-09-27 (FY)": 111482000000.0},
    ])

    class _Stmt:
        def __init__(self, df):
            self._df = df

        def to_dataframe(self):
            return self._df

    class _Fin:
        def income_statement(self):
            return _Stmt(inc)

        def balance_sheet(self):
            return _Stmt(bs)

        def cashflow_statement(self):
            return _Stmt(cf)

        def get_currency_symbol(self):
            return "$"

        def get_revenue(self, period_offset=0):
            return 416161000000.0 if period_offset == 0 else None

        def get_net_income(self, period_offset=0):
            return 112010000000.0 if period_offset == 0 else None

        def get_operating_income(self, period_offset=0):
            return 133050000000.0 if period_offset == 0 else None

        def get_shares_outstanding_diluted(self, period_offset=0):
            return 15004697000.0 if period_offset == 0 else None

    class _Company:
        cik = 320193

        def get_financials(self):
            return _Fin()

    return _Company()


def test_extract_financials_maps_all_fields(monkeypatch):
    cap = _install_fake_edgar(monkeypatch, company=_fake_financials())
    periods = sec_extract.extract_financials("AAPL", limit=1)

    assert cap["identity"] == "stockMonitor/1.0 self-hosted@example.com"
    assert len(periods) == 1
    p = periods[0]
    assert p.fiscal_year == 2025 and p.fiscal_period == "FY" and p.form == "10-K"
    assert p.period_end == date(2025, 9, 27)
    assert p.revenue == 416161000000.0
    assert p.gross_profit == 195201000000.0
    assert p.eps_basic == 7.49 and p.eps_diluted == 7.46
    assert p.cash_and_equivalents == 35934000000.0
    # 有息负债 = 长期 + 长期当期 + 短期(商业票据)
    assert p.total_debt == 78328000000.0 + 12350000000.0 + 7979000000.0
    assert p.operating_cash_flow == 111482000000.0
    assert p.shares_outstanding == 15004697000.0
    assert p.currency == "$"


def test_extract_financials_no_company_returns_empty(monkeypatch):
    _install_fake_edgar(monkeypatch, company=None)
    assert sec_extract.extract_financials("NOPE") == []


# ---------------------------------------------------------------- Form 4 内幕交易

def _insider_df(rows):
    return pd.DataFrame(rows)


def test_extract_insider_flags_ceo_buy_and_heavy_sell(monkeypatch):
    df = _insider_df([
        {"Code": "P", "Shares": 1000, "Price": 200.0, "Value": 200000.0,
         "Date": pd.Timestamp("2026-06-15"), "Insider": "Tim Cook",
         "Position": "Chief Executive Officer", "Remaining Shares": 50000},
        {"Code": "S", "Shares": 10000, "Price": 300.0, "Value": 3000000.0,
         "Date": pd.Timestamp("2026-06-16"), "Insider": "Some Officer",
         "Position": "SVP", "Remaining Shares": 1000},
        {"Code": "M", "Shares": 500, "Price": float("nan"), "Value": float("nan"),
         "Date": pd.Timestamp("2026-06-17"), "Insider": "Some Officer",
         "Position": "SVP", "Remaining Shares": 1500},
    ])
    obj = _FakeForm4(df)
    _install_fake_edgar(monkeypatch, by_accession={"f4": _FakeFiling(obj)})

    trades = sec_extract.extract_insider("AAPL", "0000320193", [("f4", "http://x/f4")])
    assert len(trades) == 3
    assert trades[0].flag == "ceo_buy"  # CEO + P
    assert trades[0].transaction_date == date(2026, 6, 15)
    assert trades[1].flag == "heavy_sell"  # S + value >= 1M
    assert trades[2].flag is None  # M 行权，无 flag
    assert trades[2].price is None  # NaN -> None（绝不臆造）
    assert trades[0].transaction_code == "P" and trades[0].shares == 1000.0
    assert trades[0].shares_owned_after == 50000.0


def test_extract_insider_small_sell_no_flag(monkeypatch):
    df = _insider_df([
        {"Code": "S", "Shares": 10, "Price": 100.0, "Value": 1000.0,
         "Date": pd.Timestamp("2026-06-15"), "Insider": "Minor",
         "Position": "Director", "Remaining Shares": 500},
    ])
    _install_fake_edgar(monkeypatch, by_accession={"f": _FakeFiling(_FakeForm4(df))})
    trades = sec_extract.extract_insider("X", "1", [("f", "u")])
    assert trades[0].flag is None  # 小额卖出不标记
