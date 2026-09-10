import StockMonitorDesign
import SwiftUI

public enum R7RepresentativePage: String, CaseIterable, Sendable {
    case overview, holdings, news, settings
}

public struct R7RepresentativeFixture: View {
    public let page: R7RepresentativePage

    public init(page: R7RepresentativePage) {
        self.page = page
    }

    public var body: some View {
        PageScaffold(width: StockMonitorContentWidth.wide) {
            header
        } content: {
            switch page {
            case .overview: overview
            case .holdings: holdings
            case .news: news
            case .settings: settings
            }
        }
        .environment(\.stockMonitorWebInspired, true)
    }

    @ViewBuilder private var header: some View {
        switch page {
        case .overview:
            WebInspiredHero("市场总览", eyebrow: "Overview", summary: "美股常规交易时段 · 组合与自选行情保持同一阅读层次。") {
                SemanticStatusLabel("实时连接", status: .live)
            } actions: {
                Button("查看异动", systemImage: "bell") {}.buttonStyle(.borderedProminent)
            }
        case .holdings:
            PageHeader("持仓", eyebrow: "Portfolio", summary: "单只持仓显示本币；组合汇总统一使用基础币种。") {
                Button("组合健康", systemImage: "heart.text.square") {}.buttonStyle(.borderedProminent)
            }
        case .news:
            PageHeader("新闻中心", eyebrow: "Market Intelligence", summary: "标题优先，来源、证券、时间与 AI 内容清晰分层。") {
                SemanticStatusLabel("48 条", status: .info)
            }
        case .settings:
            WebInspiredHero("设置", eyebrow: "Preferences", summary: "本机外观与服务端配置分层保存，变更后回读确认。") {
                SemanticStatusLabel("已同步", status: .live)
            } actions: {
                EmptyView()
            }
        }
    }

    private var overview: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.section) {
            MetricGrid([
                .init(label: "组合市值", value: FinancialValueFormatter.amount(128_450, currency: "USD"), status: .positive),
                .init(label: "今日盈亏", value: FinancialValueFormatter.amount(1284, currency: "USD"), status: .positive),
                .init(label: "异动", value: .init(text: "3 条"), status: .warning),
            ])
            .padding(StockMonitorSpacing.large)
            .stockMonitorCard()
            SectionHeader("值得关注的变化", explanation: "按影响程度排序，点击证券进入研究窗口。")
            sampleRows
        }
    }

    private var holdings: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.medium) {
            HStack {
                Picker("账户", selection: .constant("主要组合")) { Text("主要组合").tag("主要组合") }
                Spacer()
                Text("4 只持仓").stockMonitorTypography(.metadata)
            }
            .stockMonitorFilterBar()
            sampleRows
            MetadataStrip([
                .init(label: "基础币种", value: "USD"),
                .init(label: "JPY 汇率", value: "已缓存 · 12 分钟前"),
                .init(label: "估值覆盖", value: "100%"),
            ])
        }
    }

    private var news: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.medium) {
            HStack {
                Picker("范围", selection: .constant("市场")) { Text("市场").tag("市场"); Text("个股").tag("个股") }
                    .pickerStyle(.segmented)
                TextField("主题筛选", text: .constant("earnings"))
                Button("应用") {}.buttonStyle(.borderedProminent)
            }
            .stockMonitorFilterBar()
            VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                Text("大型科技公司最新财报与资本开支变化").font(.title3.weight(.semibold))
                Text("AAPL · Reuters · 14:20").stockMonitorTypography(.metadata)
                Divider()
                Text("摘要聚焦收入、利润率和管理层指引。AI 内容与原文摘要分区显示，并保留来源与时间。")
                    .stockMonitorTypography(.body)
            }
            .padding(StockMonitorSpacing.large)
            .stockMonitorCard()
        }
    }

    private var settings: some View {
        Form {
            Section("客户端外观") {
                Picker("外观", selection: .constant("system")) { Text("跟随系统").tag("system") }
                Picker("数据密度", selection: .constant("comfortable")) { Text("舒适").tag("comfortable") }
            }
            Section("安全边界") {
                Label("服务端密钥不会显示或缓存到此 Mac。", systemImage: "lock.shield")
            }
        }
        .formStyle(.grouped)
        .padding(StockMonitorSpacing.medium)
        .stockMonitorCard()
    }

    private var sampleRows: some View {
        VStack(spacing: 0) {
            sampleRow("AAPL", name: "Apple", value: "USD 234.12", change: "+1.8%")
            Divider()
            sampleRow("1578.T", name: "上场日经二倍", value: "JPY 3,412", change: "-0.6%")
            Divider()
            sampleRow("MSFT", name: "Microsoft", value: "USD 518.30", change: "+0.4%")
        }
        .padding(.horizontal, StockMonitorSpacing.medium)
        .stockMonitorCard()
    }

    private func sampleRow(_ symbol: String, name: String, value: String, change: String) -> some View {
        HStack(spacing: StockMonitorSpacing.medium) {
            VStack(alignment: .leading) {
                Text(symbol).fontWeight(.semibold)
                Text(name).stockMonitorTypography(.metadata)
            }
            Spacer()
            Text(value).financialFigures()
            Text(change)
                .financialFigures()
                .foregroundStyle(change.hasPrefix("+") ? StockMonitorChartPalette.positive : StockMonitorChartPalette.negative)
                .frame(width: 70, alignment: .trailing)
        }
        .padding(.vertical, StockMonitorSpacing.regular)
    }
}
