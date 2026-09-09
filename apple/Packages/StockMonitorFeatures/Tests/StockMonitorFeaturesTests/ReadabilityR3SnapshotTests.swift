#if os(macOS)
    import AppKit
    import StockMonitorDesign
    @testable import StockMonitorFeatures
    import SwiftUI
    import Testing

    @MainActor
    @Test func r3NavigationAndAdaptiveAnatomyVisualMatrix() throws {
        let configuredOutput = ProcessInfo.processInfo.environment["STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR"]
            .map(URL.init(fileURLWithPath:))
        let outputRoot = configuredOutput
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("stock-monitor-r3-snapshots", isDirectory: true)
        let baselineRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Tests/VisualBaselines/R3", isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)

        for scenario in R3Scenario.allCases {
            let name = "r3-\(scenario.rawValue).png"
            let output = outputRoot.appendingPathComponent(name)
            try render(
                scenario.view
                    .environment(\.interfaceDensity, scenario.density)
                    .environment(\.colorScheme, scenario.dark ? .dark : .light),
                size: scenario.size,
                appearance: scenario.dark ? .darkAqua : .aqua,
                to: output
            )
            let attributes = try FileManager.default.attributesOfItem(atPath: output.path)
            #expect((attributes[.size] as? NSNumber)?.intValue ?? 0 > 10000)
            if configuredOutput == nil {
                let baseline = baselineRoot.appendingPathComponent(name)
                #expect(FileManager.default.fileExists(atPath: baseline.path), "Missing R3 baseline \(name)")
                #expect(try pixelDifferenceRatio(baseline, output) <= 0.001, "Visual diff for \(name)")
            }
        }
    }

    @MainActor
    @Test func everyRouteHasOneStablePageAnatomy() {
        for route in AppRoute.allCases {
            let anatomy = RoutePageAnatomy.make(for: route, symbol: "AAPL")
            #expect(anatomy.navigationTitle == route.title)
            #expect(!anatomy.objectIdentity.isEmpty)
            #expect(!anatomy.primarySummary.isEmpty)
            #expect(!anatomy.primaryAction.isEmpty)
            #expect(!anatomy.provenance.isEmpty)
            #expect(anatomy.workspace == route.workspace)
        }
    }

    @MainActor
    private enum R3Scenario: String, CaseIterable {
        case beforeFlatSidebar = "before-flat-sidebar-standard-light-comfortable"
        case afterNarrow = "after-company-narrow-light-comfortable"
        case afterStandard = "after-company-standard-light-comfortable"
        case afterWideCompact = "after-portfolio-wide-dark-compact"
        case commandSearch = "after-command-search-standard-dark-comfortable"

        var dark: Bool {
            rawValue.contains("dark")
        }

        var density: InterfaceDensity {
            rawValue.contains("compact") ? .compact : .comfortable
        }

        var size: CGSize {
            switch self {
            case .afterNarrow: CGSize(width: 620, height: 720)
            case .afterWideCompact: CGSize(width: 1560, height: 900)
            default: CGSize(width: 1180, height: 760)
            }
        }

        @ViewBuilder var view: some View {
            switch self {
            case .beforeFlatSidebar: LegacyFlatNavigationFixture()
            case .afterNarrow:
                NavigationVisualAuditView(route: .fundamentals, layoutWidth: .narrow)
            case .afterStandard:
                NavigationVisualAuditView(route: .fundamentals, layoutWidth: .standard)
            case .afterWideCompact:
                NavigationVisualAuditView(route: .holdings, layoutWidth: .wide)
            case .commandSearch:
                NavigationVisualAuditView(route: .fundamentals, layoutWidth: .standard, showSearch: true)
            }
        }
    }

    private struct LegacyFlatNavigationFixture: View {
        var body: some View {
            HStack(spacing: 0) {
                List(AppRoute.allCases) { route in Label(route.title, systemImage: route.systemImage) }
                    .frame(width: 230)
                Divider()
                VStack(alignment: .leading, spacing: 16) {
                    Text("基本面").font(.title2.bold())
                    Text("基本面指标").font(.title2.bold())
                    Text("31 个入口平铺，页面标题与首屏层级各自实现。")
                    Spacer()
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
            .background(StockMonitorCanvas.background)
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
