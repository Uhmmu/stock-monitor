#include "network/ApiError.h"

#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkReply>

namespace {
QString detailFromBody(const QByteArray &body)
{
    const QJsonDocument document = QJsonDocument::fromJson(body);
    if (!document.isObject())
        return {};
    return document.object().value(QStringLiteral("detail")).toString();
}
}

bool ApiError::isNetworkLevel() const
{
    return code == ApiErrorCode::NetworkUnreachable || code == ApiErrorCode::Timeout
        || code == ApiErrorCode::TlsError;
}

bool ApiError::isRetryable() const
{
    switch (code) {
    case ApiErrorCode::NetworkUnreachable:
    case ApiErrorCode::Timeout:
    case ApiErrorCode::ServerError:
    case ApiErrorCode::RateLimited:
        return true;
    case ApiErrorCode::TlsError:
    case ApiErrorCode::Unauthorized:
    case ApiErrorCode::Forbidden:
    case ApiErrorCode::NotFound:
    case ApiErrorCode::BadRequest:
    case ApiErrorCode::BadResponse:
    case ApiErrorCode::ParseError:
    case ApiErrorCode::Cancelled:
    case ApiErrorCode::Unknown:
        return false;
    }
    return false;
}

QString ApiError::toDisplayString() const
{
    switch (code) {
    case ApiErrorCode::NetworkUnreachable:
        return QObject::tr("无法连接服务器，请检查网络连接。");
    case ApiErrorCode::Timeout:
        return QObject::tr("请求超时。");
    case ApiErrorCode::TlsError:
        return QObject::tr("安全连接失败：%1").arg(message);
    case ApiErrorCode::Unauthorized:
        return message.isEmpty() ? QObject::tr("登录状态无效。") : message;
    case ApiErrorCode::Cancelled:
        return {};
    default:
        break;
    }
    if (!message.isEmpty())
        return message;
    if (httpStatus > 0)
        return QObject::tr("请求失败（HTTP %1）。").arg(httpStatus);
    return QObject::tr("未知错误。");
}

ApiError ApiErrorFactory::fromReply(int networkError, int httpStatus, const QByteArray &body,
                                    const QString &requestName)
{
    ApiError error;
    error.requestName = requestName;
    error.httpStatus = httpStatus;
    error.message = detailFromBody(body);

    if (httpStatus == 0) {
        // Pure transport failure: no HTTP status was received.
        switch (networkError) {
        case QNetworkReply::TimeoutError:
        case QNetworkReply::OperationCanceledError:
        case QNetworkReply::TemporaryNetworkFailureError:
        case QNetworkReply::NetworkSessionFailedError:
        case QNetworkReply::UnknownNetworkError:
            error.code = ApiErrorCode::Timeout;
            break;
        case QNetworkReply::SslHandshakeFailedError:
            error.code = ApiErrorCode::TlsError;
            break;
        default:
            error.code = ApiErrorCode::NetworkUnreachable;
            break;
        }
        if (error.message.isEmpty())
            error.message = QObject::tr("网络错误");
        return error;
    }

    if (httpStatus == 401) error.code = ApiErrorCode::Unauthorized;
    else if (httpStatus == 403) error.code = ApiErrorCode::Forbidden;
    else if (httpStatus == 404) error.code = ApiErrorCode::NotFound;
    else if (httpStatus == 429) error.code = ApiErrorCode::RateLimited;
    else if (httpStatus >= 500) error.code = ApiErrorCode::ServerError;
    else if (httpStatus >= 400) error.code = ApiErrorCode::BadRequest;
    else error.code = ApiErrorCode::BadResponse;

    if (error.message.isEmpty())
        error.message = QObject::tr("请求失败（HTTP %1）。").arg(httpStatus);
    return error;
}

ApiError ApiErrorFactory::network(int networkError, const QString &errorString, const QString &requestName)
{
    return fromReply(networkError, 0, QByteArray(), requestName.isEmpty()
                     ? errorString : requestName + QStringLiteral(": ") + errorString);
}

ApiError ApiErrorFactory::parse(const QString &requestName)
{
    ApiError error;
    error.code = ApiErrorCode::ParseError;
    error.requestName = requestName;
    error.message = QObject::tr("服务器返回了无效 JSON。");
    return error;
}

ApiError ApiErrorFactory::cancelled(const QString &requestName)
{
    ApiError error;
    error.code = ApiErrorCode::Cancelled;
    error.requestName = requestName;
    return error;
}
