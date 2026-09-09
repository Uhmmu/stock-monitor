import StockMonitorCore
import StockMonitorDesign
import SwiftUI
#if os(macOS)
    import AppKit
#endif

public struct AppShellView: View {
    @Bindable private var navigation: AppNavigationModel
    private let service: MarketWorkflowService
    private let researchService: ResearchWorkspaceService
    private let goalM5Service: GoalM5Service
    @AppStorage("interface-density") private var densityRawValue = InterfaceDensity.comfortable.rawValue
    @AppStorage("appearance") private var appearance = "system"
    @AppStorage("navigation-favorites") private var storedFavorites = ""
    @AppStorage("navigation-recents") private var storedRecents = ""
    @AppStorage("navigation-route-order") private var storedRouteOrder = ""
    @AppStorage("navigation-expanded-sections") private var storedExpandedSections = AppSection.assets.rawValue
    @AppStorage("inspector-visible") private var storedInspectorVisible = false
    @SceneStorage("selected-route") private var restoredRoute = AppRoute.overview.rawValue
    @SceneStorage("navigation-column-visibility") private var columnVisibilityRaw = "all"
    @Environment(\.openWindow) private var openWindow
    @Environment(\.undoManager) private var undoManager
    @State private var refreshToken = UUID()
    @State private var columnVisibility = NavigationSplitViewVisibility.all
    @State private var restoredPreferences = false

    public init(
        navigation: AppNavigationModel, service: MarketWorkflowService,
        researchService: ResearchWorkspaceService? = nil, goalM5Service: GoalM5Service? = nil
    ) {
        self.navigation = navigation
        self.service = service
        self.researchService = researchService ?? ResearchWorkspaceService(authSession: service.authSession)
        self.goalM5Service = goalM5Service ?? GoalM5Service(authSession: service.authSession)
    }

    public var body: some View {
        AdaptiveLayoutReader {
            NavigationSplitView(columnVisibility: $columnVisibility) {
                sidebar
            } detail: {
                VStack(spacing: 0) {
                    if let workspace = navigation.selection.workspace {
                        WorkspaceRouteBar(workspace: workspace, navigation: navigation)
                    }
                    routeContent
                        .id(navigation.selection)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .inspector(isPresented: $navigation.inspectorVisible) {
                    InspectorView(route: navigation.selection, symbol: navigation.selectedSymbol)
                        .inspectorColumnWidth(min: 240, ideal: 280, max: 360)
                }
                .toolbar(id: "com.jiale.StockMonitor.main-toolbar") {
                    ToolbarItem(id: "com.jiale.StockMonitor.search", placement: .primaryAction, showsByDefault: true) {
                        Button("全局搜索", systemImage: "magnifyingglass") { navigation.searchPresented = true }
                    }
                    ToolbarItem(id: "com.jiale.StockMonitor.inspector", placement: .primaryAction, showsByDefault: true) {
                        Button("检查器", systemImage: "sidebar.trailing") { navigation.inspectorVisible.toggle() }
                    }
                    ToolbarItem(id: "com.jiale.StockMonitor.refresh", placement: .automatic, showsByDefault: true) {
                        Button("刷新", systemImage: "arrow.clockwise") { refreshToken = UUID() }
                            .keyboardShortcut("r", modifiers: .command)
                    }
                    ToolbarItem(id: "com.jiale.StockMonitor.layout", placement: .automatic, showsByDefault: false) {
                        Menu("布局", systemImage: "rectangle.3.group") {
                            Picker("数据密度", selection: $densityRawValue) {
                                ForEach(InterfaceDensity.allCases) { Text($0.title).tag($0.rawValue) }
                            }
                            Divider()
                            Button("恢复默认布局") { resetLayout() }
                        }
                    }
                }
                .navigationTitle(navigation.selection.title)
            }
            .navigationSplitViewStyle(.balanced)
        }
        .environment(\.interfaceDensity, InterfaceDensity(rawValue: densityRawValue) ?? .comfortable)
        .preferredColorScheme(appearance == "dark" ? .dark : appearance == "light" ? .light : nil)
        .onAppear {
            restorePreferencesIfNeeded()
            if let route = AppRoute(rawValue: restoredRoute) {
                navigation.navigate(to: route)
            }
        }
        .onChange(of: navigation.selection) { _, route in
            restoredRoute = route.rawValue
            persistNavigation()
        }
        .onChange(of: navigation.favorites) { _, _ in persistNavigation() }
        .onChange(of: navigation.recents) { _, _ in persistNavigation() }
        .onChange(of: navigation.routeOrder) { _, _ in persistNavigation() }
        .onChange(of: navigation.expandedSections) { _, _ in persistNavigation() }
        .onChange(of: navigation.inspectorVisible) { _, value in storedInspectorVisible = value }
        .onChange(of: columnVisibility) { _, value in columnVisibilityRaw = value == .detailOnly ? "detailOnly" : "all" }
        .onOpenURL { _ = navigation.handle(url: $0) }
        .contextMenu {
            Button("在新研究窗口打开") {
                openWindow(value: ResearchDetailRoute(
                    route: navigation.selection,
                    identifier: navigation.selectedSymbol ?? navigation.selection.rawValue
                ))
            }
            Divider()
            Button("复制深链") {
                #if os(macOS)
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString("stockmonitor://\(navigation.selection.rawValue)", forType: .string)
                #endif
            }
        }
        .sheet(isPresented: $navigation.searchPresented) {
            CommandSearchView(
                navigation: navigation,
                marketService: service,
                workspaceService: goalM5Service
            )
            .frame(minWidth: 520, minHeight: 420)
        }
    }

    private var sidebar: some View {
        List(selection: $navigation.selection) {
            if !navigation.favorites.isEmpty {
                Section("收藏") { ForEach(navigation.favorites) { shortcutRow($0) } }
            }
            if !navigation.recents.isEmpty {
                Section("最近使用") { ForEach(navigation.recents) { shortcutRow($0) } }
            }
            ForEach(AppSection.allCases) { section in
                if !navigation.routes(in: section).isEmpty {
                    DisclosureGroup(section.title, isExpanded: expansionBinding(for: section)) {
                        ForEach(navigation.routes(in: section)) { route in sidebarRow(route) }
                            .onMove { navigation.moveRoutes(in: section, from: $0, to: $1) }
                    }
                }
            }
        }
        .navigationTitle("Stock Monitor")
        .navigationSplitViewColumnWidth(min: 190, ideal: 225, max: 300)
        .accessibilityIdentifier("navigation.sidebar")
    }

    private func sidebarRow(_ route: AppRoute) -> some View {
        HStack {
            Label(route.title, systemImage: route.systemImage)
            Spacer()
            if route.isHighRiskWorkspace {
                Image(systemName: "lock.shield")
                    .foregroundStyle(.secondary)
                    .accessibilityLabel("管理与高风险工作区")
            }
        }
        .tag(route)
        .foregroundStyle(route.isHighRiskWorkspace ? .secondary : .primary)
        .contextMenu {
            Button(navigation.favorites.contains(route) ? "取消收藏" : "加入收藏") {
                navigation.toggleFavorite(route)
            }
        }
        .accessibilityLabel("\(route.title)，\(route.section.title)")
    }

    private func shortcutRow(_ route: AppRoute) -> some View {
        Button { navigation.navigate(to: route) } label: {
            Label(route.title, systemImage: route.systemImage)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button(navigation.favorites.contains(route) ? "取消收藏" : "加入收藏") {
                navigation.toggleFavorite(route)
            }
        }
        .accessibilityLabel("\(route.title)，\(route.section.title)")
    }

    private func expansionBinding(for section: AppSection) -> Binding<Bool> {
        Binding(
            get: { navigation.expandedSections.contains(section) },
            set: { expanded in
                if expanded {
                    navigation.expandedSections.insert(section)
                } else {
                    navigation.expandedSections.remove(section)
                }
            }
        )
    }

    @ViewBuilder private var routeContent: some View {
        if navigation.selection.isGoalM3Route {
            GoalM3RouteView(route: navigation.selection, navigation: navigation, service: service) { symbol in
                openWindow(value: StockDetailRoute(symbol: symbol))
            }
            .id(refreshToken)
        } else if navigation.selection.isGoalM4Route {
            GoalM4RouteView(route: navigation.selection, navigation: navigation, service: researchService) { symbol in
                openWindow(value: StockDetailRoute(symbol: symbol))
            }
            .id(refreshToken)
        } else if navigation.selection.isGoalM5Route {
            GoalM5RouteView(route: navigation.selection, navigation: navigation, service: goalM5Service)
                .id(refreshToken)
        } else {
            RoutePlaceholder(route: navigation.selection, symbol: navigation.selectedSymbol) { symbol in
                openWindow(value: StockDetailRoute(symbol: symbol))
            }
        }
    }

    private func restorePreferencesIfNeeded() {
        guard !restoredPreferences else { return }
        restoredPreferences = true
        navigation.favorites = decodeRoutes(storedFavorites)
        navigation.recents = Array(decodeRoutes(storedRecents).prefix(6))
        let order = decodeRoutes(storedRouteOrder)
        if !order.isEmpty {
            navigation.routeOrder = order + AppRoute.allCases.filter { !order.contains($0) }
        }
        let sections = Set(storedExpandedSections.split(separator: ",").compactMap { AppSection(rawValue: String($0)) })
        navigation.expandedSections = sections.union([navigation.selection.section])
        navigation.inspectorVisible = storedInspectorVisible
        columnVisibility = columnVisibilityRaw == "detailOnly" ? .detailOnly : .all
    }

    private func persistNavigation() {
        guard restoredPreferences else { return }
        storedFavorites = navigation.favorites.map(\.rawValue).joined(separator: ",")
        storedRecents = navigation.recents.map(\.rawValue).joined(separator: ",")
        storedRouteOrder = navigation.routeOrder.map(\.rawValue).joined(separator: ",")
        storedExpandedSections = navigation.expandedSections.map(\.rawValue).sorted().joined(separator: ",")
    }

    private func decodeRoutes(_ value: String) -> [AppRoute] {
        var seen = Set<AppRoute>()
        return value.split(separator: ",").compactMap { AppRoute(rawValue: String($0)) }.filter { seen.insert($0).inserted }
    }

    private func resetLayout() {
        navigation.resetNavigationLayout()
        densityRawValue = InterfaceDensity.comfortable.rawValue
        columnVisibility = .all
        persistNavigation()
        undoManager?.registerUndo(withTarget: navigation) { model in model.expandedSections = [.assets, model.selection.section] }
    }
}

private struct WorkspaceRouteBar: View {
    let workspace: AppWorkspace
    @Bindable var navigation: AppNavigationModel

    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: StockMonitorSpacing.xSmall) {
                Text(workspace.title).font(.headline).padding(.trailing, StockMonitorSpacing.small)
                ForEach(workspace.routes.filter { navigation.isAdministrator || !$0.requiresAdministrator }) { route in
                    workspaceButton(route)
                }
            }
            .padding(.horizontal, StockMonitorSpacing.medium)
            .padding(.vertical, StockMonitorSpacing.small)
        }
        .scrollIndicators(.hidden)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.bar)
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityIdentifier("workspace.\(workspace.rawValue).navigation")
    }

    @ViewBuilder private func workspaceButton(_ route: AppRoute) -> some View {
        if route == navigation.selection {
            Button(route.title) { navigation.navigate(to: route) }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
        } else {
            Button(route.title) { navigation.navigate(to: route) }
                .buttonStyle(.bordered)
                .controlSize(.small)
        }
    }
}

private struct RoutePlaceholder: View {
    let route: AppRoute
    let symbol: String?
    let openStock: (String) -> Void
    @State private var sampleSymbol = "AAPL"

    var body: some View {
        ContentUnavailableView {
            Label(route.title, systemImage: route.systemImage)
        } description: {
            Text("Goal 2 已建立此功能的稳定原生路由；业务内容将在对应功能 Goal 接入。")
        } actions: {
            if route.section == .company || route == .watchlist {
                Button("打开 AAPL 独立窗口") { openStock(symbol ?? sampleSymbol) }
            }
        }
        .navigationTitle(route.title)
        .accessibilityIdentifier("route.\(route.rawValue)")
    }
}

private struct InspectorView: View {
    let route: AppRoute
    let symbol: String?
    var body: some View {
        Form {
            Section("上下文") { LabeledContent("功能", value: route.title); LabeledContent("证券", value: symbol ?? "未选择") }
            Section("数据状态") { SemanticStatusLabel("等待业务数据", status: .unavailable) }
        }.formStyle(.grouped).padding(.vertical)
    }
}

public struct StockDetailWindow: View {
    public let route: StockDetailRoute
    public init(route: StockDetailRoute) {
        self.route = route
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(route.symbol).font(.largeTitle.bold())
            Text("公司研究入口").foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 170))], spacing: 12) {
                ForEach([AppRoute.news, .fundamentals, .valuation, .technical, .sec, .holdings, .compare, .ai]) { destination in
                    Link(destination: URL(string: "stockmonitor://\(destination.rawValue)?symbol=\(route.symbol)")!) {
                        Label(destination.title, systemImage: destination.systemImage)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(8)
                    }.buttonStyle(.bordered)
                }
            }
            Spacer()
        }.padding(28).navigationTitle("\(route.symbol) — 公司研究")
    }
}

public struct ResearchDetailWindow: View {
    public let route: ResearchDetailRoute
    public init(route: ResearchDetailRoute) {
        self.route = route
    }

    public var body: some View {
        ContentUnavailableView(route.route.title, systemImage: route.route.systemImage, description: Text(route.identifier))
            .navigationTitle("\(route.identifier) — \(route.route.title)")
    }
}

public struct StockMonitorSettingsView: View {
    @AppStorage("interface-density") private var densityRawValue = InterfaceDensity.comfortable.rawValue
    private let metrics: NetworkMetrics
    public init(metrics: NetworkMetrics) {
        self.metrics = metrics
    }

    public var body: some View {
        Form {
            Picker("数据密度", selection: $densityRawValue) { ForEach(InterfaceDensity.allCases) { Text($0.title).tag($0.rawValue) } }
            Text("服务端仍是唯一业务与数据真相。AI 与 IBKR 敏感正文默认不落盘。").foregroundStyle(.secondary)
            SupportDiagnosticsSection(metrics: metrics)
        }.formStyle(.grouped).padding().frame(width: 520)
    }
}
