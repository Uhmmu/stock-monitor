import StockMonitorDesign
import SwiftUI
#if os(macOS)
    import AppKit
#endif

public struct AppShellView: View {
    @Bindable private var navigation: AppNavigationModel
    private let service: MarketWorkflowService
    @AppStorage("interface-density") private var densityRawValue = InterfaceDensity.comfortable.rawValue
    @SceneStorage("selected-route") private var restoredRoute = AppRoute.overview.rawValue
    @Environment(\.openWindow) private var openWindow
    @Environment(\.undoManager) private var undoManager
    @State private var refreshToken = UUID()

    public init(navigation: AppNavigationModel, service: MarketWorkflowService) {
        self.navigation = navigation
        self.service = service
    }

    public var body: some View {
        NavigationSplitView {
            List(selection: $navigation.selection) {
                ForEach(AppSection.allCases) { section in
                    let routes = AppRoute.visible(isAdministrator: navigation.isAdministrator).filter { $0.section == section }
                    if !routes.isEmpty {
                        Section(section.title) {
                            ForEach(routes) { route in Label(route.title, systemImage: route.systemImage).tag(route) }
                        }
                    }
                }
            }
            .navigationTitle("Stock Monitor")
            .navigationSplitViewColumnWidth(min: 190, ideal: 225, max: 280)
        } detail: {
            routeContent
                .id(navigation.selection)
                .inspector(isPresented: $navigation.inspectorVisible) {
                    InspectorView(route: navigation.selection, symbol: navigation.selectedSymbol)
                        .inspectorColumnWidth(min: 240, ideal: 280, max: 360)
                }
                .toolbar(id: "com.jiale.StockMonitor.main-toolbar") {
                    ToolbarItem(id: "com.jiale.StockMonitor.search", placement: .primaryAction, showsByDefault: true) {
                        Button("全局搜索", systemImage: "magnifyingglass") { navigation.searchPresented = true }
                            .keyboardShortcut("k", modifiers: .command)
                    }
                    ToolbarItem(id: "com.jiale.StockMonitor.inspector", placement: .primaryAction, showsByDefault: true) {
                        Button("检查器", systemImage: "sidebar.trailing") { navigation.inspectorVisible.toggle() }
                    }
                    ToolbarItem(id: "com.jiale.StockMonitor.refresh", placement: .automatic, showsByDefault: true) {
                        Button("刷新", systemImage: "arrow.clockwise") { refreshToken = UUID() }
                            .keyboardShortcut("r", modifiers: .command)
                    }
                }
        }
        .environment(\.interfaceDensity, InterfaceDensity(rawValue: densityRawValue) ?? .comfortable)
        .onAppear {
            if let route = AppRoute(rawValue: restoredRoute) {
                navigation.navigate(to: route)
            }
        }
        .onChange(of: navigation.selection) { _, route in restoredRoute = route.rawValue }
        .onOpenURL { _ = navigation.handle(url: $0) }
        .contextMenu {
            Button("在新研究窗口打开") { openWindow(value: ResearchDetailRoute(route: navigation.selection, identifier: navigation.selectedSymbol ?? navigation.selection.rawValue)) }
            Divider()
            Button("复制深链") {
                #if os(macOS)
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString("stockmonitor://\(navigation.selection.rawValue)", forType: .string)
                #endif
            }
        }
        .sheet(isPresented: $navigation.searchPresented) { CommandSearchView(navigation: navigation).frame(minWidth: 520, minHeight: 420) }
    }

    @ViewBuilder private var routeContent: some View {
        if navigation.selection.isGoalM3Route {
            GoalM3RouteView(route: navigation.selection, navigation: navigation, service: service) { symbol in
                openWindow(value: StockDetailRoute(symbol: symbol))
            }
            .id(refreshToken)
        } else {
            RoutePlaceholder(route: navigation.selection, symbol: navigation.selectedSymbol) { symbol in
                openWindow(value: StockDetailRoute(symbol: symbol))
            }
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

private struct CommandSearchView: View {
    @Bindable var navigation: AppNavigationModel
    var body: some View {
        NavigationStack {
            List(navigation.searchResults) { route in
                Button {
                    navigation.navigate(to: route)
                } label: {
                    Label(route.title, systemImage: route.systemImage)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
            }
            .navigationTitle("前往")
            .searchable(text: $navigation.searchQuery, prompt: "搜索功能")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { navigation.searchPresented = false } } }
        }
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
        }.padding(28).navigationTitle(route.symbol)
    }
}

public struct ResearchDetailWindow: View {
    public let route: ResearchDetailRoute
    public init(route: ResearchDetailRoute) {
        self.route = route
    }

    public var body: some View {
        ContentUnavailableView(route.route.title, systemImage: route.route.systemImage, description: Text(route.identifier))
            .navigationTitle(route.route.title)
    }
}

public struct StockMonitorSettingsView: View {
    @AppStorage("interface-density") private var densityRawValue = InterfaceDensity.comfortable.rawValue
    public init() {}
    public var body: some View {
        Form {
            Picker("数据密度", selection: $densityRawValue) { ForEach(InterfaceDensity.allCases) { Text($0.title).tag($0.rawValue) } }
            Text("服务端仍是唯一业务与数据真相。AI 与 IBKR 敏感正文默认不落盘。").foregroundStyle(.secondary)
        }.formStyle(.grouped).padding().frame(width: 520)
    }
}
