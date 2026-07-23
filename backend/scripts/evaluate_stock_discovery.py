#!/usr/bin/env python3
"""Explicit, budget-capped live evaluation for stock discovery models.

Ordinary tests never import or execute this script. A real request requires both
--live and PERPLEXITY_LIVE_EVALUATION_ENABLED=true.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import User
from app.services.discovery.context import build_portfolio_context
from app.services.discovery.normalization import normalize_ticker
from app.services.discovery.perplexity import build_request, run_agent
from app.services.discovery.service import estimate_max_cost
from app.services.portfolio.transaction_service import get_or_create_default_portfolio


def _args():
    parser = argparse.ArgumentParser(description="受预算控制的机会发现 Agent API 模型评估")
    parser.add_argument("--live", action="store_true", help="确认允许真实 API 调用")
    parser.add_argument("--username", help="通过正常用户/默认组合数据访问层选择组合")
    parser.add_argument("--models", nargs="+", default=["openai/gpt-5.4-mini", "openai/gpt-5.4"])
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--output", default="stock-discovery-evaluation.json")
    return parser.parse_args()


def _score(result, holdings: set[str], latency: float) -> dict:
    candidates = [item for group in result.parsed.candidate_groups for item in group.candidates]
    raw_tickers = [item.ticker for item in candidates]
    normalized = [normalize_ticker(item.ticker, item.exchange)[0] for item in candidates]
    unique = {ticker for ticker in normalized if ticker}
    financial_fields = sum(sum(value is not None for key, value in item.financial_snapshot.model_dump().items() if key != "data_periods") for item in candidates)
    citations = sum(len(item.sources) for item in candidates)
    return {
        "model": result.model, "cost_usd": result.total_cost_usd, "model_cost_usd": result.model_cost_usd,
        "tool_cost_usd": result.tool_cost_usd, "finance_search_calls": result.finance_search_calls,
        "web_search_calls": result.web_search_calls, "latency_seconds": round(latency, 3),
        "json_schema_success": True, "candidate_count": len(candidates),
        "duplicate_count": len(raw_tickers) - len(unique), "invalid_ticker_count": sum(ticker is None for ticker in normalized),
        "current_holding_duplication": len(unique & holdings), "useful_financial_fields": financial_fields,
        "citation_count": citations, "extreme_valuation_count": sum(item.valuation_level == "extreme" for item in candidates),
        "portfolio_diagnosis_items": len(result.parsed.portfolio_diagnosis.overweight_exposures) + len(result.parsed.portfolio_diagnosis.underweight_or_missing_exposures),
        "strong_flow_directions": len(result.parsed.capital_flow_directions.strong_current_flows),
        "contrarian_directions": len(result.parsed.capital_flow_directions.weak_or_early_flows),
        "tickers": sorted(unique), "obvious_hallucinations": "需人工复核", "overall_usefulness": "需人工复核",
    }


def main() -> int:
    args, settings = _args(), get_settings()
    budget = args.budget_usd if args.budget_usd is not None else settings.perplexity_evaluation_budget_usd
    if not args.live or not settings.perplexity_live_evaluation_enabled:
        raise SystemExit("真实评估已停止：必须同时传入 --live 并设置 PERPLEXITY_LIVE_EVALUATION_ENABLED=true")
    if not settings.perplexity_api_key.strip():
        raise SystemExit("真实评估已停止：缺少 PERPLEXITY_API_KEY")
    with SessionLocal() as db:
        query = select(User).where(User.status == "active")
        if args.username:
            query = query.where(User.username == args.username)
        user = db.scalar(query.order_by(User.id).limit(1))
        if not user:
            raise SystemExit("没有可用于评估的已激活用户")
        portfolio = get_or_create_default_portfolio(db, user.id)
        context, context_hash = build_portfolio_context(db, portfolio, user.id)
    holdings = {row["ticker"] for row in context.get("holdings", [])}
    rows, spent = [], 0.0
    by_model: dict[str, list[set[str]]] = {}
    for model in args.models:
        for repetition in range(max(1, args.repetitions)):
            estimate = estimate_max_cost(context, SimpleNamespace(model=model, max_output_tokens=settings.perplexity_max_output_tokens,
                max_steps=settings.perplexity_max_steps, enable_web_search=settings.perplexity_enable_web_search))
            if spent + estimate > budget:
                rows.append({"model": model, "repetition": repetition + 1, "skipped": "保守预估将超过评估预算", "estimated_cost_usd": estimate})
                break
            request = build_request(context=context, model=model, max_steps=settings.perplexity_max_steps,
                max_output_tokens=settings.perplexity_max_output_tokens, enable_web_search=settings.perplexity_enable_web_search)
            started = time.monotonic()
            result = run_agent(request)
            row = {"repetition": repetition + 1, **_score(result, holdings, time.monotonic() - started)}
            rows.append(row); spent += result.total_cost_usd
            by_model.setdefault(model, []).append(set(row["tickers"]))
            if spent >= budget:
                break
    overlap = {}
    for model, runs in by_model.items():
        pairs = [len(left & right) / len(left | right) if left | right else 1 for index, left in enumerate(runs) for right in runs[index + 1:]]
        overlap[model] = statistics.mean(pairs) if pairs else None
    report = {"context_hash": context_hash, "budget_usd": budget, "spent_usd": round(spent, 6),
        "models": args.models, "repetitions": args.repetitions, "candidate_overlap_jaccard": overlap, "runs": rows}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
