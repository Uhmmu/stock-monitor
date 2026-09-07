import SwiftUI

public struct DesignLabView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast
    @Environment(\.interfaceDensity) private var density
    @State private var query = ""
    @State private var selection = "AAPL"
    @State private var showInspector = true
    @State private var showConfirmation = false
    @State private var showSheet = false
    @State private var showPopover = false

    public init() {}

    public var body: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 16)], alignment: .leading, spacing: 16) {
                labCard("文字角色", systemImage: "textformat") {
                    ForEach(StockMonitorTypographyRole.allCases, id: \.rawValue) { role in
                        LabeledContent(role.rawValue) { Text("苹果原生金融界面").stockMonitorTypography(role) }
                    }
                }
                labCard("间距、圆角与 Surface", systemImage: "square.3.layers.3d") {
                    HStack(spacing: StockMonitorSpacing.small) {
                        ForEach(StockMonitorSurface.allCases, id: \.rawValue) { surface in
                            Text(surface.rawValue).padding(StockMonitorSpacing.small).stockMonitorSurface(surface)
                        }
                    }
                    Text("页面 \(Int(density.pagePadding)) pt · 行高 \(Int(density.rowHeight)) pt · 控件 \(Int(density.controlHeight)) pt")
                        .stockMonitorTypography(.metadata)
                }
                labCard("语义状态", systemImage: "circle.dotted") {
                    ForEach(SemanticStatusLabel.Status.allCases, id: \.rawValue) { status in
                        SemanticStatusLabel(status.rawValue, status: status)
                    }
                }
                labCard("徽标与金融数字", systemImage: "number") {
                    HStack { SourceBadge("Yahoo"); FreshnessBadge("18 分钟前", stale: true); CoverageBadge(covered: 7, total: 10) }
                    MetricGrid([
                        .init(label: "价格", value: FinancialValueFormatter.price(234.12, currency: "USD")),
                        .init(label: "变化", value: FinancialValueFormatter.percent(-0.023), status: .negative),
                        .init(label: "市值", value: FinancialValueFormatter.amount(3_490_000_000_000, currency: "USD")),
                        .init(label: "预估倍数", value: FinancialValueFormatter.multiple(31.4, state: .estimated), status: .info),
                    ])
                }
                labCard("表格与密度", systemImage: "tablecells") {
                    Picker("证券", selection: $selection) { Text("AAPL").tag("AAPL"); Text("MSFT").tag("MSFT") }
                    Table([QuotePreview(symbol: "AAPL", price: 234.12), QuotePreview(symbol: "MSFT", price: 521.44)]) {
                        TableColumn("证券", value: \.symbol)
                        TableColumn("价格") { Text($0.price, format: .number.precision(.fractionLength(2))).monospacedDigit() }
                    }.frame(height: density.rowHeight * 3)
                }
                labCard("搜索与瞬态层", systemImage: "magnifyingglass") {
                    TextField("搜索证券或功能", text: $query).textFieldStyle(.roundedBorder)
                    Toggle("显示检查器", isOn: $showInspector)
                    HStack {
                        Button("Popover") { showPopover = true }
                            .popover(isPresented: $showPopover) { Text("与触发源保持空间关系").padding() }
                        Button("Sheet") { showSheet = true }
                    }
                    Button("破坏性确认") { showConfirmation = true }
                }
                labCard("Motion Lab", systemImage: "hand.draw") {
                    MotionLabSample()
                    Text(reduceMotion ? "Reduce Motion：直接跟随，无回弹转场" : "拖动后由当前位置回到原位；spring 可被再次拖动打断")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                labCard("图表 chrome", systemImage: "chart.xyaxis.line") {
                    HStack {
                        Picker("区间", selection: .constant("1M")) { Text("1月").tag("1M") }
                        Spacer()
                        Button("导出", systemImage: "square.and.arrow.up") {}
                    }
                    RoundedRectangle(cornerRadius: 8)
                        .fill(.quaternary)
                        .frame(height: 92)
                        .overlay(Text("图表内容层不叠加玻璃材质").foregroundStyle(.secondary))
                }
                labCard("可访问性环境", systemImage: "accessibility") {
                    LabeledContent("Reduce Motion", value: reduceMotion ? "开启" : "关闭")
                    LabeledContent("Reduce Transparency", value: reduceTransparency ? "开启" : "关闭")
                    LabeledContent("Contrast", value: contrast == .increased ? "增强" : "标准")
                }
                labCard("Loading / Empty / Error", systemImage: "rectangle.3.group") {
                    ProgressView("正在加载")
                    EmptyState("暂无数据", description: "当前范围没有可展示的记录。")
                    InlineError(message: "保留上次有效内容，并提供可复制的错误详情。", requestID: "lab-request-id")
                }
            }
            .padding(20)
        }
        .navigationTitle("Design Lab")
        .confirmationDialog("确定清除本地缓存？", isPresented: $showConfirmation) {
            Button("清除缓存", role: .destructive) {}
        } message: { Text("服务器数据不会受到影响。") }
        .sheet(isPresented: $showSheet) {
            VStack(spacing: 16) {
                Label("系统 Sheet", systemImage: "macwindow")
                Button("完成") { showSheet = false }.keyboardShortcut(.defaultAction)
            }
            .padding(32)
            .frame(minWidth: 360, minHeight: 180)
        }
    }

    private func labCard(_ title: String, systemImage: String, @ViewBuilder content: () -> some View) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) { content() }.frame(maxWidth: .infinity, alignment: .leading).padding(4)
        } label: { Label(title, systemImage: systemImage).font(.headline) }
    }
}

private struct MotionLabSample: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @GestureState private var dragOffset = CGSize.zero

    var body: some View {
        RoundedRectangle(cornerRadius: 12)
            .fill(Color.accentColor.gradient)
            .frame(width: 88, height: 52)
            .overlay(Image(systemName: "arrow.left.and.right").foregroundStyle(.white))
            .offset(dragOffset)
            .gesture(
                DragGesture()
                    .updating($dragOffset) { value, state, _ in state = value.translation }
            )
            .animation(reduceMotion ? nil : StockMonitorMotion.responsive, value: dragOffset)
            .accessibilityLabel("可拖动 spring 示例")
            .accessibilityHint("拖动并释放以检查可打断的回位动画")
    }
}

private struct QuotePreview: Identifiable { let symbol: String; let price: Double; var id: String {
    symbol
} }
