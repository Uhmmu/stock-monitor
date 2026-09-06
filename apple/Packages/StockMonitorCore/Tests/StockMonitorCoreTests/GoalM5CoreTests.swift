import Foundation
@testable import StockMonitorCore
import Testing

@Test func goalM5SSEHandlesDuplicateUnknownRichBlocksAndCitationsFailClosed() {
    var machine = AIStreamStateMachine()
    machine.consume(.init(event: "unknown.future.event", data: #"{"payload":"ignored"}"#))
    machine.consume(.init(event: "tool.started", data: #"{"tool_call_id":"search-1"}"#))
    machine.consume(.init(event: "tool.started", data: #"{"tool_call_id":"search-1"}"#))
    machine.consume(.init(event: "citation.map", data: #"{"citations":[{"url":"https://sec.gov/a"},{"title":"missing-url"}]}"#))
    machine.consume(.init(event: "response.block.completed", data: #"{"type":"table","html":"<script>bad()</script>"}"#))
    machine.consume(.init(event: "response.block.completed", data: #"{"type":"table"}"#))
    machine.consume(.init(event: "tool.completed", data: #"{"tool_call_id":"search-1"}"#))
    #expect(machine.snapshot.eventCount == 6)
    #expect(machine.snapshot.activeTools.isEmpty)
    #expect(machine.snapshot.citations == ["https://sec.gov/a", "missing-url"])
    #expect(machine.snapshot.completedBlocks == ["table"])
    #expect(machine.snapshot.answer.isEmpty)
}

@Test func goalM5CancellationWinsAgainstLateTerminalChunk() {
    var machine = AIStreamStateMachine()
    machine.consume(.init(event: "response.delta", data: #"{"delta":"保留内容"}"#))
    machine.consume(.init(event: "error", data: #"{"code":"CANCELLED","message":"已取消"}"#))
    machine.consume(.init(event: "response.completed", data: #"{"answer":"迟到结果"}"#))
    #expect(machine.snapshot.phase == .failed(code: "CANCELLED", message: "已取消"))
    #expect(machine.snapshot.answer == "保留内容")
}

@Test func streamingPostRequestCarriesJSONAndNeverAddsIdempotencyHeader() async throws {
    let configuration = try APIConfiguration(baseURL: #require(URL(string: "https://example.com")), environment: .staging)
    let client = APIClient(configuration: configuration)
    let request = try await client.makeStreamingRequest(
        path: "/api/ai/v1/conversations/3/messages", method: .post,
        body: ["message": "分析", "stream": "true"], accessToken: "access-token"
    )
    #expect(request.httpMethod == "POST")
    #expect(request.value(forHTTPHeaderField: "Accept") == "text/event-stream")
    #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")
    #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer access-token")
    #expect(request.value(forHTTPHeaderField: "Idempotency-Key") == nil)
    let body = try #require(request.httpBody)
    let object = try #require(JSONSerialization.jsonObject(with: body) as? [String: String])
    #expect(object["message"] == "分析")
}
