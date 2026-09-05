import Foundation

public enum ResourcePhase<Value: Sendable>: Sendable {
    case idle
    case loading
    case ready(Value, fetchedAt: Date)
    case refreshing(Value, fetchedAt: Date)
    case stale(Value, fetchedAt: Date, reason: String?)
    case failed(APIError, lastGood: Value?, fetchedAt: Date?)

    public var value: Value? {
        switch self {
        case let .ready(value, _), let .refreshing(value, _), let .stale(value, _, _): value
        case let .failed(_, value, _): value
        case .idle, .loading: nil
        }
    }
}

public actor ResourceStore<Key: Hashable & Sendable, Value: Sendable> {
    private var states: [Key: ResourcePhase<Value>] = [:]

    public init() {}

    public func state(for key: Key) -> ResourcePhase<Value> {
        states[key] ?? .idle
    }

    public func beginLoading(_ key: Key) {
        if let current = states[key]?.value {
            states[key] = .refreshing(current, fetchedAt: fetchedAt(for: key) ?? .distantPast)
        } else {
            states[key] = .loading
        }
    }

    public func succeed(_ value: Value, for key: Key, fetchedAt: Date = .now) {
        states[key] = .ready(value, fetchedAt: fetchedAt)
    }

    public func markStale(_ key: Key, reason: String? = nil) {
        guard let value = states[key]?.value else { return }
        states[key] = .stale(value, fetchedAt: fetchedAt(for: key) ?? .distantPast, reason: reason)
    }

    public func fail(_ error: APIError, for key: Key) {
        states[key] = .failed(error, lastGood: states[key]?.value, fetchedAt: fetchedAt(for: key))
    }

    public func removeAll() {
        states.removeAll()
    }

    private func fetchedAt(for key: Key) -> Date? {
        switch states[key] {
        case let .ready(_, date), let .refreshing(_, date), let .stale(_, date, _): date
        case let .failed(_, _, date): date
        case .idle, .loading, nil: nil
        }
    }
}
