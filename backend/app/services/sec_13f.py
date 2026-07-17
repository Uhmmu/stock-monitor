"""13F 机构季度持仓：从 SEC 全市场 13F 数据集按 CUSIP 反查自选股持有机构。

为什么走全市场数据集：SEC EDGAR 按"申报人"索引，无法"给一只股票→反查哪些机构持有它"。
唯一完整来源是官方每季度打包的全市场 13F 数据集（含对冲基金）。edgartools 只能"基金→持仓"，
帮不了反查。

内存约束（VPS 仅 2.9G）：INFOTABLE 解压后 GB 级，绝不 pandas 全量读入。做法——
- ZIP 下载到临时文件（~90MB 落盘，不进内存）；
- SUBMISSION/COVERPAGE 是小表，先建 accession→元数据索引（几千行）；
- INFOTABLE 逐行流式读，只保留 CUSIP 命中自选股的极少数行。全程内存只占几 MB。

CUSIP 映射：数据集只用 9 位 CUSIP 标识证券，无 ticker。命中集合三路来源——
① .env 手动覆盖 sec_13f_cusip_overrides；② 已持久化的 SecCusipMap；
③ 首次按 INFOTABLE 的 NAMEOFISSUER 模糊匹配自选股公司名（edgartools 取公司名），命中后回写映射复用。

⚠️ 复用 SEC_HEADERS（含 User-Agent），SEC 强制要求，否则封 IP。
"""
import io
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from app.config import get_settings
from app.services.sec_edgar import SEC_HEADERS

_TIMEOUT = 300.0
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass(frozen=True)
class HoldingDTO:
    ticker: str
    cusip: str
    manager_name: str
    accession_number: str
    report_period: date | None
    filing_date: date | None
    value_usd: float | None
    shares: float | None
    put_call: str | None


def _parse_sec_date(value: str | None) -> date | None:
    """SEC 数据集日期格式 '31-MAR-2026'。"""
    if not value:
        return None
    parts = value.strip().split("-")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[2]), _MONTHS[parts[1].upper()], int(parts[0]))
    except (ValueError, KeyError):
        return None


def _num(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def latest_dataset_url() -> str | None:
    """解析下载页，返回最新（页面第一个）13F 数据集 zip 的绝对 URL。"""
    settings = get_settings()
    try:
        resp = httpx.get(settings.sec_13f_index_url, headers=SEC_HEADERS, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return None
    links = re.findall(r'href="([^"]+form13f\.zip)"', resp.text)
    if not links:
        return None
    href = links[0]
    if href.startswith("http"):
        return href
    return "https://www.sec.gov" + href


def _manual_overrides() -> dict[str, list[str]]:
    """.env 手动 ticker→[cusip] 覆盖。"""
    raw = get_settings().sec_13f_cusip_overrides.strip()
    mapping: dict[str, list[str]] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        ticker, cusip = pair.split(":", 1)
        ticker, cusip = ticker.strip().upper(), cusip.strip()
        if ticker and cusip:
            mapping.setdefault(ticker, []).append(cusip)
    return mapping


def _normalize_name(name: str) -> str:
    """公司名归一化，用于 issuer 名称匹配：去公司后缀/标点/大小写。"""
    name = name.upper()
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    tokens = [t for t in name.split() if t not in {
        "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED",
        "PLC", "LLC", "LP", "THE", "HOLDINGS", "HOLDING", "GROUP", "CLASS",
        "COM", "NEW", "SA", "NV", "AG",
    }]
    return " ".join(tokens)


def _company_names(tickers: list[str]) -> dict[str, str]:
    """用 edgartools 取 ticker→归一化公司名，用于 issuer 名称匹配。"""
    settings = get_settings()
    names: dict[str, str] = {}
    try:
        import edgar
        edgar.set_identity(settings.sec_user_agent)
    except Exception:
        return names
    for ticker in tickers:
        try:
            company = edgar.Company(ticker)
            if company is not None and getattr(company, "name", None):
                names[ticker.upper()] = _normalize_name(company.name)
        except Exception:
            continue
    return names


def _download_to_temp(url: str) -> str:
    """流式下载 zip 到临时文件，返回路径。不进内存。"""
    fd, path = tempfile.mkstemp(suffix="_form13f.zip")
    try:
        with os.fdopen(fd, "wb") as out:
            with httpx.stream("GET", url, headers=SEC_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    out.write(chunk)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return path


def _col_index(header: str) -> dict[str, int]:
    return {name: i for i, name in enumerate(header.rstrip("\n").split("\t"))}


def _read_submission(zf: zipfile.ZipFile) -> dict[str, dict]:
    """accession → {period, filing_date, type}。只保留 13F-HR（持仓报告，排除 NT 通知）。"""
    result: dict[str, dict] = {}
    with zf.open("SUBMISSION.tsv") as raw:
        reader = io.TextIOWrapper(raw, encoding="utf-8", errors="ignore")
        idx = _col_index(reader.readline())
        for line in reader:
            cols = line.rstrip("\n").split("\t")
            if len(cols) <= max(idx.values()):
                continue
            sub_type = cols[idx["SUBMISSIONTYPE"]]
            if not sub_type.startswith("13F-HR"):
                continue
            accession = cols[idx["ACCESSION_NUMBER"]]
            result[accession] = {
                "period": _parse_sec_date(cols[idx["PERIODOFREPORT"]]),
                "filing_date": _parse_sec_date(cols[idx["FILING_DATE"]]),
            }
    return result


def _read_coverpage(zf: zipfile.ZipFile) -> dict[str, str]:
    """accession → 机构名（FILINGMANAGER_NAME）。"""
    result: dict[str, str] = {}
    with zf.open("COVERPAGE.tsv") as raw:
        reader = io.TextIOWrapper(raw, encoding="utf-8", errors="ignore")
        idx = _col_index(reader.readline())
        for line in reader:
            cols = line.rstrip("\n").split("\t")
            if len(cols) <= idx["FILINGMANAGER_NAME"]:
                continue
            result[cols[idx["ACCESSION_NUMBER"]]] = cols[idx["FILINGMANAGER_NAME"]].strip()
    return result


def parse_holdings(
    zip_path: str,
    cusip_to_ticker: dict[str, str],
    issuer_name_to_ticker: dict[str, str],
) -> tuple[list[HoldingDTO], dict[str, tuple[str, str]]]:
    """流式解析 INFOTABLE，返回命中自选股的持仓 + 新发现的 CUSIP 映射。

    cusip_to_ticker: 已知 CUSIP→ticker（精确命中，快）。
    issuer_name_to_ticker: 归一化公司名→ticker（首次靠名称模糊命中，回写映射）。
    返回 (holdings, discovered)，discovered: cusip → (ticker, issuer_name)。
    """
    discovered: dict[str, tuple[str, str]] = {}
    holdings: list[HoldingDTO] = []
    with zipfile.ZipFile(zip_path) as zf:
        submission = _read_submission(zf)
        coverpage = _read_coverpage(zf)
        with zf.open("INFOTABLE.tsv") as raw:
            reader = io.TextIOWrapper(raw, encoding="utf-8", errors="ignore")
            idx = _col_index(reader.readline())
            need = max(idx.values())
            for line in reader:
                cols = line.rstrip("\n").split("\t")
                if len(cols) <= need:
                    continue
                cusip = cols[idx["CUSIP"]].strip()
                ticker = cusip_to_ticker.get(cusip)
                if ticker is None:
                    issuer = cols[idx["NAMEOFISSUER"]].strip()
                    matched = issuer_name_to_ticker.get(_normalize_name(issuer))
                    if matched is None:
                        continue
                    ticker = matched
                    discovered[cusip] = (matched, issuer)
                    cusip_to_ticker[cusip] = matched  # 本轮后续行直接精确命中
                accession = cols[idx["ACCESSION_NUMBER"]]
                meta = submission.get(accession)
                if meta is None:  # 非 13F-HR（如 NT 通知），跳过
                    continue
                holdings.append(
                    HoldingDTO(
                        ticker=ticker,
                        cusip=cusip,
                        manager_name=coverpage.get(accession, "未知机构"),
                        accession_number=accession,
                        report_period=meta["period"],
                        filing_date=meta["filing_date"],
                        value_usd=_num(cols[idx["VALUE"]]),
                        shares=_num(cols[idx["SSHPRNAMT"]]),
                        put_call=(cols[idx["PUTCALL"]].strip() or None),
                    )
                )
    return holdings, discovered


def collect_13f_holdings(
    tickers: list[str],
    known_cusips: dict[str, str],
    company_names: dict[str, str] | None = None,
) -> tuple[list[HoldingDTO], dict[str, tuple[str, str]]]:
    """下载最新 13F 数据集并按 CUSIP 反查自选股持仓。

    known_cusips: 已知 cusip→ticker（来自 SecCusipMap + .env 覆盖）。
    company_names: ticker→归一化公司名（缺省则用 edgartools 现取）。
    返回 (holdings, discovered_cusip_map)。
    """
    if not tickers:
        return [], {}
    url = latest_dataset_url()
    if not url:
        raise RuntimeError("无法解析 SEC 13F 数据集下载链接")
    # 合并手动覆盖
    cusip_to_ticker = dict(known_cusips)
    for ticker, cusips in _manual_overrides().items():
        if ticker in {t.upper() for t in tickers}:
            for cusip in cusips:
                cusip_to_ticker.setdefault(cusip, ticker)
    if company_names is None:
        company_names = _company_names(tickers)
    issuer_name_to_ticker = {name: ticker for ticker, name in company_names.items() if name}
    zip_path = _download_to_temp(url)
    try:
        return parse_holdings(zip_path, cusip_to_ticker, issuer_name_to_ticker)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
