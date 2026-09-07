import Foundation
import StockMonitorDesign
import SwiftUI

public enum ReadabilitySeverity: String, CaseIterable, Codable, Sendable {
    case p0 = "P0", p1 = "P1", p2 = "P2", p3 = "P3"
}

public enum ReadabilityAuditAspect: String, CaseIterable, Codable, Sendable {
    case firstScreenConclusion, duplicateTitle, readingOrder, alignment, truncation, clickability, provenanceAndState
}

public enum ReadabilityAuditDisposition: String, Codable, Sendable { case pass, needsReview, fail }

public struct RouteReadabilityFinding: Identifiable, Equatable, Codable, Sendable {
    public let aspect: ReadabilityAuditAspect
    public let disposition: ReadabilityAuditDisposition
    public let note: String
    public var id: ReadabilityAuditAspect {
        aspect
    }
}

public struct RouteReadabilityAuditRecord: Identifiable, Equatable, Codable, Sendable {
    public let route: AppRoute
    public let userTask: String
    public let primaryInformation: String
    public let primaryAction: String
    public let evidence: String
    public let failureState: String
    public let baselineSeverity: ReadabilitySeverity
    public var id: AppRoute {
        route
    }

    public var baselineFindings: [RouteReadabilityFinding] {
        let rawJSON = baselineSeverity == .p0
        return [
            .init(
                aspect: .firstScreenConclusion,
                disposition: rawJSON ? .fail : .needsReview,
                note: rawJSON ? "通用 JSON 展开不能保证首屏结论。" : "已有业务页面，但强调层级尚未统一。"
            ),
            .init(aspect: .duplicateTitle, disposition: .needsReview, note: "navigation title 与页内标题需在真实窗口逐页核对。"),
            .init(
                aspect: .readingOrder,
                disposition: rawJSON ? .fail : .needsReview,
                note: rawJSON ? "字段顺序来自对象结构，不是用户任务。" : "阅读顺序分散在页面局部实现中。"
            ),
            .init(aspect: .alignment, disposition: .needsReview, note: "数字列、metadata 与窄窗口对齐缺少共享规范。"),
            .init(aspect: .truncation, disposition: .needsReview, note: "长中文、长英文、国际代码和大金额列入 golden fixture。"),
            .init(aspect: .clickability, disposition: .needsReview, note: "hover、pressed、focused 与 disabled 需按组件状态复核。"),
            .init(
                aspect: .provenanceAndState,
                disposition: rawJSON ? .fail : .needsReview,
                note: rawJSON ? "来源、时间、限制与业务值混在对象树中。" : "来源和状态位置尚未全局统一。"
            ),
        ]
    }

    public init(
        route: AppRoute,
        userTask: String,
        primaryInformation: String,
        primaryAction: String,
        evidence: String,
        failureState: String,
        baselineSeverity: ReadabilitySeverity
    ) {
        self.route = route; self.userTask = userTask; self.primaryInformation = primaryInformation; self.primaryAction = primaryAction
        self.evidence = evidence; self.failureState = failureState; self.baselineSeverity = baselineSeverity
    }
}

/// Audit copy is intentionally kept in one place so reviewers can scan every route without indirection.
public enum ReadabilityAuditCatalog {
    public static let records: [RouteReadabilityAuditRecord] = AppRoute.allCases.map(makeRecord)

    public static func record(for route: AppRoute) -> RouteReadabilityAuditRecord {
        makeRecord(route)
    }

    // The exhaustive switch is deliberately one-to-one with AppRoute.
    // swiftlint:disable:next cyclomatic_complexity
    private static func makeRecord(_ route: AppRoute) -> RouteReadabilityAuditRecord {
        // swiftlint:disable:next large_tuple
        let values: (String, String, String, String, String, ReadabilitySeverity) = switch route {
        case .overview: ("判断今天最值得关注的市场与资产变化", "市场、组合、自选和异动摘要", "进入异常或持仓详情", "指数、报价时间、最新报告", "保留 last-good 并标明旧数据", .p1)
        case .watchlist: ("扫描并管理自选证券", "价格、涨跌、状态和分组", "添加、排序或打开证券", "行情来源与更新时间", "逐行解释缺行情或映射失败", .p1)
        case .holdings: ("理解组合价值、盈亏和风险", "总市值、盈亏、覆盖率与持仓权重", "查看持仓或组合分析", "本币、基础币、FX 与报价时间", "排除不可估值项并解释覆盖缺口", .p0)
        case .ai: ("围绕投资问题持续对话", "消息、引用、工具进度和恢复状态", "发送问题或继续会话", "引用来源、模型与工具结果", "保留已生成内容并给出恢复动作", .p0)
        case .decisions: ("检查投资决策及其依据", "结论、置信度、风险与状态", "查看证据或更新决策", "输入数据、时间和模型", "区分数据不足、任务失败与旧结论", .p0)
        case .calendar: ("查看近期投资事件", "日期、事件类型、证券和确认状态", "切换范围或打开事件", "Yahoo/Finnhub 来源与同步时间", "保留缓存并显示同步覆盖缺口", .p1)
        case .discovery: ("筛选组合适配的股票机会", "候选分组、验证、风险和成本", "打开候选详情或启动刷新", "原始来源、本地验证和过滤原因", "展示上一成功批次与本次失败", .p0)
        case .options: ("评估期权市场与策略条件", "到期、行权价、波动率与流动性", "调整合约和期限", "报价源、时间和限制", "说明链路缺失或合约不可用", .p1)
        case .mood: ("判断市场与板块情绪", "总情绪、变化和驱动因素", "切换范围或查看证据", "样本覆盖、模型与生成时间", "区分样本不足、旧快照与模型失败", .p1)
        case .moodLab: ("验证情绪模型输出", "输入、阶段结果、差异与成本", "运行验证或复制诊断", "模型参数、request ID 和原始证据", "完整保留失败阶段和诊断信息", .p1)
        case .alerts: ("处理仍需关注的价格异动", "发生事项、严重度、时间和调查状态", "打开或更新调查", "触发报价、规则和新闻证据", "区分无异动与调查获取失败", .p1)
        case .news: ("快速阅读与证券相关的新闻", "标题、证券、来源、时间和摘要", "打开新闻或外部原文", "发布者、链接与 AI 身份", "保留列表并标记正文抓取失败", .p1)
        case .macro: ("理解宏观环境及其市场影响", "核心指标、趋势和发布时间", "切换指标或查看历史", "官方来源、频率和最新观测", "明确尚未发布、过期或来源失败", .p1)
        case .industry: ("比较行业强弱和资金变化", "行业排名、趋势和驱动因素", "选择行业查看详情", "成分覆盖、行情时间和算法口径", "说明覆盖不足且不生成虚假排名", .p1)
        case .fundamentals: ("判断公司质量与成长情况", "估值、盈利、成长、效率和风险", "切换证券或深入财报", "Yahoo 指标来源和查询时间", "按指标解释缺失而非整页失败", .p1)
        case .financials: ("比较多个期间的财务报表", "科目、期间、单位和同比", "切换报表或期间", "同步时间、来源和币种", "保留旧快照并解释未同步科目", .p1)
        case .valuation: ("判断估值区间与适用性", "现价、区间、置信度和模型分歧", "展开模型和证据", "模型输入、快照日期和来源", "明确模型不适用或输入缺失", .p1)
        case .compare: ("横向比较多只证券", "同口径指标和差异", "添加证券或调整指标", "每项来源、日期和币种", "保持有效列并标记不可比较项", .p1)
        case .technical: ("判断价格所处技术位置", "图表、趋势、关键位和状态", "切换周期或指标", "行情区间、更新时间和计算口径", "保留图表历史并指出数据长度不足", .p1)
        case .sec: ("检查公司 SEC 事件和文件", "文件类型、日期、关键事项和风险", "打开申报或证据", "SEC 原文、表单和抓取时间", "区分无申报、解析失败和权限问题", .p1)
        case .ownership: ("了解机构持仓与变化", "机构、仓位、变动和报告期", "选择机构或持仓详情", "13F 文件、期间和覆盖率", "标明报告滞后或实体映射缺失", .p1)
        case .congress: ("查看公开人物披露交易", "人物、证券、方向、金额区间和日期", "打开交易或来源", "官方披露和抓取时间", "强调披露延迟和金额区间限制", .p1)
        case .reports: ("查找并阅读研究报告", "标题、证券、日期、摘要和正文", "打开、搜索或复制报告", "引用、生成模型和数据截止日", "保留目录位置并说明正文加载失败", .p1)
        case .journal: ("记录交易事实与复盘", "时间线、交易事实和复盘正文", "新增或编辑记录", "关联证券、时间和版本", "草稿可恢复且保存错误可重试", .p0)
        case .settings: ("查看并调整个人设置", "当前值、作用范围和安全说明", "保存或恢复默认", "服务端回读和更新时间", "逐项显示保存失败并恢复旧值", .p0)
        case .administration: ("管理用户与服务权限", "用户、角色、状态和影响范围", "修改权限或账户状态", "服务端回读、时间和操作者", "权限拒绝与操作失败必须明确", .p0)
        case .ibkr: ("了解 IBKR 账户和同步状态", "账户状态、新鲜度、组合、绩效和现金", "重新认证或同步", "代理状态、同步历史和数据时间", "代理不可用时 fail-closed 并明确下一步", .p0)
        case .ibkrAdmin: ("管理 IBKR 连接和认证", "代理、登录、会话与同步任务状态", "登录、重认证或诊断", "安全边界、request ID 和任务历史", "禁止直连回退并给出可操作错误", .p0)
        case .cryptoResearch: ("研究加密资产市场", "标的、报价、走势和关键上下文", "切换标的或研究标签", "交易所来源、时间和覆盖", "标的不可用时不显示占位 JSON", .p0)
        case .quantBacktests: ("审阅量化定义、信号和回测", "策略、特征、运行、权益曲线和交易", "运行或打开回测", "版本、参数、数据区间和状态", "区分无结果、运行失败和不允许部署", .p0)
        case .paper: ("控制并审阅内部 PAPER 流程", "账户、订单、持仓、风控和执行状态", "提交允许的模拟操作", "报价、策略版本和执行审计", "控制关闭或数据缺失时 fail-closed", .p0)
        }
        return RouteReadabilityAuditRecord(
            route: route,
            userTask: values.0,
            primaryInformation: values.1,
            primaryAction: values.2,
            evidence: values.3,
            failureState: values.4,
            baselineSeverity: values.5
        )
    }
}

public enum VisualAuditState: String, CaseIterable, Sendable { case normal, empty, partial, stale, loading, error, permissionDenied }
public enum VisualAuditWidth: String, CaseIterable, Sendable {
    case narrow, standard, wide
    public var size: CGSize {
        switch self {
        case .narrow: CGSize(width: 620, height: 720)
        case .standard: CGSize(width: 1180, height: 760)
        case .wide: CGSize(width: 1560, height: 900)
        }
    }
}

public struct RouteVisualAuditView: View {
    public let record: RouteReadabilityAuditRecord
    public let state: VisualAuditState
    public init(route: AppRoute, state: VisualAuditState = .normal) {
        record = ReadabilityAuditCatalog.record(for: route); self.state = state
    }

    public var body: some View {
        PageScaffold {
            PageHeader(record.route.title, eyebrow: record.route.section.title, summary: record.userTask) {
                HStack {
                    SourceBadge("脱敏 fixture")
                    FreshnessBadge(state == .stale ? "18 分钟前" : "刚刚", stale: state == .stale)
                }
            }
        } content: {
            stateContent
            EvidencePanel("审计口径") {
                MetadataStrip([
                    .init(label: "主要信息", value: record.primaryInformation),
                    .init(label: "主要动作", value: record.primaryAction),
                ])
                Text(record.evidence).stockMonitorTypography(.body).textSelection(.enabled)
                Text("失败状态：\(record.failureState)").stockMonitorTypography(.metadata).textSelection(.enabled)
            }
        }
        .navigationTitle(record.route.title)
        .accessibilityIdentifier("visual-audit.\(record.route.rawValue).\(state.rawValue)")
    }

    @ViewBuilder private var stateContent: some View {
        switch state {
        case .normal, .partial, .stale:
            if state == .partial {
                InlineError("部分数据不可用", message: record.failureState, requestID: "fixture-partial")
            }
            MetricGrid([
                .init(label: "核心值", value: FinancialValueFormatter.price(234.12, currency: "USD"), status: .live),
                .init(label: "日变化", value: FinancialValueFormatter.percent(0.023), status: .positive),
                .init(
                    label: "覆盖率",
                    value: .init(text: state == .partial ? "7 / 10" : "10 / 10"),
                    status: state == .partial ? .warning : .live
                ),
            ])
            SectionHeader("主要内容", explanation: record.primaryInformation) { Button(record.primaryAction) {} }
            sampleContent
        case .empty: EmptyState("暂无\(record.route.title)数据", description: record.failureState)
        case .loading: ProgressView("正在加载\(record.route.title)").accessibilityIdentifier("state.loading")
        case .error: InlineError(message: record.failureState, requestID: "fixture-error")
        case .permissionDenied: EmptyState("没有权限", systemImage: "lock", description: "请联系管理员确认服务端角色。")
        }
    }

    @ViewBuilder private var sampleContent: some View {
        let tableRoutes: Set<AppRoute> = [.financials, .compare, .watchlist, .holdings]
        let timelineRoutes: Set<AppRoute> = [.news, .calendar, .reports, .journal, .sec]
        if tableRoutes.contains(record.route) {
            FinancialTable([
                .init(
                    label: "营业收入",
                    current: FinancialValueFormatter.amount(94_930_000_000, currency: "USD"),
                    comparison: FinancialValueFormatter.amount(85_777_000_000, currency: "USD")
                ),
                .init(
                    label: "自由现金流",
                    current: FinancialValueFormatter.amount(26_707_000_000, currency: "USD"),
                    comparison: FinancialValueFormatter.missing(.notCollected)
                ),
            ], currentTitle: "当前", comparisonTitle: "上期").frame(minHeight: 170)
        } else if timelineRoutes.contains(record.route) {
            TimelineList([
                .init(
                    id: "1",
                    title: "重要事项",
                    timestamp: "09:30",
                    detail: "包含足够长的中文证据说明，验证正文不会因次要颜色或过小字号而失去可读性。"
                ),
                .init(
                    id: "2",
                    title: "Source publishes a long English headline for layout verification",
                    timestamp: "昨天",
                    detail: record.evidence
                ),
            ])
        } else {
            ChartContainer("趋势") {
                Picker("区间", selection: .constant("1M")) { Text("1 月").tag("1M") }.labelsHidden()
            } content: {
                RoundedRectangle(cornerRadius: StockMonitorCornerRadius.control)
                    .fill(.quaternary)
                    .frame(height: 150)
                    .overlay(Text("趋势与明细内容层").foregroundStyle(.secondary))
            }
        }
    }
}
