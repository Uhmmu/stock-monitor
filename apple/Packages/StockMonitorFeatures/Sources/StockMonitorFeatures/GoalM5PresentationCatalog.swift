import Foundation

/// R2.0 端点级 typed presentation 目录：每个 M5 端点声明主摘要键、列表列与空态提示。
/// 未登记的 semantic key 回退到域默认 spec；服务端新增字段自动进入诊断区而不是主路径。
public enum GoalM5PresentationCatalog {
    public static func spec(semanticKey: String?) -> WorkspacePresentationSpec {
        guard let semanticKey else {
            return WorkspacePresentationSpec(domain: .settings, emptyHint: "服务端没有返回内容。")
        }
        if let override = overrides[semanticKey] {
            return override
        }
        guard let domain = domain(for: semanticKey) else {
            return WorkspacePresentationSpec(domain: .settings, emptyHint: "服务端没有返回内容。")
        }
        return WorkspacePresentationSpec(domain: domain, emptyHint: defaultEmptyHint(for: domain))
    }

    /// semantic key 前缀 → 业务域。
    public static func domain(for semanticKey: String) -> SemanticFieldDomain? {
        switch semanticKey.split(separator: ".").first.map(String.init) {
        case "portfolio": .portfolio
        case "journal": .journal
        case "ibkr", "ibkr-admin": .ibkr
        case "discovery": .discovery
        case "decisions": .decisions
        case "crypto": .crypto
        case "quant": .quant
        case "paper": .paper
        case "settings": .settings
        case "admin", "execution": .administration
        default: nil
        }
    }

    static let overrides: [String: WorkspacePresentationSpec] = [
        // MARK: Portfolio（优先级最高：先做组合）

        "portfolio.summary": .init(
            domain: .portfolio,
            summaryKeys: [
                "total_market_value", "total_unrealized_pnl", "total_unrealized_pnl_percent", "total_cost",
                "net_asset_value", "cash_balance", "month_return", "data_completeness",
            ],
            listKey: "positions",
            listColumnKeys: [
                "symbol", "currency", "total_quantity", "current_price", "base_currency_market_value",
                "base_currency_unrealized_pnl", "portfolio_weight",
            ],
            emptyHint: "尚无持仓；添加交易或完成 IBKR 同步后会在此汇总。"
        ),
        "portfolio.positions": .init(
            domain: .portfolio,
            listColumnKeys: [
                "symbol", "currency", "total_quantity", "current_price", "base_currency_market_value",
                "base_currency_unrealized_pnl", "portfolio_weight",
            ],
            emptyHint: "尚无持仓记录。"
        ),
        "portfolio.transactions": .init(domain: .portfolio, emptyHint: "暂无交易记录。"),
        "portfolio.open-lots": .init(domain: .portfolio, emptyHint: "暂无未平仓批次。"),
        "portfolio.completed-trades": .init(domain: .portfolio, emptyHint: "暂无已平仓交易。"),
        "portfolio.performance": .init(domain: .portfolio, emptyHint: "暂无绩效数据。"),
        "portfolio.attribution": .init(domain: .portfolio, emptyHint: "暂无归因数据。"),
        "portfolio.benchmark": .init(domain: .portfolio, emptyHint: "暂无基准对比数据。"),
        "portfolio.health": .init(
            domain: .portfolio,
            summaryKeys: ["status", "overall_score", "total_health_score", "coverage", "generated_at"],
            emptyHint: "健康检查尚未生成。"
        ),
        "portfolio.strategy-profile": .init(domain: .portfolio, emptyHint: "策略画像尚未设置。"),
        "portfolio.interpretation": .init(domain: .portfolio, emptyHint: "暂无个性化解读。"),
        "portfolio.analysis-history": .init(domain: .portfolio, emptyHint: "暂无分析任务。"),
        "portfolio.analysis-scenarios": .init(domain: .portfolio, emptyHint: "暂无压力情景预设。"),
        "portfolio.analysis-optimization-presets": .init(domain: .portfolio, emptyHint: "暂无优化预设。"),
        "portfolio.analysis-job": .init(domain: .portfolio, emptyHint: "任务不存在或已过期。"),

        // MARK: Journal

        "journal.logs": .init(
            domain: .journal,
            listColumnKeys: ["trade_date", "ticker", "direction", "quantity", "price", "status", "source_type"],
            emptyHint: "暂无日志；IBKR 对账草稿与手动记录都会出现在这里。"
        ),

        // MARK: IBKR

        "ibkr.status": .init(
            domain: .ibkr,
            summaryKeys: ["configured", "read_only", "warning_count"],
            sectionKeys: ["latest_sync", "current_or_last_attempt"],
            emptyHint: "尚未配置 IBKR 同步。"
        ),
        "ibkr.accounts": .init(domain: .ibkr, emptyHint: "暂无账户记录。"),
        "ibkr.overview": .init(
            domain: .ibkr,
            summaryKeys: ["available", "position_count", "trade_count", "order_count", "cash_ledger_count"],
            sectionKeys: ["account_summary", "latest_sync", "current_sync"],
            emptyHint: "尚无 Flex 报告；完成一次同步后可查看账户摘要。"
        ),
        "ibkr.performance-daily": .init(domain: .ibkr, emptyHint: "暂无每日绩效。"),
        "ibkr.performance-monthly": .init(domain: .ibkr, emptyHint: "暂无每月绩效。"),
        "ibkr.performance-attribution": .init(domain: .ibkr, emptyHint: "暂无归因数据。"),
        "ibkr.trades-round-trips": .init(domain: .ibkr, emptyHint: "暂无闭环交易。"),
        "ibkr.cash-flows": .init(domain: .ibkr, emptyHint: "暂无现金流记录。"),
        "ibkr.dividends": .init(domain: .ibkr, emptyHint: "暂无股息记录。"),
        "ibkr.fees": .init(domain: .ibkr, emptyHint: "暂无费用记录。"),
        "ibkr.fx-exposure": .init(domain: .ibkr, emptyHint: "暂无汇率暴露数据。"),
        "ibkr.data-health": .init(
            domain: .ibkr,
            summaryKeys: ["available", "position_match_rate", "unrecognized_records", "duplicate_records", "authority_audit_count"],
            sectionKeys: ["coverage", "derived_data", "explicit_gaps", "latest_success", "current_or_last_attempt"],
            emptyHint: "尚无数据健康记录。"
        ),
        "ibkr.cp-status": .init(domain: .ibkr, emptyHint: "Client Portal 尚未启用。"),
        "ibkr.cp-positions": .init(domain: .ibkr, emptyHint: "暂无 Gateway 当前仓位。"),
        "ibkr-admin.config": .init(domain: .ibkr, emptyHint: "配置不可用。"),
        "ibkr-admin.gateway-health": .init(domain: .ibkr, emptyHint: "网关健康数据不可用。"),
        "ibkr-admin.auth-status": .init(domain: .ibkr, emptyHint: "认证状态不可用。"),
        "ibkr-admin.flex-status": .init(domain: .ibkr, emptyHint: "Flex 状态不可用。"),

        // MARK: Discovery / Decisions

        "discovery.latest": .init(
            domain: .discovery,
            summaryKeys: [
                "status", "discovery_mode", "monthly_spend_usd", "monthly_budget_usd", "progress",
                "using_previous_result", "next_scheduled_at",
            ],
            sectionKeys: ["current_run", "result", "usage"],
            emptyHint: "尚未运行过机会发现。"
        ),
        "discovery.runs": .init(
            domain: .discovery,
            listColumnKeys: ["id", "status", "discovery_mode", "requested_at", "completed_at", "failure_code"],
            emptyHint: "暂无运行记录。"
        ),
        "discovery.history": .init(
            domain: .discovery,
            listColumnKeys: ["id", "status", "analysis_date", "created_at"],
            emptyHint: "暂无历史批次。"
        ),
        "discovery.settings": .init(domain: .discovery, emptyHint: "设置不可用。"),
        "discovery.usage": .init(
            domain: .discovery,
            summaryKeys: ["monthly_spend_usd", "monthly_budget_usd"],
            emptyHint: "暂无用量记录。"
        ),
        "discovery.run-detail": .init(
            domain: .discovery,
            sectionKeys: ["usage", "funnel_stats", "warnings", "groups", "raw_candidates", "filtered_candidates"],
            emptyHint: "运行不存在。"
        ),
        "discovery.candidate-detail": .init(
            domain: .discovery,
            summaryKeys: ["normalized_ticker", "company_name", "display_status", "verification_status", "confidence", "final_rank"],
            sectionKeys: ["investment_thesis", "bear_case", "major_risks", "filter_reasons", "financial_snapshot", "evidence", "groups"],
            emptyHint: "候选不存在。"
        ),
        "discovery.history-detail": .init(domain: .discovery, emptyHint: "历史批次不存在。"),
        "decisions.memory-candidates": .init(
            domain: .decisions,
            listColumnKeys: ["title", "memory_type", "scope", "status", "confidence", "importance", "created_at"],
            emptyHint: "暂无待确认记忆。"
        ),
        "decisions.memories": .init(
            domain: .decisions,
            listColumnKeys: ["title", "memory_type", "scope", "status", "importance", "last_used_at", "updated_at"],
            emptyHint: "暂无已保存记忆。"
        ),
        "decisions.memory-settings": .init(domain: .decisions, emptyHint: "记忆设置不可用。"),
        "decisions.investment-decisions": .init(
            domain: .decisions,
            listColumnKeys: ["decision_number", "title", "status", "decision_type", "decision_date", "confidence", "review_due"],
            emptyHint: "暂无投资决策记录。"
        ),

        // MARK: Crypto / Quant / PAPER

        "crypto.search": .init(domain: .crypto, emptyHint: "没有匹配的标的。"),
        "crypto.instruments": .init(
            domain: .crypto,
            listColumnKeys: ["display_label", "symbol", "instrument_id", "market_status"],
            emptyHint: "暂已入库的加密标的为空。"
        ),
        "crypto.market-status": .init(domain: .crypto, emptyHint: "市场状态不可用。"),
        "crypto.candles": .init(
            domain: .crypto,
            listIdentityKeys: ["time", "open_time", "close_time", "id"],
            listColumnKeys: ["time", "open", "high", "low", "close", "volume"],
            emptyHint: "该标的暂无 K 线数据。"
        ),
        "crypto.latest": .init(
            domain: .crypto,
            summaryKeys: ["last_price", "high_price_24h", "low_price_24h", "quote_volume_24h", "source", "stale", "age_seconds"],
            emptyHint: "该标的暂无行情。"
        ),
        "crypto.technical": .init(domain: .crypto, emptyHint: "该标的暂无技术指标。"),
        "crypto.fundamentals": .init(domain: .crypto, emptyHint: "该资产暂无基本面数据。"),
        "crypto.derivatives": .init(domain: .crypto, emptyHint: "该标的暂无衍生品数据。"),
        "crypto.derivatives-regime": .init(domain: .crypto, emptyHint: "该标的暂无衍生品状态识别。"),
        "crypto.research-context": .init(domain: .crypto, emptyHint: "暂无研究上下文。"),
        "crypto.news": .init(domain: .crypto, emptyHint: "暂无相关新闻。"),
        "crypto.reports": .init(domain: .crypto, emptyHint: "暂无研究报告。"),
        "quant.definitions": .init(domain: .quant, emptyHint: "暂无策略定义。"),
        "quant.features": .init(domain: .quant, emptyHint: "暂无特征数据。"),
        "quant.status": .init(domain: .quant, emptyHint: "量化服务状态不可用。"),
        "quant.backtests": .init(
            domain: .quant,
            listColumnKeys: ["id", "status", "strategy_key", "interval", "created_at"],
            emptyHint: "暂无回测运行。"
        ),
        "quant.deployments": .init(
            domain: .quant,
            listColumnKeys: ["id", "status", "strategy_key", "interval", "environment"],
            emptyHint: "暂无部署。"
        ),
        "quant.signals": .init(
            domain: .quant,
            listColumnKeys: ["instrument_symbol", "target_exposure", "status", "decision_time", "expires_at", "deployment_status"],
            emptyHint: "暂无信号。"
        ),
        "quant.signal-runs": .init(domain: .quant, emptyHint: "暂无信号运行记录。"),
        "quant.backtest-detail": .init(
            domain: .quant,
            summaryKeys: ["status", "strategy_key", "strategy_version", "interval", "start_at", "end_at", "created_at"],
            sectionKeys: ["metrics", "warnings"],
            emptyHint: "回测不存在。"
        ),
        "quant.equity": .init(
            domain: .quant,
            listIdentityKeys: ["time", "date", "id"],
            listColumnKeys: ["time", "equity"],
            emptyHint: "暂无净值曲线。"
        ),
        "quant.backtest-trades": .init(domain: .quant, emptyHint: "该回测没有交易。"),
        "paper.account": .init(
            domain: .paper,
            sectionKeys: ["account"],
            emptyHint: "尚未创建模拟账户。"
        ),
        "paper.config": .init(domain: .paper, emptyHint: "模拟器配置不可用。"),
        "paper.orders": .init(
            domain: .paper,
            listColumnKeys: ["id", "instrument_symbol", "side", "status", "intended_quantity", "avg_fill_price", "fee"],
            emptyHint: "暂无模拟订单。"
        ),
        "paper.fills": .init(
            domain: .paper,
            listColumnKeys: ["id", "instrument_symbol", "side", "quantity", "price", "fee", "fill_time"],
            emptyHint: "暂无成交。"
        ),
        "paper.ledger": .init(domain: .paper, emptyHint: "账本为空。"),
        "paper.runs": .init(domain: .paper, emptyHint: "暂无处理运行。"),
        "paper.reconciliations": .init(domain: .paper, emptyHint: "暂无对账记录。"),

        // MARK: Settings / Administration

        "settings.user": .init(
            domain: .settings,
            summaryKeys: ["threshold_20m", "threshold_1h", "threshold_day", "alert_cooldown_minutes", "price_poll_minutes"],
            emptyHint: "设置不可用。"
        ),
        "settings.providers": .init(
            domain: .settings,
            summaryKeys: ["redis_available", "generated_at"],
            sectionKeys: ["providers"],
            emptyHint: "数据源状态不可用。"
        ),
        "settings.ai-config": .init(
            domain: .settings,
            summaryKeys: ["enabled", "streaming", "default_model", "conversations_enabled"],
            sectionKeys: ["memory", "rich_content", "web_search", "models"],
            emptyHint: "AI 配置不可用。"
        ),
        "admin.users": .init(
            domain: .administration,
            listColumnKeys: ["username", "role", "status", "created_at", "note"],
            emptyHint: "暂无用户。"
        ),
        "admin.fmp-status": .init(
            domain: .administration,
            summaryKeys: ["requests_remaining", "usable_limit", "requests_used", "failed_item_count", "next_scheduled_run"],
            emptyHint: "FMP 状态不可用。"
        ),
        "execution.status": .init(domain: .administration, emptyHint: "执行控制状态不可用。"),
        "execution.accounts": .init(domain: .administration, emptyHint: "暂无执行账户。"),
        "execution.agents": .init(domain: .administration, emptyHint: "暂无执行代理。"),
        "execution.orders": .init(domain: .administration, emptyHint: "暂无执行订单。"),
        "execution.events": .init(domain: .administration, emptyHint: "暂无执行事件。"),
    ]

    static func defaultEmptyHint(for domain: SemanticFieldDomain) -> String {
        switch domain {
        case .portfolio: "尚无数据。"
        case .journal: "暂无日志。"
        case .ibkr: "尚无 IBKR 数据。"
        case .discovery: "暂无发现数据。"
        case .decisions: "暂无记录。"
        case .aiChat: "暂无消息。"
        case .crypto: "暂无数据。"
        case .quant: "暂无量化数据。"
        case .paper: "模拟器暂无数据。"
        case .settings: "设置不可用。"
        case .administration: "暂无数据。"
        case .macro: "暂无宏观数据。"
        case .mood: "暂无情绪数据。"
        case .industry: "暂无行业数据。"
        case .valuation: "暂无估值数据。"
        case .technical: "暂无技术分析数据。"
        case .financials: "暂无报表数据。"
        case .congress: "暂无数据。"
        }
    }
}
