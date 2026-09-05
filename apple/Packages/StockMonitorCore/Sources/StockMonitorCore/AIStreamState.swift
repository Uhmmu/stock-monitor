import Foundation

public enum AIStreamPhase: Equatable, Sendable { case idle, streaming, completed, failed(code: String, message: String) }

public struct AIStreamSnapshot: Equatable, Sendable {
    public var phase: AIStreamPhase = .idle
    public var answer = ""
    public var activeTools: Set<String> = []
    public var eventCount = 0
    public init() {}
}

public struct AIStreamStateMachine: Sendable {
    public private(set) var snapshot = AIStreamSnapshot()
    private let knownEvents: Set<String> = [
        "conversation.started", "message.created", "response.started", "context.ready", "model.switched",
        "tool.planning", "tool.started", "tool.completed", "tool.failed", "response.delta", "response.reset",
        "citation.map", "response.block.created", "response.block.completed", "response.rich_content.completed",
        "message.persisted", "response.completed", "error", "deep_search.created", "deep_search.queued",
        "deep_search.started", "deep_search.progress", "deep_search.completed", "deep_search.failed",
        "deep_search.cancelled", "deep_search.cost",
    ]

    public init() {}

    @discardableResult
    public mutating func consume(_ event: ServerSentEvent) -> AIStreamSnapshot {
        guard knownEvents.contains(event.event),
              let object = try? JSONSerialization.jsonObject(with: Data(event.data.utf8)) as? [String: Any]
        else { return snapshot }
        guard snapshot.phase != .completed, !isFailed else { return snapshot }
        snapshot.eventCount += 1
        if snapshot.phase == .idle {
            snapshot.phase = .streaming
        }
        switch event.event {
        case "response.delta": snapshot.answer += object["delta"] as? String ?? ""
        case "response.reset": snapshot.answer = ""
        case "tool.started", "tool.planning":
            if let id = object["tool_call_id"] as? String {
                snapshot.activeTools.insert(id)
            }
        case "tool.completed", "tool.failed":
            if let id = object["tool_call_id"] as? String {
                snapshot.activeTools.remove(id)
            }
        case "response.completed":
            if let answer = object["answer"] as? String {
                snapshot.answer = answer
            }
            snapshot.activeTools.removeAll(); snapshot.phase = .completed
        case "error":
            snapshot.activeTools.removeAll()
            snapshot.phase = .failed(code: object["code"] as? String ?? "AI_STREAM_ERROR", message: object["message"] as? String ?? "服务暂时不可用")
        default: break
        }
        return snapshot
    }

    public mutating func finishTransport() {
        if snapshot.phase == .streaming {
            snapshot.phase = .failed(code: "AI_STREAM_INTERRUPTED", message: "连接已中断，已保留服务端状态。")
        }
    }

    private var isFailed: Bool {
        if case .failed = snapshot.phase {
            true
        } else {
            false
        }
    }
}
