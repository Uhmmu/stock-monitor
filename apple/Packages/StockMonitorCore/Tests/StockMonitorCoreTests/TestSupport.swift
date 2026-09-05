import Foundation
@testable import StockMonitorCore

actor StubTransport: HTTPTransport {
    enum Outcome: Sendable {
        case response(HTTPResponse)
        case urlError(Int)
    }

    private var outcomes: [Outcome]
    private(set) var requests: [URLRequest] = []

    init(_ outcomes: [Outcome]) {
        self.outcomes = outcomes
    }

    func data(for request: URLRequest) async throws -> HTTPResponse {
        requests.append(request)
        guard !outcomes.isEmpty else { throw APIError.invalidResponse }
        switch outcomes.removeFirst() {
        case let .response(response): return response
        case let .urlError(code): throw URLError(URLError.Code(rawValue: code))
        }
    }

    func requestCount() -> Int {
        requests.count
    }
}

func jsonResponse(_ json: String, status: Int = 200, headers: [String: String] = [:]) -> StubTransport.Outcome {
    .response(HTTPResponse(data: Data(json.utf8), statusCode: status, headers: headers))
}

let tokenJSON = """
{"token":"access-1","refresh_token":"refresh-1","expires_at":"2027-01-01T00:00:00.123456+00:00",\
"role":"user","username":"alice","future_additive_field":{"nested":true}}
"""

actor SingleFlightTransport: HTTPTransport {
    private(set) var refreshCount = 0

    func data(for request: URLRequest) async throws -> HTTPResponse {
        switch request.url?.path {
        case "/api/auth/login":
            return response(tokenJSON)
        case "/api/auth/refresh":
            refreshCount += 1
            try await Task.sleep(nanoseconds: 50_000_000)
            return response(
                #"{"token":"access-2","refresh_token":"refresh-2","expires_at":"2027-01-01T00:00:00Z","role":"user","username":"alice"}"#
            )
        case "/api/auth/me":
            if request.value(forHTTPHeaderField: "Authorization") == "Bearer access-2" {
                return response(#"{"id":7,"username":"alice","role":"user"}"#)
            }
            return response(#"{"detail":"expired"}"#, status: 401)
        default:
            return response(#"{"detail":"not found"}"#, status: 404)
        }
    }

    private func response(_ json: String, status: Int = 200) -> HTTPResponse {
        HTTPResponse(data: Data(json.utf8), statusCode: status)
    }
}

actor PrivateDataStoreSpy: PrivateDataClearing {
    private(set) var clearCount = 0
    func clearPrivateData() {
        clearCount += 1
    }
}
