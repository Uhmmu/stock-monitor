@testable import StockMonitorFeatures
import Testing

@MainActor
@Test func fixtureCanRepresentAllRequiredStates() {
    let model = FoundationFeatureModel()
    #expect(model.state.rawValue == "loading")
    model.state = .ready
    #expect(model.state.rawValue == "ready")
    model.state = .stale
    #expect(model.state.rawValue == "stale")
    model.state = .error
    #expect(model.state.rawValue == "error")
}
