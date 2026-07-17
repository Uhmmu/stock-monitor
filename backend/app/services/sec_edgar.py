"""SEC EDGAR 官方 filing 采集。

数据源（均为官方、免费、无需认证）：
- CIK 查询：https://www.sec.gov/files/company_tickers.json
- 提交历史：https://data.sec.gov/submissions/CIK##########.json

⚠️ SEC 强制要求所有请求带 User-Agent header，否则封锁 IP。
"""
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import httpx

# SEC 要求的身份声明：自定义工具名/版本号 联系邮箱
SEC_HEADERS = {"User-Agent": "stockMonitor/1.0 self-hosted@example.com"}

_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"
_TIMEOUT = 15.0

# 采集的 filing 类型（含 /A 修订版等变体，用前缀匹配）。过滤掉 CORRESP/UPLOAD/EFFECT 等行政噪音。
TRACKED_FORMS = ("8-K", "6-K", "10-K", "10-Q", "20-F", "40-F", "4", "3")

# form → 中文类型名
FORM_LABELS = {
    "8-K": "重大事件公告",
    "6-K": "境外发行人报告",
    "10-K": "年报",
    "10-Q": "季报",
    "20-F": "境外年报",
    "40-F": "加拿大年报",
    "4": "内部人持股变动",
    "3": "内部人初始持股",
}

# 8-K Item 编号 → (中文事件名, 优先级)。优先级：urgent 红 / important 黄 / normal 蓝
ITEM_LABELS: dict[str, tuple[str, str]] = {
    "1.01": ("签署重大合同", "important"),
    "1.02": ("终止重大合同", "important"),
    "1.05": ("重大网络安全事故", "urgent"),
    "2.01": ("完成资产收购/处置", "important"),
    "2.02": ("业绩公告（财报）", "urgent"),
    "2.03": ("新增重大债务", "important"),
    "2.04": ("债务加速到期", "urgent"),
    "3.01": ("退市/上市规则不合规", "urgent"),
    "3.02": ("定向增发（股权稀释）", "important"),
    "4.01": ("更换会计师事务所", "important"),
    "4.02": ("过往财报不可信", "urgent"),
    "5.01": ("控制权变更", "urgent"),
    "5.02": ("高管/董事变动", "important"),
    "5.03": ("公司章程修订", "normal"),
    "7.01": ("Regulation FD 披露", "normal"),
    "8.01": ("其他重大事件", "normal"),
    "9.01": ("财务报表与附件", "normal"),
}

_PRIORITY_RANK = {"urgent": 3, "important": 2, "normal": 1}


@dataclass(frozen=True)
class FilingDTO:
    ticker: str
    cik: str
    accession_number: str
    form: str
    form_label: str
    items: str | None
    event_labels: list[str] = field(default_factory=list)
    priority: str = "normal"
    filing_date: date | None = None
    report_date: date | None = None
    primary_document: str | None = None
    filing_url: str = ""
    raw_payload: dict = field(default_factory=dict)


def _get_json(url: str) -> dict | list:
    resp = httpx.get(url, headers=SEC_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


@lru_cache(maxsize=1)
def _ticker_cik_map() -> dict[str, str]:
    """{TICKER: 10位CIK}。company_tickers.json 约 900KB，进程内缓存一次。"""
    data = _get_json(_COMPANY_TICKERS_URL)
    rows = data.values() if isinstance(data, dict) else data
    mapping: dict[str, str] = {}
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        cik = row.get("cik_str")
        if ticker and cik is not None:
            mapping[ticker] = str(cik).zfill(10)
    return mapping


def get_cik(ticker: str) -> str | None:
    """按 ticker 查 10 位补零 CIK，未找到返回 None。"""
    return _ticker_cik_map().get((ticker or "").strip().upper())


def _tracked(form: str) -> bool:
    return any(form == f or form.startswith(f + "/") for f in TRACKED_FORMS)


def _parse_items(raw_items: str) -> tuple[list[str], str]:
    """拆解 '1.01,2.03' → (中文事件名列表, 最高优先级)。"""
    codes = [code.strip() for code in (raw_items or "").split(",") if code.strip()]
    labels: list[str] = []
    priority = "normal"
    for code in codes:
        name, level = ITEM_LABELS.get(code, (f"Item {code}", "normal"))
        labels.append(name)
        if _PRIORITY_RANK[level] > _PRIORITY_RANK[priority]:
            priority = level
    return labels, priority


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _build_url(cik: str, accession: str, document: str | None) -> str:
    if not document:
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=40"
    return _ARCHIVE_URL.format(
        cik_int=int(cik), accession=accession.replace("-", ""), document=document
    )


def fetch_filings(ticker: str, limit: int = 40) -> list[FilingDTO]:
    """拉取自选股最近的 SEC filing，过滤+中文映射后返回 DTO 列表。"""
    cik = get_cik(ticker)
    if not cik:
        return []
    payload = _get_json(_SUBMISSIONS_URL.format(cik=cik))
    recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload, dict) else {}
    forms = recent.get("form", [])
    if not forms:
        return []
    accessions = recent.get("accessionNumber", [])
    items_arr = recent.get("items", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    documents = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    results: list[FilingDTO] = []
    for i, form in enumerate(forms):
        if not _tracked(form):
            continue
        accession = accessions[i] if i < len(accessions) else ""
        raw_items = items_arr[i] if i < len(items_arr) else ""
        document = documents[i] if i < len(documents) else None
        event_labels, priority = _parse_items(raw_items)
        results.append(
            FilingDTO(
                ticker=ticker.upper(),
                cik=cik,
                accession_number=accession,
                form=form,
                form_label=FORM_LABELS.get(form.split("/")[0], form),
                items=raw_items or None,
                event_labels=event_labels,
                priority=priority,
                filing_date=_parse_date(filing_dates[i] if i < len(filing_dates) else None),
                report_date=_parse_date(report_dates[i] if i < len(report_dates) else None),
                primary_document=document,
                filing_url=_build_url(cik, accession, document),
                raw_payload={
                    "form": form,
                    "items": raw_items,
                    "filingDate": filing_dates[i] if i < len(filing_dates) else None,
                    "reportDate": report_dates[i] if i < len(report_dates) else None,
                    "primaryDocDescription": descriptions[i] if i < len(descriptions) else None,
                },
            )
        )
        if len(results) >= limit:
            break
    return results
