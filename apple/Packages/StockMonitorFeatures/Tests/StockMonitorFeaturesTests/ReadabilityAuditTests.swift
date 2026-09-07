@testable import StockMonitorFeatures
import Testing

@Test func readabilityAuditCoversEveryRouteExactlyOnce() {
    let records = ReadabilityAuditCatalog.records
    #expect(records.count == 31)
    #expect(Set(records.map(\.route)) == Set(AppRoute.allCases))
    #expect(Set(records.map(\.id)).count == records.count)
}

@Test func everyRouteAuditHasActionableContent() {
    for record in ReadabilityAuditCatalog.records {
        #expect(!record.userTask.isEmpty)
        #expect(!record.primaryInformation.isEmpty)
        #expect(!record.primaryAction.isEmpty)
        #expect(!record.evidence.isEmpty)
        #expect(!record.failureState.isEmpty)
        #expect(Set(record.baselineFindings.map(\.aspect)) == Set(ReadabilityAuditAspect.allCases))
        #expect(record.baselineFindings.allSatisfy { !$0.note.isEmpty })
    }
}

@Test func rawJSONWorkspacesAreRecordedAsP0() {
    let goalM5 = ReadabilityAuditCatalog.records.filter(\.route.isGoalM5Route)
    #expect(goalM5.count == 12)
    #expect(goalM5.allSatisfy { $0.baselineSeverity == .p0 })
}

@Test func visualAuditDimensionsAndStatesAreComplete() {
    #expect(VisualAuditWidth.allCases.map(\.rawValue) == ["narrow", "standard", "wide"])
    #expect(VisualAuditState.allCases.map(\.rawValue) == ["normal", "empty", "partial", "stale", "loading", "error", "permissionDenied"])
    #expect(VisualAuditWidth.narrow.size.width < VisualAuditWidth.standard.size.width)
    #expect(VisualAuditWidth.standard.size.width < VisualAuditWidth.wide.size.width)
}
