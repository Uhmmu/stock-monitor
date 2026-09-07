import Foundation

public enum FinancialValueState: String, CaseIterable, Sendable {
    case actual, estimated, stale, missing, notApplicable, notCollected, providerFailed
}

public struct FinancialDisplayValue: Equatable, Sendable {
    public let text: String
    public let qualifier: String?
    public let accessibilityLabel: String

    public init(text: String, qualifier: String? = nil, accessibilityLabel: String? = nil) {
        self.text = text
        self.qualifier = qualifier
        self.accessibilityLabel = accessibilityLabel ?? [text, qualifier].compactMap(\.self).joined(separator: "，")
    }
}

public enum FinancialValueFormatter {
    public static let unavailable = "—"

    public static func price(
        _ value: Double?,
        currency: String,
        precision: Int = 2,
        state: FinancialValueState = .actual
    ) -> FinancialDisplayValue {
        guard let value, value.isFinite else { return missing(state) }
        let number = value.formatted(.number.grouping(.automatic).precision(.fractionLength(precision)))
        return qualified("\(currency.uppercased()) \(number)", state: state)
    }

    public static func amount(_ value: Double?, currency: String, state: FinancialValueState = .actual) -> FinancialDisplayValue {
        guard let value, value.isFinite else { return missing(state) }
        let magnitude = abs(value)
        let scaledAndSuffix: (Double, String) = switch magnitude {
        case 1_000_000_000...: (value / 1_000_000_000, "B")
        case 1_000_000...: (value / 1_000_000, "M")
        case 1000...: (value / 1000, "K")
        default: (value, "")
        }
        let (scaled, suffix) = scaledAndSuffix
        let number = scaled.formatted(.number.grouping(.automatic).precision(.fractionLength(suffix.isEmpty ? 2 : 1)))
        return qualified("\(currency.uppercased()) \(number)\(suffix)", state: state)
    }

    public static func percent(_ decimalValue: Double?, precision: Int = 1, state: FinancialValueState = .actual) -> FinancialDisplayValue {
        guard let decimalValue, decimalValue.isFinite else { return missing(state) }
        let text = decimalValue.formatted(.percent.precision(.fractionLength(precision)).sign(strategy: .always()))
        return qualified(text, state: state)
    }

    public static func multiple(_ value: Double?, precision: Int = 1, state: FinancialValueState = .actual) -> FinancialDisplayValue {
        guard let value, value.isFinite else { return missing(state) }
        return qualified("\(value.formatted(.number.precision(.fractionLength(precision))))×", state: state)
    }

    public static func date(_ value: Date?, state: FinancialValueState = .actual) -> FinancialDisplayValue {
        guard let value else { return missing(state) }
        return qualified(value.formatted(.dateTime.year().month(.twoDigits).day(.twoDigits)), state: state)
    }

    public static func time(_ value: Date?, state: FinancialValueState = .actual) -> FinancialDisplayValue {
        guard let value else { return missing(state) }
        return qualified(value.formatted(.dateTime.hour(.twoDigits(amPM: .omitted)).minute(.twoDigits)), state: state)
    }

    public static func missing(_ state: FinancialValueState = .missing) -> FinancialDisplayValue {
        let reason = switch state {
        case .notApplicable: "不适用"
        case .notCollected: "尚未采集"
        case .providerFailed: "数据源失败"
        case .stale: "旧数据"
        case .estimated: "估算值缺失"
        case .actual, .missing: "数据不足"
        }
        return FinancialDisplayValue(text: unavailable, qualifier: reason)
    }

    private static func qualified(_ text: String, state: FinancialValueState) -> FinancialDisplayValue {
        let qualifier: String? = switch state {
        case .estimated: "估算"
        case .stale: "旧数据"
        case .actual: nil
        case .missing, .notApplicable, .notCollected, .providerFailed: missing(state).qualifier
        }
        return FinancialDisplayValue(text: text, qualifier: qualifier)
    }
}
