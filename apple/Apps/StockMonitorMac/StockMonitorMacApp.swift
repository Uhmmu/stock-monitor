import StockMonitorCore
import StockMonitorDesign
import StockMonitorFeatures
import SwiftUI

@main
struct StockMonitorMacApp: App {
    private let apiClient: APIClient
    private let authSession: AuthSession
    private let marketService: MarketWorkflowService
    private let sessionModel: AppSessionModel
    private let metrics: NetworkMetrics
    @State private var navigation = AppNavigationModel()

    init() {
        do {
            let configuration = try APIConfiguration.load()
            let metrics = NetworkMetrics()
            let client = APIClient(configuration: configuration, metrics: metrics)
            apiClient = client
            self.metrics = metrics
            authSession = AuthSession(client: client, tokenStore: Self.refreshTokenStore())
            marketService = MarketWorkflowService(authSession: authSession)
            sessionModel = AppSessionModel(session: authSession)
        } catch {
            fatalError("Invalid API configuration")
        }
    }

    private static func refreshTokenStore() -> KeychainRefreshTokenStore {
        // swiftlint:disable opening_brace
        #if DEBUG
            if let service = ProcessInfo.processInfo.environment["STOCK_MONITOR_TEST_KEYCHAIN_SERVICE"],
               service.hasPrefix("com.jiale.StockMonitor.ui-tests.")
            {
                return KeychainRefreshTokenStore(service: service)
            }
        #endif
        // swiftlint:enable opening_brace
        return KeychainRefreshTokenStore()
    }

    var body: some Scene {
        WindowGroup("Stock Monitor") {
            if let auditRoute = Self.visualAuditRoute {
                RouteVisualAuditView(route: auditRoute, state: Self.visualAuditState)
                    .environment(\.interfaceDensity, Self.visualAuditDensity)
                    .preferredColorScheme(Self.visualAuditColorScheme)
                    .frame(minWidth: Self.visualAuditWidth.size.width, minHeight: Self.visualAuditWidth.size.height)
            } else {
                ClientCompatibilityGateView(client: apiClient, currentVersion: Self.appVersion) {
                    SessionGateView(model: sessionModel) { identity in
                        AppShellView(navigation: navigation, service: marketService)
                            .onAppear { navigation.isAdministrator = identity.role == "admin" }
                    }
                }
            }
        }
        .defaultSize(width: 1180, height: 760)
        .commands {
            CommandMenu("导航") {
                Button("总览") { navigation.navigate(to: .overview) }.keyboardShortcut("1", modifiers: .command)
                Button("自选股") { navigation.navigate(to: .watchlist) }.keyboardShortcut("2", modifiers: .command)
                Button("持仓") { navigation.navigate(to: .holdings) }.keyboardShortcut("3", modifiers: .command)
                Divider()
                Button("显示检查器") { navigation.inspectorVisible.toggle() }.keyboardShortcut("i", modifiers: [.command, .option])
            }
        }

        WindowGroup("证券", for: StockDetailRoute.self) { $route in
            if let route {
                StockDetailWindow(route: route)
            }
        }
        .defaultSize(width: 820, height: 620)

        WindowGroup("研究", for: ResearchDetailRoute.self) { $route in
            if let route {
                ResearchDetailWindow(route: route)
            }
        }
        .defaultSize(width: 900, height: 680)

        Window("Design Lab", id: "design-lab") { DesignLabView() }
            .defaultSize(width: 980, height: 720)

        Settings { StockMonitorSettingsView(metrics: metrics) }
    }

    private static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"
    }

    private static var visualAuditRoute: AppRoute? {
        guard ProcessInfo.processInfo.arguments.contains("--visual-audit"),
              let value = ProcessInfo.processInfo.environment["STOCK_MONITOR_VISUAL_AUDIT_ROUTE"]
        else { return nil }
        return AppRoute(rawValue: value)
    }

    private static var visualAuditState: VisualAuditState {
        VisualAuditState(rawValue: ProcessInfo.processInfo.environment["STOCK_MONITOR_VISUAL_AUDIT_STATE"] ?? "normal") ?? .normal
    }

    private static var visualAuditDensity: InterfaceDensity {
        let value = ProcessInfo.processInfo.environment["STOCK_MONITOR_VISUAL_AUDIT_DENSITY"] ?? "comfortable"
        return InterfaceDensity(rawValue: value) ?? .comfortable
    }

    private static var visualAuditWidth: VisualAuditWidth {
        VisualAuditWidth(rawValue: ProcessInfo.processInfo.environment["STOCK_MONITOR_VISUAL_AUDIT_WIDTH"] ?? "standard") ?? .standard
    }

    private static var visualAuditColorScheme: ColorScheme? {
        switch ProcessInfo.processInfo.environment["STOCK_MONITOR_VISUAL_AUDIT_APPEARANCE"] {
        case "light": .light
        case "dark": .dark
        default: nil
        }
    }
}
