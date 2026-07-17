from types import SimpleNamespace

import pytest

from app.services import sec_edgar

# 模拟 company_tickers.json 结构：{"0":{cik_str,ticker,title}, ...}
_TICKERS = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "2": {"cik_str": 1878848, "ticker": "IREN", "title": "IREN Ltd"},
}

# 模拟 submissions API 的 filings.recent 列式并行数组（含应过滤的 CORRESP）
_SUBMISSIONS = {
    "filings": {
        "recent": {
            "accessionNumber": ["0001-26-01", "0001-26-02", "0001-26-03", "0001-26-04"],
            "form": ["8-K", "10-Q", "CORRESP", "6-K"],
            "items": ["1.01,2.02", "", "", ""],
            "filingDate": ["2026-07-01", "2026-05-08", "2026-05-01", "2026-06-30"],
            "reportDate": ["2026-06-30", "2026-03-31", "", "2026-06-30"],
            "primaryDocument": ["ef_8k.htm", "iren-q.htm", "corr.htm", "iren-6k.htm"],
            "primaryDocDescription": ["8-K", "10-Q", "CORRESP", "6-K"],
        }
    }
}


@pytest.fixture(autouse=True)
def _clear_cache():
    sec_edgar._ticker_cik_map.cache_clear()
    yield
    sec_edgar._ticker_cik_map.cache_clear()


def test_headers_declare_user_agent():
    # SEC 强制要求带 User-Agent，缺失会被封锁
    assert "User-Agent" in sec_edgar.SEC_HEADERS
    assert "self-hosted@example.com" in sec_edgar.SEC_HEADERS["User-Agent"]


def test_get_json_sends_headers(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        captured["headers"] = headers
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"ok": 1})

    monkeypatch.setattr(sec_edgar.httpx, "get", fake_get)
    sec_edgar._get_json("https://data.sec.gov/x.json")
    assert captured["headers"] == sec_edgar.SEC_HEADERS


def test_get_cik_pads_and_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(sec_edgar, "_get_json", lambda url: _TICKERS)
    assert sec_edgar.get_cik("aapl") == "0000320193"
    assert sec_edgar.get_cik("IREN") == "0001878848"


def test_get_cik_missing_returns_none(monkeypatch):
    monkeypatch.setattr(sec_edgar, "_get_json", lambda url: _TICKERS)
    assert sec_edgar.get_cik("NOTREAL") is None


def test_parse_items_takes_highest_priority():
    # 1.01=important, 2.02=urgent → 取 urgent
    labels, priority = sec_edgar._parse_items("1.01,2.02")
    assert priority == "urgent"
    assert "签署重大合同" in labels and "业绩公告（财报）" in labels


def test_parse_items_unknown_code_defaults_normal():
    labels, priority = sec_edgar._parse_items("9.99")
    assert priority == "normal"
    assert labels == ["Item 9.99"]


def test_parse_items_empty():
    assert sec_edgar._parse_items("") == ([], "normal")


def test_fetch_filings_filters_and_maps(monkeypatch):
    def fake_get_json(url):
        return _SUBMISSIONS if "submissions" in url else _TICKERS

    monkeypatch.setattr(sec_edgar, "_get_json", fake_get_json)
    filings = sec_edgar.fetch_filings("IREN")

    # CORRESP 被过滤，保留 8-K / 10-Q / 6-K
    forms = [f.form for f in filings]
    assert forms == ["8-K", "10-Q", "6-K"]

    eightk = filings[0]
    assert eightk.priority == "urgent"
    assert eightk.form_label == "重大事件公告"
    assert eightk.ticker == "IREN"
    assert eightk.cik == "0001878848"
    # URL 拼接：accession 去横杠、cik 去前导零
    assert eightk.filing_url == "https://www.sec.gov/Archives/edgar/data/1878848/00012601/ef_8k.htm"

    # 6-K 无 items → normal，境外发行人报告
    sixk = filings[2]
    assert sixk.priority == "normal"
    assert sixk.form_label == "境外发行人报告"
    assert sixk.event_labels == []


def test_fetch_filings_unknown_ticker_returns_empty(monkeypatch):
    monkeypatch.setattr(sec_edgar, "_get_json", lambda url: _TICKERS)
    assert sec_edgar.fetch_filings("NOPE") == []


def test_tracked_matches_variants():
    assert sec_edgar._tracked("8-K")
    assert sec_edgar._tracked("8-K/A")
    assert sec_edgar._tracked("10-K")
    assert not sec_edgar._tracked("CORRESP")
    assert not sec_edgar._tracked("S-8")
