#if os(macOS)
    import AppKit
    @testable import StockMonitorFeatures
    import SwiftUI
    import Testing

    @MainActor
    @Test(.disabled(if: ProcessInfo.processInfo.environment["CI"] != nil)) func r7RepresentativePagesRenderInWebInspiredStyle() throws {
        let configuredOutput = ProcessInfo.processInfo.environment["STOCK_MONITOR_R7_SNAPSHOT_OUTPUT_DIR"]
            .map(URL.init(fileURLWithPath:))
        let outputRoot = configuredOutput
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("stock-monitor-r7-snapshots", isDirectory: true)
        let baselineRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Tests/VisualBaselines/R7", isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)

        for page in R7RepresentativePage.allCases {
            for dark in [false, true] {
                let name = "r7-\(page.rawValue)-standard-\(dark ? "dark" : "light").png"
                let output = outputRoot.appendingPathComponent(name)
                try render(
                    R7RepresentativeFixture(page: page)
                        .environment(\.interfaceDensity, .comfortable)
                        .environment(\.stockMonitorLayoutWidth, .standard)
                        .environment(\.colorScheme, dark ? .dark : .light),
                    appearance: dark ? .darkAqua : .aqua,
                    size: CGSize(width: 1180, height: 820),
                    to: output
                )
                try verify(output: output, name: name, baselineRoot: baselineRoot, recording: configuredOutput != nil)
            }
        }

        let narrowName = "r7-holdings-narrow-light-compact.png"
        let narrowOutput = outputRoot.appendingPathComponent(narrowName)
        try render(
            R7RepresentativeFixture(page: .holdings)
                .environment(\.interfaceDensity, .compact)
                .environment(\.stockMonitorLayoutWidth, .narrow)
                .environment(\.colorScheme, .light),
            appearance: .aqua,
            size: CGSize(width: 620, height: 780),
            to: narrowOutput
        )
        try verify(output: narrowOutput, name: narrowName, baselineRoot: baselineRoot, recording: configuredOutput != nil)

        let wideName = "r7-news-wide-dark-comfortable.png"
        let wideOutput = outputRoot.appendingPathComponent(wideName)
        try render(
            R7RepresentativeFixture(page: .news)
                .environment(\.interfaceDensity, .comfortable)
                .environment(\.stockMonitorLayoutWidth, .wide)
                .environment(\.colorScheme, .dark),
            appearance: .darkAqua,
            size: CGSize(width: 1480, height: 900),
            to: wideOutput
        )
        try verify(output: wideOutput, name: wideName, baselineRoot: baselineRoot, recording: configuredOutput != nil)
    }

    private func verify(output: URL, name: String, baselineRoot: URL, recording: Bool) throws {
        let size = try (FileManager.default.attributesOfItem(atPath: output.path)[.size] as? NSNumber)?.intValue ?? 0
        #expect(size > 10000)
        guard !recording else { return }
        let baseline = baselineRoot.appendingPathComponent(name)
        #expect(FileManager.default.fileExists(atPath: baseline.path), "Missing R7 baseline \(name)")
        #expect(try Data(contentsOf: baseline) == Data(contentsOf: output), "Visual diff for \(name)")
    }

    @MainActor private func render(
        _ view: some View,
        appearance: NSAppearance.Name,
        size: CGSize,
        to url: URL
    ) throws {
        let hosting = NSHostingView(rootView: view.frame(width: size.width, height: size.height))
        hosting.frame = CGRect(origin: .zero, size: size)
        hosting.appearance = NSAppearance(named: appearance)
        let window = NSWindow(contentRect: hosting.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = hosting.appearance
        window.contentView = hosting
        window.layoutIfNeeded(); hosting.layoutSubtreeIfNeeded(); hosting.displayIfNeeded()
        guard let bitmap = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) else { throw R7SnapshotError.render }
        hosting.cacheDisplay(in: hosting.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else { throw R7SnapshotError.encode }
        try data.write(to: url, options: .atomic)
        window.contentView = nil
    }

    private enum R7SnapshotError: Error { case render, encode }
#endif
