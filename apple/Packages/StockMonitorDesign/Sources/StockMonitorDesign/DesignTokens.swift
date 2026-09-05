import SwiftUI

public enum InterfaceDensity: String, CaseIterable, Identifiable, Sendable {
    case compact, comfortable
    public var id: Self {
        self
    }

    public var title: String {
        self == .compact ? "紧凑" : "舒适"
    }

    public var rowHeight: CGFloat {
        self == .compact ? 28 : 36
    }
}

public enum StockMonitorSpacing {
    public static let compact: CGFloat = 8
    public static let regular: CGFloat = 12
    public static let section: CGFloat = 20
}

public enum StockMonitorMotion {
    public static let responsive = Animation.interpolatingSpring(stiffness: 420, damping: 38)
    public static let emphasized = Animation.interpolatingSpring(stiffness: 320, damping: 32)
}

public extension EnvironmentValues {
    @Entry var interfaceDensity: InterfaceDensity = .comfortable
}

public struct SemanticStatusLabel: View {
    public enum Status: Sendable { case live, stale, warning, unavailable }
    private let title: String
    private let status: Status

    public init(_ title: String, status: Status) {
        self.title = title; self.status = status
    }

    public var body: some View {
        Label(title, systemImage: icon)
            .font(.caption)
            .foregroundStyle(color)
            .accessibilityLabel("\(title)，\(accessibilityStatus)")
    }

    private var icon: String {
        switch status { case .live: "circle.fill"; case .stale: "clock"; case .warning: "exclamationmark.triangle"; case .unavailable: "questionmark.circle" }
    }

    private var color: Color {
        switch status { case .live: .green; case .stale: .secondary; case .warning: .orange; case .unavailable: .secondary }
    }

    private var accessibilityStatus: String {
        switch status { case .live: "实时"; case .stale: "已过期"; case .warning: "警告"; case .unavailable: "数据不足" }
    }
}

public extension View {
    func financialFigures() -> some View {
        monospacedDigit()
    }
}
