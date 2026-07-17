"""基于 edgartools 从 SEC filing 抽取「结构化正文/财务大表/内幕交易」。

与轻量的 `sec_edgar.py`（submissions 索引）互补：sec_edgar 负责 filing 列表，
本模块负责深挖单份 filing 的实际内容。

⚠️ 内存敏感：edgartools 的 XBRL 解析会拉起 pandas/pyarrow，单次可达数百 MB。
因此：
- `import edgar` 只在函数内部执行（懒加载），避免 api / 默认 worker 进程也加载重依赖；
- 所有出站请求经 `set_identity()` 带上 SEC 强制要求的 User-Agent；
- 相关 Celery 任务走独立 `--concurrency=1` 的 sec_heavy 队列，永不并发解析。
"""
import gc
import re
from dataclasses import dataclass, field
from datetime import date

from app.config import get_settings
from app.services.sec_edgar import ITEM_LABELS, _PRIORITY_RANK

# 日期列形如 "2025-09-27 (FY)" / "2025-06-28 (Q3)"（利润表/现金流量表带期间标签）
_PERIOD_COL = re.compile(r"(\d{4})-(\d{2})-(\d{2})\s*\(([^)]*)\)")
# 资产负债表日期列通常是纯日期 "2025-09-27"（无期间标签），用宽松前缀匹配
_DATE_COL = re.compile(r"^\d{4}-\d{2}-\d{2}")

# 资产负债表里计入「总负债（有息）」的 standardized concept
_DEBT_CONCEPTS = {"LongTermDebt", "CurrentPortionOfLongTermDebt", "ShortTermDebt"}

_identity_ready = False


@dataclass(frozen=True)
class EventDTO:
    ticker: str
    cik: str
    accession_number: str
    form: str
    item_code: str
    item_label: str
    priority: str
    text: str | None
    filing_date: date | None
    filing_url: str


@dataclass(frozen=True)
class FinPeriodDTO:
    ticker: str
    fiscal_year: int
    fiscal_period: str
    form: str
    period_end: date | None
    filed_at: date | None = None
    accession_number: str | None = None
    revenue: float | None = None
    net_income: float | None = None
    operating_income: float | None = None
    gross_profit: float | None = None
    eps_basic: float | None = None
    eps_diluted: float | None = None
    cash_and_equivalents: float | None = None
    total_debt: float | None = None
    shares_outstanding: float | None = None
    operating_cash_flow: float | None = None
    currency: str | None = None
    raw_payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class InsiderDTO:
    ticker: str
    cik: str
    accession_number: str
    insider_name: str
    insider_title: str | None
    transaction_date: date | None
    transaction_code: str | None
    shares: float | None
    price: float | None
    value: float | None
    shares_owned_after: float | None
    flag: str | None
    filing_url: str


def _ensure_identity():
    """进程内一次性配置 edgartools：身份（UA 硬约束）+ 本地缓存。"""
    global _identity_ready
    if _identity_ready:
        return
    import edgar

    settings = get_settings()
    edgar.set_identity(settings.sec_user_agent)
    try:
        edgar.use_local_storage(settings.edgar_local_data_dir)
    except Exception:
        pass
    _identity_ready = True


def _num(value) -> float | None:
    """把 pandas 值转成 float，NaN/None/非数一律 None（绝不臆造）。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN


def _to_date(value) -> date | None:
    if value is None:
        return None
    try:
        return value.date()  # pandas Timestamp
    except AttributeError:
        pass
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- 8-K / 6-K 正文

def extract_events(ticker: str, cik: str, filings: list) -> list[EventDTO]:
    """filings: [(accession_number, form, filing_date, filing_url), ...]（来自 sec_filings 表的 8-K/6-K）。

    返回每个 Item 一条 EventDTO；异常单条跳过，不影响整体。
    """
    _ensure_identity()
    import edgar

    results: list[EventDTO] = []
    for accession, form, filing_date, filing_url in filings:
        try:
            filing = edgar.get_by_accession_number(accession)
            if filing is None:
                continue
            obj = filing.obj()
            item_codes = list(getattr(obj, "items", []) or [])
            for raw_code in item_codes:
                code = str(raw_code).replace("Item", "").strip()
                try:
                    text = obj[raw_code]
                except Exception:
                    text = None
                label, priority = ITEM_LABELS.get(code, (f"Item {code}", "normal"))
                results.append(
                    EventDTO(
                        ticker=ticker.upper(), cik=cik, accession_number=accession, form=form,
                        item_code=code, item_label=label, priority=priority,
                        text=(str(text).strip() if text else None),
                        filing_date=filing_date, filing_url=filing_url,
                    )
                )
        except Exception:
            continue
    return results


# ---------------------------------------------------------------- 财务大表

def _period_map(df, concept_col: str, keys: set[str]) -> dict[str, dict[str, float]]:
    """{日期列: {standardized_concept: 求和值}}。只取 standard_concept 命中 keys 的行。"""
    date_cols = [c for c in df.columns if _DATE_COL.match(str(c))]
    out: dict[str, dict[str, float]] = {c: {} for c in date_cols}
    for _, row in df.iterrows():
        key = str(row.get(concept_col) or "")
        if key not in keys:
            continue
        for c in date_cols:
            v = _num(row.get(c))
            if v is not None:
                out[c][key] = out[c].get(key, 0.0) + v
    return out


def _eps_map(df) -> dict[str, tuple[float | None, float | None]]:
    """{日期列: (eps_basic, eps_diluted)}，按 raw concept 匹配（EPS 无 standard_concept）。"""
    date_cols = [c for c in df.columns if _PERIOD_COL.match(str(c))]
    basic: dict[str, float | None] = {}
    diluted: dict[str, float | None] = {}
    for _, row in df.iterrows():
        concept = str(row.get("concept") or "")
        target = basic if concept == "us-gaap_EarningsPerShareBasic" else (
            diluted if concept == "us-gaap_EarningsPerShareDiluted" else None
        )
        if target is None:
            continue
        for c in date_cols:
            v = _num(row.get(c))
            if v is not None and c not in target:
                target[c] = v
    return {c: (basic.get(c), diluted.get(c)) for c in date_cols}


def _statement_df(financials, name: str):
    try:
        stmt = getattr(financials, name)()
        return stmt.to_dataframe()
    except Exception:
        return None


def extract_financials(ticker: str, form: str = "10-K", limit: int = 4) -> list[FinPeriodDTO]:
    """抽取近 `limit` 个财务期（默认年报 FY）。抽不到的字段留 None。"""
    _ensure_identity()
    import edgar

    try:
        company = edgar.Company(ticker)
        fin = company.get_financials()
    except Exception:
        return []
    if fin is None:
        return []

    inc = _statement_df(fin, "income_statement")
    if inc is None:
        return []
    bs = _statement_df(fin, "balance_sheet")
    cf = _statement_df(fin, "cashflow_statement")

    currency = None
    try:
        currency = fin.get_currency_symbol()
    except Exception:
        pass

    # 期间由利润表的日期列驱动
    inc_cols = [c for c in inc.columns if _PERIOD_COL.match(str(c))]
    gross = _period_map(inc, "standard_concept", {"GrossProfit"})
    eps = _eps_map(inc)
    cash = _period_map(bs, "standard_concept", {"CashAndMarketableSecurities"}) if bs is not None else {}
    debt = _period_map(bs, "standard_concept", _DEBT_CONCEPTS) if bs is not None else {}
    ocf = _period_map(cf, "standard_concept", {"NetCashFromOperatingActivities"}) if cf is not None else {}

    def _match_by_date(pool: dict, day: str):
        for col in pool:
            if str(col).startswith(day):
                return pool[col]
        return {}

    results: list[FinPeriodDTO] = []
    for offset, col in enumerate(inc_cols[:limit]):
        m = _PERIOD_COL.match(str(col))
        year, month, dom, tag = int(m.group(1)), m.group(2), m.group(3), (m.group(4) or "FY").strip()
        period_end = _to_date(f"{year}-{month}-{dom}")
        day = f"{year}-{month}-{dom}"

        def _acc(method):
            try:
                return _num(getattr(fin, method)(period_offset=offset))
            except Exception:
                return None

        eps_b, eps_d = eps.get(col, (None, None))
        debt_row = _match_by_date(debt, day)
        cash_row = _match_by_date(cash, day)
        ocf_row = _match_by_date(ocf, day)
        results.append(
            FinPeriodDTO(
                ticker=ticker.upper(),
                fiscal_year=year,
                fiscal_period=tag,
                form="10-K" if tag == "FY" else form,
                period_end=period_end,
                revenue=_acc("get_revenue"),
                net_income=_acc("get_net_income"),
                operating_income=_acc("get_operating_income"),
                gross_profit=(gross.get(col, {}) or {}).get("GrossProfit"),
                eps_basic=eps_b,
                eps_diluted=eps_d,
                cash_and_equivalents=cash_row.get("CashAndMarketableSecurities"),
                total_debt=(sum(debt_row.values()) if debt_row else None),
                shares_outstanding=_acc("get_shares_outstanding_diluted"),
                operating_cash_flow=ocf_row.get("NetCashFromOperatingActivities"),
                currency=currency,
                raw_payload={"period_col": str(col), "offset": offset},
            )
        )
    del inc, bs, cf
    gc.collect()
    return results


# ---------------------------------------------------------------- Form 4 内幕交易

def _insider_flag(code: str | None, position: str | None, value: float | None, threshold: float) -> str | None:
    pos = (position or "").lower()
    is_exec = any(k in pos for k in ("ceo", "chief executive", "president"))
    if code == "P" and is_exec:
        return "ceo_buy"
    if code == "S" and value is not None and value >= threshold:
        return "heavy_sell"
    return None


def extract_insider(ticker: str, cik: str, filings: list) -> list[InsiderDTO]:
    """filings: [(accession_number, filing_url), ...]（来自 sec_filings 表的 Form 4）。"""
    _ensure_identity()
    import edgar

    threshold = get_settings().sec_insider_heavy_sell_value
    results: list[InsiderDTO] = []
    for accession, filing_url in filings:
        try:
            filing = edgar.get_by_accession_number(accession)
            if filing is None:
                continue
            obj = filing.obj()
            df = obj.to_dataframe(detailed=True, include_metadata=True)
        except Exception:
            continue
        try:
            for _, row in df.iterrows():
                code = row.get("Code")
                code = str(code).strip() if code is not None else None
                value = _num(row.get("Value"))
                position = row.get("Position")
                results.append(
                    InsiderDTO(
                        ticker=ticker.upper(), cik=cik, accession_number=accession,
                        insider_name=str(row.get("Insider") or "").strip() or "未知",
                        insider_title=(str(position).strip() if position else None),
                        transaction_date=_to_date(row.get("Date")),
                        transaction_code=code,
                        shares=_num(row.get("Shares")),
                        price=_num(row.get("Price")),
                        value=value,
                        shares_owned_after=_num(row.get("Remaining Shares")),
                        flag=_insider_flag(code, position, value, threshold),
                        filing_url=filing_url,
                    )
                )
        finally:
            del df
            gc.collect()
    return results


# ---------------------------------------------------------------- Haiku 中文翻译+总结
# 对已入库的 8-K/6-K 事件正文（sec_events.text）做中文翻译+总结。
# 纯 OpenAI 调用（复用翻译栈 translation_*），不 import edgar、不触 SEC 出站，
# 因此可在轻量默认 worker 运行，无 OOM 约束。

_SUMMARY_SYSTEM_PROMPT = """# Role
你是一位严谨的美股 SEC 公告中文整编员。请把给定的 SEC 表单（8-K/6-K）正文翻译并总结成中文，供中文投资者快速理解。

# 要求
- 只依据给定的 SEC 原文，严禁补充原文没有的数字、金额、日期或结论；原文未提供的信息明确写"原文未提供"。
- 先用 2-4 句中文概括本次公告的核心内容，再按需分条列出关键事实（涉及的金额、日期、人事变动、协议条款、业绩指引等）。
- 保留原文的数字精度与专有名词（公司名、人名、职务可中英对照）。
- 保持客观中立，不作投资建议，不臆测股价影响。
- 只输出 Markdown 正文，不要寒暄，不要用 Markdown 代码块包裹。
"""


def summarize_sec_event(item_label: str, form: str, text: str) -> tuple[str, str | None]:
    """对单条 SEC 事件正文做中文翻译+总结。text 为空则跳过（返回 ("", None)）。"""
    if not text or not text.strip():
        return "", None

    from openai import OpenAI

    settings = get_settings()
    if not settings.translation_api_key:
        raise RuntimeError("尚未配置 TRANSLATION_API_KEY")
    client = OpenAI(
        api_key=settings.translation_api_key,
        base_url=settings.translation_base_url,
        timeout=60,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=settings.translation_model,
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": f"表单类型：{form}\n事件：{item_label}\n\n原文：\n{text}"},
        ],
        temperature=0,
    )
    summary = (response.choices[0].message.content or "").strip()
    if not summary:
        raise ValueError("SEC 事件总结响应为空")
    return summary, settings.translation_model
