import StockMonitorCore
import StockMonitorDesign
import SwiftUI

// MARK: - Goal R5 deterministic visual fixtures

enum R5FixtureData {
    static let portfolio: JSONValue = .object([
        "base_currency": .string("USD"),
        "total_market_value": .number(248_420.15),
        "total_unrealized_pnl": .number(18934.62),
        "total_unrealized_pnl_percent": .number(0.0825),
        "overall_score": .number(78),
        "coverage": .number(0.91),
        "valuation_available": .bool(false),
        "missing_fx": .array([.string("JPY")]),
        "positions": .array([
            .object([
                "symbol": .string("NVDA"), "currency": .string("USD"), "total_quantity": .number(120),
                "current_price": .number(128.44), "base_currency_market_value": .number(15412.8),
                "base_currency_unrealized_pnl": .number(2318.4), "portfolio_weight": .number(0.062),
            ]),
            .object([
                "symbol": .string("1578.T"), "currency": .string("JPY"), "total_quantity": .number(300),
                "current_price": .number(3145), "base_currency_market_value": .null,
                "base_currency_unrealized_pnl": .null, "portfolio_weight": .null,
            ]),
        ]),
        "generated_at": .string("2026-09-10T10:12:00Z"),
    ])

    static let discovery: JSONValue = .object([
        "status": .string("completed"), "monthly_spend_usd": .number(1.284), "monthly_budget_usd": .number(10),
        "funnel_stats": .object([
            "raw_candidate_count": .number(12), "verified_candidate_count": .number(10), "accepted_count": .number(8),
        ]),
        "result": .object([
            "groups": .array([
                .object(["name": .string("盈利质量"), "candidate_count": .number(3)]),
                .object(["name": .string("估值修复"), "candidate_count": .number(5)]),
            ]),
        ]),
        "next_scheduled_at": .string("2026-09-13T02:00:00Z"),
    ])

    static let journal: JSONValue = .object([
        "items": .array([
            .object([
                "trade_date": .string("2026-09-09"), "ticker": .string("NVDA"), "direction": .string("buy"),
                "quantity": .number(20), "price": .number(124.8), "status": .string("reviewed"),
                "source_type": .string("IBKR"), "review": .string("等待财报后再评估仓位上限。"),
            ]),
            .object([
                "trade_date": .string("2026-09-03"), "ticker": .string("MSFT"), "direction": .string("sell"),
                "quantity": .number(8), "price": .number(421.2), "status": .string("draft"),
                "source_type": .string("manual"),
            ]),
        ]),
    ])

    static let ibkr: JSONValue = .object([
        "available": .bool(true), "position_count": .number(12), "trade_count": .number(31),
        "order_count": .number(4), "cash_ledger_count": .number(18), "position_match_rate": .number(0.96),
        "account_summary": .object(["account_id_masked": .string("***1842"), "base_currency": .string("USD")]),
        "latest_sync": .object(["status": .string("completed"), "completed_at": .string("2026-09-10T09:45:00Z")]),
    ])

    static let crypto: JSONValue = .object([
        "symbol": .string("BTC-USDT"), "last_price": .number(112_480.35), "high_price_24h": .number(114_092.4),
        "low_price_24h": .number(109_842.1), "quote_volume_24h": .number(2_483_000_000),
        "source": .string("Binance market data"), "stale": .bool(false), "as_of": .string("2026-09-10T10:10:00Z"),
    ])

    static let quant: JSONValue = .object([
        "status": .string("completed"), "strategy_key": .string("btc-momentum-v4"), "strategy_version": .string("4.2"),
        "interval": .string("1d"), "start_at": .string("2022-01-01"), "end_at": .string("2026-09-01"),
        "metrics": .object(["total_return": .number(0.684), "max_drawdown": .number(-0.172), "sharpe_ratio": .number(1.43)]),
        "warnings": .array([.string("手续费按历史配置估算")]),
    ])

    static let paper: JSONValue = .object([
        "mode": .string("PAPER"), "live_trading": .bool(false),
        "account": .object([
            "status": .string("active"), "base_currency": .string("USDT"), "equity": .number(104_281.22),
            "cash_balance": .number(42830.18), "order_count": .number(18),
        ]),
        "last_reconciled_at": .string("2026-09-10T09:55:00Z"),
    ])

    static let settings: JSONValue = .object([
        "redis_available": .bool(true), "generated_at": .string("2026-09-10T10:00:00Z"),
        "providers": .array([
            .object(["name": .string("Yahoo"), "available": .bool(true), "freshness": .string("live")]),
            .object(["name": .string("SEC EDGAR"), "available": .bool(true), "freshness": .string("cached")]),
        ]),
    ])

    static let admin: JSONValue = .object([
        "items": .array([
            .object([
                "username": .string("admin"), "role": .string("admin"),
                "status": .string("active"), "created_at": .string("2026-07-01"),
            ]),
            .object([
                "username": .string("research"), "role": .string("user"),
                "status": .string("active"), "created_at": .string("2026-08-12"),
            ]),
        ]),
    ])

    static let messages: JSONValue = .object([
        "items": .array([
            .object([
                "role": .string("user"), "content": .string("请解释 **NVDA** 当前仓位最重要的风险，并给出证据。"),
                "created_at": .string("2026-09-10T10:01:00Z"),
            ]),
            .object([
                "role": .string("assistant"), "model": .string("gpt-5.4"),
                "content": .string("### 结论\n\n当前主要风险不是单日波动，而是组合对同一盈利逻辑的集中。\n\n- 仓位权重高于策略画像上限。\n- 估值模型分歧扩大。\n- 数据覆盖为 91%，仍有 JPY 汇率缺口。"),
                "created_at": .string("2026-09-10T10:02:12Z"), "citation_count": .number(2), "tool_call_count": .number(2),
                "citations": .array([.string("https://example.com/report"), .string("组合健康检查 · 2026-09-10")]),
                "content_parts": .object(["parts": .array([
                    .object(["type": .string("tool_status"), "title": .string("读取组合健康"), "status": .string("完成")]),
                    .object(["type": .string("code"), "title": .string("风险口径"), "code": .string("weight > profile.max_position_weight")]),
                ])]),
            ]),
        ]),
    ])
}

struct R5BeforeGenericWorkspaceFixture: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: StockMonitorSpacing.medium) {
                Text("组合与风险分析").font(.title2.bold())
                Text("/api/portfolio/summary").font(.caption).foregroundStyle(.secondary)
                GroupBox("total_market_value") { Text("248420.15") }
                GroupBox("missing_fx") { GroupBox("#1") { Text("JPY") } }
                GroupBox("positions") {
                    GroupBox("#1") { Text("symbol: NVDA\nbase_currency_market_value: 15412.8") }
                }
            }
            .padding(StockMonitorSpacing.large)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(StockMonitorCanvas.background)
    }
}

struct R5AIConversationFixture: View {
    var body: some View {
        ScrollView {
            AIConversationMessagesView(messages: R5FixtureData.messages)
                .frame(maxWidth: StockMonitorContentWidth.readable)
                .padding(StockMonitorSpacing.large)
                .frame(maxWidth: .infinity)
        }
        .background(StockMonitorCanvas.background)
    }
}

struct R5WorkspaceFixture: View {
    let descriptor: WorkspaceDescriptor
    let semantic: String
    let payload: JSONValue

    var body: some View {
        let endpoint = descriptor.endpoints.first { $0.semantic == semantic } ?? descriptor.endpoints[0]
        let presentation = SemanticPresentationBuilder.presentation(
            title: endpoint.title,
            spec: GoalM5PresentationCatalog.spec(semanticKey: semantic),
            payload: payload
        )
        R5WorkspaceContentView(descriptor: descriptor, endpoint: endpoint, payload: payload, presentation: presentation)
    }
}
