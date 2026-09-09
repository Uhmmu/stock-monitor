import SwiftUI

public struct PageScaffold<Header: View, Content: View>: View {
    @Environment(\.interfaceDensity) private var density
    @Environment(\.stockMonitorLayoutWidth) private var layoutWidth
    private let width: CGFloat
    private let header: Header
    private let content: Content

    public init(
        width: CGFloat = StockMonitorContentWidth.standard,
        @ViewBuilder header: () -> Header,
        @ViewBuilder content: () -> Content
    ) {
        self.width = width
        self.header = header()
        self.content = content()
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: density.sectionSpacing) {
                header
                content
            }
            .frame(maxWidth: effectiveWidth, alignment: .leading)
            .padding(effectivePadding)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .background(StockMonitorCanvas.background)
        .accessibilityElement(children: .contain)
    }

    private var effectiveWidth: CGFloat {
        layoutWidth == .narrow ? .infinity : width
    }

    private var effectivePadding: CGFloat {
        switch layoutWidth {
        case .narrow: max(StockMonitorSpacing.regular, density.pagePadding - 8)
        case .standard, .wide: density.pagePadding
        }
    }
}

public struct PageHeader<Trailing: View>: View {
    private let title: String
    private let eyebrow: String?
    private let summary: String?
    private let trailing: Trailing

    public init(_ title: String, eyebrow: String? = nil, summary: String? = nil, @ViewBuilder trailing: () -> Trailing) {
        self.title = title
        self.eyebrow = eyebrow
        self.summary = summary
        self.trailing = trailing()
    }

    public var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline, spacing: StockMonitorSpacing.large) {
                identity
                Spacer(minLength: StockMonitorSpacing.medium)
                trailing
            }
            VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
                identity
                trailing
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("page.header")
    }

    private var identity: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            if let eyebrow {
                Text(eyebrow).stockMonitorTypography(.metadata)
            }
            Text(title).stockMonitorTypography(.pageTitle).textSelection(.enabled)
            if let summary {
                Text(summary).stockMonitorTypography(.body).foregroundStyle(.secondary).lineSpacing(2).textSelection(.enabled)
            }
        }
    }
}

public extension PageHeader where Trailing == EmptyView {
    init(_ title: String, eyebrow: String? = nil, summary: String? = nil) {
        self.init(title, eyebrow: eyebrow, summary: summary) { EmptyView() }
    }
}

public struct SectionHeader<Trailing: View>: View {
    private let title: String
    private let explanation: String?
    private let trailing: Trailing

    public init(_ title: String, explanation: String? = nil, @ViewBuilder trailing: () -> Trailing) {
        self.title = title
        self.explanation = explanation
        self.trailing = trailing()
    }

    public var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline) {
                sectionIdentity
                Spacer()
                trailing
            }
            VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                sectionIdentity
                trailing
            }
        }
        .accessibilityIdentifier("section.\(title)")
    }

    private var sectionIdentity: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
            Text(title).stockMonitorTypography(.sectionTitle)
            if let explanation {
                Text(explanation).stockMonitorTypography(.metadata).textSelection(.enabled)
            }
        }
    }
}

public extension SectionHeader where Trailing == EmptyView {
    init(_ title: String, explanation: String? = nil) {
        self.init(title, explanation: explanation) { EmptyView() }
    }
}

public struct MetricItem: Identifiable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let value: FinancialDisplayValue
    public let status: SemanticStatusLabel.Status

    public init(id: String? = nil, label: String, value: FinancialDisplayValue, status: SemanticStatusLabel.Status = .neutral) {
        self.id = id ?? label; self.label = label; self.value = value; self.status = status
    }
}

public struct MetricHero: View {
    public let item: MetricItem
    public init(_ item: MetricItem) {
        self.item = item
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
            Text(item.label).stockMonitorTypography(.metricLabel)
            Text(item.value.text).font(.system(.title, design: .rounded, weight: .semibold)).financialFigures().textSelection(.enabled)
            if let qualifier = item.value.qualifier {
                SemanticStatusLabel(qualifier, status: item.status)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(item.label)，\(item.value.accessibilityLabel)")
        .accessibilityIdentifier("metric.\(item.id)")
    }
}

public struct MetricGrid: View {
    @Environment(\.stockMonitorLayoutWidth) private var layoutWidth
    private let items: [MetricItem]
    private let minimumWidth: CGFloat
    public init(_ items: [MetricItem], minimumWidth: CGFloat = 150) {
        self.items = items; self.minimumWidth = minimumWidth
    }

    public var body: some View {
        LazyVGrid(
            columns: columns,
            alignment: .leading,
            spacing: StockMonitorSpacing.medium
        ) {
            ForEach(items) { MetricHero($0).frame(maxWidth: .infinity, alignment: .leading) }
        }
    }

    private var columns: [GridItem] {
        let count = min(layoutWidth.maximumMetricColumns, max(items.count, 1))
        return Array(repeating: GridItem(.flexible(minimum: minimumWidth), alignment: .leading), count: count)
    }
}

public struct MetadataItem: Identifiable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let value: String
    public init(id: String? = nil, label: String, value: String) {
        self.id = id ?? label; self.label = label; self.value = value
    }
}

public struct MetadataStrip: View {
    private let items: [MetadataItem]
    public init(_ items: [MetadataItem]) {
        self.items = items
    }

    public var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: StockMonitorSpacing.medium) { entries }
            VStack(alignment: .leading, spacing: StockMonitorSpacing.small) { entries }
        }
        .stockMonitorTypography(.metadata)
        .textSelection(.enabled)
        .accessibilityIdentifier("metadata.strip")
    }

    private var entries: some View {
        ForEach(items) { item in LabeledContent(item.label, value: item.value).fixedSize(horizontal: true, vertical: false) }
    }
}

public struct StatusBadge: View {
    private let title: String
    private let systemImage: String
    private let tint: Color
    private let identifier: String
    public init(_ title: String, systemImage: String, tint: Color, identifier: String) {
        self.title = title; self.systemImage = systemImage; self.tint = tint; self.identifier = identifier
    }

    public var body: some View {
        Label(title, systemImage: systemImage)
            .font(StockMonitorTypographyRole.metadata.font.weight(.medium))
            .padding(.horizontal, StockMonitorSpacing.small)
            .padding(.vertical, StockMonitorSpacing.xSmall)
            .foregroundStyle(tint)
            .background(tint.opacity(0.12), in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.badge))
            .accessibilityIdentifier(identifier)
    }
}

public struct SourceBadge: View {
    private let source: String
    public init(_ source: String) {
        self.source = source
    }

    public var body: some View {
        StatusBadge(source, systemImage: "link", tint: .blue, identifier: "badge.source")
    }
}

public struct FreshnessBadge: View {
    private let title: String
    private let stale: Bool
    public init(_ title: String, stale: Bool) {
        self.title = title; self.stale = stale
    }

    public var body: some View {
        StatusBadge(
            title,
            systemImage: stale ? "clock.badge.exclamationmark" : "clock",
            tint: stale ? .orange : .secondary,
            identifier: "badge.freshness"
        )
    }
}

public struct CoverageBadge: View {
    private let covered: Int
    private let total: Int
    public init(covered: Int, total: Int) {
        self.covered = covered; self.total = total
    }

    public var body: some View {
        let safeTotal = max(total, 0)
        StatusBadge(
            "覆盖 \(covered)/\(safeTotal)",
            systemImage: "chart.bar.doc.horizontal",
            tint: covered < safeTotal ? .orange : .green,
            identifier: "badge.coverage"
        )
        .accessibilityLabel("数据覆盖 \(covered) 项，共 \(safeTotal) 项")
    }
}

public struct EmptyState: View {
    private let title: String
    private let systemImage: String
    private let description: String
    public init(_ title: String, systemImage: String = "tray", description: String) {
        self.title = title; self.systemImage = systemImage; self.description = description
    }

    public var body: some View {
        ContentUnavailableView(title, systemImage: systemImage, description: Text(description)).accessibilityIdentifier("state.empty")
    }
}

public struct InlineError: View {
    private let title: String
    private let message: String
    private let requestID: String?
    public init(_ title: String = "暂时无法加载", message: String, requestID: String? = nil) {
        self.title = title; self.message = message; self.requestID = requestID
    }

    public var body: some View {
        HStack(alignment: .top, spacing: StockMonitorSpacing.regular) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                Text(title).font(.headline)
                Text(message).stockMonitorTypography(.body).textSelection(.enabled)
                if let requestID {
                    Text("Request ID：\(requestID)").stockMonitorTypography(.metadata).textSelection(.enabled)
                }
            }
        }
        .padding(StockMonitorSpacing.medium)
        .frame(maxWidth: .infinity, alignment: .leading)
        .stockMonitorSurface(.danger)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("state.error")
    }
}

public struct DisclosureSection<Content: View>: View {
    private let title: String
    private let content: Content
    @State private var expanded: Bool
    public init(_ title: String, expanded: Bool = false, @ViewBuilder content: () -> Content) {
        self.title = title; self.content = content(); _expanded = State(initialValue: expanded)
    }

    public var body: some View {
        DisclosureGroup(title, isExpanded: $expanded) {
            content.padding(.top, StockMonitorSpacing.small)
        }
        .accessibilityIdentifier("disclosure.\(title)")
    }
}

public struct ActionBar<Content: View>: View {
    private let content: Content
    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    public var body: some View {
        HStack(spacing: StockMonitorSpacing.small) {
            Spacer()
            content
        }
        .padding(.vertical, StockMonitorSpacing.small)
        .accessibilityIdentifier("action.bar")
    }
}
