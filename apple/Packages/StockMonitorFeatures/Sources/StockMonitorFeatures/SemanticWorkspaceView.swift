import StockMonitorCore
import StockMonitorDesign
import SwiftUI

// MARK: - 原始 JSON 诊断视图（仅诊断用途，默认折叠）

/// Debug-only：主页面禁止使用；未识别字段与"原始响应"检查都收在这里。
public struct RawJSONDiagnosticsView: View {
    let value: JSONValue
    var key: String?

    public init(value: JSONValue, key: String? = nil) {
        self.value = value
        self.key = key
    }

    public var body: some View {
        switch value {
        case let .object(object):
            VStack(alignment: .leading, spacing: 10) {
                if let key {
                    Text(key).font(.headline)
                }
                ForEach(object.keys.sorted(), id: \.self) { itemKey in
                    if let item = object[itemKey] {
                        RawJSONDiagnosticsView(value: item, key: itemKey)
                    }
                }
            }
        case let .array(array):
            VStack(alignment: .leading, spacing: 8) {
                if let key {
                    Text("\(key) · \(array.count)").font(.headline)
                }
                if array.isEmpty {
                    Text("数据不足").foregroundStyle(.secondary)
                }
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(array.enumerated()), id: \.offset) { index, item in
                        GroupBox("#\(index + 1)") {
                            RawJSONDiagnosticsView(value: item).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
        default:
            LabeledContent(key ?? "值") {
                Text(value.displayText).textSelection(.enabled).multilineTextAlignment(.trailing)
            }.accessibilityElement(children: .combine)
        }
    }
}

// MARK: - 语义证据视图（R2.1，替代 JSONEvidenceView 主路径）

/// 按字段目录渲染证据对象：首层关键证据 → "更多字段" → "诊断 · 未识别字段"。
public struct SemanticEvidenceView: View {
    let value: JSONValue?
    let domain: SemanticFieldDomain
    var baseCurrency: String?

    public init(value: JSONValue?, domain: SemanticFieldDomain, baseCurrency: String? = nil) {
        self.value = value
        self.domain = domain
        self.baseCurrency = baseCurrency
    }

    public var body: some View {
        let model = SemanticPresentationBuilder.evidence(value, domain: domain, baseCurrency: baseCurrency)
        SemanticEvidenceContentView(model: model)
    }
}

struct SemanticEvidenceContentView: View {
    let model: SemanticEvidenceModel

    var body: some View {
        if model.isEmpty {
            Text("服务端未返回该区块内容")
                .stockMonitorTypography(.metadata)
                .foregroundStyle(.secondary)
                .accessibilityIdentifier("evidence.empty")
        } else {
            VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                ForEach(model.primary) { field in
                    evidenceRow(field)
                }
                ForEach(model.rows, id: \.self) { row in
                    Text(row).stockMonitorTypography(.metadata).textSelection(.enabled)
                }
                if !model.secondary.isEmpty {
                    DisclosureSection("更多字段（\(model.secondary.count)）") {
                        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                            ForEach(model.secondary) { field in
                                evidenceRow(field)
                            }
                        }
                    }
                }
                if !model.unrecognizedKeys.isEmpty {
                    DisclosureSection("诊断 · 未识别字段（\(model.unrecognizedKeys.count)）") {
                        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                            ForEach(model.unrecognizedKeys, id: \.self) { key in
                                Text(key).stockMonitorTypography(.microAnnotation).textSelection(.enabled)
                            }
                        }
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("evidence.semantic")
        }
    }

    private func evidenceRow(_ field: PresentationField) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: StockMonitorSpacing.regular) {
            Text(field.label).stockMonitorTypography(.metadata)
            Spacer(minLength: StockMonitorSpacing.regular)
            VStack(alignment: .trailing, spacing: 1) {
                Text(field.display.text)
                    .stockMonitorTypography(.body)
                    .financialFigures()
                    .multilineTextAlignment(.trailing)
                    .textSelection(.enabled)
                if let qualifier = field.display.qualifier {
                    Text(qualifier).stockMonitorTypography(.microAnnotation)
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(field.label)，\(field.display.accessibilityLabel)")
        .accessibilityIdentifier("evidence.field.\(field.key)")
    }
}

// MARK: - 动态列表（中文列头 + 右对齐数值）

/// R2 阶段的语义列表：列来自字段目录，首列为行标识，数值右对齐 + tabular figures。
/// R6.0 会在列审计中升级为完整 macOS Table（排序/列宽/narrow fallback）。
struct SemanticListView: View {
    @Environment(\.interfaceDensity) private var density
    let list: PresentationList

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            Grid(alignment: .topLeading, horizontalSpacing: StockMonitorSpacing.regular, verticalSpacing: 0) {
                GridRow {
                    ForEach(list.columns, id: \.key) { column in
                        Text(column.label)
                            .stockMonitorTypography(.metricLabel)
                            .frame(
                                minWidth: column.key == list.columns.first?.key ? 120 : 72,
                                maxWidth: column.key == list.columns.first?.key ? 260 : .infinity,
                                alignment: column.key == list.columns.first?.key ? .leading : .trailing
                            )
                            .padding(.vertical, density.rowPadding)
                    }
                }
                Rectangle().fill(StockMonitorSeparator.standard).frame(height: 1)
                ForEach(list.rows) { row in
                    GridRow {
                        Text(row.identity)
                            .stockMonitorTypography(.body)
                            .fontWeight(.medium)
                            .frame(
                                minWidth: 120, maxWidth: 260, alignment: .leading
                            )
                            .padding(.vertical, density.rowPadding)
                        ForEach(Array(row.values.enumerated()), id: \.offset) { _, value in
                            valueCell(value)
                        }
                    }
                    Rectangle().fill(StockMonitorSeparator.standard.opacity(0.5)).frame(height: 1)
                }
            }
            Text("共 \(list.total) 条").stockMonitorTypography(.microAnnotation)
            if let note = list.truncationNote {
                Text(note).stockMonitorTypography(.microAnnotation).foregroundStyle(.orange)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("list.semantic")
    }

    private func valueCell(_ value: FinancialDisplayValue) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            Text(value.text)
                .stockMonitorTypography(.body)
                .financialFigures()
                .frame(minWidth: 72, maxWidth: .infinity, alignment: .trailing)
                .textSelection(.enabled)
            if let qualifier = value.qualifier {
                Text(qualifier).stockMonitorTypography(.microAnnotation)
            }
        }
        .padding(.vertical, density.rowPadding)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(value.accessibilityLabel)
    }
}

// MARK: - 语义工作台内容（R2.0 主路径）

/// 服务端 payload → `WorkspacePresentation` 的语义渲染。raw JSON 只出现在折叠的诊断区。
struct SemanticWorkspaceContentView: View {
    let title: String
    let summary: String?
    let presentation: WorkspacePresentation
    var diagnosticsExpanded = false

    var body: some View {
        PageScaffold(width: StockMonitorContentWidth.wide) {
            PageHeader(title, summary: summary) {
                HStack(spacing: StockMonitorSpacing.small) {
                    if let phase = presentation.jobPhase {
                        JobStateBadge(phase, detail: presentation.jobDetail)
                    }
                }
            }
        } content: {
            SemanticWorkspaceSectionsView(presentation: presentation, diagnosticsExpanded: diagnosticsExpanded)
        }
        .accessibilityIdentifier("workspace.semantic")
    }
}

/// Reusable semantic body for R5 domain workspaces that provide their own single page header and first-screen summary.
struct SemanticWorkspaceSectionsView: View {
    let presentation: WorkspacePresentation
    var diagnosticsExpanded = false
    var suppressSummary = false
    var suppressList = false

    var body: some View {
        if presentation.isEmpty {
            EmptyState("暂无数据", systemImage: "tray", description: presentation.emptyHint ?? "服务端没有返回内容。")
        } else {
            contentSections
        }
    }

    @ViewBuilder private var contentSections: some View {
        ForEach(Array(presentation.warnings.enumerated()), id: \.offset) { _, warning in
            InlineError("服务端警告", message: warning)
        }
        if !suppressSummary, !presentation.summary.isEmpty {
            SectionHeader("关键指标")
            MetricGrid(presentation.summary.map { field in
                MetricItem(label: field.label, value: field.display)
            })
            .accessibilityIdentifier("workspace.summary")
        }
        if !suppressList, let list = presentation.list {
            SectionHeader("记录（\(list.total)）", explanation: list.truncationNote)
            SemanticListView(list: list)
        }
        ForEach(Array(presentation.sections.enumerated()), id: \.element.id) { index, section in
            DisclosureSection(section.title, expanded: index == 0 && presentation.summary.isEmpty) {
                SemanticEvidenceContentView(model: section.evidence)
            }
        }
        if !presentation.provenance.isEmpty {
            SectionHeader("来源与时间")
            MetadataStrip(presentation.provenance.map { field in
                MetadataItem(label: field.label, value: field.display.text)
            })
        }
        ForEach(presentation.limitations, id: \.self) { limitation in
            Text("限制：\(limitation)")
                .stockMonitorTypography(.metadata)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
        diagnosticsSection
    }

    @ViewBuilder private var diagnosticsSection: some View {
        if let raw = presentation.raw {
            DisclosureSection(
                "诊断 · 原始响应\(presentation.diagnostics.isEmpty ? "" : "（未识别字段 \(presentation.diagnostics.count) 个）")",
                expanded: diagnosticsExpanded
            ) {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                    if !presentation.diagnostics.isEmpty {
                        Text("以下服务端字段尚未纳入中文目录：\(presentation.diagnostics.joined(separator: "、"))")
                            .stockMonitorTypography(.microAnnotation)
                            .textSelection(.enabled)
                    }
                    RawJSONDiagnosticsView(value: raw)
                }
            }
        }
    }
}

// MARK: - AI 会话消息（typed 渲染，替代递归 JSON 树）

/// 会话消息按角色分层渲染：角色徽标 → 正文 → 模型/引用/时间元数据。
/// 结构化富内容与未识别字段进入折叠诊断区。
public struct AIConversationMessagesView: View {
    let messages: JSONValue

    public init(messages: JSONValue) {
        self.messages = messages
    }

    public var body: some View {
        let items = messages.objectValue["items"]?.arrayValue ?? messages.arrayValue
        if items.isEmpty {
            EmptyState("暂无消息", systemImage: "bubble.left", description: "在下方输入框发送第一条问题。")
        } else {
            VStack(alignment: .leading, spacing: StockMonitorSpacing.medium) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    AIChatMessageRow(message: item)
                }
            }
        }
    }
}

struct AIChatMessageRow: View {
    let message: JSONValue

    private var object: [String: JSONValue] {
        message.objectValue
    }

    var body: some View {
        HStack(alignment: .top, spacing: StockMonitorSpacing.medium) {
            if userRole {
                Spacer(minLength: 72)
            }
            VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                HStack(spacing: StockMonitorSpacing.small) {
                    roleBadge
                    if let model = object["model"]?.stringValue {
                        Text(model).stockMonitorTypography(.microAnnotation)
                    }
                    Spacer(minLength: StockMonitorSpacing.regular)
                    if let created = object["created_at"]?.stringValue {
                        Text(SemanticFieldFormatter.readableTimestamp(created))
                            .stockMonitorTypography(.microAnnotation)
                    }
                }
                contentText
                metadataStrip
                activityDisclosure
                citationDisclosure
                richContentDisclosure
            }
            .padding(StockMonitorSpacing.regular)
            .frame(maxWidth: userRole ? 560 : 760, alignment: .leading)
            .background(
                userRole ? AnyShapeStyle(.tint.opacity(0.12)) : AnyShapeStyle(.background),
                in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.prominent)
            )
            .overlay {
                RoundedRectangle(cornerRadius: StockMonitorCornerRadius.prominent)
                    .stroke(StockMonitorSeparator.standard.opacity(userRole ? 0.35 : 0.7))
            }
            if !userRole {
                Spacer(minLength: 36)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("ai.message")
    }

    private var userRole: Bool {
        object["role"]?.stringValue == "user"
    }

    @ViewBuilder private var roleBadge: some View {
        let role = object["role"]?.stringValue ?? "unknown"
        let mapping: (label: String, status: SemanticStatusLabel.Status) = switch role {
        case "user": ("用户", .info)
        case "assistant": ("助手", .live)
        case "system": ("系统", .neutral)
        case "tool": ("工具", .warning)
        default: (role, .neutral)
        }
        SemanticStatusLabel(mapping.label, status: mapping.status)
    }

    @ViewBuilder private var contentText: some View {
        let content = object["content"]?.stringValue
        if let content, !content.isEmpty {
            R5MarkdownContent(text: content)
        } else if object["has_partial_content"]?.boolValue == true, let safe = object["error_message_safe"]?.stringValue {
            InlineError("回复中断", message: safe)
        } else {
            Text("（无文本内容）").stockMonitorTypography(.metadata).foregroundStyle(.secondary)
        }
    }

    private var contentParts: [JSONValue] {
        if case let .object(document)? = object["content_parts"], case let .array(parts)? = document["parts"] {
            return parts
        }
        return []
    }

    private var activityParts: [JSONValue] {
        contentParts.filter { part in
            let type = part.objectValue["block"]?.objectValue["block_type"]?.stringValue
                ?? part.objectValue["block_type"]?.stringValue
                ?? part.objectValue["type"]?.stringValue ?? ""
            return type.contains("tool") || type.contains("progress") || type.contains("status")
        }
    }

    private var citations: [String] {
        var values = object["citations"]?.arrayValue.compactMap { item in
            item.stringValue ?? item.objectValue["url"]?.stringValue ?? item.objectValue["title"]?.stringValue
        } ?? []
        for part in contentParts {
            let item = part.objectValue["block"]?.objectValue ?? part.objectValue
            let type = item["block_type"]?.stringValue ?? item["type"]?.stringValue ?? ""
            if type.contains("citation"), let value = item["url"]?.stringValue ?? item["title"]?.stringValue {
                values.append(value)
            }
        }
        return Array(Set(values)).sorted()
    }

    @ViewBuilder private var activityDisclosure: some View {
        if !activityParts.isEmpty {
            DisclosureSection("工具活动（\(activityParts.count)）") {
                TimelineList(activityParts.enumerated().map { index, part in
                    let item = part.objectValue["block"]?.objectValue ?? part.objectValue
                    let title = item["title"]?.stringValue ?? item["tool_name"]?.stringValue ?? "工具步骤 \(index + 1)"
                    let detail = item["message"]?.stringValue ?? item["status"]?.stringValue ?? "已记录"
                    return TimelineEntry(id: "tool-\(index)", title: title, timestamp: "", detail: detail, systemImage: "hammer")
                })
            }
        }
    }

    @ViewBuilder private var citationDisclosure: some View {
        if !citations.isEmpty {
            DisclosureSection("引用（\(citations.count)）") {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                    ForEach(citations, id: \.self) { citation in
                        if let url = URL(string: citation), url.scheme != nil {
                            Link(citation, destination: url).lineLimit(2)
                        } else {
                            Text(citation).textSelection(.enabled)
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder private var metadataStrip: some View {
        if !metadataItems.isEmpty {
            MetadataStrip(metadataItems)
        }
    }

    private var metadataItems: [MetadataItem] {
        var items: [MetadataItem] = []
        if let citations = object["citation_count"]?.intValue, citations > 0 {
            items.append(.init(label: "引用", value: "\(citations)"))
        }
        if let toolCalls = object["tool_call_count"]?.intValue, toolCalls > 0 {
            items.append(.init(label: "工具调用", value: "\(toolCalls)"))
        }
        if let tokens = object["total_tokens"]?.intValue, tokens > 0 {
            items.append(.init(label: "Token", value: "\(tokens)"))
        }
        if let cost = object["external_search_cost_usd"]?.numberValue {
            items.append(.init(label: "外部检索成本", value: FinancialValueFormatter.amount(cost, currency: "USD").text))
        }
        if let status = object["status"]?.stringValue, status != "completed" {
            items.append(.init(label: "状态", value: status))
        }
        return items
    }

    @ViewBuilder private var richContentDisclosure: some View {
        let richParts = contentParts.filter { !activityParts.contains($0) }
        if !richParts.isEmpty {
            DisclosureSection("丰富内容（\(richParts.count) 块）") {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                    ForEach(Array(richParts.prefix(20).enumerated()), id: \.offset) { index, part in
                        R5RichContentBlock(part: part, index: index)
                    }
                }
            }
        }
    }
}

struct AIStreamingResponseView: View {
    let stream: AIStreamSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            HStack {
                SemanticStatusLabel("助手正在生成", status: .info)
                Spacer()
                ProgressView().controlSize(.small)
            }
            R5MarkdownContent(text: stream.answer)
            if let progress = stream.progressMessage {
                Label(progress, systemImage: "magnifyingglass")
                    .stockMonitorTypography(.metadata)
            }
            if !stream.activeTools.isEmpty {
                DisclosureSection("工具活动（\(stream.activeTools.count)）") {
                    TimelineList(stream.activeTools.sorted().enumerated().map { index, tool in
                        TimelineEntry(id: "active-\(index)", title: tool, timestamp: "进行中", detail: "服务端正在执行", systemImage: "hammer")
                    })
                }
            }
        }
        .padding(StockMonitorSpacing.regular)
        .frame(maxWidth: 760, alignment: .leading)
        .stockMonitorSurface(.grouped)
        .accessibilityIdentifier("ai.streaming-response")
    }
}

struct R5MarkdownContent: View {
    let text: String

    private var blocks: [String] {
        text.components(separatedBy: "\n\n").filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                let trimmed = block.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.hasPrefix("#") {
                    Text(trimmed.drop(while: { $0 == "#" || $0 == " " }))
                        .font(.headline)
                        .textSelection(.enabled)
                } else {
                    Text((try? AttributedString(markdown: trimmed)) ?? AttributedString(trimmed))
                        .stockMonitorTypography(.body)
                        .lineSpacing(3)
                        .textSelection(.enabled)
                }
            }
        }
    }
}

struct R5RichContentBlock: View {
    let part: JSONValue
    let index: Int

    var body: some View {
        let item = part.objectValue["block"]?.objectValue ?? part.objectValue
        let type = item["block_type"]?.stringValue ?? item["type"]?.stringValue ?? "内容"
        let title = item["title"]?.stringValue ?? type
        let text = item["text"]?.stringValue ?? item["content"]?.stringValue ?? item["code"]?.stringValue
        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
            Text(title).font(.headline)
            if let text {
                Text(text)
                    .font(type.contains("code") ? .system(.body, design: .monospaced) : .body)
                    .textSelection(.enabled)
            } else {
                Text("结构化内容块 \(index + 1)").stockMonitorTypography(.metadata)
            }
            if let urlString = item["url"]?.stringValue, let url = URL(string: urlString) {
                Link("打开来源", destination: url)
            }
        }
        .padding(StockMonitorSpacing.small)
        .stockMonitorSurface(.content)
    }
}
