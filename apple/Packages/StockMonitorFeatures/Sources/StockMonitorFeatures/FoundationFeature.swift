import Observation
import StockMonitorCore
import StockMonitorDesign
import SwiftUI

@MainActor
@Observable
public final class FoundationFeatureModel {
    public var state: ResourcePresentationState
    public var lastUpdated: Date?

    public init(state: ResourcePresentationState = .loading, lastUpdated: Date? = nil) {
        self.state = state
        self.lastUpdated = lastUpdated
    }
}

public struct FoundationFeatureView: View {
    @State private var model: FoundationFeatureModel

    public init(model: FoundationFeatureModel) {
        _model = State(initialValue: model)
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Stock Monitor")
                    .font(.title2.bold())
                    .accessibilityIdentifier("foundation.title")
                Text("Apple 原生工程地基已就绪").foregroundStyle(.secondary)
                if let lastUpdated = model.lastUpdated {
                    Text(lastUpdated, format: .dateTime.year().month().day().hour().minute())
                        .font(.caption).foregroundStyle(.tertiary)
                }
            }
        }
        .padding()
        .frame(minWidth: 420, minHeight: 260, alignment: .topLeading)
        .accessibilityIdentifier("foundation.resource-state")
    }
}

#if DEBUG
    private struct FoundationFeaturePreview: PreviewProvider {
        static var previews: some View {
            Group {
                FoundationFeatureView(model: FoundationFeatureModel(state: .loading))
                    .previewDisplayName("Loading")
                FoundationFeatureView(model: FoundationFeatureModel(state: .ready, lastUpdated: .now))
                    .previewDisplayName("Ready")
                FoundationFeatureView(model: FoundationFeatureModel(state: .stale, lastUpdated: .now.addingTimeInterval(-3600)))
                    .previewDisplayName("Stale")
                FoundationFeatureView(model: FoundationFeatureModel(state: .error))
                    .previewDisplayName("Error")
            }
        }
    }
#endif
