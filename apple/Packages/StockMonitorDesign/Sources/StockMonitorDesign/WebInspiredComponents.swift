import SwiftUI

/// A compact hero used by high-level pages. Its hierarchy follows the web client,
/// while typography, colors and accessibility remain native and adaptive.
public struct WebInspiredHero<Metrics: View, Actions: View>: View {
    private let eyebrow: String?
    private let title: String
    private let summary: String
    private let metrics: Metrics
    private let actions: Actions

    public init(
        _ title: String,
        eyebrow: String? = nil,
        summary: String,
        @ViewBuilder metrics: () -> Metrics,
        @ViewBuilder actions: () -> Actions
    ) {
        self.title = title
        self.eyebrow = eyebrow
        self.summary = summary
        self.metrics = metrics()
        self.actions = actions()
    }

    public var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: StockMonitorSpacing.large) {
                identity
                Spacer(minLength: StockMonitorSpacing.medium)
                metrics
                actions
            }
            VStack(alignment: .leading, spacing: StockMonitorSpacing.medium) {
                identity
                metrics
                actions
            }
        }
        .padding(StockMonitorSpacing.large)
        .background {
            ZStack {
                StockMonitorSurface.raised.fill
                LinearGradient(
                    colors: [Color.accentColor.opacity(0.11), StockMonitorAccent.coolTint, .clear],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            }
            .clipShape(RoundedRectangle(cornerRadius: StockMonitorCornerRadius.webCard, style: .continuous))
        }
        .stockMonitorCard()
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("page.header")
    }

    private var identity: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            if let eyebrow {
                Text(eyebrow.uppercased())
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tint)
            }
            Text(title).font(.title.weight(.bold)).tracking(-0.5)
            Text(summary).stockMonitorTypography(.body).foregroundStyle(.secondary)
        }
        .frame(maxWidth: 620, alignment: .leading)
    }
}

public struct SelectionPill: View {
    private let title: String
    private let systemImage: String?
    private let selected: Bool

    public init(_ title: String, systemImage: String? = nil, selected: Bool) {
        self.title = title
        self.systemImage = systemImage
        self.selected = selected
    }

    public var body: some View {
        Group {
            if let systemImage {
                Label(title, systemImage: systemImage)
            } else {
                Text(title)
            }
        }
        .font(.callout.weight(.medium))
        .foregroundStyle(selected ? AnyShapeStyle(.tint) : AnyShapeStyle(.primary))
        .padding(.horizontal, StockMonitorSpacing.regular)
        .frame(minHeight: 30)
        .background(selected ? StockMonitorAccent.selectionFill : Color.clear, in: Capsule())
        .overlay { Capsule().stroke(selected ? StockMonitorAccent.selectionStroke : StockMonitorSeparator.standard.opacity(0.55)) }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
