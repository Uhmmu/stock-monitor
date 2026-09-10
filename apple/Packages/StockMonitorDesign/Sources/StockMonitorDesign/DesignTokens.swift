import SwiftUI
#if os(iOS)
    import UIKit
#endif

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

    public var controlHeight: CGFloat {
        self == .compact ? 24 : 30
    }

    public var pagePadding: CGFloat {
        self == .compact ? 20 : 28
    }

    public var sectionSpacing: CGFloat {
        self == .compact ? 20 : 28
    }

    public var rowPadding: CGFloat {
        self == .compact ? 5 : 8
    }
}

public enum StockMonitorSpacing {
    public static let xSmall: CGFloat = 4
    public static let small: CGFloat = 8
    public static let regular: CGFloat = 12
    public static let medium: CGFloat = 16
    public static let section: CGFloat = 20
    public static let large: CGFloat = 24
    public static let xLarge: CGFloat = 32
    public static let page: CGFloat = 40

    @available(*, deprecated, renamed: "small")
    public static let compact = small
}

public enum StockMonitorContentWidth {
    public static let readable: CGFloat = 720
    public static let standard: CGFloat = 1040
    public static let wide: CGFloat = 1440
    public static let minimum: CGFloat = 420
}

public enum StockMonitorLayoutWidth: String, CaseIterable, Identifiable, Sendable {
    case narrow, standard, wide

    public var id: Self {
        self
    }

    public static func classify(_ width: CGFloat) -> Self {
        if width < 760 {
            return .narrow
        }
        if width < 1280 {
            return .standard
        }
        return .wide
    }

    public var title: String {
        switch self {
        case .narrow: "窄"
        case .standard: "标准"
        case .wide: "宽"
        }
    }

    public var maximumMetricColumns: Int {
        switch self {
        case .narrow: 2
        case .standard: 4
        case .wide: 6
        }
    }
}

public enum StockMonitorCornerRadius {
    public static let badge: CGFloat = 5
    public static let control: CGFloat = 7
    public static let surface: CGFloat = 10
    public static let prominent: CGFloat = 14
    public static let webCard: CGFloat = 18
    public static let floatingControl: CGFloat = 13
}

public enum StockMonitorElevation {
    public static let floatingRadius: CGFloat = 12
    public static let floatingY: CGFloat = 5
    public static let floatingOpacity: Double = 0.12
    public static let cardRadius: CGFloat = 18
    public static let cardY: CGFloat = 7
    public static let cardOpacity: Double = 0.07
}

public enum StockMonitorAccent {
    public static let primary = Color.accentColor
    public static let selectionFill = Color.accentColor.opacity(0.12)
    public static let selectionStroke = Color.accentColor.opacity(0.26)
    public static let coolTint = Color.indigo.opacity(0.055)
}

public enum StockMonitorTypographyRole: String, CaseIterable, Sendable {
    case pageTitle, sectionTitle, body, metricLabel, metadata, microAnnotation

    public var font: Font {
        switch self {
        case .pageTitle: .title.weight(.semibold)
        case .sectionTitle: .headline.weight(.semibold)
        case .body: .body
        case .metricLabel: .callout.weight(.medium)
        case .metadata: .callout
        case .microAnnotation: .caption
        }
    }

    public var foregroundStyle: HierarchicalShapeStyle {
        switch self {
        case .pageTitle, .sectionTitle, .body, .metricLabel: .primary
        case .metadata, .microAnnotation: .secondary
        }
    }
}

public enum StockMonitorSurface: String, CaseIterable, Sendable {
    case content, grouped, raised, chrome, danger

    public var fill: Color {
        switch self {
        case .content: .clear
        case .grouped: platformGroupedBackground
        case .raised: platformRaisedBackground
        case .chrome: platformChromeBackground.opacity(0.88)
        case .danger: Color.red.opacity(0.08)
        }
    }

    private var platformGroupedBackground: Color {
        #if os(macOS)
            Color(nsColor: .controlBackgroundColor)
        #else
            Color(uiColor: .secondarySystemGroupedBackground)
        #endif
    }

    private var platformRaisedBackground: Color {
        #if os(macOS)
            Color(nsColor: .textBackgroundColor)
        #else
            Color(uiColor: .systemBackground)
        #endif
    }

    private var platformChromeBackground: Color {
        #if os(macOS)
            Color(nsColor: .windowBackgroundColor)
        #else
            Color(uiColor: .systemBackground)
        #endif
    }
}

public enum StockMonitorSeparator {
    #if os(macOS)
        public static let standard = Color(nsColor: .separatorColor)
        public static let emphasized = Color(nsColor: .gridColor)
    #else
        public static let standard = Color(uiColor: .separator)
        public static let emphasized = Color(uiColor: .opaqueSeparator)
    #endif
}

public enum StockMonitorCanvas {
    #if os(macOS)
        public static let background = Color(nsColor: .windowBackgroundColor)
    #else
        public static let background = Color(uiColor: .systemBackground)
    #endif
}

public enum StockMonitorChartPalette {
    public static let categorical: [Color] = [.blue, .purple, .teal, .indigo, .orange, .pink]
    public static let positive = Color.green
    public static let negative = Color.red
    public static let neutral = Color.secondary
    public static let estimate = Color.purple
}

public enum StockMonitorMotion {
    public static let responsive = Animation.interpolatingSpring(stiffness: 420, damping: 38)
    public static let emphasized = Animation.interpolatingSpring(stiffness: 320, damping: 32)
}

public enum ContentSemanticRole: String, CaseIterable, Sendable {
    case summary, metric, trend, evidence, limitation, source, action, danger
}

public extension EnvironmentValues {
    @Entry var interfaceDensity: InterfaceDensity = .comfortable
    @Entry var stockMonitorLayoutWidth: StockMonitorLayoutWidth = .standard
}

public struct AdaptiveLayoutReader<Content: View>: View {
    private let content: Content

    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    public var body: some View {
        GeometryReader { proxy in
            content
                .environment(\.stockMonitorLayoutWidth, StockMonitorLayoutWidth.classify(proxy.size.width))
                .frame(width: proxy.size.width, height: proxy.size.height)
        }
    }
}

public struct SemanticStatusLabel: View {
    public enum Status: String, CaseIterable, Sendable {
        case live, positive, negative, neutral, info, stale, warning, danger, unavailable
    }

    private let title: String
    private let status: Status

    public init(_ title: String, status: Status) {
        self.title = title
        self.status = status
    }

    public var body: some View {
        Label(title, systemImage: icon)
            .font(StockMonitorTypographyRole.metadata.font)
            .foregroundStyle(color)
            .accessibilityLabel("\(title)，\(accessibilityStatus)")
    }

    private var icon: String {
        switch status {
        case .live, .positive: "checkmark.circle.fill"
        case .negative: "arrow.down.right.circle.fill"
        case .neutral: "minus.circle"
        case .info: "info.circle"
        case .stale: "clock"
        case .warning: "exclamationmark.triangle"
        case .danger: "xmark.octagon"
        case .unavailable: "questionmark.circle"
        }
    }

    private var color: Color {
        switch status {
        case .live, .positive: .green
        case .negative, .danger: .red
        case .warning: .orange
        case .info: .blue
        case .neutral, .stale, .unavailable: .secondary
        }
    }

    private var accessibilityStatus: String {
        switch status {
        case .live: "实时"
        case .positive: "正向"
        case .negative: "负向"
        case .neutral: "中性"
        case .info: "信息"
        case .stale: "已过期"
        case .warning: "警告"
        case .danger: "危险"
        case .unavailable: "数据不足"
        }
    }
}

private struct StockMonitorSurfaceModifier: ViewModifier {
    let surface: StockMonitorSurface
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
        content
            .background(
                surface.fill.opacity(reduceTransparency ? 1 : 0.94),
                in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.surface)
            )
            .overlay {
                RoundedRectangle(cornerRadius: StockMonitorCornerRadius.surface)
                    .stroke(
                        contrast == .increased ? StockMonitorSeparator.emphasized : StockMonitorSeparator.standard.opacity(0.65),
                        lineWidth: contrast == .increased ? 1.5 : 0.5
                    )
            }
    }
}

/// Web-inspired content card rendered with native dynamic colors. It deliberately
/// stays opaque enough for financial figures; glass remains in chrome/transient layers.
private struct StockMonitorCardModifier: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
        content
            .background(
                StockMonitorSurface.raised.fill.opacity(reduceTransparency ? 1 : 0.97),
                in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.webCard, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: StockMonitorCornerRadius.webCard, style: .continuous)
                    .stroke(
                        contrast == .increased ? StockMonitorSeparator.emphasized : StockMonitorSeparator.standard.opacity(0.55),
                        lineWidth: contrast == .increased ? 1.5 : 0.5
                    )
            }
            .shadow(
                color: Color.black.opacity(contrast == .increased ? 0 : StockMonitorElevation.cardOpacity),
                radius: StockMonitorElevation.cardRadius,
                y: StockMonitorElevation.cardY
            )
    }
}

private struct StockMonitorFilterBarModifier: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        content
            .padding(.horizontal, StockMonitorSpacing.regular)
            .padding(.vertical, StockMonitorSpacing.small)
            .background(
                reduceTransparency ? AnyShapeStyle(StockMonitorSurface.raised.fill) : AnyShapeStyle(.bar),
                in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.floatingControl, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: StockMonitorCornerRadius.floatingControl, style: .continuous)
                    .stroke(StockMonitorSeparator.standard.opacity(0.55), lineWidth: 0.5)
            }
    }
}

public extension View {
    func financialFigures() -> some View {
        monospacedDigit()
    }

    func stockMonitorSurface(_ surface: StockMonitorSurface = .grouped) -> some View {
        modifier(StockMonitorSurfaceModifier(surface: surface))
    }

    func stockMonitorTypography(_ role: StockMonitorTypographyRole) -> some View {
        font(role.font).foregroundStyle(role.foregroundStyle)
    }

    func stockMonitorCard() -> some View {
        modifier(StockMonitorCardModifier())
    }

    func stockMonitorFilterBar() -> some View {
        modifier(StockMonitorFilterBarModifier())
    }
}
