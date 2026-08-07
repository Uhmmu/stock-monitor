from __future__ import annotations

import argparse
import json
import time

import httpx

from app.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a paid, read-only Exa Financial Datasets smoke test.")
    parser.add_argument("--live", action="store_true", help="Required acknowledgement for a paid API call")
    parser.add_argument("--ticker", default="MSFT")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("Stopped: pass --live to authorize the paid Exa smoke request")

    settings = get_settings()
    key = settings.exa_api_key.strip()
    if not key:
        raise SystemExit("Stopped: EXA_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Exa-Beta": settings.exa_agent_beta,
    }
    request = {
        "query": (
            f"Use Financial Datasets to retrieve the company name and latest available market capitalization "
            f"for U.S. ticker {args.ticker}. Include the data period or quote time."
        ),
        "systemPrompt": "Use the attached Financial Datasets provider. Do not guess missing values.",
        "effort": "minimal",
        "dataSources": [{"provider": "financial_datasets"}],
        "outputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ticker", "company_name", "market_cap", "as_of"],
            "properties": {
                "ticker": {"type": "string"},
                "company_name": {"type": "string", "description": "Company name from Financial Datasets"},
                "market_cap": {
                    "type": ["number", "null"],
                    "description": "Latest market capitalization from Financial Datasets",
                },
                "as_of": {"type": ["string", "null"]},
            },
        },
    }
    response = httpx.post(settings.exa_agent_url, headers=headers, json=request, timeout=60)
    response.raise_for_status()
    payload = response.json()
    run_id = payload.get("id")
    if not run_id:
        raise SystemExit("Exa did not return a run id")
    deadline = time.monotonic() + args.timeout
    while payload.get("status") in ("queued", "running"):
        if time.monotonic() >= deadline:
            raise SystemExit("Exa smoke run timed out")
        time.sleep(4)
        response = httpx.get(
            f"{settings.exa_agent_url.rstrip('/')}/{run_id}",
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
    if payload.get("status") != "completed":
        raise SystemExit(f"Exa smoke run ended with status={payload.get('status')}")
    structured = (payload.get("output") or {}).get("structured") or {}
    if structured.get("ticker", "").upper() != args.ticker.upper():
        raise SystemExit("Exa smoke output did not contain the requested ticker")
    usage = payload.get("usage") or {}
    provider_calls = (usage.get("dataSources") or {}).get("financial_datasets", 0)
    if provider_calls < 1:
        raise SystemExit("Exa completed without invoking Financial Datasets")
    print(json.dumps({
        "status": payload.get("status"),
        "stop_reason": payload.get("stopReason"),
        "ticker": structured.get("ticker"),
        "company_name_present": bool(structured.get("company_name")),
        "market_cap_present": structured.get("market_cap") is not None,
        "financial_datasets_calls": provider_calls,
        "web_search_calls": usage.get("searches", 0),
        "cost_dollars": (payload.get("costDollars") or {}).get("total", 0),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
