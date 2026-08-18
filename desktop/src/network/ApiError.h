#pragma once

#include <QString>

// Stable, client-side error taxonomy mapped from QNetworkReply/HTTP/JSON
// outcomes. UI code must branch on `code`, never on message strings.
enum class ApiErrorCode {
    NetworkUnreachable,
    Timeout,
    TlsError,
    Unauthorized,     // 401: session may be recoverable via refresh
    Forbidden,        // 403
    NotFound,         // 404
    BadRequest,       // 4xx other than the above
    RateLimited,      // 429
    ServerError,      // 5xx
    BadResponse,      // 2xx with invalid body
    ParseError,
    Cancelled,
    Unknown,
};

struct ApiError {
    ApiErrorCode code = ApiErrorCode::Unknown;
    int httpStatus = 0;
    QString message;
    QString requestName;

    bool isNetworkLevel() const;
    bool isRetryable() const;  // safe to retry for idempotent requests only
    QString toDisplayString() const;
};

namespace ApiErrorFactory {
// Map a finished reply state to an ApiError. `body` is used for detail text.
ApiError fromReply(int networkError, int httpStatus, const QByteArray &body,
                   const QString &requestName);
ApiError network(int networkError, const QString &errorString, const QString &requestName);
ApiError parse(const QString &requestName);
ApiError cancelled(const QString &requestName);
}
