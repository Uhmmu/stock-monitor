#if os(macOS)
    import AppKit
    import StockMonitorDesign
    @testable import StockMonitorFeatures
    import SwiftUI
    import Testing

    @MainActor
    @Test func readabilitySnapshotHarnessRendersEveryRouteAndGoldenState() throws {
        let configuredOutput = ProcessInfo.processInfo.environment["STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR"]
            .map(URL.init(fileURLWithPath:))
        let outputRoot = configuredOutput
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("stock-monitor-r1-snapshots", isDirectory: true)
        let baselineRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Tests/VisualBaselines/R1", isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)

        var scenarios = AppRoute.allCases.map { SnapshotScenario(route: $0) }
        scenarios += [
            .init(route: .overview, width: .narrow),
            .init(route: .financials, state: .partial, density: .compact),
            .init(route: .news, state: .stale, width: .wide, colorScheme: .dark),
            .init(route: .ibkr, state: .error, colorScheme: .dark, density: .compact),
            .init(route: .watchlist, state: .empty, width: .narrow, colorScheme: .dark),
            .init(route: .reports, state: .loading, width: .wide, density: .compact),
            .init(route: .administration, state: .permissionDenied),
        ]

        var renderedNames = Set<String>()
        for (index, scenario) in scenarios.enumerated() {
            let name = index < AppRoute.allCases.count
                ? "route-\(scenario.route.rawValue)-standard-light-comfortable-normal.png"
                : scenario.goldenName
            let url = outputRoot.appendingPathComponent(name)
            try render(
                RouteVisualAuditView(route: scenario.route, state: scenario.state)
                    .environment(\.interfaceDensity, scenario.density)
                    .environment(\.colorScheme, scenario.colorScheme),
                size: scenario.width.size,
                appearance: scenario.colorScheme == .dark ? .darkAqua : .aqua,
                to: url
            )
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            #expect((attributes[FileAttributeKey.size] as? NSNumber)?.intValue ?? 0 > 10000)
            if configuredOutput == nil {
                let baselineURL = baselineRoot.appendingPathComponent(name)
                #expect(
                    FileManager.default.fileExists(atPath: baselineURL.path),
                    "Missing baseline \(name); record with STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR"
                )
                let difference = try pixelDifferenceRatio(baselineURL, url)
                #expect(difference <= 0.001, "Visual difference \(difference) exceeded 0.1% for \(name)")
            }
            renderedNames.insert(name)
        }
        #expect(renderedNames.count == 38)
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

    private struct SnapshotScenario {
        let route: AppRoute
        var state = VisualAuditState.normal
        var width = VisualAuditWidth.standard
        var colorScheme = ColorScheme.light
        var density = InterfaceDensity.comfortable

        var goldenName: String {
            let appearance = colorScheme == .dark ? "dark" : "light"
            return "golden-\(route.rawValue)-\(width.rawValue)-\(appearance)-\(density.rawValue)-\(state.rawValue).png"
        }
    }

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
