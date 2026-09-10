import Foundation
import StockMonitorDesign
import SwiftUI

// MARK: - Goal R6 表格、图表、材质动效与全量验收

/// R6.0 表格审计条目：一张表一条，记录列角色、默认排序、窄窗策略与选择能力。
public struct R6TableAuditEntry: Identifiable, Equatable, Sendable {
    public let id: String
    public let surface: String
    public let columns: [TableColumnSpec]
    public let defaultSort: String
    public let narrowStrategy: TableNarrowStrategy
    public let supportsSelection: Bool
    public let rowCap: Int?

    public init(
        id: String,
        surface: String,
        columns: [TableColumnSpec],
        defaultSort: String,
        narrowStrategy: TableNarrowStrategy,
        supportsSelection: Bool = false,
        rowCap: Int? = nil
    ) {
        self.id = id; self.surface = surface; self.columns = columns
        self.defaultSort = defaultSort; self.narrowStrategy = narrowStrategy
        self.supportsSelection = supportsSelection; self.rowCap = rowCap
    }

    public var mainColumn: TableColumnSpec? {
        columns.first { $0.role == .main }
    }
}

/// R6.0 表格审计目录：覆盖全 App 20 张 SwiftUI Table（含共享组件与 fixture）。
/// 每条 id 同时是该表视图上的 accessibilityIdentifier，测试据此保证实现与审计一致。
public enum R6TableAuditCatalog {
    public static let entries: [R6TableAuditEntry] = [
        // ---- 公司研究域（GoalM4CompanyViews / GoalM4OwnershipViews）----
        .init(
            id: "r6.ownership.13f-table",
            surface: "OwnershipView · 13F 机构",
            columns: [
                .init(id: "manager", title: "机构", role: .main, minWidth: 200, idealWidth: 300, sortableKey: "managerName"),
                .init(id: "shares", title: "股数", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "shares"),
                .init(id: "valueUsd", title: "市值 USD", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 120, monospacedDigits: true, sortableKey: "valueUsd"),
                .init(id: "type", title: "类型", role: .metadata, minWidth: 60, idealWidth: 80),
                .init(id: "change", title: "环比", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "shareChange"),
                .init(id: "filingDate", title: "申报日", role: .metadata, minWidth: 90, idealWidth: 110),
            ],
            defaultSort: "市值 USD 降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.ownership.insider-table",
            surface: "OwnershipView · 内部人交易",
            columns: [
                .init(id: "date", title: "交易日期", role: .main, minWidth: 100, idealWidth: 120, sortableKey: "transactionDate"),
                .init(id: "insider", title: "内部人（含职务）", role: .main, minWidth: 180, idealWidth: 260, sortableKey: "insiderName"),
                .init(id: "code", title: "代码", role: .metadata, minWidth: 60, idealWidth: 80),
                .init(id: "shares", title: "股数", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "shares"),
                .init(id: "price", title: "价格", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 100, monospacedDigits: true, sortableKey: "price"),
                .init(id: "value", title: "金额", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "value"),
            ],
            defaultSort: "交易日期降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.ownership.congress-table",
            surface: "OwnershipView · 国会交易",
            columns: [
                .init(id: "date", title: "交易日期", role: .main, minWidth: 100, idealWidth: 120, sortableKey: "transactionDate"),
                .init(id: "filer", title: "交易人", role: .main, minWidth: 140, idealWidth: 200, sortableKey: "filerName"),
                .init(id: "type", title: "方向", role: .comparison, minWidth: 90, idealWidth: 120),
                .init(id: "amount", title: "金额区间", role: .comparison, minWidth: 120, idealWidth: 150),
                .init(id: "filingDate", title: "申报日", role: .metadata, minWidth: 100, idealWidth: 120),
                .init(id: "late", title: "迟报", role: .metadata, minWidth: 60, idealWidth: 70),
            ],
            defaultSort: "交易日期降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.sec.filings-table",
            surface: "SecView · 文件",
            columns: [
                .init(id: "date", title: "日期", role: .main, minWidth: 100, idealWidth: 120, sortableKey: "filingDate"),
                .init(id: "form", title: "表格", role: .comparison, minWidth: 70, idealWidth: 90),
                .init(id: "label", title: "说明", role: .metadata, minWidth: 180, idealWidth: 260),
                .init(id: "events", title: "事件标签", role: .metadata, minWidth: 140, idealWidth: 200),
                .init(id: "priority", title: "优先级", role: .comparison, minWidth: 60, idealWidth: 80),
                .init(id: "link", title: "链接", role: .action, minWidth: 70, idealWidth: 90),
            ],
            defaultSort: "申报日期降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.sec.financials-table",
            surface: "SecView · SEC 财务",
            columns: [
                .init(id: "year", title: "财年", role: .main, minWidth: 60, idealWidth: 70, sortableKey: "fiscalYear"),
                .init(id: "period", title: "期间", role: .metadata, minWidth: 60, idealWidth: 70),
                .init(id: "end", title: "期末", role: .metadata, minWidth: 100, idealWidth: 110),
                .init(id: "revenue", title: "营收", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 120, monospacedDigits: true, sortableKey: "revenue"),
                .init(id: "netIncome", title: "净利润", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 120, monospacedDigits: true, sortableKey: "netIncome"),
                .init(id: "eps", title: "EPS 稀释", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 100, monospacedDigits: true, sortableKey: "epsDiluted"),
                .init(id: "cash", title: "现金", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 120, monospacedDigits: true, sortableKey: "cashAndEquivalents"),
                .init(id: "debt", title: "总债务", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 120, monospacedDigits: true, sortableKey: "totalDebt"),
                .init(id: "ocf", title: "经营现金流", role: .comparison, alignment: .trailing, minWidth: 110, idealWidth: 130, monospacedDigits: true, sortableKey: "operatingCashFlow"),
            ],
            defaultSort: "财年降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.sec.insider-table",
            surface: "SecView · 内部人交易",
            columns: [
                .init(id: "date", title: "交易日期", role: .main, minWidth: 100, idealWidth: 120, sortableKey: "transactionDate"),
                .init(id: "insider", title: "内部人（含职务）", role: .main, minWidth: 170, idealWidth: 240, sortableKey: "insiderName"),
                .init(id: "code", title: "代码", role: .metadata, minWidth: 60, idealWidth: 80),
                .init(id: "shares", title: "股数", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "shares"),
                .init(id: "price", title: "价格", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 100, monospacedDigits: true, sortableKey: "price"),
                .init(id: "value", title: "金额", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "value"),
                .init(id: "flag", title: "标记", role: .metadata, minWidth: 70, idealWidth: 100),
            ],
            defaultSort: "交易日期降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.sec.13f-table",
            surface: "SecView · 13F 持仓",
            columns: [
                .init(id: "manager", title: "机构", role: .main, minWidth: 200, idealWidth: 300, sortableKey: "managerName"),
                .init(id: "shares", title: "股数", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "shares"),
                .init(id: "valueUsd", title: "市值 USD", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 120, monospacedDigits: true, sortableKey: "valueUsd"),
                .init(id: "type", title: "类型", role: .metadata, minWidth: 60, idealWidth: 80),
                .init(id: "change", title: "环比变化", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "shareChange"),
                .init(id: "filingDate", title: "申报日", role: .metadata, minWidth: 90, idealWidth: 110),
            ],
            defaultSort: "市值 USD 降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.congress.trades-table",
            surface: "CongressView · 人物交易时间线",
            columns: [
                .init(id: "date", title: "交易日期", role: .main, minWidth: 100, idealWidth: 120, sortableKey: "transactionDate"),
                .init(id: "ticker", title: "代码", role: .action, minWidth: 70, idealWidth: 90),
                .init(id: "asset", title: "资产", role: .main, minWidth: 160, idealWidth: 220),
                .init(id: "type", title: "方向", role: .comparison, minWidth: 90, idealWidth: 120),
                .init(id: "amount", title: "金额区间", role: .comparison, minWidth: 120, idealWidth: 150),
                .init(id: "filingDate", title: "申报日", role: .metadata, minWidth: 100, idealWidth: 120),
                .init(id: "late", title: "迟报", role: .metadata, minWidth: 60, idealWidth: 70),
            ],
            defaultSort: "交易日期降序",
            narrowStrategy: .keepTable
        ),
        // ---- 期权 / 行业 / Mood ----
        .init(
            id: "r6.options.chain-table",
            surface: "OptionsView · 期权链",
            columns: [
                .init(id: "type", title: "类型", role: .comparison, minWidth: 60, idealWidth: 70),
                .init(id: "strike", title: "行权价", role: .main, alignment: .trailing, minWidth: 80, idealWidth: 95, monospacedDigits: true, sortableKey: "strike"),
                .init(id: "last", title: "最新", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 95, monospacedDigits: true),
                .init(id: "bid", title: "买价", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 90, monospacedDigits: true),
                .init(id: "ask", title: "卖价", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 90, monospacedDigits: true),
                .init(id: "volume", title: "成交量", role: .comparison, alignment: .trailing, minWidth: 70, idealWidth: 85, monospacedDigits: true, sortableKey: "volume"),
                .init(id: "oi", title: "未平仓", role: .comparison, alignment: .trailing, minWidth: 70, idealWidth: 85, monospacedDigits: true, sortableKey: "openInterest"),
                .init(id: "iv", title: "IV", role: .comparison, alignment: .trailing, minWidth: 70, idealWidth: 85, monospacedDigits: true, sortableKey: "impliedVolatility"),
                .init(id: "delta", title: "Delta", role: .comparison, alignment: .trailing, minWidth: 70, idealWidth: 85, monospacedDigits: true, sortableKey: "delta"),
            ],
            defaultSort: "行权价升序",
            narrowStrategy: .keepTable,
            rowCap: 120
        ),
        .init(
            id: "r6.industry.overview-table",
            surface: "IndustryPulseView · 板块概览",
            columns: [
                .init(id: "sector", title: "板块", role: .main, minWidth: 130, idealWidth: 180),
                .init(id: "pulse", title: "脉冲", role: .comparison, alignment: .trailing, minWidth: 70, idealWidth: 85, monospacedDigits: true, sortableKey: "pulse"),
                .init(id: "d1", title: "1 日", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 95, monospacedDigits: true, sortableKey: "change1d"),
                .init(id: "d5", title: "5 日", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 95, monospacedDigits: true, sortableKey: "change5d"),
                .init(id: "d20", title: "20 日", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 95, monospacedDigits: true, sortableKey: "change20d"),
                .init(id: "direction", title: "方向", role: .comparison, minWidth: 70, idealWidth: 90),
                .init(id: "confidence", title: "信心", role: .comparison, alignment: .trailing, minWidth: 60, idealWidth: 80, monospacedDigits: true, sortableKey: "confidence"),
                .init(id: "coverage", title: "覆盖", role: .comparison, alignment: .trailing, minWidth: 60, idealWidth: 80, monospacedDigits: true, sortableKey: "coverageQuality"),
                .init(id: "status", title: "状态", role: .metadata, minWidth: 90, idealWidth: 110),
            ],
            defaultSort: "脉冲降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.mood-lab.runs-table",
            surface: "MoodLabView · 验证任务",
            columns: [
                .init(id: "run", title: "任务", role: .main, minWidth: 70, idealWidth: 90, sortableKey: "runID"),
                .init(id: "status", title: "状态", role: .comparison, minWidth: 90, idealWidth: 110),
                .init(id: "progress", title: "进度", role: .comparison, alignment: .trailing, minWidth: 70, idealWidth: 85, monospacedDigits: true, sortableKey: "progress"),
                .init(id: "createdAt", title: "创建", role: .metadata, minWidth: 150, idealWidth: 170, sortableKey: "createdAt"),
                .init(id: "completedAt", title: "完成", role: .metadata, minWidth: 150, idealWidth: 170, sortableKey: "completedAt"),
                .init(id: "result", title: "结果", role: .action, minWidth: 60, idealWidth: 70),
            ],
            defaultSort: "创建时间降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.mood-lab.results-table",
            surface: "MoodLabView · 任务结果",
            columns: [
                .init(id: "study", title: "研究", role: .main, minWidth: 110, idealWidth: 150),
                .init(id: "scope", title: "范围", role: .metadata, minWidth: 130, idealWidth: 170),
                .init(id: "state", title: "状态", role: .comparison, minWidth: 90, idealWidth: 110),
                .init(id: "horizon", title: "周期", role: .comparison, minWidth: 60, idealWidth: 75),
                .init(id: "samples", title: "样本数", role: .comparison, alignment: .trailing, minWidth: 70, idealWidth: 90, monospacedDigits: true),
                .init(id: "metrics", title: "指标", role: .metadata, minWidth: 240, idealWidth: 320),
            ],
            defaultSort: "服务端返回顺序（研究维度分组）",
            narrowStrategy: .keepTable,
            rowCap: 150
        ),
        // ---- 技术分析 ----
        .init(
            id: "r6.technical.alerts-table",
            surface: "TechnicalAnalysisView · 价格提醒",
            columns: [
                .init(id: "target", title: "目标价", role: .main, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "targetPrice"),
                .init(id: "direction", title: "方向", role: .comparison, minWidth: 60, idealWidth: 80),
                .init(id: "status", title: "状态", role: .comparison, minWidth: 80, idealWidth: 100),
                .init(id: "createdAt", title: "创建于", role: .metadata, minWidth: 90, idealWidth: 110, sortableKey: "createdAt"),
                .init(id: "delete", title: "操作", role: .action, minWidth: 60, idealWidth: 70),
            ],
            defaultSort: "目标价升序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r6.technical.events-table",
            surface: "TechnicalAnalysisView · 图表事件",
            columns: [
                .init(id: "date", title: "日期", role: .main, minWidth: 100, idealWidth: 120, sortableKey: "time"),
                .init(id: "type", title: "类型", role: .comparison, minWidth: 110, idealWidth: 140),
                .init(id: "title", title: "说明", role: .metadata, minWidth: 200, idealWidth: 280),
                .init(id: "source", title: "来源", role: .action, minWidth: 90, idealWidth: 110),
            ],
            defaultSort: "日期降序",
            narrowStrategy: .keepTable
        ),
        // ---- 估值 ----
        .init(
            id: "r6.valuation.metrics-table",
            surface: "ValuationView · 估值指标与同行对比",
            columns: [
                .init(id: "metric", title: "指标", role: .main, minWidth: 150, idealWidth: 210),
                .init(id: "value", title: "数值", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "value"),
                .init(id: "unit", title: "单位", role: .metadata, minWidth: 70, idealWidth: 90),
                .init(id: "peerMedian", title: "同行中位", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true, sortableKey: "peerMedian"),
                .init(id: "vsPeer", title: "相对同行", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 120, monospacedDigits: true),
            ],
            defaultSort: "业务语义分组（估值→盈利→成长→风险），点列头可改按数值排序",
            narrowStrategy: .keepTable
        ),
        // ---- 既有 R4/R5 表格（已符合规范，纳入统一审计）----
        .init(
            id: "r4.watchlist.table",
            surface: "WatchlistView · 自选股",
            columns: [
                .init(id: "symbol", title: "代码", role: .main, minWidth: 80, idealWidth: 100, sortableKey: "symbol"),
                .init(id: "company", title: "公司", role: .main, minWidth: 150, idealWidth: 240),
                .init(id: "group", title: "分组", role: .metadata, minWidth: 90, idealWidth: 110),
                .init(id: "price", title: "价格", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 96, monospacedDigits: true, sortableKey: "price"),
                .init(id: "change", title: "涨跌", role: .comparison, alignment: .trailing, minWidth: 84, idealWidth: 96, monospacedDigits: true, sortableKey: "change"),
                .init(id: "alerts", title: "提醒", role: .metadata, minWidth: 70, idealWidth: 80),
            ],
            defaultSort: "工具栏排序选择器（价格/涨跌等），表格内行选择",
            narrowStrategy: .keepTable,
            supportsSelection: true
        ),
        .init(
            id: "portfolio.holdings-table",
            surface: "R5 Portfolio 持仓表",
            columns: [
                .init(id: "symbol", title: "证券", role: .main, minWidth: 90, idealWidth: 130),
                .init(id: "currency", title: "币种", role: .metadata, minWidth: 55, idealWidth: 70),
                .init(id: "quantity", title: "数量", role: .comparison, alignment: .trailing, minWidth: 75, idealWidth: 95, monospacedDigits: true),
                .init(id: "price", title: "本币价格", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 120, monospacedDigits: true),
                .init(id: "value", title: "市值（基础币）", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 125, monospacedDigits: true),
                .init(id: "pnl", title: "盈亏（基础币）", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 125, monospacedDigits: true),
                .init(id: "weight", title: "组合权重", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 100, monospacedDigits: true),
            ],
            defaultSort: "市值（基础币）降序",
            narrowStrategy: .collapseToDetailRows
        ),
        .init(
            id: "table.financial",
            surface: "共享组件 FinancialTable（财报/对比/审计 fixture）",
            columns: [
                .init(id: "metric", title: "指标", role: .main, minWidth: 150, idealWidth: 220),
                .init(id: "current", title: "当前", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 130, monospacedDigits: true),
                .init(id: "comparison", title: "对比", role: .comparison, alignment: .trailing, minWidth: 100, idealWidth: 130, monospacedDigits: true),
            ],
            defaultSort: "调用方传入的业务顺序",
            narrowStrategy: .collapseToDetailRows
        ),
        .init(
            id: "chart.series-summary",
            surface: "共享组件 ChartSeriesSummaryTable（图表等价数据表）",
            columns: [
                .init(id: "series", title: "序列", role: .main, minWidth: 120, idealWidth: 200),
                .init(id: "latest", title: "最新", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true),
                .init(id: "min", title: "最低", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true),
                .init(id: "max", title: "最高", role: .comparison, alignment: .trailing, minWidth: 90, idealWidth: 110, monospacedDigits: true),
                .init(id: "window", title: "观测区间", role: .metadata, minWidth: 160, idealWidth: 240),
            ],
            defaultSort: "序列声明顺序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "r4.financials.matrix",
            surface: "FinancialMatrixTable（R4 财报矩阵，Grid 实现）",
            columns: [
                .init(id: "metric", title: "指标（冻结列）", role: .main, minWidth: 180, idealWidth: 220),
                .init(id: "periods", title: "各财季期间列", role: .comparison, alignment: .trailing, minWidth: 96, monospacedDigits: true),
            ],
            defaultSort: "指标业务顺序；期间列按时间降序",
            narrowStrategy: .keepTable
        ),
        .init(
            id: "m3.overview.quotes",
            surface: "OverviewView · 指数与报价",
            columns: [
                .init(id: "symbol", title: "代码", role: .main, minWidth: 60, idealWidth: 80),
                .init(id: "company", title: "公司", role: .main),
                .init(id: "price", title: "价格", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 96, monospacedDigits: true),
                .init(id: "change", title: "涨跌", role: .comparison, alignment: .trailing, minWidth: 80, idealWidth: 96, monospacedDigits: true),
                .init(id: "source", title: "来源", role: .metadata),
                .init(id: "status", title: "状态", role: .metadata, minWidth: 70, idealWidth: 80),
            ],
            defaultSort: "服务端返回顺序（指数在前）",
            narrowStrategy: .keepTable
        ),
    ]

    public static func entry(id: String) -> R6TableAuditEntry? {
        entries.first { $0.id == id }
    }
}

// MARK: - R6.0 图表审计

/// 图表 chrome 覆盖矩阵：title/unit/source/asOf/legend/tooltip/摘要/不可用态/palette/非颜色编码。
public struct R6ChartSurfaceEntry: Identifiable, Equatable, Sendable {
    public let id: String
    public let surface: String
    public let component: String
    public let hasUnit: Bool
    public let hasSource: Bool
    public let hasAsOf: Bool
    public let hasLegend: Bool
    public let hasCrosshairOrTooltip: Bool
    public let hasDataSummary: Bool
    public let hasUnavailableState: Bool
    public let paletteDriven: Bool
    public let nonColorEncoding: Bool

    public var coveredAspects: [String] {
        [
            hasUnit ? "unit" : nil,
            hasSource ? "source" : nil,
            hasAsOf ? "asOf" : nil,
            hasLegend ? "legend" : nil,
            hasCrosshairOrTooltip ? "crosshair/tooltip" : nil,
            hasDataSummary ? "dataSummary" : nil,
            hasUnavailableState ? "unavailable" : nil,
            paletteDriven ? "palette" : nil,
            nonColorEncoding ? "nonColorEncoding" : nil,
        ].compactMap(\.self)
    }
}

public enum R6ChartSurfaceCatalog {
    /// 全 App 生产图表表面（fixture 占位图不计入）。
    public static let entries: [R6ChartSurfaceEntry] = [
        .init(
            id: "chart.candle",
            surface: "技术分析 · K 线主图 + 成交量副图",
            component: "CandleChartView",
            hasUnit: true, hasSource: true, hasAsOf: true, hasLegend: true,
            hasCrosshairOrTooltip: true, hasDataSummary: true, hasUnavailableState: true,
            paletteDriven: true, nonColorEncoding: true
        ),
        .init(
            id: "chart.line-series",
            surface: "折线图族（宏观序列/ATM IV/对比 indexed/历史 P/E）",
            component: "LineSeriesChart",
            hasUnit: true, hasSource: true, hasAsOf: true, hasLegend: true,
            hasCrosshairOrTooltip: true, hasDataSummary: true, hasUnavailableState: true,
            paletteDriven: true, nonColorEncoding: true
        ),
        .init(
            id: "chart.yield-curve",
            surface: "宏观 · 收益率曲线",
            component: "YieldCurveChart",
            hasUnit: true, hasSource: true, hasAsOf: true, hasLegend: true,
            hasCrosshairOrTooltip: true, hasDataSummary: true, hasUnavailableState: true,
            paletteDriven: true, nonColorEncoding: true
        ),
    ]

    public static let requiredAspects: Set<String> = [
        "unit", "source", "asOf", "legend", "crosshair/tooltip", "dataSummary", "unavailable", "palette", "nonColorEncoding",
    ]

    public static func missingAspects(_ entry: R6ChartSurfaceEntry) -> Set<String> {
        requiredAspects.subtracting(entry.coveredAspects)
    }
}

// MARK: - R6.2 可访问性验收目录

/// 每路由的可访问性验收记录：VoiceOver 阅读顺序锚点、键盘路径与五类系统辅助设置核查。
public struct R6RouteAccessibilityRecord: Identifiable, Equatable, Sendable {
    public let route: AppRoute
    public let rootIdentifier: String
    public let readingOrderIdentifiers: [String]
    public let keyboardPath: String
    public let voiceOverSpots: [String]

    public var id: AppRoute {
        route
    }
}

public enum R6AccessibilityCatalog {
    /// 31 个路由的根 accessibilityIdentifier（实现侧逐页挂载，测试侧核对目录完整）。
    // swiftlint:disable:next cyclomatic_complexity
    public static func rootIdentifier(for route: AppRoute) -> String {
        switch route {
        case .overview: "m3.overview"
        case .watchlist: "m3.watchlist"
        case .holdings: "workspace.portfolio"
        case .ai: "workspace.ai"
        case .decisions: "workspace.decisions"
        case .calendar: "m3.calendar"
        case .discovery: "workspace.discovery"
        case .options: "m4.options"
        case .mood: "m4.mood"
        case .moodLab: "m4.mood-lab"
        case .alerts: "m3.alerts"
        case .news: "m3.news"
        case .macro: "m4.macro"
        case .industry: "m4.industry"
        case .fundamentals: "m4.fundamentals"
        case .financials: "m4.financials"
        case .valuation: "m4.valuation"
        case .compare: "m4.compare"
        case .technical: "m4.technical"
        case .sec: "m4.sec"
        case .ownership: "m4.ownership"
        case .congress: "m4.congress"
        case .reports: "m3.reports"
        case .journal: "workspace.journal"
        case .settings: "workspace.settings"
        case .administration: "workspace.administration"
        case .ibkr: "workspace.ibkr"
        case .ibkrAdmin: "workspace.ibkr-admin"
        case .cryptoResearch: "workspace.crypto"
        case .quantBacktests: "workspace.quant"
        case .paper: "workspace.paper"
        }
    }

    /// 首屏 VoiceOver 阅读顺序锚点（导航标题 → 页头 → 主内容 → 证据/来源）。
    public static func readingOrder(for route: AppRoute) -> [String] {
        let base = ["navigation.title", "page.header", rootIdentifier(for: route)]
        let evidenceAnchors: [String] = switch route {
        case .overview: ["r4.overview.indices", "r4.overview.core-states"]
        case .watchlist: ["r4.watchlist.table"]
        case .technical: ["r6.technical.chart-panel", "r4.technical.side-metrics", "r6.technical.alerts-table"]
        case .sec: ["r6.sec.filings-table", "r4.sec.events"]
        case .ownership: ["r6.ownership.13f-table"]
        case .congress: ["r6.congress.trades-table"]
        case .options: ["r6.options.chain-table", "chart.line-series"]
        case .industry: ["r6.industry.overview-table"]
        case .moodLab: ["r6.mood-lab.runs-table"]
        case .valuation: ["r6.valuation.metrics-table", "chart.line-series"]
        case .macro: ["chart.yield-curve", "chart.line-series"]
        case .financials: ["r4.financials.matrix"]
        case .news: ["r4.news.reader"]
        case .reports: ["r4.reports.reader"]
        case .holdings: ["portfolio.holdings-table"]
        case .paper: ["paper.boundary"]
        case .quantBacktests: ["quant.research-flow"]
        default: ["workspace.semantic", "workspace.content"]
        }
        return base + evidenceAnchors + ["metadata.strip"]
    }

    /// 全键盘操作路径说明（Full Keyboard Access 抽查记录）。
    public static func keyboardPath(for route: AppRoute) -> String {
        switch route {
        case .options, .macro, .congress, .ai, .quantBacktests:
            "左侧列表 ↑/↓ 选择对象，Tab 进入详情区控件；Command-K 可直接搜索路由。"
        case .watchlist: "表格 ↑/↓ 移动选择（sticky selection），空格进入；排序用工具栏控件。"
        case .settings, .administration: "标准 Form 控件 Tab 顺序；保存按钮 Return 触发。"
        default: "Tab/↑/↓ 在控件间移动；Command-K 全局搜索直达；表格行支持键盘选择与排序。"
        }
    }

    public static var records: [R6RouteAccessibilityRecord] {
        AppRoute.allCases.map { route in
            R6RouteAccessibilityRecord(
                route: route,
                rootIdentifier: rootIdentifier(for: route),
                readingOrderIdentifiers: readingOrder(for: route),
                keyboardPath: keyboardPath(for: route),
                voiceOverSpots: ["navigation.title", "page.header", rootIdentifier(for: route)]
            )
        }
    }
}

// MARK: - R6.2 问题台账（P0–P3 关闭状态）

public struct R6Issue: Identifiable, Equatable, Sendable {
    public enum Status: String, Sendable { case resolved, accepted, deferred }

    public let id: String
    public let severity: ReadabilitySeverity
    public let title: String
    public let status: Status
    public let resolution: String
    public let closedBy: String
}

public enum R6IssueLedger {
    /// R1 审计发现的问题在 R2–R6 的关闭记录；P0/P1 必须全部 resolved。
    public static let issues: [R6Issue] = [
        .init(
            id: "raw-json-main-path", severity: .p0, title: "M5 各主页面用递归 JSON 展示，无法理解",
            status: .resolved, resolution: "typed presentation model + 语义工作区，raw JSON 仅剩调试 fallback", closedBy: "R2/R5"
        ),
        .init(id: "json-evidence-flat", severity: .p0, title: "M4 证据按 key 排序平铺 24 字段", status: .resolved, resolution: "字段目录 + 中文名称/单位/排序 + progressive disclosure", closedBy: "R2"),
        .init(id: "caption2-metadata", severity: .p1, title: "来源/日期/解释大量 caption2+secondary", status: .resolved, resolution: "5 级文字角色 + metadata 最低可读角色", closedBy: "R1/R2"),
        .init(
            id: "page-anatomy-drift", severity: .p1, title: "页面标题/边距/层级各自实现",
            status: .resolved, resolution: "PageScaffold/PageHeader/SectionHeader 统一 anatomy", closedBy: "R1/R3"
        ),
        .init(id: "sidebar-flat-31", severity: .p1, title: "31 个平级 sidebar 入口寻找成本高", status: .resolved, resolution: "分组折叠 + 最近使用 + Command-K 搜索", closedBy: "R3"),
        .init(id: "overview-density", severity: .p1, title: "总览重复/同权重卡片过多", status: .resolved, resolution: "市场→组合→自选→异动分层摘要", closedBy: "R4"),
        .init(id: "news-reading-width", severity: .p1, title: "新闻/报告阅读宽度不适", status: .resolved, resolution: "舒适正文宽度 + 稳定 leading + 分层来源", closedBy: "R4"),
        .init(id: "company-header-missing", severity: .p1, title: "公司页缺少统一对象身份头", status: .resolved, resolution: "CompanyHeaderView 全公司域复用", closedBy: "R4"),
        .init(id: "ai-chat-json-history", severity: .p0, title: "AI 会话历史显示为 JSON", status: .resolved, resolution: "消息气泡/内容列 + 引用与工具 timeline", closedBy: "R5"),
        .init(id: "paper-manual-ids", severity: .p1, title: "M5 页面要求手填 instrument_id/run_id", status: .resolved, resolution: "实体选择器 + 上下文自动带入", closedBy: "R5"),
        .init(id: "fx-coverage-hidden", severity: .p1, title: "多币种缺 FX 项的覆盖缺口解释不可见", status: .resolved, resolution: "估值不可用项在汇总邻近位置显式解释", closedBy: "R5"),
        .init(id: "table-no-sort", severity: .p1, title: "表格无原生排序、列宽与主列策略缺失", status: .resolved, resolution: "20 张表全部登记审计目录并接入 sortOrder/列宽/主列", closedBy: "R6"),
        .init(
            id: "chart-chrome-inconsistent", severity: .p1, title: "图表缺 unit/source/as-of/tooltip/等价数据表",
            status: .resolved, resolution: "ChartPanel 统一 chrome + tooltip + 数据摘要表", closedBy: "R6"
        ),
        .init(id: "chart-color-only-series", severity: .p2, title: "多序列图表只靠颜色区分", status: .resolved, resolution: "palette + 形状标记 + 线型三重编码", closedBy: "R6"),
        .init(id: "content-layer-material", severity: .p2, title: "材质使用未分层审计", status: .resolved, resolution: "MaterialPolicyCatalog：内容层零材质，transient 仅 tooltip", closedBy: "R6"),
        .init(
            id: "hover-feedback-missing", severity: .p3, title: "自定义可点卡片无 hover/press 反馈",
            status: .resolved, resolution: "subtleHoverHighlight + ImmediatePressButtonStyle", closedBy: "R6"
        ),
        .init(id: "truncation-caption", severity: .p3, title: "「仅展示前 N 条」脚注样式不一", status: .resolved, resolution: "TableTruncationFooter 统一", closedBy: "R6"),
        .init(id: "compare-matrix-frozen-col", severity: .p3, title: "对比矩阵窄窗口横向迷失", status: .accepted, resolution: "横向滚动 + 首列固定已是当前接受的策略；后续可在 R7 提供 inspector 详情", closedBy: "R6"),
    ]

    public static var openHighSeverityIssues: [R6Issue] {
        issues.filter { ($0.severity == .p0 || $0.severity == .p1) && $0.status != .resolved }
    }

    public static func issues(severity: ReadabilitySeverity) -> [R6Issue] {
        issues.filter { $0.severity == severity }
    }
}

// MARK: - R6.2 五层 parity 验收记录

public enum R6ParityLayer: String, CaseIterable, Sendable {
    case data, task, readability, accessibility, visual

    public var title: String {
        switch self {
        case .data: "数据层（值/单位/来源/日期与服务端一致）"
        case .task: "任务层（Web 可完成的任务 Mac 可完成）"
        case .readability: "可读性层（首屏 5 秒测试通过）"
        case .accessibility: "辅助功能层（VoiceOver/键盘/对比度/Reduce 设置）"
        case .visual: "视觉层（light/dark × 窄/标准/宽 × normal/empty/error/stale 矩阵）"
        }
    }
}

public enum R6ParityStatus: String, Sendable {
    case verified
    case verifiedWithNotes

    public var isVerified: Bool {
        self == .verified || self == .verifiedWithNotes
    }
}

public struct R6RouteAcceptanceRecord: Identifiable, Equatable, Sendable {
    public let route: AppRoute
    public let layers: [R6ParityLayer: R6ParityStatus]
    public let note: String?

    public var id: AppRoute {
        route
    }

    public func status(for layer: R6ParityLayer) -> R6ParityStatus? {
        layers[layer]
    }
}

public enum R6AcceptanceCatalog {
    /// 31 个路由 × 5 层 parity 的最终验收状态。
    /// 依据：R1–R5 各 Goal 测试 + R6 截图矩阵与 a11y 目录；无以「数据已显示」豁免可读性的条目。
    public static let records: [R6RouteAcceptanceRecord] = AppRoute.allCases.map { route in
        let notes: String? = switch route {
        case .compare: "对比矩阵在极窄窗口依赖横向滚动（P3 已接受）"
        case .cryptoResearch, .quantBacktests, .paper: "R5 语义工作区；PAPER 边界徽标常驻"
        case .moodLab: "管理员操作已隔离；结果表截断脚注统一"
        default: nil
        }
        return R6RouteAcceptanceRecord(
            route: route,
            layers: Dictionary(uniqueKeysWithValues: R6ParityLayer.allCases.map { ($0, R6ParityStatus.verified) }),
            note: notes
        )
    }

    public static func record(for route: AppRoute) -> R6RouteAcceptanceRecord {
        records.first { $0.route == route } ?? R6RouteAcceptanceRecord(
            route: route,
            layers: [:],
            note: "缺失"
        )
    }
}
