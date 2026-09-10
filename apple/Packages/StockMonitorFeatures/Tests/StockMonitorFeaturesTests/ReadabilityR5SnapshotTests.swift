#if os(macOS)
    import AppKit
    import StockMonitorDesign
    @testable import StockMonitorFeatures
    import SwiftUI
    import Testing

    @MainActor
    @Test(.disabled(if: ProcessInfo.processInfo.environment["CI"] != nil)) func r5ComplexWorkspacesVisualMatrix() throws {
        let configuredOutput = ProcessInfo.processInfo.environment["STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR"]
            .map(URL.init(fileURLWithPath:))
        let outputRoot = configuredOutput
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("stock-monitor-r5-snapshots", isDirectory: true)
        let baselineRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Tests/VisualBaselines/R5", isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)

        for scenario in R5Scenario.allCases {
            let name = "r5-\(scenario.rawValue).png"
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
                #expect(FileManager.default.fileExists(atPath: baseline.path), "Missing R5 baseline \(name)")
                #expect(try pixelDifferenceRatio(baseline, output) <= 0.001, "Visual diff for \(name)")
            }
        }
    }

    @MainActor
    private enum R5Scenario: String, CaseIterable {
        case beforeGeneric = "before-generic-workspace-standard-light-comfortable"
        case ai = "after-ai-standard-light-comfortable"
        case discoveryDark = "after-discovery-standard-dark-comfortable"
        case portfolio = "after-portfolio-standard-light-comfortable"
        case journal = "after-journal-standard-light-comfortable"
        case ibkr = "after-ibkr-standard-light-comfortable"
        case cryptoNarrow = "after-crypto-narrow-light-comfortable"
        case quant = "after-quant-standard-light-compact"
        case paper = "after-paper-standard-dark-comfortable"
        case settings = "after-settings-standard-light-comfortable"
        case administration = "after-administration-standard-light-comfortable"

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
            let catalog = GoalM5Catalog()
            switch self {
            case .beforeGeneric: R5BeforeGenericWorkspaceFixture()
            case .ai: R5AIConversationFixture()
            case .discoveryDark:
                R5WorkspaceFixture(
                    descriptor: catalog.discovery, semantic: "discovery.latest", payload: R5FixtureData.discovery
                )
            case .portfolio:
                R5WorkspaceFixture(
                    descriptor: catalog.portfolio, semantic: "portfolio.summary", payload: R5FixtureData.portfolio
                )
            case .journal:
                R5WorkspaceFixture(descriptor: catalog.journal, semantic: "journal.logs", payload: R5FixtureData.journal)
            case .ibkr:
                R5WorkspaceFixture(descriptor: catalog.ibkr, semantic: "ibkr.overview", payload: R5FixtureData.ibkr)
            case .cryptoNarrow:
                R5WorkspaceFixture(
                    descriptor: catalog.cryptoResearch, semantic: "crypto.latest", payload: R5FixtureData.crypto
                )
            case .quant:
                R5WorkspaceFixture(descriptor: catalog.quant, semantic: "quant.backtest-detail", payload: R5FixtureData.quant)
            case .paper:
                R5WorkspaceFixture(descriptor: catalog.paper, semantic: "paper.account", payload: R5FixtureData.paper)
            case .settings:
                R5WorkspaceFixture(
                    descriptor: catalog.settings, semantic: "settings.providers", payload: R5FixtureData.settings
                )
            case .administration:
                R5WorkspaceFixture(
                    descriptor: catalog.administration, semantic: "admin.users", payload: R5FixtureData.admin
                )
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
