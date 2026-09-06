import StockMonitorCore
import StockMonitorDesign
import StockMonitorFeatures
import SwiftUI

@main
struct StockMonitorMacApp: App {
    private let authSession: AuthSession
    private let marketService: MarketWorkflowService
    private let sessionModel: AppSessionModel
    @State private var navigation = AppNavigationModel()

    init() {
        do {
            let configuration = try APIConfiguration.load()
            let client = APIClient(configuration: configuration)
            authSession = AuthSession(client: client, tokenStore: Self.refreshTokenStore())
            marketService = MarketWorkflowService(authSession: authSession)
            sessionModel = AppSessionModel(session: authSession)
        } catch {
            fatalError("Invalid API configuration")
        }
    }

    private static func refreshTokenStore() -> KeychainRefreshTokenStore {
        #if DEBUG
            if let service = ProcessInfo.processInfo.environment["STOCK_MONITOR_TEST_KEYCHAIN_SERVICE"],
               service.hasPrefix("com.jiale.StockMonitor.ui-tests.")
            {
                return KeychainRefreshTokenStore(service: service)
            }
        #endif
        return KeychainRefreshTokenStore()
    }

    var body: some Scene {
        WindowGroup("Stock Monitor") {
            SessionGateView(model: sessionModel) { identity in
                AppShellView(navigation: navigation, service: marketService)
                    .onAppear { navigation.isAdministrator = identity.role == "admin" }
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

        Settings { StockMonitorSettingsView() }
    }
}
