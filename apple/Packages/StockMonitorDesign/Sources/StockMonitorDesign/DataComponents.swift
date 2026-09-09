import SwiftUI

public struct FinancialTableRow: Identifiable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let current: FinancialDisplayValue
    public let comparison: FinancialDisplayValue?
    public init(id: String? = nil, label: String, current: FinancialDisplayValue, comparison: FinancialDisplayValue? = nil) {
        self.id = id ?? label; self.label = label; self.current = current; self.comparison = comparison
    }
}

public struct FinancialTable: View {
    @Environment(\.interfaceDensity) private var density
    @Environment(\.stockMonitorLayoutWidth) private var layoutWidth
    private let rows: [FinancialTableRow]
    private let currentTitle: String
    private let comparisonTitle: String?
    public init(_ rows: [FinancialTableRow], currentTitle: String, comparisonTitle: String? = nil) {
        self.rows = rows; self.currentTitle = currentTitle; self.comparisonTitle = comparisonTitle
    }

    public var body: some View {
        Group {
            if layoutWidth == .narrow {
                List(rows) { row in
                    VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                        Text(row.label).font(.headline)
                        LabeledContent(currentTitle) { valueCell(row.current) }
                        if let comparisonTitle, let comparison = row.comparison {
                            LabeledContent(comparisonTitle) { valueCell(comparison) }
                        }
                    }
                    .padding(.vertical, density.rowPadding)
                    .accessibilityElement(children: .contain)
                }
            } else {
                Table(rows) {
                    TableColumn("指标", value: \.label).width(min: 150, ideal: 220)
                    TableColumn(currentTitle) { valueCell($0.current) }.width(min: 100, ideal: 130)
                    TableColumn(comparisonTitle ?? "对比") { row in
                        if let comparison = row.comparison {
                            valueCell(comparison)
                        } else {
                            Text(FinancialValueFormatter.unavailable).foregroundStyle(.secondary)
                        }
                    }.width(min: 100, ideal: 130)
                }
            }
        }
        .environment(\.defaultMinListRowHeight, density.rowHeight)
        .accessibilityIdentifier("table.financial")
    }

    private func valueCell(_ value: FinancialDisplayValue) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            Text(value.text).financialFigures()
            if let qualifier = value.qualifier {
                Text(qualifier).stockMonitorTypography(.microAnnotation)
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(value.accessibilityLabel)
    }
}

public struct ComparisonTable: View {
    private let rows: [FinancialTableRow]
    private let leftTitle: String
    private let rightTitle: String
    public init(_ rows: [FinancialTableRow], leftTitle: String, rightTitle: String) {
        self.rows = rows; self.leftTitle = leftTitle; self.rightTitle = rightTitle
    }

    public var body: some View {
        FinancialTable(rows, currentTitle: leftTitle, comparisonTitle: rightTitle).accessibilityIdentifier("table.comparison")
    }
}

public struct TimelineEntry: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let timestamp: String
    public let detail: String
    public let systemImage: String
    public init(id: String, title: String, timestamp: String, detail: String, systemImage: String = "circle.fill") {
        self.id = id; self.title = title; self.timestamp = timestamp; self.detail = detail; self.systemImage = systemImage
    }
}

public struct TimelineList: View {
    private let entries: [TimelineEntry]
    public init(_ entries: [TimelineEntry]) {
        self.entries = entries
    }

    public var body: some View {
        LazyVStack(alignment: .leading, spacing: 0) {
            ForEach(Array(entries.enumerated()), id: \.element.id) { index, entry in
                HStack(alignment: .top, spacing: StockMonitorSpacing.regular) {
                    VStack(spacing: 0) {
                        Image(systemName: entry.systemImage).foregroundStyle(.tint)
                        if index < entries.count - 1 {
                            Rectangle().fill(StockMonitorSeparator.standard).frame(width: 1, height: 42)
                        }
                    }
                    VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                        ViewThatFits(in: .horizontal) {
                            HStack(alignment: .firstTextBaseline) {
                                Text(entry.title).font(.headline)
                                Spacer()
                                Text(entry.timestamp).stockMonitorTypography(.metadata)
                            }
                            VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                                Text(entry.title).font(.headline)
                                Text(entry.timestamp).stockMonitorTypography(.metadata)
                            }
                        }
                        Text(entry.detail).stockMonitorTypography(.body).textSelection(.enabled)
                    }
                    .padding(.bottom, StockMonitorSpacing.medium)
                }
            }
        }
        .accessibilityIdentifier("list.timeline")
    }
}

public struct EvidencePanel<Content: View>: View {
    private let title: String
    private let content: Content
    public init(_ title: String = "证据", @ViewBuilder content: () -> Content) {
        self.title = title; self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) { SectionHeader(title); content }
            .padding(StockMonitorSpacing.medium)
            .stockMonitorSurface(.grouped)
            .accessibilityIdentifier("panel.evidence")
    }
}

public struct ChartContainer<Controls: View, Content: View>: View {
    private let title: String
    private let controls: Controls
    private let content: Content
    public init(_ title: String, @ViewBuilder controls: () -> Controls, @ViewBuilder content: () -> Content) {
        self.title = title; self.controls = controls(); self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) { SectionHeader(title) { controls }; content }
            .padding(StockMonitorSpacing.medium)
            .stockMonitorSurface(.content)
            .accessibilityIdentifier("chart.container")
    }
}
