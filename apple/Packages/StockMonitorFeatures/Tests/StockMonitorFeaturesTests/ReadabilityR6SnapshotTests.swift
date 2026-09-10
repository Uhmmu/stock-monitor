#if os(macOS)
    import AppKit
    import StockMonitorDesign
    @testable import StockMonitorFeatures
    import SwiftUI
    import Testing

    /// R6.2 视觉矩阵：31 路由 dark 基线 + 轮换的宽度和状态组合，
    /// 加上 R6.0 图表/表格 golden 与 before/after 对照。
    @MainActor
    @Test(.disabled(if: ProcessInfo.processInfo.environment["CI"] != nil)) func r6PolishAndAcceptanceVisualMatrix() throws {
        let configuredOutput = ProcessInfo.processInfo.environment["STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR"]
            .map(URL.init(fileURLWithPath:))
        let outputRoot = configuredOutput
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("stock-monitor-r6-snapshots", isDirectory: true)
        let baselineRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Tests/VisualBaselines/R6", isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)

        var scenarioCount = 0
        for scenario in R6GoldenScenario.allCases {
            let name = "r6-\(scenario.rawValue).png"
            try renderAndCompare(
                scenario.view
                    .environment(\.interfaceDensity, scenario.density)
                    .environment(\.stockMonitorLayoutWidth, scenario.layoutWidth)
                    .environment(\.colorScheme, scenario.dark ? .dark : .light),
                size: scenario.size,
                appearance: scenario.appearance,
                name: name,
                outputRoot: outputRoot,
                baselineRoot: baselineRoot,
                configuredOutput: configuredOutput
            )
            scenarioCount += 1
        }
        #expect(scenarioCount >= 7)

        // 路由矩阵：每路由 dark-standard-normal；再按序号轮换补 empty/stale/error × 窄/宽。
        for (index, route) in AppRoute.allCases.enumerated() {
            let darkName = "r6-route-\(route.rawValue)-standard-dark-comfortable-normal.png"
            try renderAndCompare(
                RouteVisualAuditView(route: route, state: .normal)
                    .environment(\.interfaceDensity, .comfortable)
                    .environment(\.stockMonitorLayoutWidth, .standard)
                    .environment(\.colorScheme, .dark),
                size: VisualAuditWidth.standard.size,
                appearance: .darkAqua,
                name: darkName,
                outputRoot: outputRoot,
                baselineRoot: baselineRoot,
                configuredOutput: configuredOutput
            )
            scenarioCount += 1

            let rotation = index % 3
            let rotated: (VisualAuditState, VisualAuditWidth, ColorScheme) = switch rotation {
            case 0: (.empty, .narrow, .light)
            case 1: (.stale, .wide, .dark)
            default: (.error, .standard, .light)
            }
            let rotatedName = "r6-route-\(route.rawValue)-\(rotated.1.rawValue)-\(rotated.2 == .dark ? "dark" : "light")-comfortable-\(rotated.0.rawValue).png"
            try renderAndCompare(
                RouteVisualAuditView(route: route, state: rotated.0)
                    .environment(\.interfaceDensity, .comfortable)
                    .environment(\.stockMonitorLayoutWidth, StockMonitorLayoutWidth(rawValue: rotated.1.rawValue) ?? .standard)
                    .environment(\.colorScheme, rotated.2),
                size: rotated.1.size,
                appearance: rotated.2 == .dark ? .darkAqua : .aqua,
                name: rotatedName,
                outputRoot: outputRoot,
                baselineRoot: baselineRoot,
                configuredOutput: configuredOutput
            )
            scenarioCount += 1
        }
        // 31 路由 × 2 + goldens。
        #expect(scenarioCount == AppRoute.allCases.count * 2 + R6GoldenScenario.allCases.count)
    }

    @MainActor
    private enum R6GoldenScenario: String, CaseIterable {
        case chartBefore = "chart-before-standard-light-comfortable"
        case chartsAfter = "charts-after-standard-light-comfortable"
        case chartsAfterDark = "charts-after-standard-dark-comfortable"
        case chartsNarrow = "charts-after-narrow-light-comfortable"
        case tableAfter = "table-after-standard-light-comfortable"
        case tableAfterNarrow = "table-after-narrow-light-comfortable"
        case tableAfterCompact = "table-after-standard-light-compact"

        var dark: Bool {
            rawValue.contains("dark")
        }

        var density: InterfaceDensity {
            rawValue.contains("compact") ? .compact : .comfortable
        }

        var layoutWidth: StockMonitorLayoutWidth {
            rawValue.contains("narrow") ? .narrow : .standard
        }

        var appearance: NSAppearance.Name {
            dark ? .darkAqua : .aqua
        }

        var size: CGSize {
            layoutWidth == .narrow ? CGSize(width: 620, height: 780) : CGSize(width: 1180, height: 900)
        }

        @ViewBuilder var view: some View {
            switch self {
            case .chartBefore: R6ChartBeforeFixture()
            case .chartsAfter, .chartsAfterDark, .chartsNarrow: R6ChartsFixture()
            case .tableAfter, .tableAfterNarrow, .tableAfterCompact: R6TablesFixture()
            }
        }
    }

    @MainActor
    private func renderAndCompare(
        _ view: some View,
        size: CGSize,
        appearance: NSAppearance.Name,
        name: String,
        outputRoot: URL,
        baselineRoot: URL,
        configuredOutput: URL?
    ) throws {
        let output = outputRoot.appendingPathComponent(name)
        try render(view, size: size, appearance: appearance, to: output)
        let attributes = try FileManager.default.attributesOfItem(atPath: output.path)
        #expect((attributes[.size] as? NSNumber)?.intValue ?? 0 > 10000, "\(name) 渲染过小")
        if configuredOutput == nil {
            let baseline = baselineRoot.appendingPathComponent(name)
            #expect(FileManager.default.fileExists(atPath: baseline.path), "Missing R6 baseline \(name)")
            #expect(try pixelDifferenceRatio(baseline, output) <= 0.001, "Visual diff for \(name)")
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
