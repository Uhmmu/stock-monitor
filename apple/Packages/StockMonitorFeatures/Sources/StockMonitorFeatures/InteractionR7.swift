import Foundation

public struct RouteInteractionAudit: Identifiable, Equatable, Sendable {
    public let route: AppRoute
    public let entry: String
    public let primaryAction: String
    public let context: String
    public let retainedState: String
    public let detailPattern: String
    public let failureRecovery: String

    public var id: AppRoute {
        route
    }
}

/// R7.0 baseline for the 31 production routes. The catalog is deliberately behavioral:
/// it describes how a person enters, acts, drills in, returns, and recovers.
public enum R7InteractionAuditCatalog {
    public static let entries: [RouteInteractionAudit] = AppRoute.allCases.map(make)

    public static func entry(for route: AppRoute) -> RouteInteractionAudit {
        entries.first { $0.route == route }!
    }

    private static func make(_ route: AppRoute) -> RouteInteractionAudit {
        let primaryAction: String
        let context: String
        let retained: String
        let detail: String

        switch route {
        case .overview:
            primaryAction = "打开值得关注的证券或异动"
            context = "全市场与组合摘要"
            retained = "滚动位置"
            detail = "证券独立研究窗口"
        case .watchlist:
            primaryAction = "搜索并选择证券"
            context = "证券、分组与同行"
            retained = "分组、排序、选中证券"
            detail = "同页详情栏或研究窗口"
        case .holdings:
            primaryAction = "检查持仓与组合风险"
            context = "组合与基础币种"
            retained = "工作区端点、选中持仓"
            detail = "右侧详情栏"
        case .news:
            primaryAction = "筛选并阅读新闻"
            context = "范围、证券与主题"
            retained = "范围、筛选词、选中文章"
            detail = "阅读 Sheet"
        case .settings, .administration, .ibkrAdmin:
            primaryAction = "检查并保存设置"
            context = "用户与权限范围"
            retained = "当前设置分区"
            detail = "Form 或安全确认"
        case .fundamentals, .financials, .valuation, .technical, .sec, .ownership, .compare:
            primaryAction = "选择证券并检查证据"
            context = "共享公司证券"
            retained = "证券、区间、比较项"
            detail = "检查器或研究窗口"
        case .ai, .reports, .discovery:
            primaryAction = "选择研究对象并继续研究"
            context = "证券与研究记录"
            retained = "工作区端点、选择与筛选"
            detail = "右侧详情或独立研究窗口"
        default:
            primaryAction = "筛选、选择并检查详情"
            context = route.workspace?.title ?? route.section.title
            retained = "筛选、排序与选择"
            detail = "同页详情栏或检查器"
        }

        return RouteInteractionAudit(
            route: route,
            entry: "侧栏、最近使用、收藏或 Command-K",
            primaryAction: primaryAction,
            context: context,
            retainedState: retained,
            detailPattern: detail,
            failureRecovery: "保留 last-good 内容，显示原因并提供重试"
        )
    }
}
