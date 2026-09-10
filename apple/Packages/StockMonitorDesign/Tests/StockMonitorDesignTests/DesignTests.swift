@testable import StockMonitorDesign
import Testing

@Test func everyFoundationStateHasStableRawValue() {
    #expect(ResourcePresentationState.allCases.map(\.rawValue) == [
        "idle", "loading", "ready", "refreshing", "partial", "stale", "empty", "error", "permissionDenied", "offline",
    ])
}

@Test func jobPhasesAndMutationFeedbackCarryStableTitles() {
    #expect(WorkspaceJobPhase.allCases.map(\.rawValue) == ["queued", "running", "completed", "failed", "canceled", "unknown"])
    #expect(WorkspaceJobPhase(serverStatus: "pending") == .queued)
    #expect(WorkspaceJobPhase(serverStatus: "running") == .running)
    #expect(WorkspaceJobPhase(serverStatus: "partial_failed") == .completed)
    #expect(WorkspaceJobPhase(serverStatus: "failed") == .failed)
    #expect(WorkspaceJobPhase.queued.status == .info)
    #expect(WorkspaceJobPhase.failed.status == .danger)
    #expect(WorkspaceJobPhase.completed.title == "已完成")

    let idle: MutationFeedbackPhase = .idle
    #expect(idle == .idle)
    #expect(MutationFeedbackPhase.pending(actionTitle: "重建持仓") != idle)
    #expect(
        MutationFeedbackPhase.confirmed(actionTitle: "对账", message: "ok")
            == MutationFeedbackPhase.confirmed(actionTitle: "对账", message: "ok")
    )
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

@Test func adaptiveLayoutUsesStableMacBreakpoints() {
    #expect(StockMonitorLayoutWidth.classify(620) == .narrow)
    #expect(StockMonitorLayoutWidth.classify(759) == .narrow)
    #expect(StockMonitorLayoutWidth.classify(760) == .standard)
    #expect(StockMonitorLayoutWidth.classify(1279) == .standard)
    #expect(StockMonitorLayoutWidth.classify(1280) == .wide)
    #expect(StockMonitorLayoutWidth.narrow.maximumMetricColumns == 2)
    #expect(StockMonitorLayoutWidth.wide.maximumMetricColumns == 6)
}

// MARK: - R6 表格/图表/材质动效 token

@Test func tableFoundationRolesAndAlignmentAreComplete() {
    #expect(TableColumnRole.allCases.map(\.rawValue) == ["main", "comparison", "metadata", "action"])
    #expect(TableColumnAlignment.allCases.count == 2)
    #expect(TableNarrowStrategy.allCases.count == 3)
    let spec = TableColumnSpec(
        id: "value", title: "市值", role: .comparison, alignment: .trailing,
        minWidth: 100, idealWidth: 120, monospacedDigits: true, sortableKey: "valueUsd"
    )
    #expect(spec.id == "value")
    #expect(spec.role == .comparison)
    #expect(spec.alignment == .trailing)
}

@Test func chartPalettePairsColorWithNonColorEncoding() {
    // 每个分类色都有对应形状标记；颜色不是唯一编码。
    let markerCount = Set((0 ..< 6).map(StockMonitorChartPalette.seriesMarker)).count
    #expect(markerCount == 6)
    #expect(StockMonitorChartPalette.seriesMarker(0) == .circle)
    #expect(StockMonitorChartPalette.seriesMarker(6) == .circle)
    #expect(StockMonitorChartPalette.seriesColor(6) == StockMonitorChartPalette.seriesColor(0))
    // 线型在第三个系列后出现虚线差异。
    #expect(StockMonitorChartPalette.seriesStroke(0).dash.isEmpty)
    #expect(StockMonitorChartPalette.seriesStroke(2).dash.isEmpty == false)
    #expect(StockMonitorChartPalette.seriesStroke(0).lineWidth > StockMonitorChartPalette.seriesStroke(1).lineWidth)
    // 涨跌语义色不同且都有语义标签承载（SemanticStatusLabel 图标/文字）。
    #expect(StockMonitorChartPalette.positive != StockMonitorChartPalette.negative)
    #expect(ChartSeriesMarker.allCases.count == 6)
    #expect(ChartSeriesMarker.circle.systemImageName == "circle.fill")
}

@Test func materialPolicyKeepsContentLayerFreeOfSystemMaterials() {
    #expect(MaterialPolicyCatalog.contentLayerUsesSystemMaterial.isEmpty)
    #expect(MaterialPolicyCatalog.entries.count >= 6)
    #expect(MaterialPolicyLayer.allCases.map(\.rawValue) == ["content", "chrome", "transient"])
    // 唯一 transient 自定义材质是 K 线 tooltip。
    let transient = MaterialPolicyCatalog.entries.filter { $0.layer == .transient && $0.surface.contains("tooltip") }
    #expect(transient.count == 1)
}

@Test func motionAuditKeepsHighFrequencyPathsInstant() {
    #expect(StockMonitorMotionAudit.highFrequencySurfacesWithAnimation.isEmpty)
    #expect(StockMonitorMotionAudit.animatedSurfacesMissingFallback.isEmpty)
    #expect(StockMonitorMotionAudit.highFrequencySurfaces.count >= 5)
    // stateChange 是短 cross-fade（Reduce Motion 降级路径）。
    #expect(StockMonitorMotion.hoverHighlightOpacity <= 0.08)
}

@Test func webInspiredTokensKeepContentLegibleAndSelectionSemantic() {
    #expect(StockMonitorCornerRadius.webCard > StockMonitorCornerRadius.surface)
    #expect(StockMonitorCornerRadius.floatingControl < StockMonitorCornerRadius.webCard)
    #expect(StockMonitorElevation.cardOpacity <= 0.08)
    #expect(StockMonitorElevation.cardY > 0)
}
