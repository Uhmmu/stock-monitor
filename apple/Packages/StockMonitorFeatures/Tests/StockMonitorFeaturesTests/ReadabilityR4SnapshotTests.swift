#if os(macOS)
    import AppKit
    import StockMonitorDesign
    @testable import StockMonitorFeatures
    import SwiftUI
    import Testing

    /// R4 高频市场与研究页面的确定性像素矩阵：Before（R4 前布局）与 After（R4 组件布局）。
    @MainActor
    @Test(.disabled(if: ProcessInfo.processInfo.environment["CI"] != nil)) func r4HighFrequencyPagesVisualMatrix() throws {
        let configuredOutput = ProcessInfo.processInfo.environment["STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR"]
            .map(URL.init(fileURLWithPath:))
        let outputRoot = configuredOutput
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("stock-monitor-r4-snapshots", isDirectory: true)
        let baselineRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Tests/VisualBaselines/R4", isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)

        for scenario in R4Scenario.allCases {
            let name = "r4-\(scenario.rawValue).png"
            let output = outputRoot.appendingPathComponent(name)
            try render(
                scenario.view
                    .environment(\.interfaceDensity, scenario.density)
                    .environment(\.stockMonitorLayoutWidth, scenario.layoutWidth)
                    .environment(\.colorScheme, scenario.dark ? .dark : .light),
                size: scenario.size,
                appearance: scenario.dark ? .darkAqua : .aqua,
                to: output
            )
            let attributes = try FileManager.default.attributesOfItem(atPath: output.path)
            #expect((attributes[.size] as? NSNumber)?.intValue ?? 0 > 10000)
            if configuredOutput == nil {
                let baseline = baselineRoot.appendingPathComponent(name)
                #expect(FileManager.default.fileExists(atPath: baseline.path), "Missing R4 baseline \(name)")
                #expect(try pixelDifferenceRatio(baseline, output) <= 0.001, "Visual diff for \(name)")
            }
        }
    }

    @MainActor
    private enum R4Scenario: String, CaseIterable {
        case beforeOverview = "before-overview-standard-light-comfortable"
        case afterOverview = "after-overview-standard-light-comfortable"
        case afterWatchlist = "after-watchlist-standard-light-comfortable"
        case afterAlerts = "after-alerts-standard-light-comfortable"
        case afterNewsDark = "after-news-standard-dark-comfortable"
        case afterOverviewDarkCompact = "after-overview-standard-dark-compact"
        case afterCalendar = "after-calendar-standard-light-comfortable"
        case afterReports = "after-reports-standard-light-comfortable"
        case beforeCompany = "before-company-standard-light-comfortable"
        case afterCompany = "after-company-standard-light-comfortable"
        case afterCompanyNarrow = "after-company-narrow-light-comfortable"

        var dark: Bool {
            rawValue.contains("dark")
        }

        var density: InterfaceDensity {
            rawValue.contains("compact") ? .compact : .comfortable
        }

        var layoutWidth: StockMonitorLayoutWidth {
            rawValue.contains("narrow") ? .narrow : .standard
        }

        var size: CGSize {
            layoutWidth == .narrow ? CGSize(width: 620, height: 720) : CGSize(width: 1180, height: 760)
        }

        @ViewBuilder var view: some View {
            switch self {
            case .beforeOverview: R4BeforeOverviewFixture()
            case .afterOverview: R4AfterOverviewFixture()
            case .afterWatchlist: R4AfterWatchlistFixture()
            case .afterAlerts: R4AfterAlertsFixture()
            case .afterNewsDark: R4AfterNewsFixture()
            case .afterOverviewDarkCompact: R4AfterOverviewFixture()
            case .afterCalendar: R4AfterCalendarFixture()
            case .afterReports: R4AfterReportsFixture()
            case .beforeCompany: R4BeforeCompanyFixture()
            case .afterCompany: R4AfterCompanyFixture()
            case .afterCompanyNarrow: R4AfterCompanyFixture()
            }
        }
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
