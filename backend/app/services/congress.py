"""kadoa congress-trading-monitor 数据源客户端。

三院（众议院/参议院/行政部门）STOCK Act 披露，纯静态 JSON，无需 key。
- ticker/{TICKER}.json  某股相关全部交易
- filer/{filer_id}.json  某政客档案 + 全部交易
- filers.json           全部 filer 名单（搜索用）
金额是披露区间（如 $1,001 - $15,000），无精确值。
"""
from __future__ import annotations

from datetime import date

_BASE = "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/main/public/data"
_UA = "Mozilla/5.0 (X11; Linux x86_64) stock-monitor/0.1"
_TIMEOUT = 20.0


def _get_json(path: str):
    import httpx

    url = f"{_BASE}/{path}"
    with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _UA}, follow_redirects=True) as c:
        resp = c.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def fetch_ticker_trades(ticker: str) -> list[dict]:
    """某股相关的全部政客交易。"""
    data = _get_json(f"ticker/{ticker.upper()}.json")
    if not data:
        return []
    if isinstance(data, dict):
        return data.get("trades", [])
    return data


def fetch_filer(filer_id: str) -> dict | None:
    """某政客档案 + 全部交易：{filer:{...}, trades:[...]}。"""
    return _get_json(f"filer/{filer_id}.json")


def fetch_filers_index() -> list[dict]:
    """全部 filer 名单（含 trade_count 等汇总）。"""
    data = _get_json("filers.json")
    return data or []


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def amount_bounds(trade: dict) -> tuple[float | None, float | None, str | None]:
    """从 kadoa 交易取金额区间下/上界与标签。"""
    low = trade.get("amount_range_low")
    high = trade.get("amount_range_high")
    label = trade.get("amount_range_label") or trade.get("amount")
    try:
        low = float(low) if low is not None else None
    except (TypeError, ValueError):
        low = None
    try:
        high = float(high) if high is not None else None
    except (TypeError, ValueError):
        high = None
    return low, high, label


def amount_midpoint(trade: dict) -> float | None:
    low, high, _ = amount_bounds(trade)
    if low is not None and high is not None:
        return (low + high) / 2
    return low or high


# kadoa asset_type → 我们的持仓桶
_ASSET_CATEGORY = {
    "ST": "stock",
    "SA": "stock",
    "ET": "etf",
    "OP": "option",
    "OT": "other",
}


def infer_category(asset_type: str | None, asset_name: str | None, ticker: str | None) -> str:
    """把一笔交易/资产归到饼图的类别桶。"""
    name = (asset_name or "").lower()
    if asset_type and asset_type.upper() in _ASSET_CATEGORY:
        cat = _ASSET_CATEGORY[asset_type.upper()]
        if cat != "other":
            return cat
    if "municipal" in name or "muni " in name:
        return "muni_bond"
    if "treasury" in name or "t-bill" in name or "u.s. treasury" in name:
        return "treasury"
    if "call" in name or "put" in name or "option" in name:
        return "option"
    if "perp" in name or "preferred" in name:
        return "preferred"
    if "note" in name or "bond" in name or "due" in name:
        return "corp_bond"
    if "%" in name:
        return "preferred"
    if "etf" in name or "fund" in name or "trust" in name:
        return "etf"
    if ticker:
        return "stock"
    return "other"
