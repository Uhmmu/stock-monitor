import SwiftUI

// MARK: - R6.0 表格列规范

/// 表格列在业务上的角色：主列承载对象身份，比较列承载可比数值，
/// metadata 列承载来源/日期等上下文，action 列承载操作。
public enum TableColumnRole: String, CaseIterable, Sendable {
    case main, comparison, metadata, action

    public var title: String {
        switch self {
        case .main: "主列"
        case .comparison: "比较列"
        case .metadata: "元数据列"
        case .action: "操作列"
        }
    }
}

/// 列对齐策略：数值列右对齐 + tabular figures，文本列左对齐。
public enum TableColumnAlignment: String, CaseIterable, Sendable {
    case leading, trailing
}

/// 单个表格列的完整展示规范，供列审计与实现共同引用。
public struct TableColumnSpec: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let role: TableColumnRole
    public let alignment: TableColumnAlignment
    public let minWidth: CGFloat?
    public let idealWidth: CGFloat?
    public let monospacedDigits: Bool
    public let sortableKey: String?

    public init(
        id: String,
        title: String,
        role: TableColumnRole,
        alignment: TableColumnAlignment = .leading,
        minWidth: CGFloat? = nil,
        idealWidth: CGFloat? = nil,
        monospacedDigits: Bool = false,
        sortableKey: String? = nil
    ) {
        self.id = id; self.title = title; self.role = role; self.alignment = alignment
        self.minWidth = minWidth; self.idealWidth = idealWidth
        self.monospacedDigits = monospacedDigits; self.sortableKey = sortableKey
    }
}

/// 窄窗口下多列表格的降级策略。
public enum TableNarrowStrategy: String, CaseIterable, Sendable {
    /// 保持 Table，靠列宽与横向滚动（列数 ≤ 6 且主列固定）。
    case keepTable
    /// 折叠为 key-value 列表，主列做标题（列数 ≥ 7 或数值密集）。
    case collapseToDetailRows
    /// 进入 inspector/detail 层（R3 已定义的页面使用）。
    case deferToDetail

    public var title: String {
        switch self {
        case .keepTable: "保留表格（列宽优先级 + 横向滚动）"
        case .collapseToDetailRows: "折叠为主列 + 明细行"
        case .deferToDetail: "次级列进入详情层"
        }
    }
}

/// 数字单元格：右对齐、tabular figures、缺失值降级为次要色「数据不足」。
public struct NumericTableCell: View {
    private let text: String
    private let missing: Bool

    public init(_ text: String, missing: Bool = false) {
        self.text = text; self.missing = missing
    }

    public init(value: Double?, digits: Int = 2, compact: Bool = false) {
        if let value {
            let format: FloatingPointFormatStyle<Double> = if compact {
                .number.notation(.compactName).precision(.fractionLength(digits))
            } else {
                .number.precision(.fractionLength(digits))
            }
            text = value.formatted(format)
            missing = false
        } else {
            text = "数据不足"
            missing = true
        }
    }

    /// 百分比单元格：小数形式（0.45 → 45.0%），缺失时同上下文降级。
    public init(percent decimal: Double?, digits: Int = 1) {
        if let decimal {
            text = decimal.formatted(.percent.precision(.fractionLength(digits)))
            missing = false
        } else {
            text = "数据不足"
            missing = true
        }
    }

    public var body: some View {
        Text(text)
            .financialFigures()
            .foregroundStyle(missing ? AnyShapeStyle(.secondary) : AnyShapeStyle(.primary))
            .frame(maxWidth: .infinity, alignment: .trailing)
            .accessibilityElement(children: .combine)
            .accessibilityLabel(missing ? "数据不足" : text)
    }
}

/// 表格截断脚注：前 N 条说明或数据截至时间，不截断到无法恢复。
public struct TableTruncationFooter: View {
    private let text: String

    public init(shown: Int, total: Int) {
        text = "仅展示前 \(shown) 条（共 \(total) 条），完整数据可在服务端导出。"
    }

    public init(asOf: String) {
        text = "数据截至 \(asOf)。"
    }

    public var body: some View {
        Text(text)
            .stockMonitorTypography(.metadata)
            .textSelection(.enabled)
            .accessibilityIdentifier("table.truncation-footer")
    }
}

/// 表格主列单元格：身份信息（名称 + 可选副标题），保持可扫描的视觉重量。
public struct MainTableCell: View {
    private let title: String
    private let subtitle: String?

    public init(_ title: String, subtitle: String? = nil) {
        self.title = title; self.subtitle = subtitle
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title).fontWeight(.medium).textSelection(.enabled)
            if let subtitle, !subtitle.isEmpty {
                Text(subtitle).stockMonitorTypography(.microAnnotation)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(subtitle.map { "\(title)，\($0)" } ?? title)
    }
}
