from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings, get_settings
from .exceptions import IbkrFlexError, IbkrFlexNotConfiguredError, IbkrGatewayTimeoutError, IbkrGatewayUnavailableError
from .http_transport import build_ibkr_http_client, validated_ibkr_proxy_url
from .redaction import sanitize_xml

SECTION_TAGS = {
    "account_information": {"AccountInformation"}, "open_positions": {"OpenPosition"},
    "trades": {"Trade"}, "cash_transactions": {"CashTransaction"}, "dividends": {"DividendAccrual"},
    "fees": {"TierInterestDetail", "BrokerFeeDetail"}, "interest": {"InterestAccrualsCurrency"},
    "transfers": {"Transfer"}, "performance": {"EquitySummaryByReportDateInBase", "MTMPerformanceSummaryUnderlying"},
}


class IbkrFlexClient:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        validated_ibkr_proxy_url(self.settings)
        self._owned = client is None
        self.client = client or build_ibkr_http_client(
            self.settings,
            timeout=self.settings.ibkr_flex_timeout_seconds,
            headers={"User-Agent": "stock-monitor-read-only-ibkr-test/1.0"},
        )

    async def close(self):
        if self._owned:
            await self.client.aclose()

    def status(self) -> dict[str, Any]:
        query = self.settings.ibkr_flex_query_id
        return {"configured": bool(self.settings.ibkr_flex_token and query), "enabled": self.settings.ibkr_flex_enabled,
                "query_id_present": bool(query), "token_present": bool(self.settings.ibkr_flex_token),
                "query_id_hint": f"******{query[-4:]}" if query else None,
                "proxy_enforced": True, "last_test_at": None, "last_test_success": None}

    def _ensure_configured(self):
        if not self.settings.ibkr_flex_enabled or not self.settings.ibkr_flex_token or not self.settings.ibkr_flex_query_id:
            raise IbkrFlexNotConfiguredError("Flex Web Service 尚未配置")

    async def _get(self, path: str, params: dict[str, Any]) -> tuple[str, int, int]:
        began = time.perf_counter()
        try:
            response = await self.client.get(self.settings.ibkr_flex_base_url.rstrip("/") + path, params=params)
        except httpx.TimeoutException as exc:
            raise IbkrGatewayTimeoutError("IBKR Flex 请求超时（代理不可用时不会直连）") from exc
        except httpx.RequestError as exc:
            raise IbkrGatewayUnavailableError("IBKR Flex 无法通过 10808 SOCKS5h 代理连接") from exc
        if not response.is_success:
            raise IbkrFlexError("Flex Web Service 请求失败", f"HTTP {response.status_code}")
        return response.text, response.status_code, round((time.perf_counter() - began) * 1000)

    @staticmethod
    def _xml(text: str) -> ET.Element:
        try:
            return ET.fromstring(text)
        except ET.ParseError as exc:
            raise IbkrFlexError("Flex 返回了无效 XML") from exc

    async def initiate_report(self) -> dict[str, Any]:
        self._ensure_configured()
        text, status, duration = await self._get("/SendRequest", {"t": self.settings.ibkr_flex_token, "q": self.settings.ibkr_flex_query_id, "v": 3})
        root = self._xml(text)
        if (root.findtext("Status") or "").lower() != "success":
            raise IbkrFlexError(root.findtext("ErrorMessage") or "Flex 报告生成请求失败", root.findtext("ErrorCode"))
        reference = root.findtext("ReferenceCode")
        if not reference:
            raise IbkrFlexError("Flex 成功响应缺少 ReferenceCode")
        return {"reference_code": reference, "raw_xml": sanitize_xml(text), "status_code": status, "duration_ms": duration}

    async def fetch_report(self, reference_code: str) -> dict[str, Any]:
        text, status, duration = await self._get("/GetStatement", {"t": self.settings.ibkr_flex_token, "q": reference_code, "v": 3})
        root = self._xml(text)
        error_code = root.findtext("ErrorCode")
        if error_code:
            if error_code in {"1001", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"}:
                return {"pending": True, "error_code": error_code, "raw_xml": sanitize_xml(text), "status_code": status, "duration_ms": duration}
            raise IbkrFlexError(root.findtext("ErrorMessage") or "Flex 报告获取失败", error_code)
        sections = {key: [] for key in SECTION_TAGS}
        for key, tags in SECTION_TAGS.items():
            sections[key] = [dict(node.attrib) for node in root.iter() if node.tag.split("}")[-1] in tags]
        known = set().union(*SECTION_TAGS.values())
        unknown = [{"tag": node.tag.split("}")[-1], "attributes": dict(node.attrib)} for node in root.iter()
                   if node.attrib and node.tag.split("}")[-1] not in known]
        warnings = [f"Flex Query 未包含 {key}" for key, rows in sections.items() if not rows]
        return {"pending": False, "sections": sections, "unknown": unknown, "warnings": warnings,
                "raw_xml": sanitize_xml(text), "status_code": status, "duration_ms": duration}

    async def download_report(self, reference_code: str) -> dict[str, Any]:
        """Internal-only report download used by the import pipeline.

        The unsanitized XML must never be returned by an API or logged. Keeping
        this separate from ``fetch_report`` makes that boundary explicit.
        """
        text, status, duration = await self._get(
            "/GetStatement", {"t": self.settings.ibkr_flex_token, "q": reference_code, "v": 3}
        )
        root = self._xml(text)
        error_code = root.findtext("ErrorCode")
        if error_code:
            if error_code in {"1001", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"}:
                return {"pending": True, "error_code": error_code, "status_code": status, "duration_ms": duration}
            raise IbkrFlexError(root.findtext("ErrorMessage") or "Flex 报告获取失败", error_code)
        return {"pending": False, "xml": text, "status_code": status, "duration_ms": duration}

    async def download_complete_report(self, max_attempts: int = 10, interval_seconds: float = 2.0) -> dict[str, Any]:
        initiated = await self.initiate_report()
        reference = initiated["reference_code"]
        total_duration = initiated["duration_ms"]
        report: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            report = await self.download_report(reference)
            total_duration += report["duration_ms"]
            if not report["pending"]:
                return {"xml": report["xml"], "reference_code": reference, "duration_ms": total_duration}
            if attempt + 1 < max_attempts:
                await asyncio.sleep(interval_seconds)
        raise IbkrFlexError("Flex 报告在有限轮询次数内仍未生成完成", report.get("error_code") if report else None)

    async def run_query(self, max_attempts: int = 5, interval_seconds: float = 2.0) -> dict[str, Any]:
        started = datetime.now(UTC)
        initiated = await self.initiate_report()
        duration = initiated["duration_ms"]
        report = None
        for attempt in range(max_attempts):
            report = await self.fetch_report(initiated["reference_code"])
            duration += report["duration_ms"]
            if not report["pending"]:
                break
            if attempt + 1 < max_attempts:
                await asyncio.sleep(interval_seconds)
        if report is None or report["pending"]:
            raise IbkrFlexError("Flex 报告在有限轮询次数内仍未生成完成", report.get("error_code") if report else None)
        completed = datetime.now(UTC)
        return {"success": True, "operation": "flex_run", "timestamp": completed, "started_at": started,
                "completed_at": completed, "duration_ms": duration,
                "request": {"method": "GET", "path": "/SendRequest → /GetStatement", "query": {"v": 3}},
                "status_code": report["status_code"], "normalized": report["sections"],
                "raw": {"xml": report["raw_xml"]}, "warnings": report["warnings"]}


_flex_client: IbkrFlexClient | None = None


def get_flex_client() -> IbkrFlexClient:
    global _flex_client
    if _flex_client is None:
        _flex_client = IbkrFlexClient()
    return _flex_client


async def close_flex_client() -> None:
    global _flex_client
    if _flex_client is not None:
        await _flex_client.close()
        _flex_client = None
