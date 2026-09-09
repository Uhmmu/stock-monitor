import Foundation
import StockMonitorCore
import StockMonitorDesign
import SwiftUI

// MARK: - Goal R5 workspace information architecture

public struct R5NavigationSection: Identifiable, Equatable, Sendable {
    public let title: String
    public let endpoints: [WorkspaceEndpoint]

    public var id: String {
        title
    }
}

public enum R5WorkspaceBlueprint {
    /// Complex workspaces use a stable task hierarchy instead of exposing the API catalogue as one flat list.
    public static func sections(for descriptor: WorkspaceDescriptor) -> [R5NavigationSection] {
        let grouped = Dictionary(grouping: descriptor.endpoints) { endpoint in
            sectionTitle(for: endpoint.semantic, phase: descriptor.phase)
        }
        return sectionOrder(for: descriptor.phase).compactMap { title in
            guard let endpoints = grouped[title], !endpoints.isEmpty else { return nil }
            return R5NavigationSection(title: title, endpoints: endpoints)
        }
    }

    public static func visibleSections(
        for descriptor: WorkspaceDescriptor,
        contextValues: [String: String]
    ) -> [R5NavigationSection] {
        sections(for: descriptor).compactMap { section in
            let visible = section.endpoints.filter { endpoint in
                endpoint.placeholders.allSatisfy { contextValues[$0]?.isEmpty == false }
            }
            return visible.isEmpty ? nil : R5NavigationSection(title: section.title, endpoints: visible)
        }
    }

    public static func icon(for semantic: String?) -> String {
        guard let semantic else { return "rectangle.stack" }
        if semantic.contains("summary") || semantic.hasSuffix(".status") || semantic.hasSuffix(".latest") {
            return "gauge"
        }
        if semantic.contains("position") || semantic.contains("holding") {
            return "chart.pie"
        }
        if semantic.contains("performance") || semantic.contains("equity") {
            return "chart.xyaxis.line"
        }
        if semantic.contains("transaction") || semantic.contains("trade") || semantic.contains("fill") {
            return "list.bullet.rectangle"
        }
        if semantic.contains("analysis") || semantic.contains("run") || semantic.contains("backtest") {
            return "clock.arrow.circlepath"
        }
        if semantic.contains("setting") || semantic.contains("config") {
            return "slider.horizontal.3"
        }
        if semantic.contains("health") || semantic.contains("risk") {
            return "shield.lefthalf.filled"
        }
        if semantic.contains("news") || semantic.contains("report") {
            return "doc.text"
        }
        if semantic.contains("account") || semantic.contains("ledger") {
            return "building.columns"
        }
        return "rectangle.stack"
    }

    public static func contextualFields(for descriptor: WorkspaceDescriptor) -> [String] {
        var seen = Set<String>()
        return descriptor.endpoints.flatMap(\.placeholders).filter { seen.insert($0).inserted }
    }

    public static func contextSource(for field: String, descriptor: WorkspaceDescriptor) -> WorkspaceEndpoint? {
        let preferredSemantic: String? = switch field {
        case "instrument_id", "asset_id": "crypto.instruments"
        case "job_id": "portfolio.analysis-history"
        case "candidate_id": "discovery.latest"
        case "history_id": "discovery.history"
        case "run_id": descriptor.phase == .ai ? "discovery.runs" : "quant.backtests"
        default: nil
        }
        return descriptor.endpoints.first { $0.semantic == preferredSemantic }
    }

    public static func fieldLabel(_ field: String) -> String {
        switch field {
        case "instrument_id", "asset_id": "研究标的"
        case "job_id": "分析任务"
        case "run_id": "运行批次"
        case "candidate_id": "候选股票"
        case "history_id": "历史批次"
        default: "当前对象"
        }
    }

    private static func sectionTitle(for semantic: String?, phase: GoalM5Phase) -> String {
        guard let semantic else { return "其他" }
        switch phase {
        case .ai:
            if semantic.hasPrefix("decisions.memory") {
                return "记忆"
            }
            if semantic.hasPrefix("decisions.investment") {
                return "决策"
            }
            if semantic == "discovery.latest" || semantic == "discovery.usage" {
                return "发现概览"
            }
            if semantic.contains("candidate") {
                return "候选详情"
            }
            if semantic.contains("run") {
                return "运行"
            }
            if semantic.contains("history") {
                return "历史"
            }
            return "设置"
        case .portfolio:
            if semantic.hasPrefix("journal") {
                return "交易日志"
            }
            if semantic.hasPrefix("ibkr-admin") {
                return "连接诊断"
            }
            if semantic == "ibkr.status" || semantic == "ibkr.overview" || semantic == "ibkr.accounts" {
                return "账户概览"
            }
            if semantic.hasPrefix("ibkr.performance") || semantic.contains("round-trips") {
                return "绩效与交易"
            }
            if semantic.contains("cash-flow") || semantic.contains("dividend") || semantic.contains("fees") || semantic.contains("fx-") {
                return "现金、费用与 FX"
            }
            if semantic.hasPrefix("ibkr") {
                return "数据与同步"
            }
            if semantic == "portfolio.summary" || semantic == "portfolio.positions" || semantic == "portfolio.health" {
                return "组合概览"
            }
            if semantic.contains("transaction") || semantic.contains("lots") || semantic.contains("completed") {
                return "交易与批次"
            }
            if semantic.contains("performance") || semantic.contains("attribution") || semantic.contains("benchmark") {
                return "绩效"
            }
            if semantic.contains("strategy") || semantic.contains("interpretation") {
                return "策略画像"
            }
            return "分析任务"
        case .crypto:
            if semantic.hasPrefix("settings") {
                return "服务端设置"
            }
            if semantic.hasPrefix("admin") || semantic.hasPrefix("execution") {
                return semantic.hasPrefix("execution") ? "执行控制" : "系统状态"
            }
            if semantic.hasPrefix("paper") {
                return semantic == "paper.account" || semantic == "paper.config" ? "PAPER 概览" : "订单、账本与对账"
            }
            if semantic.hasPrefix("quant") {
                if semantic.contains("definition") || semantic.contains("feature") || semantic.hasSuffix(".status") {
                    return "研究定义"
                }
                if semantic.contains("signal") || semantic.contains("deployment") {
                    return "信号与部署"
                }
                return "回测"
            }
            if semantic == "crypto.search" || semantic == "crypto.instruments" || semantic == "crypto.market-status" {
                return "市场概览"
            }
            if semantic.contains("candle") || semantic.contains("latest") || semantic.contains("technical") {
                return "行情与图表"
            }
            if semantic.contains("fundamental") || semantic.contains("derivative") {
                return "基本面与衍生品"
            }
            return "新闻与研究"
        }
    }

    private static func sectionOrder(for phase: GoalM5Phase) -> [String] {
        switch phase {
        case .ai: ["发现概览", "候选详情", "运行", "历史", "记忆", "决策", "设置", "其他"]
        case .portfolio: ["组合概览", "交易与批次", "绩效", "策略画像", "分析任务", "交易日志", "账户概览", "绩效与交易", "现金、费用与 FX", "数据与同步", "连接诊断", "其他"]
        case .crypto: ["市场概览", "行情与图表", "基本面与衍生品", "新闻与研究", "研究定义", "回测", "信号与部署", "PAPER 概览", "订单、账本与对账", "服务端设置", "系统状态", "执行控制", "其他"]
        }
    }
}

public struct R5EntityOption: Identifiable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let secondary: String?
}

public enum R5EntityOptionExtractor {
    /// Extracts user-facing choices from authoritative list payloads. IDs remain transport details.
    public static func options(for field: String, payload: JSONValue) -> [R5EntityOption] {
        let keys: [String] = switch field {
        case "instrument_id": ["instrument_id", "id"]
        case "asset_id": ["asset_id", "id"]
        case "job_id": ["job_id", "id"]
        case "run_id": ["run_id", "id"]
        case "candidate_id": ["candidate_id", "id"]
        case "history_id": ["history_id", "id"]
        default: [field, "id"]
        }
        var found: [R5EntityOption] = []
        collect(payload, field: field, keys: keys, into: &found, depth: 0)
        var seen = Set<String>()
        return found.filter { seen.insert($0.id).inserted }.prefix(100).map(\.self)
    }

    private static func collect(
        _ value: JSONValue,
        field: String,
        keys: [String],
        into found: inout [R5EntityOption],
        depth: Int
    ) {
        guard depth < 7, found.count < 200 else { return }
        switch value {
        case let .array(items):
            for item in items {
                collect(item, field: field, keys: keys, into: &found, depth: depth + 1)
            }
        case let .object(object):
            if eligible(object, for: field), let id = keys.compactMap({ scalarText(object[$0]) }).first {
                let label = ["display_label", "symbol", "ticker", "normalized_ticker", "title", "name", "strategy_key"]
                    .compactMap { scalarText(object[$0]) }.first ?? "记录 \(id)"
                let secondary = ["company_name", "status", "created_at", "requested_at"]
                    .compactMap { scalarText(object[$0]) }.first
                found.append(R5EntityOption(id: id, label: label, secondary: secondary))
            }
            for child in object.values {
                collect(child, field: field, keys: keys, into: &found, depth: depth + 1)
            }
        default: break
        }
    }

    private static func eligible(_ object: [String: JSONValue], for field: String) -> Bool {
        if object[field] != nil {
            return true
        }
        return switch field {
        case "instrument_id": object["symbol"] != nil && object["asset_id"] != nil
        case "asset_id": false
        case "job_id": object["analysis_type"] != nil
        case "run_id": object["discovery_mode"] != nil || object["strategy_key"] != nil
        case "candidate_id":
            object["normalized_ticker"] != nil || object["raw_ticker"] != nil || object["company_name"] != nil
        case "history_id": object["analysis_date"] != nil
        default: false
        }
    }

    private static func scalarText(_ value: JSONValue?) -> String? {
        guard let value else { return nil }
        switch value {
        case let .string(text): return text
        case let .number(number): return number.rounded() == number ? String(Int(number)) : String(number)
        default: return nil
        }
    }
}

// MARK: - Goal R5 semantic summaries

public struct R5SummaryMetric: Identifiable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let value: FinancialDisplayValue
    public let status: SemanticStatusLabel.Status
}

public enum R5WorkspaceSummary {
    public static func portfolio(_ payload: JSONValue) -> [R5SummaryMetric] {
        let object = payload.objectValue
        let currency = object["base_currency"]?.stringValue ?? "USD"
        return compact([
            metric("value", "总市值", object["total_market_value"], kind: .amount(currency)),
            metric("pnl", "浮动盈亏", object["total_unrealized_pnl"], kind: .amount(currency), directional: true),
            metric("return", "收益率", object["total_unrealized_pnl_percent"] ?? object["month_return"], kind: .percent, directional: true),
            metric("risk", "风险评分", object["overall_score"] ?? object["total_health_score"], kind: .score),
            metric("coverage", "数据覆盖", object["coverage"] ?? object["data_completeness"], kind: .percent),
        ])
    }

    public static func discovery(_ payload: JSONValue) -> [R5SummaryMetric] {
        let object = payload.objectValue
        return compact([
            metric("status", "运行状态", object["status"], kind: .plain),
            metric("raw", "原始候选", findNumber("raw_candidate_count", in: payload), kind: .integer),
            metric("verified", "本地验证", findNumber("verified_candidate_count", in: payload), kind: .integer),
            metric("accepted", "最终入选", findNumber("accepted_count", in: payload), kind: .integer),
            metric("spend", "本月成本", object["monthly_spend_usd"], kind: .amount("USD")),
        ])
    }

    public static func ibkr(_ payload: JSONValue) -> [R5SummaryMetric] {
        let object = payload.objectValue
        return compact([
            metric("available", "账户状态", object["available"] ?? object["configured"], kind: .availability),
            metric("positions", "持仓", object["position_count"], kind: .integer),
            metric("trades", "交易", object["trade_count"], kind: .integer),
            metric("coverage", "匹配率", object["position_match_rate"], kind: .percent),
            metric("warnings", "警告", object["warning_count"], kind: .integer),
        ])
    }

    public static func paper(_ payload: JSONValue) -> [R5SummaryMetric] {
        let object = payload.objectValue["account"]?.objectValue ?? payload.objectValue
        let currency = object["base_currency"]?.stringValue ?? object["currency"]?.stringValue ?? "USD"
        return compact([
            metric("equity", "模拟净值", object["equity"] ?? object["net_asset_value"], kind: .amount(currency)),
            metric("cash", "模拟现金", object["cash"] ?? object["cash_balance"], kind: .amount(currency)),
            metric("orders", "订单", object["order_count"], kind: .integer),
            metric("status", "运行状态", object["status"], kind: .plain),
        ])
    }

    public static func crypto(_ payload: JSONValue) -> [R5SummaryMetric] {
        let object = payload.objectValue
        return compact([
            metric("last", "最新价", object["last_price"] ?? object["price"], kind: .number),
            metric("high", "24 小时高", object["high_price_24h"], kind: .number),
            metric("low", "24 小时低", object["low_price_24h"], kind: .number),
            metric("volume", "24 小时成交额", object["quote_volume_24h"], kind: .number),
        ])
    }

    private enum MetricKind { case amount(String), percent, score, integer, number, availability, plain }

    private static func metric(
        _ id: String, _ label: String, _ value: JSONValue?, kind: MetricKind,
        directional: Bool = false
    ) -> R5SummaryMetric? {
        guard let value, value != .null else { return nil }
        let display: FinancialDisplayValue
        switch kind {
        case let .amount(currency): display = FinancialValueFormatter.amount(value.numberValue, currency: currency)
        case .percent: display = FinancialValueFormatter.percent(value.numberValue)
        case .score: display = numericDisplay(value.numberValue, fractionDigits: 0)
        case .integer: display = numericDisplay(value.numberValue, fractionDigits: 0)
        case .number: display = numericDisplay(value.numberValue, fractionDigits: 2)
        case .availability:
            let available = value.boolValue == true
            display = FinancialDisplayValue(text: available ? "可用" : "不可用", accessibilityLabel: available ? "可用" : "不可用")
        case .plain:
            display = FinancialDisplayValue(text: value.displayText, accessibilityLabel: value.displayText)
        }
        let status: SemanticStatusLabel.Status = if directional, let number = value.numberValue {
            number > 0 ? .positive : (number < 0 ? .negative : .neutral)
        } else {
            .neutral
        }
        return R5SummaryMetric(id: id, label: label, value: display, status: status)
    }

    private static func compact(_ values: [R5SummaryMetric?]) -> [R5SummaryMetric] {
        values.compactMap(\.self)
    }

    private static func numericDisplay(_ value: Double?, fractionDigits: Int) -> FinancialDisplayValue {
        guard let value, value.isFinite else { return FinancialValueFormatter.missing() }
        let text = value.formatted(.number.grouping(.automatic).precision(.fractionLength(fractionDigits)))
        return FinancialDisplayValue(text: text)
    }

    private static func findNumber(_ key: String, in value: JSONValue, depth: Int = 0) -> JSONValue? {
        guard depth < 6 else { return nil }
        if let direct = value.objectValue[key], direct.numberValue != nil {
            return direct
        }
        for child in value.objectValue.values {
            if let result = findNumber(key, in: child, depth: depth + 1) {
                return result
            }
        }
        for child in value.arrayValue {
            if let result = findNumber(key, in: child, depth: depth + 1) {
                return result
            }
        }
        return nil
    }
}

struct R5WorkspaceContentView: View {
    let descriptor: WorkspaceDescriptor
    let endpoint: WorkspaceEndpoint
    let payload: JSONValue
    let presentation: WorkspacePresentation

    var body: some View {
        PageScaffold(width: StockMonitorContentWidth.wide) {
            PageHeader(endpoint.title, eyebrow: descriptor.title, summary: descriptor.summary) {
                if let phase = presentation.jobPhase {
                    JobStateBadge(phase, detail: presentation.jobDetail)
                }
            }
        } content: {
            specializedFirstScreen
            SemanticWorkspaceSectionsView(
                presentation: presentation,
                suppressSummary: hasSpecializedSummary,
                suppressList: suppressesSemanticList
            )
        }
        .accessibilityIdentifier("workspace.r5.\(endpoint.semantic ?? "unknown")")
    }

    @ViewBuilder private var specializedFirstScreen: some View {
        let semantic = endpoint.semantic ?? ""
        if semantic.hasPrefix("portfolio") {
            if semantic.contains("analysis") {
                JobStatusTimelineView(entries: R5TimelineBuilder.job(payload))
            } else {
                R5MetricSummaryView(
                    title: semantic == "portfolio.summary" ? "组合总览" : "当前分析",
                    metrics: R5WorkspaceSummary.portfolio(payload),
                    warning: portfolioWarning
                )
                let positions = R5PortfolioPositionRow.rows(from: payload)
                if !positions.isEmpty {
                    PortfolioHoldingsTable(rows: positions, baseCurrency: payload.objectValue["base_currency"]?.stringValue ?? "USD")
                }
            }
        } else if semantic.hasPrefix("discovery") {
            DiscoveryFunnelView(metrics: R5WorkspaceSummary.discovery(payload))
        } else if semantic.hasPrefix("journal") {
            JournalReadingGuide()
            JournalTimelineView(entries: R5TimelineBuilder.journal(payload))
        } else if semantic.hasPrefix("ibkr") {
            R5MetricSummaryView(title: "账户与数据状态", metrics: R5WorkspaceSummary.ibkr(payload), warning: nil)
        } else if semantic.hasPrefix("crypto") {
            R5MetricSummaryView(title: "市场摘要", metrics: R5WorkspaceSummary.crypto(payload), warning: nil)
        } else if semantic.hasPrefix("quant") {
            QuantResearchFlowView(activeSemantic: semantic)
        } else if semantic.hasPrefix("paper") {
            PaperBoundaryView(metrics: R5WorkspaceSummary.paper(payload))
        } else if semantic.hasPrefix("settings") {
            SettingsBoundaryView()
        } else if semantic.hasPrefix("admin") || semantic.hasPrefix("execution") {
            AdministrationBoundaryView(execution: semantic.hasPrefix("execution"))
        }
    }

    private var portfolioWarning: String? {
        let object = payload.objectValue
        if object["valuation_available"]?.boolValue == false {
            let currencies = object["missing_fx"]?.arrayValue.compactMap(\.stringValue).joined(separator: "、") ?? "部分币种"
            return "\(currencies) 缺少汇率；相关持仓未参与基础币种汇总。"
        }
        return nil
    }

    private var hasSpecializedSummary: Bool {
        let semantic = endpoint.semantic ?? ""
        if semantic.hasPrefix("portfolio") {
            return !R5WorkspaceSummary.portfolio(payload).isEmpty || portfolioWarning != nil
        }
        if semantic.hasPrefix("discovery") {
            return !R5WorkspaceSummary.discovery(payload).isEmpty
        }
        if semantic.hasPrefix("ibkr") {
            return !R5WorkspaceSummary.ibkr(payload).isEmpty
        }
        if semantic.hasPrefix("crypto") {
            return !R5WorkspaceSummary.crypto(payload).isEmpty
        }
        if semantic.hasPrefix("paper") {
            return !R5WorkspaceSummary.paper(payload).isEmpty
        }
        return false
    }

    private var suppressesSemanticList: Bool {
        if endpoint.semantic?.hasPrefix("journal") == true {
            return !R5TimelineBuilder.journal(payload).isEmpty
        }
        if endpoint.semantic == "portfolio.summary" || endpoint.semantic == "portfolio.positions" {
            return !R5PortfolioPositionRow.rows(from: payload).isEmpty
        }
        return false
    }
}

public struct R5PortfolioPositionRow: Identifiable, Equatable, Sendable {
    public let id: String
    public let symbol: String
    public let currency: String
    public let quantity: FinancialDisplayValue
    public let localPrice: FinancialDisplayValue
    public let baseMarketValue: FinancialDisplayValue
    public let basePnL: FinancialDisplayValue
    public let weight: FinancialDisplayValue

    public static func rows(from payload: JSONValue) -> [R5PortfolioPositionRow] {
        let baseCurrency = payload.objectValue["base_currency"]?.stringValue ?? "USD"
        let values = payload.objectValue["positions"]?.arrayValue ?? payload.arrayValue
        return values.enumerated().map { index, value in
            let object = value.objectValue
            let symbol = object["symbol"]?.stringValue ?? object["ticker"]?.stringValue ?? "持仓 \(index + 1)"
            let currency = object["currency"]?.stringValue ?? "—"
            return R5PortfolioPositionRow(
                id: object["id"]?.displayText ?? symbol,
                symbol: symbol,
                currency: currency,
                quantity: numeric(object["total_quantity"]?.numberValue ?? object["quantity"]?.numberValue, digits: 4),
                localPrice: FinancialValueFormatter.price(object["current_price"]?.numberValue, currency: currency),
                baseMarketValue: FinancialValueFormatter.amount(object["base_currency_market_value"]?.numberValue, currency: baseCurrency),
                basePnL: FinancialValueFormatter.amount(object["base_currency_unrealized_pnl"]?.numberValue, currency: baseCurrency),
                weight: FinancialValueFormatter.percent(object["portfolio_weight"]?.numberValue)
            )
        }
    }

    private static func numeric(_ value: Double?, digits: Int) -> FinancialDisplayValue {
        guard let value else { return FinancialValueFormatter.missing() }
        return FinancialDisplayValue(text: value.formatted(.number.precision(.fractionLength(0 ... digits))))
    }
}

struct PortfolioHoldingsTable: View {
    @Environment(\.stockMonitorLayoutWidth) private var layoutWidth
    @Environment(\.interfaceDensity) private var density
    let rows: [R5PortfolioPositionRow]
    let baseCurrency: String

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            SectionHeader("持仓", explanation: "价格使用证券本币；市值、盈亏和权重使用 \(baseCurrency) 汇总，缺 FX 时明确排除。")
            if layoutWidth == .narrow {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(rows) { row in
                        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                            HStack { Text(row.symbol).font(.headline); Spacer(); Text(row.currency).stockMonitorTypography(.metadata) }
                            LabeledContent("数量", value: row.quantity.text)
                            LabeledContent("本币价格", value: row.localPrice.text)
                            LabeledContent("\(baseCurrency) 市值", value: row.baseMarketValue.text)
                            LabeledContent("组合权重", value: row.weight.text)
                        }
                        .padding(.vertical, density.rowPadding)
                        Divider()
                    }
                }
            } else {
                Table(rows) {
                    TableColumn("证券", value: \.symbol).width(min: 90, ideal: 130)
                    TableColumn("币种", value: \.currency).width(min: 55, ideal: 70)
                    TableColumn("数量") { cell($0.quantity) }.width(min: 75, ideal: 95)
                    TableColumn("本币价格") { cell($0.localPrice) }.width(min: 90, ideal: 120)
                    TableColumn("市值（\(baseCurrency)）") { cell($0.baseMarketValue) }.width(min: 100, ideal: 125)
                    TableColumn("盈亏（\(baseCurrency)）") { cell($0.basePnL) }.width(min: 100, ideal: 125)
                    TableColumn("组合权重") { cell($0.weight) }.width(min: 80, ideal: 100)
                }
                .alternatingRowBackgrounds(.enabled)
                .frame(height: min(CGFloat(rows.count) * density.rowHeight + 48, 360))
            }
        }
        .accessibilityIdentifier("portfolio.holdings-table")
    }

    private func cell(_ value: FinancialDisplayValue) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            Text(value.text).financialFigures()
            if let qualifier = value.qualifier {
                Text(qualifier).stockMonitorTypography(.microAnnotation)
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(value.accessibilityLabel)
    }
}

public enum R5TimelineBuilder {
    public static func job(_ payload: JSONValue) -> [TimelineEntry] {
        let object = payload.objectValue
        var result: [TimelineEntry] = []
        append(
            &result,
            entry: TimelineEntry(
                id: "submitted", title: "任务已提交", timestamp: "", detail: "服务端已记录参数与任务范围",
                systemImage: "tray.and.arrow.down"
            ),
            time: object["requested_at"] ?? object["created_at"]
        )
        append(
            &result,
            entry: TimelineEntry(
                id: "started", title: "开始运行", timestamp: "", detail: "使用服务端权威数据执行分析",
                systemImage: "play.circle"
            ),
            time: object["started_at"]
        )
        let status = object["status"]?.stringValue ?? "等待状态"
        let detail = object["error_message"]?.stringValue
            ?? object["warning"]?.stringValue
            ?? "结果、限制与证据保存在本任务中"
        append(
            &result,
            entry: TimelineEntry(
                id: "finished", title: statusLabel(status), timestamp: "", detail: detail,
                systemImage: status.contains("fail") ? "xmark.circle" : "checkmark.circle"
            ),
            time: object["completed_at"] ?? object["updated_at"]
        )
        return result
    }

    public static func journal(_ payload: JSONValue) -> [TimelineEntry] {
        let items = payload.objectValue["items"]?.arrayValue ?? payload.arrayValue
        return items.prefix(100).enumerated().map { index, item in
            let object = item.objectValue
            let ticker = object["ticker"]?.stringValue ?? object["symbol"]?.stringValue ?? "交易"
            let direction = directionLabel(object["direction"]?.stringValue ?? object["side"]?.stringValue)
            let quantity = object["quantity"]?.displayText ?? "—"
            let price = object["price"]?.displayText ?? "—"
            let review = object["content"]?.stringValue
                ?? object["note"]?.stringValue
                ?? object["review"]?.stringValue
                ?? object["notes"]?.stringValue
                ?? "尚未填写复盘"
            return TimelineEntry(
                id: object["id"]?.displayText ?? "journal-\(index)",
                title: "\(ticker) · \(direction) \(quantity) @ \(price)",
                timestamp: object["trade_date"]?.stringValue ?? object["created_at"]?.stringValue ?? "时间未知",
                detail: review,
                systemImage: direction == "买入" ? "arrow.down.left.circle" : "arrow.up.right.circle"
            )
        }
    }

    private static func append(_ entries: inout [TimelineEntry], entry: TimelineEntry, time: JSONValue?) {
        guard let time, time != .null else { return }
        entries.append(
            TimelineEntry(
                id: entry.id, title: entry.title, timestamp: time.displayText,
                detail: entry.detail, systemImage: entry.systemImage
            )
        )
    }

    private static func statusLabel(_ status: String) -> String {
        switch status.lowercased() {
        case "completed", "succeeded", "success": "分析完成"
        case "failed", "error": "分析失败"
        case "running": "正在运行"
        case "queued", "pending": "等待运行"
        default: status
        }
    }

    private static func directionLabel(_ direction: String?) -> String {
        switch direction?.lowercased() {
        case "buy", "long": "买入"
        case "sell", "short": "卖出"
        default: direction ?? "交易"
        }
    }
}

struct R5MetricSummaryView: View {
    let title: String
    let metrics: [R5SummaryMetric]
    let warning: String?

    var body: some View {
        if !metrics.isEmpty || warning != nil {
            VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
                SectionHeader(title)
                if !metrics.isEmpty {
                    MetricGrid(metrics.map { MetricItem(id: $0.id, label: $0.label, value: $0.value, status: $0.status) })
                }
                if let warning {
                    InlineError("覆盖缺口", message: warning)
                }
            }
            .accessibilityIdentifier("r5.primary-summary")
        }
    }
}

struct DiscoveryFunnelView: View {
    let metrics: [R5SummaryMetric]

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            SectionHeader("发现漏斗", explanation: "原始候选经过本地证券映射、数据验证与组合过滤后，才进入最终结果。")
            if metrics.isEmpty {
                SemanticStatusLabel("等待首次运行", status: .neutral)
            } else {
                MetricGrid(metrics.map { MetricItem(id: $0.id, label: $0.label, value: $0.value, status: $0.status) })
            }
            HStack(spacing: StockMonitorSpacing.small) {
                funnelStep("原始候选", icon: "sparkles")
                Image(systemName: "chevron.right").foregroundStyle(.secondary)
                funnelStep("本地验证", icon: "checkmark.shield")
                Image(systemName: "chevron.right").foregroundStyle(.secondary)
                funnelStep("组合过滤", icon: "line.3.horizontal.decrease.circle")
                Image(systemName: "chevron.right").foregroundStyle(.secondary)
                funnelStep("最终分组", icon: "square.grid.2x2")
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("发现流程：原始候选，本地验证，组合过滤，最终分组")
        }
        .accessibilityIdentifier("discovery.funnel")
    }

    private func funnelStep(_ label: String, icon: String) -> some View {
        Label(label, systemImage: icon)
            .stockMonitorTypography(.metadata)
            .padding(.horizontal, StockMonitorSpacing.small)
            .padding(.vertical, StockMonitorSpacing.xSmall)
            .stockMonitorSurface(.grouped)
    }
}

struct JournalReadingGuide: View {
    var body: some View {
        HStack(spacing: StockMonitorSpacing.large) {
            Label("交易事实", systemImage: "checklist")
            Image(systemName: "chevron.right").foregroundStyle(.secondary)
            Label("复盘正文", systemImage: "text.alignleft")
            Image(systemName: "chevron.right").foregroundStyle(.secondary)
            Label("AI 总结", systemImage: "sparkles")
        }
        .stockMonitorTypography(.metadata)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("日志结构：交易事实，复盘正文，AI 总结")
        .accessibilityIdentifier("journal.layers")
    }
}

struct JournalTimelineView: View {
    let entries: [TimelineEntry]

    var body: some View {
        if !entries.isEmpty {
            VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
                SectionHeader("交易与复盘", explanation: "交易事实保持不可混淆；复盘正文可连续阅读，AI 总结只按明确操作生成。")
                TimelineList(entries)
            }
            .accessibilityIdentifier("journal.timeline")
        }
    }
}

struct JobStatusTimelineView: View {
    let entries: [TimelineEntry]

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            SectionHeader("任务进度", explanation: "参数、状态、结果与限制按一次服务端任务归档。")
            if entries.isEmpty {
                SemanticStatusLabel("等待任务记录", status: .neutral)
            } else {
                TimelineList(entries)
            }
        }
        .accessibilityIdentifier("portfolio.job-timeline")
    }
}

struct QuantResearchFlowView: View {
    let activeSemantic: String

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            SectionHeader("研究流程", explanation: "定义与特征产生信号；回测证据通过后，部署仍只连接内部 PAPER。")
            HStack(spacing: StockMonitorSpacing.small) {
                step("定义", matches: "definition")
                step("特征", matches: "feature")
                step("信号", matches: "signal")
                step("回测", matches: "backtest")
                step("PAPER 部署", matches: "deployment")
            }
        }
        .accessibilityIdentifier("quant.research-flow")
    }

    private func step(_ title: String, matches token: String) -> some View {
        Label(title, systemImage: activeSemantic.contains(token) ? "circle.inset.filled" : "circle")
            .foregroundStyle(activeSemantic.contains(token) ? AnyShapeStyle(.tint) : AnyShapeStyle(.secondary))
            .stockMonitorTypography(.metadata)
            .frame(maxWidth: .infinity)
    }
}

struct PaperBoundaryView: View {
    let metrics: [R5SummaryMetric]

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            Label("内部 PAPER · 不连接真实交易", systemImage: "checkmark.shield")
                .font(.headline)
                .foregroundStyle(.secondary)
                .accessibilityIdentifier("paper.boundary")
            if !metrics.isEmpty {
                MetricGrid(metrics.map { MetricItem(id: $0.id, label: $0.label, value: $0.value, status: $0.status) })
            }
        }
    }
}

struct SettingsBoundaryView: View {
    var body: some View {
        Label("密钥与供应商凭据只保存在服务端；此页面只显示配置状态。", systemImage: "lock.shield")
            .stockMonitorTypography(.metadata)
            .accessibilityIdentifier("settings.server-boundary")
    }
}

struct AdministrationBoundaryView: View {
    let execution: Bool

    var body: some View {
        Label(
            execution ? "执行控制是独立的高风险诊断区；日常研究不会展示这些字段。" : "管理员状态与普通工作区隔离。",
            systemImage: execution ? "exclamationmark.shield" : "person.badge.key"
        )
        .stockMonitorTypography(.metadata)
        .accessibilityIdentifier("administration.boundary")
    }
}
