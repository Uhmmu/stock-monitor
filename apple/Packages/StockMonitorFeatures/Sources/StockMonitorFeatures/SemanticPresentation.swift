import Foundation
import StockMonitorDesign

// MARK: - 展示模型

/// 语义化展示的单个字段值：中文名称 + 格式化数值 + 口径解释。
public struct PresentationField: Identifiable, Equatable, Sendable {
    public let key: String
    public let label: String
    public let display: FinancialDisplayValue
    public let explanation: String?

    public init(key: String, label: String, display: FinancialDisplayValue, explanation: String? = nil) {
        self.key = key
        self.label = label
        self.display = display
        self.explanation = explanation
    }

    public var id: String {
        key
    }
}

/// R2.1 证据模型：主证据 / 次级证据 / 诊断字段三层，替代按字母序平铺的 JSON 证据。
public struct SemanticEvidenceModel: Equatable, Sendable {
    public let domain: SemanticFieldDomain
    public let primary: [PresentationField]
    public let secondary: [PresentationField]
    public let rows: [String]
    public let unrecognizedKeys: [String]

    public init(
        domain: SemanticFieldDomain, primary: [PresentationField], secondary: [PresentationField],
        rows: [String], unrecognizedKeys: [String]
    ) {
        self.domain = domain
        self.primary = primary
        self.secondary = secondary
        self.rows = rows
        self.unrecognizedKeys = unrecognizedKeys
    }

    public var isEmpty: Bool {
        primary.isEmpty && secondary.isEmpty && rows.isEmpty && unrecognizedKeys.isEmpty
    }

    public static func empty(domain: SemanticFieldDomain) -> SemanticEvidenceModel {
        SemanticEvidenceModel(domain: domain, primary: [], secondary: [], rows: [], unrecognizedKeys: [])
    }
}

/// M5 主列表（持仓、订单、运行等）：中文列头 + 右对齐数值列 + 行标识。
public struct PresentationList: Equatable, Sendable {
    public struct Column: Equatable, Sendable {
        public let key: String
        public let label: String
        public let kind: SemanticFieldKind

        public init(key: String, label: String, kind: SemanticFieldKind) {
            self.key = key
            self.label = label
            self.kind = kind
        }
    }

    public struct Row: Equatable, Sendable, Identifiable {
        public let identity: String
        public let values: [FinancialDisplayValue]
        public var id: String {
            identity
        }
    }

    public let columns: [Column]
    public let rows: [Row]
    public let total: Int
    public let truncationNote: String?

    public init(columns: [Column], rows: [Row], total: Int, truncationNote: String?) {
        self.columns = columns
        self.rows = rows
        self.total = total
        self.truncationNote = truncationNote
    }
}

public struct PresentationSection: Identifiable, Equatable, Sendable {
    public let key: String
    public let title: String
    public let evidence: SemanticEvidenceModel

    public var id: String {
        key
    }
}

/// R2.0 typed presentation model：主摘要 → 列表 → 分区证据 → 来源/限制 → 诊断。
public struct WorkspacePresentation: Equatable, Sendable {
    public let title: String
    public let summary: [PresentationField]
    public let list: PresentationList?
    public let sections: [PresentationSection]
    public let provenance: [PresentationField]
    public let warnings: [String]
    public let limitations: [String]
    public let jobPhase: WorkspaceJobPhase?
    public let jobDetail: String?
    public let diagnostics: [String]
    public let emptyHint: String?
    public let baseCurrency: String?
    public let raw: JSONValue?

    public init(
        title: String, summary: [PresentationField], list: PresentationList?, sections: [PresentationSection],
        provenance: [PresentationField], warnings: [String], limitations: [String],
        jobPhase: WorkspaceJobPhase?, jobDetail: String?, diagnostics: [String],
        emptyHint: String?, baseCurrency: String?, raw: JSONValue?
    ) {
        self.title = title
        self.summary = summary
        self.list = list
        self.sections = sections
        self.provenance = provenance
        self.warnings = warnings
        self.limitations = limitations
        self.jobPhase = jobPhase
        self.jobDetail = jobDetail
        self.diagnostics = diagnostics
        self.emptyHint = emptyHint
        self.baseCurrency = baseCurrency
        self.raw = raw
    }

    public var isEmpty: Bool {
        summary.isEmpty && list == nil && sections.isEmpty && provenance.isEmpty
    }
}

// MARK: - 构建器

/// 每个服务端端点的展示口径：主摘要键、列表列、来源键与警告键。
/// 服务层仍容忍 additive JSON 字段；未登记字段只进入诊断区，不进主路径。
public struct WorkspacePresentationSpec: Equatable, Sendable {
    public let domain: SemanticFieldDomain
    public let summaryKeys: [String]?
    public let listKey: String?
    public let listIdentityKeys: [String]?
    public let listColumnKeys: [String]?
    public let sectionKeys: [String]?
    public let provenanceKeys: [String]?
    public let warningKeys: [String]?
    public let emptyHint: String?

    public init(
        domain: SemanticFieldDomain,
        summaryKeys: [String]? = nil,
        listKey: String? = nil,
        listIdentityKeys: [String]? = nil,
        listColumnKeys: [String]? = nil,
        sectionKeys: [String]? = nil,
        provenanceKeys: [String]? = nil,
        warningKeys: [String]? = nil,
        emptyHint: String? = nil
    ) {
        self.domain = domain
        self.summaryKeys = summaryKeys
        self.listKey = listKey
        self.listIdentityKeys = listIdentityKeys
        self.listColumnKeys = listColumnKeys
        self.sectionKeys = sectionKeys
        self.provenanceKeys = provenanceKeys
        self.warningKeys = warningKeys
        self.emptyHint = emptyHint
    }
}

public enum SemanticPresentationBuilder {
    public static let defaultIdentityKeys = [
        "symbol", "ticker", "instrument_symbol", "normalized_ticker", "raw_ticker",
        "username", "name", "company_name", "title", "display_label", "strategy_key",
        "decision_number", "memory_type", "series_key", "scope_key", "id",
    ]

    public static let defaultProvenanceKeys = [
        "as_of", "asOf", "generated_at", "synced_at", "updated_at", "server_time",
        "latest_sync_at", "price_as_of", "received_at", "next_scheduled_at",
        "account_data_source", "market_price_source", "source", "provider", "data_completeness",
    ]

    public static let defaultWarningKeys = ["warnings", "warning", "failure_reason", "failure_code", "error_message"]

    /// 首屏摘要最多展示的指标数，其余进入分区证据。
    public static let summaryLimit = 8
    /// 列表最多展示行数（超出时截断并说明）。
    public static let listRowLimit = 200
    /// 证据首层字段数，其余进入"更多字段"。
    public static let evidencePrimaryLimit = 8

    public static func presentation(
        title: String, spec: WorkspacePresentationSpec, payload: JSONValue
    ) -> WorkspacePresentation {
        let baseCurrency = payload.objectValue["base_currency"]?.stringValue
            ?? payload.objectValue["currency"]?.stringValue

        let (containerObject, listItems) = unwrapContainer(payload, listKey: spec.listKey)
        let object = containerObject ?? payload.objectValue

        let summaryKeys = spec.summaryKeys ?? SemanticKeyDictionary.primaryKeys(for: spec.domain)
        let provenanceKeys = spec.provenanceKeys ?? defaultProvenanceKeys
        let warningKeys = spec.warningKeys ?? defaultWarningKeys

        var consumed = Set<String>()
        let summary = fields(keys: summaryKeys, in: object, domain: spec.domain, baseCurrency: baseCurrency, consumed: &consumed, limit: summaryLimit)
        let provenance = fields(keys: provenanceKeys, in: object, domain: spec.domain, baseCurrency: baseCurrency, consumed: &consumed)
        let warnings = strings(values: warningKeys.compactMap { object[$0] })
        warningKeys.forEach { _ = consumed.insert($0) }

        var limitations: [String] = []
        if case let .array(items)? = object["limitations"] {
            limitations = items.compactMap(\.stringValue)
            consumed.insert("limitations")
        }
        // discovery/latest 等端点把任务状态与限制放在嵌套的 run/result 里。
        if case let .array(items)? = object["result"]?.objectValue["limitations"] {
            limitations.append(contentsOf: items.compactMap(\.stringValue))
        }

        let jobPhase: WorkspaceJobPhase?
        let jobDetail: String?
        let runObject = object["current_run"]?.objectValue ?? object["run"]?.objectValue
        if let statusValue = object["status"]?.stringValue ?? runObject?["status"]?.stringValue {
            jobPhase = WorkspaceJobPhase(serverStatus: statusValue)
            jobDetail = detailText(for: object)
        } else {
            jobPhase = nil
            jobDetail = nil
        }
        consumed.insert("status")

        let list = listItems.map { items in
            buildList(items: items, spec: spec, domain: spec.domain, baseCurrency: baseCurrency)
        }
        if let listKey = spec.listKey {
            consumed.insert(listKey)
        }
        if object["items"] != nil {
            consumed.insert("items")
        }
        // 分页包装键不进入证据区
        for key in ["total", "page", "limit", "offset", "cursor", "has_more"] {
            if object[key] != nil {
                consumed.insert(key)
            }
        }

        let sections = buildSections(object: object, spec: spec, baseCurrency: baseCurrency, consumed: &consumed)

        let diagnostics = object.keys
            .filter { key in
                guard !consumed.contains(key) else { return false }
                if case .null = object[key] {
                    return false
                }
                return SemanticKeyDictionary.resolve(key: key, domain: spec.domain) == nil
            }
            .sorted()

        return WorkspacePresentation(
            title: title,
            summary: summary,
            list: list,
            sections: sections,
            provenance: provenance,
            warnings: warnings,
            limitations: limitations,
            jobPhase: jobPhase,
            jobDetail: jobDetail,
            diagnostics: diagnostics,
            emptyHint: spec.emptyHint,
            baseCurrency: baseCurrency,
            raw: payload
        )
    }

    // MARK: Evidence（R2.1 证据模型）

    public static func evidence(
        _ value: JSONValue?, domain: SemanticFieldDomain, baseCurrency: String? = nil
    ) -> SemanticEvidenceModel {
        guard let value, value != .null else {
            return .empty(domain: domain)
        }
        switch value {
        case let .object(fields):
            let orderedKeys = orderedKeys(for: fields, domain: domain)
            var primary: [PresentationField] = []
            var secondary: [PresentationField] = []
            let unknown: [String]
            for key in orderedKeys {
                guard let spec = SemanticKeyDictionary.resolve(key: key, domain: domain) else { continue }
                let raw = fields[key] ?? .null
                let state = raw == .null ? SemanticMissingSemantics.state(for: raw, in: fields) : nil
                let display = displayValue(raw, spec: spec, baseCurrency: baseCurrency, state: state)
                let field = PresentationField(key: key, label: spec.label, display: display, explanation: spec.explanation)
                if primary.count < evidencePrimaryLimit {
                    primary.append(field)
                } else {
                    secondary.append(field)
                }
            }
            unknown = fields.keys
                .filter { SemanticKeyDictionary.resolve(key: $0, domain: domain) == nil }
                .sorted()
            if primary.isEmpty, secondary.isEmpty, unknown.isEmpty {
                return .empty(domain: domain)
            }
            return SemanticEvidenceModel(domain: domain, primary: primary, secondary: secondary, rows: [], unrecognizedKeys: unknown)
        case let .array(items):
            if items.isEmpty {
                return SemanticEvidenceModel(domain: domain, primary: [], secondary: [], rows: [], unrecognizedKeys: [])
            }
            let rows = items.prefix(30).map { item in
                switch item {
                case let .object(fields):
                    let ordered = orderedKeys(for: fields, domain: domain)
                    let parts = ordered.compactMap { key -> String? in
                        guard let spec = SemanticKeyDictionary.resolve(key: key, domain: domain) else { return nil }
                        let raw = fields[key] ?? .null
                        guard raw != .null else { return nil }
                        return "\(spec.label) \(displayValue(raw, spec: spec, baseCurrency: baseCurrency, state: nil).text)"
                    }
                    return parts.isEmpty ? item.displayText : parts.joined(separator: " · ")
                default:
                    return item.displayText
                }
            }
            let note = items.count > 30 ? ["共 \(items.count) 条，仅列前 30 条"] : []
            return SemanticEvidenceModel(domain: domain, primary: [], secondary: [], rows: rows + note, unrecognizedKeys: [])
        default:
            let field = PresentationField(
                key: "value", label: "数值",
                display: SemanticFieldFormatter.display(value, spec: .init("value", "数值", .text), baseCurrency: baseCurrency)
            )
            return SemanticEvidenceModel(domain: domain, primary: [field], secondary: [], rows: [], unrecognizedKeys: [])
        }
    }

    // MARK: Internals

    private static func unwrapContainer(_ payload: JSONValue, listKey: String?) -> ([String: JSONValue]?, [JSONValue]?) {
        switch payload {
        case let .array(items):
            return (nil, items)
        case let .object(object):
            if let listKey, case let .array(items)? = object[listKey] {
                var remaining = object
                remaining[listKey] = nil
                return (remaining, items)
            }
            if case let .array(items)? = object["items"] {
                var remaining = object
                remaining["items"] = nil
                return (remaining, items)
            }
            return (object, nil)
        default:
            return (payload.objectValue.isEmpty ? nil : payload.objectValue, nil)
        }
    }

    private static func fields(
        keys: [String], in object: [String: JSONValue], domain: SemanticFieldDomain,
        baseCurrency: String?, consumed: inout Set<String>, limit: Int? = nil
    ) -> [PresentationField] {
        var results: [PresentationField] = []
        for key in keys {
            guard results.count < (limit ?? Int.max) else { break }
            guard let raw = object[key], raw != .null else { continue }
            guard isScalar(raw) else { continue }
            guard let spec = SemanticKeyDictionary.resolve(key: key, domain: domain) else {
                consumed.insert(key)
                continue
            }
            results.append(
                PresentationField(
                    key: key, label: spec.label,
                    display: displayValue(raw, spec: spec, baseCurrency: baseCurrency, state: nil),
                    explanation: spec.explanation
                )
            )
            consumed.insert(key)
        }
        return results
    }

    private static func buildList(
        items: [JSONValue], spec: WorkspacePresentationSpec, domain: SemanticFieldDomain, baseCurrency: String?
    ) -> PresentationList {
        let objectItems = items.compactMap(\.objectValue)
        let columns = listColumns(for: objectItems, spec: spec, domain: domain)
        let identityKeys = spec.listIdentityKeys ?? defaultIdentityKeys
        let rows: [PresentationList.Row] = objectItems.prefix(listRowLimit).map { item in
            let identity = identityKeys.compactMap { key in
                item[key]?.stringValue ?? item[key]?.numberValue.map { $0 == $0.rounded() ? String(Int($0)) : String($0) }
            }.first ?? "—"
            let values = columns.dropFirst().map { column in
                let raw = item[column.key] ?? .null
                let state: FinancialValueState? = raw == .null ? SemanticMissingSemantics.state(for: raw, in: item) : nil
                return displayValue(raw, spec: .init(column.key, column.label, column.kind), baseCurrency: baseCurrency, state: state)
            }
            return PresentationList.Row(identity: identity, values: values)
        }
        let truncationNote = objectItems.count > listRowLimit ? "共 \(objectItems.count) 行，仅展示前 \(listRowLimit) 行" : nil
        return PresentationList(columns: columns, rows: rows, total: objectItems.count, truncationNote: truncationNote)
    }

    private static func listColumns(
        for objectItems: [[String: JSONValue]], spec: WorkspacePresentationSpec, domain: SemanticFieldDomain
    ) -> [PresentationList.Column] {
        let identityKeys = spec.listIdentityKeys ?? defaultIdentityKeys
        let first = objectItems.first ?? [:]

        let identityKey = identityKeys.first { first[$0] != nil } ?? "id"
        var columns: [PresentationList.Column] = []
        if let identitySpec = SemanticKeyDictionary.resolve(key: identityKey, domain: domain) {
            columns.append(.init(key: identityKey, label: identitySpec.label, kind: identitySpec.kind))
        } else {
            columns.append(.init(key: identityKey, label: "名称", kind: .text))
        }

        let preferred = spec.listColumnKeys ?? SemanticKeyDictionary.primaryKeys(for: domain)
        for key in preferred where key != identityKey {
            guard columns.count < 7 else { break }
            guard let raw = first[key], isScalar(raw) || raw == .null else { continue }
            guard let fieldSpec = SemanticKeyDictionary.resolve(key: key, domain: domain) else { continue }
            columns.append(.init(key: key, label: fieldSpec.label, kind: fieldSpec.kind))
        }
        if columns.count == 1 {
            // 没有可用列时退化为对象内已知标量字段，仍使用中文字段目录。
            for key in SemanticKeyDictionary.primaryKeys(for: domain) where key != identityKey {
                guard columns.count < 5 else { break }
                if let fieldSpec = SemanticKeyDictionary.resolve(key: key, domain: domain), first[key] != nil {
                    columns.append(.init(key: key, label: fieldSpec.label, kind: fieldSpec.kind))
                }
            }
        }
        return columns
    }

    private static func buildSections(
        object: [String: JSONValue], spec: WorkspacePresentationSpec, baseCurrency: String?, consumed: inout Set<String>
    ) -> [PresentationSection] {
        let orderedKeys: [String]
        if let sectionKeys = spec.sectionKeys {
            orderedKeys = sectionKeys + object.keys.filter { !sectionKeys.contains($0) }.sorted()
        } else {
            let primary = SemanticKeyDictionary.primaryKeys(for: spec.domain)
            orderedKeys = primary + object.keys.filter { !primary.contains($0) }.sorted()
        }
        var sections: [PresentationSection] = []
        for key in orderedKeys {
            guard !consumed.contains(key), let raw = object[key], raw != .null else { continue }
            switch raw {
            case .object, .array:
                break
            default:
                continue
            }
            let evidence = SemanticPresentationBuilder.evidence(raw, domain: spec.domain, baseCurrency: baseCurrency)
            guard !evidence.isEmpty else { continue }
            let title = SemanticKeyDictionary.resolve(key: key, domain: spec.domain)?.label ?? sectionFallbackTitle(key)
            sections.append(PresentationSection(key: key, title: title, evidence: evidence))
            consumed.insert(key)
        }
        return sections
    }

    /// 目录之外的分区键显示为"其他：key"形式，明确这是未纳入业务目录的数据。
    public static func sectionFallbackTitle(_ key: String) -> String {
        "其他：\(key)"
    }

    private static func orderedKeys(for fields: [String: JSONValue], domain: SemanticFieldDomain) -> [String] {
        let primary = SemanticKeyDictionary.primaryKeys(for: domain)
        let ranked = primary.filter { fields[$0] != nil }
        let rest = fields.keys.filter { !primary.contains($0) }.sorted()
        return ranked + rest
    }

    private static func displayValue(
        _ raw: JSONValue, spec: SemanticFieldSpec, baseCurrency: String?, state: FinancialValueState?
    ) -> FinancialDisplayValue {
        let display = SemanticFieldFormatter.display(raw, spec: spec, baseCurrency: baseCurrency)
        guard raw == .null else { return display }
        let missingState = state ?? SemanticMissingSemantics.state(for: raw, in: [:])
        return FinancialValueFormatter.missing(missingState)
    }

    private static func strings(values: [JSONValue]) -> [String] {
        values.flatMap { value in
            switch value {
            case let .string(string): return [string]
            case let .array(items): return items.compactMap(\.stringValue)
            default: return []
            }
        }
    }

    private static func detailText(for object: [String: JSONValue]) -> String? {
        for key in ["stage", "failure_code", "error_code", "trigger_type"] {
            if let value = object[key]?.stringValue {
                return value
            }
        }
        return nil
    }

    private static func isScalar(_ value: JSONValue) -> Bool {
        switch value {
        case .object, .array: false
        case .string, .number, .bool, .null: true
        }
    }
}
