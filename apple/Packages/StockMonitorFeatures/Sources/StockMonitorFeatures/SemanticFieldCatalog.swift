import Foundation
import StockMonitorDesign

/// R2.1 字段目录：服务端 snake_case（技术分析为 camelCase）字段 → 中文名称、单位与排序。
/// 同一指标在所有页面使用同一名称、精度和单位；未登记字段进入诊断区，不再平铺英文 key。
public enum SemanticFieldKind: Equatable, Sendable {
    case text
    case longText
    case integer
    case decimal(precision: Int)
    /// 0.023 → +2.3%
    case percent(precision: Int)
    /// 已是百分数值（0-100 或任意），仅追加 % 与符号
    case percentValue(precision: Int)
    case multiple(precision: Int)
    /// 缩写金额（K/M/B）；nil 表示使用页面基础币种
    case amount(currency: String?)
    case price(precision: Int, currency: String?)
    case boolean(trueLabel: String, falseLabel: String)
    case dateText
    case datetimeText
    /// 秒数 → 可读时长
    case duration
    case identifier

    public static var equalByCase: (SemanticFieldKind, SemanticFieldKind) -> Bool {
        { $0 == $1 }
    }
}

public struct SemanticFieldSpec: Sendable, Equatable {
    public let key: String
    public let label: String
    public let kind: SemanticFieldKind
    public let explanation: String?

    public init(_ key: String, _ label: String, _ kind: SemanticFieldKind, explanation: String? = nil) {
        self.key = key
        self.label = label
        self.kind = kind
        self.explanation = explanation
    }

    public static func == (lhs: SemanticFieldSpec, rhs: SemanticFieldSpec) -> Bool {
        lhs.key == rhs.key
    }

    /// 数组字面量里的登记简写：`.spec("key", "中文名", .kind)`。
    public static func spec(
        _ key: String, _ label: String, _ kind: SemanticFieldKind, explanation: String? = nil
    ) -> SemanticFieldSpec {
        SemanticFieldSpec(key, label, kind, explanation: explanation)
    }
}

public enum SemanticFieldDomain: String, CaseIterable, Sendable {
    // M5 工作台域
    case portfolio, journal, ibkr, discovery, decisions, aiChat
    case crypto, quant, paper, settings, administration
    // M4 证据域
    case macro, mood, industry, valuation, technical, financials, congress
}

/// 全局共享 key 目录：跨域同名同义的字段只登记一次。
/// 域目录负责领域专属字段与业务排序；查找顺序为 域覆盖 → 全局。
public enum SemanticKeyDictionary {
    public static let shared: [String: SemanticFieldSpec] = dictionary([
        // 标识与通用元数据
        spec("id", "标识", .identifier),
        spec("status", "状态", .text),
        spec("stage", "阶段", .text),
        spec("created_at", "创建时间", .datetimeText),
        spec("updated_at", "更新时间", .datetimeText),
        spec("started_at", "开始时间", .datetimeText),
        spec("completed_at", "完成时间", .datetimeText),
        spec("finished_at", "完成时间", .datetimeText),
        spec("requested_at", "发起时间", .datetimeText),
        spec("cancelled_at", "取消时间", .datetimeText),
        spec("generated_at", "生成时间", .datetimeText),
        spec("as_of", "数据截至", .dateText),
        spec("asOf", "数据截至", .dateText),
        spec("synced_at", "同步时间", .datetimeText),
        spec("fetched_at", "抓取时间", .datetimeText),
        spec("server_time", "服务器时间", .datetimeText),
        spec("received_at", "接收时间", .datetimeText),
        spec("total", "总数", .integer),
        spec("page", "页码", .integer),
        spec("limit", "每页数量", .integer),
        spec("offset", "起始位置", .integer),
        spec("cursor", "分页游标", .text),
        spec("has_more", "还有更多", .boolean(trueLabel: "是", falseLabel: "否")),
        spec("items", "记录列表", .text),
        spec("count", "数量", .integer),
        spec("warnings", "警告", .longText),
        spec("warning", "提示", .longText),
        spec("error", "错误信息", .longText),
        spec("error_message", "错误信息", .longText),
        spec("error_stage", "出错阶段", .text),
        spec("error_code", "错误代码", .text),
        spec("source", "来源", .text),
        spec("provider", "数据源", .text),
        spec("currency", "币种", .text),
        spec("base_currency", "基础币种", .text),
        spec("symbol", "代码", .text),
        spec("ticker", "代码", .text),
        spec("name", "名称", .text),
        spec("title", "标题", .text),
        spec("enabled", "已启用", .boolean(trueLabel: "已启用", falseLabel: "未启用")),
        spec("configured", "已配置", .boolean(trueLabel: "已配置", falseLabel: "未配置")),
        spec("available", "可用", .boolean(trueLabel: "可用", falseLabel: "不可用")),
        spec("stale", "是否过期", .boolean(trueLabel: "旧数据", falseLabel: "最新")),
        spec("confidence", "置信度", .percent(precision: 0), explanation: "服务端给出的 0–1 置信度。"),
        spec("progress", "进度", .percentValue(precision: 0)),
        spec("trigger_type", "触发方式", .text),
        spec("note", "备注", .longText),
        spec("description", "说明", .longText),
        spec("reason", "原因", .longText),
        spec("interval", "周期", .text),
        spec("version", "版本", .text),
        spec("mode", "模式", .text),
        spec("read_only", "只读模式", .boolean(trueLabel: "只读", falseLabel: "可写")),
        spec("pending", "待处理", .integer),
        spec("failed", "失败", .integer),
        // 金额与收益通用
        spec("fees", "费用", .amount(currency: nil)),
        spec("taxes", "税费", .amount(currency: nil)),
        spec("realized_pnl", "已实现盈亏", .amount(currency: nil)),
        spec("unrealized_pnl", "浮动盈亏", .amount(currency: nil)),
        spec("unrealized_pnl_percent", "浮动盈亏比例", .percent(precision: 2)),
        spec("max_drawdown", "最大回撤", .percent(precision: 1)),
        spec("win_rate", "胜率", .percent(precision: 1)),
    ])

    // swiftlint:disable:next cyclomatic_complexity
    public static func dictionary(_ specs: [SemanticFieldSpec]) -> [String: SemanticFieldSpec] {
        Dictionary(specs.map { ($0.key, $0) }, uniquingKeysWith: { first, _ in first })
    }

    public static func spec(
        _ key: String, _ label: String, _ kind: SemanticFieldKind, explanation: String? = nil
    ) -> SemanticFieldSpec {
        SemanticFieldSpec(key, label, kind, explanation: explanation)
    }

    /// 按域解析字段：先查域覆盖，再回退全局目录。
    public static func resolve(key: String, domain: SemanticFieldDomain) -> SemanticFieldSpec? {
        SemanticDomainCatalog.fields(for: domain)[key] ?? shared[key]
    }

    /// 域内业务排序：摘要与列表列按此顺序展示。
    public static func primaryKeys(for domain: SemanticFieldDomain) -> [String] {
        SemanticDomainCatalog.primaryKeys(for: domain)
    }
}

/// 各业务域的字段目录与业务排序。新增字段时在这里登记中文名、单位与解释。
public enum SemanticDomainCatalog {
    public static func fields(for domain: SemanticFieldDomain) -> [String: SemanticFieldSpec] {
        switch domain {
        case .portfolio: portfolioFields
        case .journal: journalFields
        case .ibkr: ibkrFields
        case .discovery: discoveryFields
        case .decisions: decisionsFields
        case .aiChat: aiChatFields
        case .crypto: cryptoFields
        case .quant: quantFields
        case .paper: paperFields
        case .settings: settingsFields
        case .administration: administrationFields
        case .macro: macroFields
        case .mood: moodFields
        case .industry: industryFields
        case .valuation: valuationFields
        case .technical: technicalFields
        case .financials: financialsFields
        case .congress: congressFields
        }
    }

    public static func primaryKeys(for domain: SemanticFieldDomain) -> [String] {
        switch domain {
        case .portfolio:
            [
                "total_market_value", "total_unrealized_pnl", "total_unrealized_pnl_percent", "total_cost",
                "net_asset_value", "cash_balance", "month_return", "year_return", "data_completeness",
                "position_count", "priced_count", "valuation_available",
                "symbol", "currency", "total_quantity", "current_price", "market_value",
                "base_currency_market_value", "portfolio_weight", "daily_change_percent", "valuation_available",
                "authority_source", "fx_rate", "latest_sync_at", "account_data_source",
            ]
        case .journal:
            ["trade_date", "ticker", "direction", "quantity", "price", "status", "ai_summary", "created_at"]
        case .ibkr:
            [
                "available", "configured", "status", "net_liquidation", "total_cash", "realized_pnl",
                "unrealized_pnl", "dividends", "data_completeness", "position_match_rate",
                "latest_sync", "account_id_masked", "warning_count", "position_count",
            ]
        case .discovery:
            [
                "status", "discovery_mode", "monthly_spend_usd", "monthly_budget_usd", "progress",
                "using_previous_result", "next_scheduled_at", "counts", "usage", "groups",
                "raw_candidates", "filtered_candidates", "limitations",
            ]
        case .decisions:
            [
                "title", "status", "decision_type", "decision_date", "confidence", "importance",
                "memory_type", "scope", "action", "position_intent", "time_horizon", "review_due",
            ]
        case .aiChat:
            ["role", "status", "model", "content", "citation_count", "created_at"]
        case .crypto:
            [
                "last_price", "high_price_24h", "low_price_24h", "quote_volume_24h", "display_label",
                "source", "stale", "age_seconds", "event_time_ms", "instrument_id", "symbol",
            ]
        case .quant:
            [
                "status", "strategy_key", "strategy_version", "interval", "metrics", "created_at",
                "target_exposure", "decision_time", "expires_at", "deployment_status",
            ]
        case .paper:
            [
                "status", "nav", "equity", "cash", "gross_exposure", "exposure_ratio", "execution_mode",
                "available_balance", "used_margin", "performance", "positions", "orders",
            ]
        case .settings:
            [
                "threshold_20m", "threshold_1h", "threshold_day", "alert_cooldown_minutes",
                "price_poll_minutes", "generated_at", "redis_available",
            ]
        case .administration:
            ["username", "role", "status", "created_at", "note", "requests_remaining", "usable_limit"]
        case .macro:
            [
                "state", "label_zh", "why_it_matters", "rising_interpretation", "falling_interpretation",
                "bullish_scenarios", "bearish_scenarios", "context_notes", "status", "age_days",
                "latest", "previous", "observation_date", "value", "unit", "frequency", "display_name_zh",
            ]
        case .mood:
            [
                "state", "mood_score", "direction", "severity", "confidence", "active", "resolved",
                "trading_date", "status", "coverage", "scope_key",
            ]
        case .industry:
            ["status", "total", "freshness", "priorities", "started_at", "finished_at", "failed"]
        case .valuation:
            [
                "value", "current_price", "margin_of_safety", "status", "available", "growth_rate",
                "intrinsic_value", "premium_or_discount", "eps_ttm", "book_value_per_share", "aaa_yield",
            ]
        case .technical:
            [
                "generatedAt", "dataThrough", "latestClose", "weeklyTrend", "nearestSupport",
                "nearestResistance", "source", "analysisVersion",
            ]
        case .financials:
            ["revenue", "net_income", "eps", "total_assets", "shareholders_equity", "free_cash_flow", "period_end"]
        case .congress:
            ["buys", "sells"]
        }
    }
}

/// 缺失语义：区分 missing、not applicable、not collected、stale、provider failed，
/// 不再把所有缺口写成同一句"数据不足"。
public enum SemanticMissingSemantics {
    /// 服务端/网页惯用的缺口哨兵值 → 对应状态。
    public static func state(fromString raw: String) -> FinancialValueState? {
        switch raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "not_applicable", "not applicable", "n/a", "不适用":
            .notApplicable
        case "not_collected", "not collected", "尚未采集":
            .notCollected
        case "provider_failed", "provider failed", "数据源失败", "source_unavailable", "unavailable":
            .providerFailed
        case "stale", "旧数据", "expired", "过期":
            .stale
        case "insufficient", "insufficient_data", "数据不足", "missing", "no_data":
            .missing
        default:
            nil
        }
    }

    /// 从对象上下文推断某字段的缺失状态：null → missing；哨兵字符串 → 对应状态；
    /// 同级 `data_status`/`status` 为 provider_failed 时整块视为数据源失败。
    public static func state(for value: JSONValue, in object: [String: JSONValue]) -> FinancialValueState {
        if case let .string(raw) = value, let mapped = state(fromString: raw) {
            return mapped
        }
        for key in ["data_status", "status"] where (object[key]?.stringValue).map({ state(fromString: $0) }) != nil {
            if case let .string(raw) = object[key] ?? .null, let mapped = state(fromString: raw) {
                return mapped
            }
        }
        if object["stale"]?.boolValue == true {
            return .stale
        }
        return .missing
    }
}

/// 字段格式化：kind + JSONValue → FinancialDisplayValue。字符串数字（Crypto 价格）也会解析。
public enum SemanticFieldFormatter {
    // swiftlint:disable:next cyclomatic_complexity
    public static func display(
        _ value: JSONValue?, spec: SemanticFieldSpec, baseCurrency: String?
    ) -> FinancialDisplayValue {
        guard let value, value != .null else {
            return FinancialValueFormatter.missing(.missing)
        }
        switch spec.kind {
        case .text, .longText:
            return textValue(value)
        case .identifier:
            switch value {
            case let .number(number): return FinancialDisplayValue(text: "#\(Int(number))")
            case let .string(string): return FinancialDisplayValue(text: string)
            default: return textValue(value)
            }
        case .integer:
            if let int = numeric(value) {
                return FinancialDisplayValue(text: int.formatted(.number.grouping(.automatic).precision(.fractionLength(0))))
            }
            return textValue(value)
        case let .decimal(precision):
            if let double = numeric(value) {
                return FinancialDisplayValue(
                    text: double.formatted(.number.grouping(.automatic).precision(.fractionLength(precision)))
                )
            }
            return textValue(value)
        case let .percent(precision):
            if let double = numeric(value) {
                return FinancialValueFormatter.percent(double, precision: precision)
            }
            return textValue(value)
        case let .percentValue(precision):
            if let double = numeric(value) {
                let text = double.formatted(
                    .number.grouping(.automatic).precision(.fractionLength(precision)).sign(strategy: .always())
                ) + "%"
                return FinancialDisplayValue(text: text)
            }
            return textValue(value)
        case let .multiple(precision):
            return FinancialValueFormatter.multiple(numeric(value), precision: precision)
        case let .amount(currency):
            return FinancialValueFormatter.amount(numeric(value), currency: currency ?? baseCurrency ?? "")
        case let .price(precision, currency):
            return FinancialValueFormatter.price(numeric(value), currency: currency ?? baseCurrency ?? "", precision: precision)
        case let .boolean(trueLabel, falseLabel):
            if case let .bool(bool) = value {
                return FinancialDisplayValue(text: bool ? trueLabel : falseLabel)
            }
            return textValue(value)
        case .dateText:
            return FinancialDisplayValue(text: shortDate(value.displayText))
        case .datetimeText:
            return FinancialDisplayValue(text: readableTimestamp(value.displayText))
        case .duration:
            if let seconds = numeric(value) {
                return FinancialDisplayValue(text: durationText(seconds))
            }
            return textValue(value)
        }
    }

    static func numeric(_ value: JSONValue) -> Double? {
        switch value {
        case let .number(number): number.isFinite ? number : nil
        case let .string(string): Double(string.trimmingCharacters(in: .whitespaces))
        default: nil
        }
    }

    static func textValue(_ value: JSONValue) -> FinancialDisplayValue {
        switch value {
        case let .array(items):
            if items.isEmpty {
                return FinancialDisplayValue(text: FinancialValueFormatter.unavailable, qualifier: "数据不足")
            }
            let shown = items.prefix(6).map(\.displayText)
            let suffix = items.count > 6 ? "…（共 \(items.count) 项）" : ""
            return FinancialDisplayValue(text: shown.joined(separator: "；") + suffix)
        case let .object(fields):
            let pairs = fields.keys.sorted().prefix(6).map { "\($0)：\(fields[$0]?.displayText ?? "—")" }
            if pairs.isEmpty {
                return FinancialDisplayValue(text: FinancialValueFormatter.unavailable, qualifier: "服务端未返回内容")
            }
            let suffix = fields.count > 6 ? "…（共 \(fields.count) 项）" : ""
            return FinancialDisplayValue(text: pairs.joined(separator: "；") + suffix)
        case .bool, .string, .number:
            return FinancialDisplayValue(text: value.displayText)
        case .null:
            return FinancialDisplayValue(text: FinancialValueFormatter.unavailable, qualifier: "数据不足")
        }
    }

    /// ISO 时间戳（或毫秒时间戳数字）→ 可读的 yyyy-MM-dd HH:mm（UTC 原样，不做时区换算）。
    public static func readableTimestamp(_ raw: String) -> String {
        if let milliseconds = Double(raw), milliseconds > 1_000_000_000_000 {
            let seconds = milliseconds / 1000
            let date = Date(timeIntervalSince1970: seconds)
            return date.formatted(.iso8601.year().month().day().dateSeparator(.dash).timeSeparator(.colon).time(includingFractionalSeconds: false)) + " UTC"
        }
        let cleaned = raw.replacingOccurrences(of: "T", with: " ")
        let noZone = cleaned.split(separator: ".").first.map(String.init) ?? cleaned
        return String(noZone.prefix(16))
    }

    public static func shortDate(_ raw: String) -> String {
        String(raw.prefix(10))
    }

    public static func durationText(_ seconds: Double) -> String {
        guard seconds >= 0, seconds.isFinite else { return "—" }
        if seconds < 60 {
            return "\(Int(seconds)) 秒"
        }
        if seconds < 3600 {
            return String(format: "%.0f 分钟", seconds / 60)
        }
        if seconds < 86400 {
            return String(format: "%.1f 小时", seconds / 3600)
        }
        return String(format: "%.1f 天", seconds / 86400)
    }
}
