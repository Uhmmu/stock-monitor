#if os(macOS)
    import AppKit
    import StockMonitorDesign
    @testable import StockMonitorFeatures
    import SwiftUI
    import Testing

    /// R2 Before/After 视觉证据：同一 fixture、同一窗口尺寸与外观，
    /// 对比 raw JSON 树（Before）与语义化页面（After）。基线存于 Tests/VisualBaselines/R2。
    @MainActor
    @Test func r2SemanticWorkspacesBeatRawJSONRendering() throws {
        let configuredOutput = ProcessInfo.processInfo.environment["STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR"]
            .map(URL.init(fileURLWithPath:))
        let outputRoot = configuredOutput
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("stock-monitor-r2-snapshots", isDirectory: true)
        let baselineRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Tests/VisualBaselines/R2", isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)

        for scenario in SnapshotScenario.allCases {
            let name = "r2-\(scenario.rawValue).png"
            let url = outputRoot.appendingPathComponent(name)
            try render(
                scenario.view
                    .environment(\.interfaceDensity, scenario.density)
                    .environment(\.colorScheme, scenario.appearance == .dark ? ColorScheme.dark : ColorScheme.light),
                size: scenario.size,
                appearance: scenario.appearance == .dark ? NSAppearance.Name.darkAqua : NSAppearance.Name.aqua,
                to: url
            )
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            #expect((attributes[FileAttributeKey.size] as? NSNumber)?.intValue ?? 0 > 10000)
            if configuredOutput == nil {
                let baselineURL = baselineRoot.appendingPathComponent(name)
                #expect(
                    FileManager.default.fileExists(atPath: baselineURL.path),
                    "Missing R2 baseline \(name); record with STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR"
                )
                #expect(try pixelDifferenceRatio(baselineURL, url) <= 0.001, "Visual diff for \(name)")
            }
        }
    }

    private enum ScenarioAppearance: String { case light, dark }

    private enum SnapshotScenario: String, CaseIterable {
        case beforePortfolioLight = "before-portfolio-light-comfortable"
        case afterPortfolioLight = "after-portfolio-light-comfortable"
        case afterPortfolioDark = "after-portfolio-dark-compact"
        case beforePaperLight = "before-paper-light-comfortable"
        case afterPaperLight = "after-paper-light-comfortable"
        case beforeIbkrLight = "before-ibkr-light-comfortable"
        case afterIbkrLight = "after-ibkr-light-comfortable"
        case afterDiscoveryDark = "after-discovery-dark-comfortable"

        var appearance: ScenarioAppearance {
            rawValue.contains("dark") ? .dark : .light
        }

        var density: InterfaceDensity {
            rawValue.contains("compact") ? .compact : .comfortable
        }

        var size: CGSize {
            CGSize(width: 1180, height: 820)
        }

        @ViewBuilder var view: some View {
            switch self {
            case .beforePortfolioLight:
                LegacyWorkspaceShell(title: "组合摘要", payload: Fixtures.portfolio)
            case .afterPortfolioLight, .afterPortfolioDark:
                SemanticWorkspaceContentView(
                    title: "组合摘要",
                    summary: "多币种估值、健康、画像与异步分析全部服务端计算。",
                    presentation: SemanticPresentationBuilder.presentation(
                        title: "组合摘要",
                        spec: GoalM5PresentationCatalog.spec(semanticKey: "portfolio.summary"),
                        payload: Fixtures.portfolio
                    )
                )
            case .beforePaperLight:
                LegacyWorkspaceShell(title: "订单", payload: Fixtures.paperOrders)
            case .afterPaperLight:
                SemanticWorkspaceContentView(
                    title: "订单",
                    summary: "订单、撮合、账本、运行和对账全部回读服务端模拟器。",
                    presentation: SemanticPresentationBuilder.presentation(
                        title: "订单",
                        spec: GoalM5PresentationCatalog.spec(semanticKey: "paper.orders"),
                        payload: Fixtures.paperOrders
                    )
                )
            case .beforeIbkrLight:
                LegacyWorkspaceShell(title: "状态", payload: Fixtures.ibkrStatus)
            case .afterIbkrLight:
                SemanticWorkspaceContentView(
                    title: "状态",
                    summary: "只呈现服务端同步的账户、绩效、现金流与数据健康。",
                    presentation: SemanticPresentationBuilder.presentation(
                        title: "状态",
                        spec: GoalM5PresentationCatalog.spec(semanticKey: "ibkr.status"),
                        payload: Fixtures.ibkrStatus
                    )
                )
            case .afterDiscoveryDark:
                SemanticWorkspaceContentView(
                    title: "最新结果",
                    summary: "渐进结果、历史、设置和精确用量均以服务端记录为准。",
                    presentation: SemanticPresentationBuilder.presentation(
                        title: "最新结果",
                        spec: GoalM5PresentationCatalog.spec(semanticKey: "discovery.latest"),
                        payload: Fixtures.discoveryLatest
                    )
                )
            }
        }
    }

    /// Before 视图：R2 之前主路径的渲染方式（原始 JSON 树）。
    private struct LegacyWorkspaceShell: View {
        let title: String
        let payload: JSONValue

        var body: some View {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    Text(title).font(.title2.bold())
                    RawJSONDiagnosticsView(value: payload)
                }
                .padding(22)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(StockMonitorCanvas.background)
        }
    }

    /// fixture 为编译期常量；解码失败会直接让快照测试失败。
    private func decodeFixture(_ data: Data) -> JSONValue {
        // swiftlint:disable:next force_try
        try! JSONDecoder().decode(JSONValue.self, from: data)
    }

    private enum Fixtures {
        static let portfolio: JSONValue = decodeFixture(Data(
            #"""
            {"base_currency":"USD","position_count":3,"priced_count":2,
             "total_market_value":289241.02,"total_cost":198400.00,
             "total_unrealized_pnl":90841.02,"total_unrealized_pnl_percent":0.458,
             "cash_balance":12034.55,"month_return":0.0312,"data_completeness":0.91,
             "latest_sync_at":"2026-09-08T02:31:00Z","account_data_source":"ibkr_flex",
             "has_unconverted_positions":true,
             "positions":[
               {"symbol":"NVDA","currency":"USD","total_quantity":120.5,"current_price":234.12,
                "base_currency_market_value":28211.46,"base_currency_unrealized_pnl":6120.10,"portfolio_weight":0.45},
               {"symbol":"MSFT","currency":"USD","total_quantity":54,"current_price":412.20,
                "base_currency_market_value":22258.80,"base_currency_unrealized_pnl":3980.44,"portfolio_weight":0.36},
               {"symbol":"1578.T","currency":"JPY","total_quantity":20,"current_price":5100.0,
                "base_currency_market_value":680.20,"base_currency_unrealized_pnl":45.30,"portfolio_weight":0.01}
             ]}
            """#.utf8
        ))

        static let paperOrders: JSONValue = decodeFixture(Data(
            #"""
            {"items":[
               {"id":7,"instrument_symbol":"BTCUSDT","side":"buy","status":"filled",
                "intended_quantity":"0.124","avg_fill_price":"80360.10","fee":"4.98"},
               {"id":6,"instrument_symbol":"ETHUSDT","side":"sell","status":"filled",
                "intended_quantity":"1.500","avg_fill_price":"2912.40","fee":"2.19"},
               {"id":5,"instrument_symbol":"BTCUSDT","side":"buy","status":"pending",
                "intended_quantity":"0.080","avg_fill_price":null,"fee":null}
             ],"total":3,"limit":50,"offset":0}
            """#.utf8
        ))

        static let ibkrStatus: JSONValue = decodeFixture(Data(
            #"""
            {"configured":true,"read_only":true,
             "latest_sync":{"id":3,"account_id_masked":"***1234","status":"completed","stage":"done",
                             "trigger_type":"manual","warning_count":0,"completed_at":"2026-09-07T21:05:12Z",
                             "section_counts":{"Trade":[{"Blotter":120}]}},
             "current_or_last_attempt":{"id":3,"status":"completed","stage":"done"}}
            """#.utf8
        ))

        static let discoveryLatest: JSONValue = decodeFixture(Data(
            #"""
            {"current_run":{"id":14,"status":"completed","discovery_mode":"pi_agent","progress":100,
                             "requested_at":"2026-08-21T10:00:00Z","completed_at":"2026-08-21T10:07:01Z"},
             "result":{"counts":{"raw":13,"accepted":8},
                       "limitations":["候选由模型生成，需自行核实","外部验证仅覆盖行情与财报"],
                       "usage":{"total_cost_usd":0.34686,"finance_search_calls":6}},
             "using_previous_result":false,"discovery_mode":"pi_agent",
             "monthly_spend_usd":3.82,"monthly_budget_usd":10.0,"next_scheduled_at":"2026-08-24T01:00:00Z"}
            """#.utf8
        ))
    }

    @MainActor
    private func render(_ view: some View, size: CGSize, appearance: NSAppearance.Name, to url: URL) throws {
        let hosting = NSHostingView(rootView: view.frame(width: size.width, height: size.height))
        hosting.frame = CGRect(origin: .zero, size: size)
        hosting.appearance = NSAppearance(named: appearance)
        let window = NSWindow(contentRect: hosting.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = hosting.appearance
        window.contentView = hosting
        window.layoutIfNeeded()
        hosting.layoutSubtreeIfNeeded()
        hosting.displayIfNeeded()
        guard let representation = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) else {
            throw SnapshotError.renderFailed
        }
        hosting.cacheDisplay(in: hosting.bounds, to: representation)
        guard let data = representation.representation(using: .png, properties: [:]) else {
            throw SnapshotError.encodingFailed
        }
        try data.write(to: url, options: .atomic)
        window.contentView = nil
    }

    private enum SnapshotError: Error { case renderFailed, encodingFailed }

    private func pixelDifferenceRatio(_ baselineURL: URL, _ renderedURL: URL) throws -> Double {
        guard let baseline = try NSBitmapImageRep(data: Data(contentsOf: baselineURL)),
              let rendered = try NSBitmapImageRep(data: Data(contentsOf: renderedURL)),
              baseline.pixelsWide == rendered.pixelsWide,
              baseline.pixelsHigh == rendered.pixelsHigh,
              let baselinePixels = baseline.cgImage?.dataProvider?.data,
              let renderedPixels = rendered.cgImage?.dataProvider?.data
        else { return 1 }
        return baselinePixels == renderedPixels ? 0 : 1
    }
#endif
