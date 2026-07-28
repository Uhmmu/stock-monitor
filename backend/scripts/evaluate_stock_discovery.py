#!/usr/bin/env python3
"""Explicit live evaluation of the manual Search + local-AI discovery pipeline."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import User
from app.services.discovery.analysis import analyze_opportunities
from app.services.discovery.context import build_local_research_context, build_portfolio_context
from app.services.discovery.search import build_search_queries, run_search
from app.services.portfolio.transaction_service import get_or_create_default_portfolio


def _args():
    parser = argparse.ArgumentParser(description="受预算控制的 Search + 本地 GPT 机会发现评估")
    parser.add_argument("--live", action="store_true", help="确认允许真实 API 调用")
    parser.add_argument("--username", help="选择已激活用户的默认组合")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--output", default="stock-discovery-evaluation.json")
    return parser.parse_args()


def main() -> int:
    args, settings = _args(), get_settings()
    budget = args.budget_usd if args.budget_usd is not None else settings.perplexity_evaluation_budget_usd
    if not args.live or not settings.perplexity_live_evaluation_enabled:
        raise SystemExit("真实评估已停止：必须同时传入 --live 并显式开启评估开关")
    if not settings.perplexity_api_key.strip() or not settings.openai_api_key.strip():
        raise SystemExit("真实评估已停止：缺少 Perplexity Search 或本地 GPT API Key")
    with SessionLocal() as db:
        query = select(User).where(User.status == "active")
        if args.username:
            query = query.where(User.username == args.username)
        user = db.scalar(query.order_by(User.id).limit(1))
        if not user:
            raise SystemExit("没有可用于评估的已激活用户")
        portfolio = get_or_create_default_portfolio(db, user.id)
        context, context_hash = build_portfolio_context(db, portfolio, user.id)
        context = build_local_research_context(db, context)

    rows, spent = [], 0.0
    for repetition in range(max(1, args.repetitions)):
        if spent + 0.005 > budget:
            rows.append({"repetition": repetition + 1, "skipped": "Search 成本将超过评估预算"})
            break
        started = time.monotonic()
        search = run_search(build_search_queries(context))
        analysis = analyze_opportunities(
            search_results=search.results,
            local_context=context,
            max_output_tokens=settings.perplexity_max_output_tokens,
        )
        spent += search.cost_usd
        rows.append({
            "repetition": repetition + 1,
            "search_source": "perplexity_search",
            "search_cost_usd": search.cost_usd,
            "perplexity_model_tokens": 0,
            "analysis_model": analysis.model,
            "analysis_tokens": analysis.total_tokens,
            "latency_seconds": round(time.monotonic() - started, 3),
            "opportunity_count": len(analysis.parsed.opportunities),
            "tickers": [item.ticker for item in analysis.parsed.opportunities],
            "schema_success": True,
        })
    report = {
        "context_hash": context_hash,
        "budget_usd": budget,
        "measured_perplexity_cost_usd": round(spent, 6),
        "analysis_model": settings.model_important,
        "runs": rows,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
