import Foundation
import StockMonitorCore

public enum GoalM5Phase: String, CaseIterable, Sendable {
    case ai = "M5.0"
    case portfolio = "M5.1"
    case crypto = "M5.2"
}

public struct WorkspaceEndpoint: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let path: String
    public let query: [URLQueryItem]
    public let administratorOnly: Bool

    public init(_ title: String, path: String, query: [URLQueryItem] = [], administratorOnly: Bool = false) {
        id = path + "?" + query.map { "\($0.name)=\($0.value ?? "")" }.joined(separator: "&")
        self.title = title
        self.path = path
        self.query = query
        self.administratorOnly = administratorOnly
    }

    public var placeholders: [String] {
        let source = ([path] + query.compactMap(\.value)).joined(separator: " ")
        return ["instrument_id", "asset_id", "job_id", "run_id", "candidate_id", "history_id"].filter { source.contains("{\($0)}") }
    }

    public func resolving(_ values: [String: String]) -> WorkspaceEndpoint {
        func replace(_ input: String) -> String {
            values.reduce(input) { value, pair in value.replacingOccurrences(of: "{\(pair.key)}", with: pair.value) }
        }
        return WorkspaceEndpoint(
            title, path: replace(path),
            query: query.map { URLQueryItem(name: $0.name, value: $0.value.map(replace)) },
            administratorOnly: administratorOnly
        )
    }
}

public struct WorkspaceAction: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let path: String
    public let method: HTTPMethod
    public let body: JSONValue
    public let destructive: Bool
    public let confirmation: String
    public let administratorOnly: Bool

    public init(
        _ title: String, path: String, method: HTTPMethod = .post,
        body: JSONValue = .object([:]), destructive: Bool = false,
        confirmation: String, administratorOnly: Bool = false
    ) {
        id = "\(method.rawValue):\(path):\(title)"
        self.title = title; self.path = path; self.method = method; self.body = body
        self.destructive = destructive; self.confirmation = confirmation
        self.administratorOnly = administratorOnly
    }
}

public struct WorkspaceDescriptor: Equatable, Sendable {
    public let phase: GoalM5Phase
    public let title: String
    public let summary: String
    public let endpoints: [WorkspaceEndpoint]
    public let actions: [WorkspaceAction]
    public let securityNotice: String?
}

public struct AIConversationCreateRequest: Codable, Equatable, Sendable {
    public let title: String?
    public let message: String?
    public let model: String?
    public let webAccessMode: String

    public init(title: String? = nil, message: String? = nil, model: String? = nil, webAccessMode: String = "off") {
        self.title = title; self.message = message; self.model = model; self.webAccessMode = webAccessMode
    }

    enum CodingKeys: String, CodingKey { case title, message, model; case webAccessMode = "web_access_mode" }
}

public struct AIMessageRequest: Codable, Equatable, Sendable {
    public let message: String
    public let model: String?
    public let webAccessMode: String
    public let stream: Bool
    public let activeSymbol: String?
    public let deepSearchConfirmed: Bool

    public init(
        message: String, model: String?, webAccessMode: String, activeSymbol: String?,
        stream: Bool = true, deepSearchConfirmed: Bool = false
    ) {
        self.message = message; self.model = model; self.webAccessMode = webAccessMode
        self.activeSymbol = activeSymbol; self.stream = stream
        self.deepSearchConfirmed = deepSearchConfirmed
    }

    enum CodingKeys: String, CodingKey {
        case message, model, stream
        case webAccessMode = "web_access_mode"
        case activeSymbol = "active_symbol"
        case deepSearchConfirmed = "deep_search_confirmed"
    }
}

public struct DeepSearchCreateRequest: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let userMessageID: Int
    public let assistantMessageID: Int
    public let query: String
    public let webAccessMode: String
    public let generationIndex: Int
    public let confirmation: Bool

    enum CodingKeys: String, CodingKey {
        case query, confirmation
        case conversationID = "conversation_id"
        case userMessageID = "user_message_id"
        case assistantMessageID = "assistant_message_id"
        case webAccessMode = "web_access_mode"
        case generationIndex = "generation_index"
    }
}

public struct GoalM5Catalog: Sendable {
    public init() {}

    public func descriptor(for route: AppRoute, isAdministrator: Bool) -> WorkspaceDescriptor? {
        let all: WorkspaceDescriptor? = switch route {
        case .decisions: decisions
        case .discovery: discovery
        case .holdings: portfolio
        case .journal: journal
        case .ibkr: ibkr
        case .ibkrAdmin: ibkrAdmin
        case .cryptoResearch: cryptoResearch
        case .quantBacktests: quant
        case .paper: paper
        case .settings: settings
        case .administration: administration
        default: nil
        }
        guard let all else { return nil }
        return WorkspaceDescriptor(
            phase: all.phase, title: all.title, summary: all.summary,
            endpoints: all.endpoints.filter { isAdministrator || !$0.administratorOnly },
            actions: all.actions.filter { isAdministrator || !$0.administratorOnly },
            securityNotice: all.securityNotice
        )
    }

    public var decisions: WorkspaceDescriptor {
        .init(
            phase: .ai, title: "记忆与投资决策", summary: "建议、确认、审核与解决保持独立；这里永不执行交易。",
            endpoints: [
                .init("待确认记忆", path: "/api/ai/v1/memory-candidates", query: [.init(name: "limit", value: "50")]),
                .init("已保存记忆", path: "/api/ai/v1/memories", query: [.init(name: "limit", value: "50")]),
                .init("记忆设置", path: "/api/ai/v1/memory-settings"),
                .init("投资决策", path: "/api/ai/v1/investment-decisions", query: [.init(name: "limit", value: "100")]),
            ], actions: [], securityNotice: "投资决策是用户确认的研究记录，不会触发下单。"
        )
    }

    public var discovery: WorkspaceDescriptor {
        .init(
            phase: .ai, title: "机会发现", summary: "渐进结果、历史、设置和精确用量均以服务端记录为准。",
            endpoints: [
                .init("最新结果", path: "/api/discovery/latest"), .init("运行中", path: "/api/discovery/runs"),
                .init("历史", path: "/api/discovery/history"), .init("设置", path: "/api/discovery/settings"),
                .init("用量", path: "/api/discovery/usage"),
                .init("运行详情", path: "/api/discovery/runs/{run_id}"),
                .init("候选详情", path: "/api/discovery/candidates/{candidate_id}"),
                .init("历史详情", path: "/api/discovery/history/{history_id}"),
            ], actions: [.init("运行发现", path: "/api/discovery/refresh", confirmation: "会触发一次可能产生费用的服务端发现任务。")],
            securityNotice: "刷新受冷却、预算、幂等与服务端锁保护。"
        )
    }

    public var portfolio: WorkspaceDescriptor {
        .init(
            phase: .portfolio, title: "组合与风险分析", summary: "多币种估值、健康、画像与异步分析全部服务端计算。",
            endpoints: [
                .init("组合摘要", path: "/api/portfolio/summary"), .init("持仓", path: "/api/portfolio/positions"),
                .init("交易", path: "/api/portfolio/transactions"), .init("Lots", path: "/api/portfolio/open-lots"),
                .init("已完成交易", path: "/api/portfolio/completed-trades"), .init("绩效", path: "/api/portfolio/performance"),
                .init("归因", path: "/api/portfolio/attribution"), .init("Benchmark", path: "/api/portfolio/benchmark"),
                .init("健康检查", path: "/api/portfolio/health"), .init("策略画像", path: "/api/portfolio/strategy-profile"),
                .init("个性化解读", path: "/api/portfolio/interpretation"),
                .init("分析历史", path: "/api/portfolio/analysis/history"),
                .init("压力情景", path: "/api/portfolio/analysis/scenarios/presets"),
                .init("优化预设", path: "/api/portfolio/analysis/optimization-presets"),
                .init("任务详情", path: "/api/portfolio/analysis/jobs/{job_id}"),
            ], actions: [.init("重建持仓", path: "/api/portfolio/rebuild", destructive: true, confirmation: "将从服务端交易账本重建当前持仓；请确认范围。")],
            securityNotice: "缺少 FX 的持仓会保持覆盖缺口，Mac 不会按 1:1 猜测。"
        )
    }

    public var journal: WorkspaceDescriptor {
        .init(
            phase: .portfolio, title: "交易日志", summary: "交易事实与用户复盘分层，AI 总结只按明确操作触发。",
            endpoints: [.init("日志", path: "/api/trade-logs")], actions: [], securityNotice: nil
        )
    }

    public var ibkr: WorkspaceDescriptor {
        .init(
            phase: .portfolio, title: "IBKR", summary: "只呈现服务端同步的账户、绩效、现金流与数据健康。",
            endpoints: [
                .init("状态", path: "/api/ibkr/status"), .init("账户", path: "/api/ibkr/accounts"),
                .init("总览", path: "/api/ibkr/overview"), .init("日绩效", path: "/api/ibkr/performance/daily"),
                .init("月绩效", path: "/api/ibkr/performance/monthly"), .init("归因", path: "/api/ibkr/performance/attribution"),
                .init("闭环交易", path: "/api/ibkr/trades/round-trips"), .init("现金流", path: "/api/ibkr/cash-flows/summary"),
                .init("分红", path: "/api/ibkr/dividends/summary"), .init("费用", path: "/api/ibkr/fees/summary"),
                .init("FX 暴露", path: "/api/ibkr/fx/exposure"), .init("数据健康", path: "/api/ibkr/data-health"),
                .init("Client Portal", path: "/api/ibkr/client-portal/status"), .init("Portal 持仓", path: "/api/ibkr/client-portal/positions"),
            ], actions: [
                .init("同步 Flex", path: "/api/ibkr/sync", confirmation: "请求服务端通过强制代理同步 Flex 数据。"),
                .init("同步 Client Portal", path: "/api/ibkr/client-portal/sync", confirmation: "请求服务端同步 Client Portal；可能需要手机批准。"),
            ], securityNotice: "Mac App 不保存 IBKR 凭据或代理配置；所有连接只能由 VPS 通过 socks5h 代理且失败关闭。"
        )
    }

    public var ibkrAdmin: WorkspaceDescriptor {
        .init(
            phase: .portfolio, title: "IBKR 管理", summary: "管理员诊断仅调用服务端安全边界。",
            endpoints: [
                .init("配置（脱敏）", path: "/api/admin/integrations/ibkr/config", administratorOnly: true),
                .init("网关健康", path: "/api/admin/integrations/ibkr/gateway/health", administratorOnly: true),
                .init("认证状态", path: "/api/admin/integrations/ibkr/auth/status", administratorOnly: true),
                .init("Flex 状态", path: "/api/admin/integrations/ibkr/flex/status", administratorOnly: true),
            ], actions: [
                .init("Flex 测试", path: "/api/admin/integrations/ibkr/flex/test", confirmation: "仅执行服务端连接测试，不向 Mac 暴露凭据。", administratorOnly: true),
                .init("初始化会话", path: "/api/admin/integrations/ibkr/session/initialize", confirmation: "由服务端初始化 IBKR 会话；代理不可用时必须失败。", administratorOnly: true),
            ], securityNotice: "禁止在此客户端输入或缓存 IBKR 用户名、密码、代理地址或密钥。"
        )
    }

    public var cryptoResearch: WorkspaceDescriptor {
        .init(
            phase: .crypto, title: "Crypto 研究", summary: "身份证据、市场、衍生品、技术、基本面和新闻保持来源可追溯。",
            endpoints: [
                .init("搜索", path: "/api/crypto/search", query: [.init(name: "q", value: "BTC")]),
                .init("证券", path: "/api/crypto/instruments"), .init("市场状态", path: "/api/crypto/market/status"),
                .init("K 线", path: "/api/crypto/market/candles", query: [.init(name: "instrument_id", value: "{instrument_id}"), .init(name: "interval", value: "1d")]),
                .init("最新行情", path: "/api/crypto/market/latest", query: [.init(name: "instrument_id", value: "{instrument_id}")]),
                .init("技术指标", path: "/api/crypto/market/technical", query: [.init(name: "instrument_id", value: "{instrument_id}")]),
                .init("基本面", path: "/api/crypto/fundamentals", query: [.init(name: "asset_id", value: "{asset_id}")]),
                .init("衍生品", path: "/api/crypto/derivatives", query: [.init(name: "instrument_id", value: "{instrument_id}")]),
                .init("衍生品 Regime", path: "/api/crypto/derivatives/regime", query: [.init(name: "instrument_id", value: "{instrument_id}")]),
                .init("研究上下文", path: "/api/crypto/research/context", query: [.init(name: "instrument_id", value: "{instrument_id}")]),
                .init("新闻", path: "/api/crypto/news", query: [.init(name: "asset_id", value: "{asset_id}"), .init(name: "instrument_id", value: "{instrument_id}")]),
                .init("报告", path: "/api/crypto/reports"),
            ], actions: [], securityNotice: "研究数据不构成真实交易入口。"
        )
    }

    public var quant: WorkspaceDescriptor {
        .init(
            phase: .crypto, title: "量化与回测", summary: "定义、特征、信号、回测和部署状态均由服务端持久化。",
            endpoints: [
                .init("定义", path: "/api/crypto/quant/definitions"), .init("特征", path: "/api/crypto/quant/features"),
                .init("状态", path: "/api/crypto/quant/status"), .init("回测", path: "/api/crypto/quant/backtests"),
                .init("部署", path: "/api/crypto/quant/deployments"),
                .init("信号", path: "/api/crypto/quant/signals"), .init("信号运行", path: "/api/crypto/quant/signals/runs"),
                .init("回测详情", path: "/api/crypto/quant/backtests/{run_id}"),
                .init("净值曲线", path: "/api/crypto/quant/backtests/{run_id}/equity"),
                .init("回测交易", path: "/api/crypto/quant/backtests/{run_id}/trades"),
            ], actions: [.init("生成信号", path: "/api/crypto/quant/signals/generate", confirmation: "启动一次服务端信号生成任务。")],
            securityNotice: "部署只连接内部 PAPER，不创建真实交易能力。"
        )
    }

    public var paper: WorkspaceDescriptor {
        .init(
            phase: .crypto, title: "内部 PAPER", summary: "订单、撮合、账本、运行和对账全部回读服务端模拟器。",
            endpoints: [
                .init("账户", path: "/api/crypto/quant/paper"), .init("配置", path: "/api/crypto/quant/paper/config"),
                .init("订单", path: "/api/crypto/quant/paper/orders"), .init("成交", path: "/api/crypto/quant/paper/fills"),
                .init("账本", path: "/api/crypto/quant/paper/ledger"), .init("运行", path: "/api/crypto/quant/paper/runs"),
                .init("对账", path: "/api/crypto/quant/paper/reconciliations"),
            ], actions: [
                .init("创建模拟账户", path: "/api/crypto/quant/paper/account", confirmation: "使用服务端默认资金与成本参数创建内部 PAPER 账户。"),
                .init("处理撮合", path: "/api/crypto/quant/paper/process", confirmation: "让内部模拟器处理待撮合订单。"),
                .init("对账", path: "/api/crypto/quant/paper/reconcile", confirmation: "执行只读式服务端账本对账。"),
                .init("修复对账", path: "/api/crypto/quant/paper/reconcile/repair", destructive: true, confirmation: "将按服务端权威账本修复派生状态，请确认范围。"),
                .init("暂停", path: "/api/crypto/quant/paper/pause", confirmation: "暂停内部 PAPER 账户。"),
                .init("恢复", path: "/api/crypto/quant/paper/resume", confirmation: "恢复内部 PAPER 账户。"),
                .init(
                    "重置", path: "/api/crypto/quant/paper/reset",
                    body: .object(["confirm": .string("RESET PAPER")]), destructive: true,
                    confirmation: "危险操作：清空内部 PAPER 派生状态并重建模拟账户；不会影响真实账户。"
                ),
            ], securityNotice: "仅内部模拟器；不提供 Binance Demo、Testnet、Live 或真实下单入口。"
        )
    }

    public var settings: WorkspaceDescriptor {
        .init(
            phase: .crypto, title: "服务与用户设置", summary: "数据源状态、配额与同步设置均来自服务端。",
            endpoints: [.init("用户设置", path: "/api/settings"), .init("数据源健康", path: "/api/market/providers/status"), .init("AI 配置", path: "/api/ai/v1/config")],
            actions: [], securityNotice: "密钥只在服务端配置，客户端不会显示或缓存。"
        )
    }

    public var administration: WorkspaceDescriptor {
        .init(
            phase: .crypto, title: "系统管理", summary: "用户、同步与执行控制严格按管理员角色隔离。",
            endpoints: [
                .init("用户", path: "/api/auth/admin/users", administratorOnly: true),
                .init("FMP", path: "/api/admin/fmp/status", administratorOnly: true),
                .init("执行状态", path: "/api/execution/admin/status", administratorOnly: true),
                .init("执行账户", path: "/api/execution/admin/accounts", administratorOnly: true),
                .init("执行代理", path: "/api/execution/admin/agents", administratorOnly: true),
                .init("执行订单", path: "/api/execution/admin/orders", administratorOnly: true),
                .init("执行事件", path: "/api/execution/admin/events", administratorOnly: true),
            ], actions: [.init("同步 FMP", path: "/api/admin/fmp/sync", confirmation: "启动管理员数据同步任务。", administratorOnly: true)],
            securityNotice: "普通用户不可见，服务端仍会独立执行角色校验。"
        )
    }
}
