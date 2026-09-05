import Foundation

public enum AsyncJobStatus: String, Codable, Sendable { case pending, running, completed, failed, cancelled }

public struct ActiveJobPollingPolicy: Equatable, Sendable {
    public let initialDelay: TimeInterval
    public let maximumDelay: TimeInterval
    public init(initialDelay: TimeInterval = 1, maximumDelay: TimeInterval = 15) {
        self.initialDelay = initialDelay; self.maximumDelay = maximumDelay
    }

    public func delay(afterAttempt attempt: Int, status: AsyncJobStatus) -> TimeInterval? {
        guard status == .pending || status == .running else { return nil }
        return min(maximumDelay, initialDelay * pow(2, Double(min(attempt, 6))))
    }
}
