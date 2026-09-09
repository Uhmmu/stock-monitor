import StockMonitorDesign
import SwiftUI

public struct RoutePageAnatomy: Equatable, Sendable {
    public let navigationTitle: String
    public let objectIdentity: String
    public let primarySummary: String
    public let primaryAction: String
    public let provenance: String
    public let workspace: AppWorkspace?

    public static func make(for route: AppRoute, symbol: String? = nil) -> Self {
        let audit = ReadabilityAuditCatalog.record(for: route)
        let identity = route.workspace == .company ? (symbol ?? "选择证券") : route.title
        return .init(
            navigationTitle: route.title,
            objectIdentity: identity,
            primarySummary: audit.primaryInformation,
            primaryAction: audit.primaryAction,
            provenance: audit.evidence,
            workspace: route.workspace
        )
    }
}

/// 无网络的 R3 导航与页面骨架视觉夹具；生产 Shell 使用相同的导航模型和 Design 组件。
public struct NavigationVisualAuditView: View {
    @State private var navigation: AppNavigationModel
    private let layoutWidth: StockMonitorLayoutWidth
    private let showSearch: Bool

    public init(route: AppRoute = .fundamentals, layoutWidth: StockMonitorLayoutWidth = .standard, showSearch: Bool = false) {
        _navigation = State(initialValue: AppNavigationModel(
            selection: route,
            favorites: [.overview, .watchlist, .fundamentals],
            recents: [.fundamentals, .news, .holdings]
        ))
        self.layoutWidth = layoutWidth
        self.showSearch = showSearch
    }

    public var body: some View {
        HStack(spacing: 0) {
            if layoutWidth != .narrow {
                auditSidebar.frame(width: layoutWidth == .wide ? 270 : 230)
                Divider()
            }
            VStack(spacing: 0) {
                if let workspace = navigation.selection.workspace {
                    workspaceBar(workspace)
                }
                auditPage
            }
            .overlay {
                if showSearch {
                    searchOverlay
                }
            }
        }
        .environment(\.stockMonitorLayoutWidth, layoutWidth)
    }

    private var auditSidebar: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                sidebarGroup("收藏", routes: navigation.favorites)
                sidebarGroup("最近使用", routes: navigation.recents)
                sidebarGroup("公司分析", routes: navigation.routes(in: .company))
                Label("记录与系统", systemImage: "chevron.right")
                    .stockMonitorTypography(.metadata)
                    .padding(.top, StockMonitorSpacing.small)
            }
            .padding(StockMonitorSpacing.medium)
        }
        .background(.bar)
    }

    private func sidebarGroup(_ title: String, routes: [AppRoute]) -> some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
            Text(title).stockMonitorTypography(.metadata).fontWeight(.semibold)
            ForEach(routes) { route in
                Label(route.title, systemImage: route.systemImage)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, StockMonitorSpacing.small)
                    .padding(.vertical, StockMonitorSpacing.xSmall)
                    .background(
                        route == navigation.selection ? Color.accentColor.opacity(0.16) : .clear,
                        in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.control)
                    )
            }
        }
    }

    private func workspaceBar(_ workspace: AppWorkspace) -> some View {
        ScrollView(.horizontal) {
            HStack(spacing: StockMonitorSpacing.small) {
                Text(workspace.title).font(.headline)
                ForEach(workspace.routes) { route in
                    Text(route.title)
                        .font(.callout.weight(route == navigation.selection ? .semibold : .regular))
                        .padding(.horizontal, StockMonitorSpacing.small)
                        .padding(.vertical, StockMonitorSpacing.xSmall)
                        .background(route == navigation.selection ? Color.accentColor : .clear, in: Capsule())
                        .foregroundStyle(route == navigation.selection ? .white : .primary)
                }
            }.padding(.horizontal, StockMonitorSpacing.medium).padding(.vertical, StockMonitorSpacing.small)
        }
        .scrollIndicators(.hidden)
        .background(.bar)
        .overlay(alignment: .bottom) { Divider() }
    }

    private var auditPage: some View {
        let anatomy = RoutePageAnatomy.make(for: navigation.selection, symbol: "AAPL")
        return PageScaffold {
            PageHeader(anatomy.objectIdentity, eyebrow: anatomy.navigationTitle, summary: anatomy.primarySummary) {
                FreshnessBadge("09:30 更新", stale: false)
            }
        } content: {
            MetricGrid([
                .init(label: "现价", value: FinancialValueFormatter.price(234.12, currency: "USD"), status: .live),
                .init(label: "日变化", value: FinancialValueFormatter.percent(0.023), status: .positive),
                .init(label: "数据覆盖", value: .init(text: "18 / 20", qualifier: "部分指标待更新"), status: .warning),
            ])
            SectionHeader("主要内容", explanation: anatomy.primarySummary) { Button(anatomy.primaryAction) {} }
            TimelineList([
                .init(id: "1", title: "盈利质量保持稳定", timestamp: "刚刚", detail: "主要结论位于 leading edge，来源、日期和限制保持可追溯。"),
                .init(id: "2", title: "国际证券代码与超长公司名称的正式布局夹具", timestamp: "昨天", detail: anatomy.provenance),
            ])
            SectionHeader("来源与限制")
            MetadataStrip([
                .init(label: "来源", value: "服务端脱敏 fixture"),
                .init(label: "数据时间", value: "2026-09-09 09:30"),
            ])
        }
        .navigationTitle(anatomy.navigationTitle)
        .accessibilityIdentifier("r3.navigation.\(layoutWidth.rawValue)")
    }

    private var searchOverlay: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            TextField("搜索功能、股票、会话或报告", text: .constant("AAPL"))
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("r3.command-search")
            ForEach(NavigationSearchKind.allCases) { kind in
                VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                    Text(kind.title).stockMonitorTypography(.metadata)
                    HStack {
                        Image(systemName: kind == .security ? "chart.line.uptrend.xyaxis" : "arrow.turn.down.right")
                        Text(kind == .security ? "AAPL" : kind.title)
                        Spacer()
                        Text(kind == .security ? "公司工作区" : "目标上下文").stockMonitorTypography(.metadata)
                    }
                }
            }
        }
        .padding(StockMonitorSpacing.large)
        .frame(width: 460)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.prominent))
        .shadow(radius: StockMonitorElevation.floatingRadius, y: StockMonitorElevation.floatingY)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("r3.command-search")
    }
}
