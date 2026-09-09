import Foundation
import StockMonitorCore

/// Goal M5 boundary. The Mac client transports server-owned state and never
/// carries business algorithms, broker credentials, provider keys, or proxy config.
public actor GoalM5Service {
    public let authSession: AuthSession
    private let streamer: any SSEStreaming

    public init(authSession: AuthSession, streamer: any SSEStreaming = URLSessionSSEStreamer()) {
        self.authSession = authSession
        self.streamer = streamer
    }

    public func load(_ endpoint: WorkspaceEndpoint) async throws -> JSONValue {
        try await authSession.authorizedGet(JSONValue.self, path: endpoint.path, queryItems: endpoint.query)
    }

    public func perform(_ action: WorkspaceAction) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: action.path, method: action.method,
            body: action.body, idempotent: true
        )
    }

    public func tradeLogs() async throws -> JSONValue {
        try await authSession.authorizedGet(JSONValue.self, path: "/api/trade-logs")
    }

    public func updateTradeLog(_ draft: TradeLogDraft) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: "/api/trade-logs/\(draft.id)", method: .patch,
            body: draft.requestBody, idempotent: true
        )
    }

    public func summarizeTradeLog(id: Int) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: "/api/trade-logs/\(id)/summarize", method: .post,
            body: EmptyRequestBody(), idempotent: true
        )
    }

    public func conversations(page: Int = 1) async throws -> JSONValue {
        try await authSession.authorizedGet(
            JSONValue.self, path: "/api/ai/v1/conversations",
            queryItems: [.init(name: "page", value: String(page)), .init(name: "limit", value: "40")]
        )
    }

    public func createConversation() async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: "/api/ai/v1/conversations", method: .post,
            body: AIConversationCreateRequest(), idempotent: true
        )
    }

    public func messages(conversationID: Int, page: Int = 1) async throws -> JSONValue {
        try await authSession.authorizedGet(
            JSONValue.self, path: "/api/ai/v1/conversations/\(conversationID)/messages",
            queryItems: [
                .init(name: "page", value: String(page)), .init(name: "limit", value: "50"),
                .init(name: "rich_content", value: "true"),
            ]
        )
    }

    public func activeGeneration(conversationID: Int) async throws -> JSONValue {
        try await authSession.authorizedGet(
            JSONValue.self, path: "/api/ai/v1/conversations/\(conversationID)/active-generation"
        )
    }

    public func stop(conversationID: Int) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: "/api/ai/v1/conversations/\(conversationID)/stop",
            method: .post, body: EmptyRequestBody(), idempotent: true
        )
    }

    public func archive(conversationID: Int) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: "/api/ai/v1/conversations/\(conversationID)/archive",
            method: .post, body: EmptyRequestBody(), idempotent: true
        )
    }

    public func regenerate(conversationID: Int, messageID: Int) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self,
            path: "/api/ai/v1/conversations/\(conversationID)/messages/\(messageID)/regenerate",
            method: .post,
            body: JSONValue.object(["stream": .bool(false)]), idempotent: true
        )
    }

    public func streamMessage(
        conversationID: Int, message: String, model: String?, webAccessMode: String,
        activeSymbol: String?, deepSearchConfirmed: Bool = false
    ) async throws -> AsyncThrowingStream<ServerSentEvent, Error> {
        let request = try await authSession.authorizedStreamingRequest(
            path: "/api/ai/v1/conversations/\(conversationID)/messages", method: .post,
            body: AIMessageRequest(
                message: message, model: model, webAccessMode: webAccessMode,
                activeSymbol: activeSymbol, deepSearchConfirmed: deepSearchConfirmed
            )
        )
        return streamer.events(for: request)
    }

    public func deepRun(_ runID: String) async throws -> JSONValue {
        try await authSession.authorizedGet(JSONValue.self, path: "/api/external-search/v1/deep-runs/\(runID)")
    }

    public func cancelDeepRun(_ runID: String) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: "/api/external-search/v1/deep-runs/\(runID)/cancel",
            method: .post, body: EmptyRequestBody(), idempotent: true
        )
    }

    public func job(path: String) async throws -> JSONValue {
        try await authSession.authorizedGet(JSONValue.self, path: path)
    }
}

public extension JSONValue {
    func value(at key: String) -> JSONValue? {
        objectValue[key]
    }

    var intValue: Int? {
        numberValue.map(Int.init)
    }

    var boolValue: Bool? {
        if case let .bool(value) = self {
            value
        } else {
            nil
        }
    }
}
