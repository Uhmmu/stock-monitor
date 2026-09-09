import StockMonitorDesign
import SwiftUI

struct CommandSearchView: View {
    @Bindable var navigation: AppNavigationModel
    let marketService: MarketWorkflowService
    let workspaceService: GoalM5Service
    @State private var indexError: String?

    var body: some View {
        NavigationStack {
            List {
                if let indexError {
                    Section { Text(indexError).stockMonitorTypography(.metadata) }
                }
                ForEach(navigation.groupedSearchResults, id: \.0) { kind, results in
                    Section(kind.title) {
                        ForEach(results) { result in
                            Button { navigation.navigate(to: result) } label: {
                                HStack {
                                    Label(result.title, systemImage: result.route.systemImage)
                                    Spacer()
                                    Text(result.context).stockMonitorTypography(.metadata)
                                }
                                .contentShape(Rectangle())
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .navigationTitle("前往")
            .searchable(text: $navigation.searchQuery, prompt: "搜索功能、股票、会话或报告")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { navigation.searchPresented = false }
                }
            }
        }
        .task { await refreshIndex() }
    }

    @MainActor private func refreshIndex() async {
        async let reportsRequest = try? marketService.reports(limit: 40)
        async let conversationsRequest = try? workspaceService.conversations()
        async let dashboardRequest = try? marketService.dashboard()
        let (reports, conversations, dashboard) = await (reportsRequest, conversationsRequest, dashboardRequest)

        let securityResults: [NavigationSearchResult] = dashboard?.stocks.map { stock in
            NavigationSearchResult(
                kind: .security,
                title: stock.ticker,
                context: stock.companyName ?? "自选证券",
                route: .fundamentals,
                symbol: stock.ticker
            )
        } ?? []

        let reportResults: [NavigationSearchResult] = reports?.map { report in
            NavigationSearchResult(
                kind: .report,
                title: report.title,
                context: "\(report.ticker) · \(String(report.createdAt.prefix(10)))",
                route: .reports,
                symbol: report.ticker
            )
        } ?? []
        let conversationResults: [NavigationSearchResult] = conversations.map { value in
            let items = value.objectValue["items"]?.arrayValue ?? value.arrayValue
            return items.compactMap { item -> NavigationSearchResult? in
                guard let id = item.objectValue["id"]?.intValue else { return nil }
                return .init(
                    kind: .conversation,
                    title: item.objectValue["title"]?.stringValue ?? "会话 #\(id)",
                    context: "AI Chat · 会话 #\(id)",
                    route: .ai,
                    symbol: nil
                )
            }
        } ?? []
        navigation.replaceSearchIndex(
            securities: securityResults,
            conversations: conversationResults,
            reports: reportResults
        )
        let indexingFailed = securityResults.isEmpty && reportResults.isEmpty && conversationResults.isEmpty
            && reports == nil && conversations == nil && dashboard == nil
        if indexingFailed {
            indexError = "会话与报告暂时无法索引；功能和股票搜索仍可使用。"
        }
    }
}
