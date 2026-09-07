@testable import StockMonitorDesign
import Testing

@Test func everyFoundationStateHasStableRawValue() {
    #expect(ResourcePresentationState.allCases.map(\.rawValue) == [
        "idle", "loading", "ready", "refreshing", "stale", "empty", "error", "permissionDenied", "offline",
    ])
}

@Test func designLanguageHasCompleteStableRoles() {
    #expect(StockMonitorTypographyRole.allCases.map(\.rawValue) == [
        "pageTitle", "sectionTitle", "body", "metricLabel", "metadata", "microAnnotation",
    ])
    #expect(ContentSemanticRole.allCases.count == 8)
    #expect(SemanticStatusLabel.Status.allCases.count == 9)
    #expect(InterfaceDensity.compact.rowHeight < InterfaceDensity.comfortable.rowHeight)
    #expect(InterfaceDensity.compact.controlHeight >= 24)
    #expect(StockMonitorContentWidth.readable < StockMonitorContentWidth.standard)
}

@Test func financialFormatterKeepsUnitsSignsAndMissingReasons() {
    let price = FinancialValueFormatter.price(234.125, currency: "usd")
    #expect(price.text.hasPrefix("USD "))
    #expect(price.text.contains("234.12") || price.text.contains("234,12"))

    let gain = FinancialValueFormatter.percent(0.023)
    #expect(gain.text.contains("+"))
    #expect(gain.text.contains("2.3") || gain.text.contains("2,3"))
    #expect(FinancialValueFormatter.multiple(31.4).text.hasSuffix("×"))
    #expect(FinancialValueFormatter.amount(3_490_000_000, currency: "USD").text.hasSuffix("B"))
    #expect(FinancialValueFormatter.price(.infinity, currency: "USD").text == FinancialValueFormatter.unavailable)
    #expect(FinancialValueFormatter.missing(.providerFailed).qualifier == "数据源失败")
    #expect(FinancialValueFormatter.missing(.notApplicable).qualifier == "不适用")
}

@Test func metricAndMetadataModelsHaveStableAccessibilityContent() {
    let value = FinancialDisplayValue(text: "USD 12.34", qualifier: "估算")
    #expect(value.accessibilityLabel == "USD 12.34，估算")
    #expect(MetricItem(label: "价格", value: value).id == "价格")
    #expect(MetadataItem(label: "来源", value: "Yahoo").id == "来源")
}
