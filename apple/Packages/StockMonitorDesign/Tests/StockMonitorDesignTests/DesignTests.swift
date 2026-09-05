@testable import StockMonitorDesign
import Testing

@Test func everyFoundationStateHasStableRawValue() {
    #expect(ResourcePresentationState.allCases.map(\.rawValue) == ["idle", "loading", "ready", "refreshing", "stale", "empty", "error", "permissionDenied", "offline"])
}
