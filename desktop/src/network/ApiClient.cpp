#include "network/ApiClient.h"

#include <QDateTime>
#include <QJsonDocument>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QRandomGenerator>
#include <QTimer>
#include <utility>

#include "app/AppEnvironment.h"

namespace {
constexpr int kRequestTimeoutMs = 30'000;
}

ApiClient::ApiClient(QObject *parent)
    : QObject(parent)
{
}

void ApiClient::setEnvironment(AppEnvironment *environment)
{
    m_environment = environment;
}

void ApiClient::setAccessTokenProvider(std::function<QString()> provider)
{
    m_accessTokenProvider = std::move(provider);
}

void ApiClient::setRefreshTokenProvider(std::function<QString()> provider)
{
    m_refreshTokenProvider = std::move(provider);
}

void ApiClient::setAccessTokenSink(std::function<void(const QString &)> sink)
{
    m_accessTokenSink = std::move(sink);
}

void ApiClient::setRefreshTokenSink(std::function<void(const QString &)> sink)
{
    m_refreshTokenSink = std::move(sink);
}

void ApiClient::setRetryDelays(QVector<int> delaysMs)
{
    m_retryDelaysMs = delaysMs.isEmpty() ? QVector<int>{0} : delaysMs;
}

RequestHandle ApiClient::get(const QString &path, const JsonCallback &callback)
{
    return get(path, callback, RequestOptions{});
}

RequestHandle ApiClient::get(const QString &path, const JsonCallback &callback,
                             const RequestOptions &options)
{
    PendingRequest request;
    request.id = m_nextId++;
    request.path = path;
    request.options = options;
    request.callback = callback;
    sendRequest(std::move(request));
    return RequestHandle(m_pending.value(request.id).reply, request.id, this);
}

RequestHandle ApiClient::post(const QString &path, const QJsonObject &body,
                              const JsonCallback &callback)
{
    return post(path, body, callback, RequestOptions{});
}

RequestHandle ApiClient::post(const QString &path, const QJsonObject &body,
                              const JsonCallback &callback, const RequestOptions &options)
{
    PendingRequest request;
    request.id = m_nextId++;
    request.path = path;
    request.body = body;
    request.method = "POST";
    request.options = options;
    request.callback = callback;
    sendRequest(std::move(request));
    return RequestHandle(m_pending.value(request.id).reply, request.id, this);
}

RequestHandle ApiClient::patch(const QString &path, const QJsonObject &body,
                               const JsonCallback &callback)
{
    return patch(path, body, callback, RequestOptions{});
}

RequestHandle ApiClient::patch(const QString &path, const QJsonObject &body,
                               const JsonCallback &callback, const RequestOptions &options)
{
    PendingRequest request;
    request.id = m_nextId++;
    request.path = path;
    request.body = body;
    request.method = "PATCH";
    request.options = options;
    request.callback = callback;
    sendRequest(std::move(request));
    return RequestHandle(m_pending.value(request.id).reply, request.id, this);
}

RequestHandle ApiClient::remove(const QString &path, const JsonCallback &callback,
                                const RequestOptions &options)
{
    PendingRequest request;
    request.id = m_nextId++;
    request.path = path;
    request.method = "DELETE";
    request.options = options;
    request.callback = callback;
    sendRequest(std::move(request));
    return RequestHandle(m_pending.value(request.id).reply, request.id, this);
}

RequestHandle ApiClient::remove(const QString &path, const JsonCallback &callback)
{
    return remove(path, callback, RequestOptions{});
}

void ApiClient::sendRequest(PendingRequest request)
{
    const quint64 id = request.id;
    const bool hasBody = request.method == "POST" || request.method == "PATCH";
    const QByteArray payload = hasBody
        ? QJsonDocument(request.body).toJson(QJsonDocument::Compact) : QByteArray();

    QUrl url = m_environment->apiUrl(request.path);
    url.setQuery(request.options.query);
    QNetworkRequest networkRequest(url);
    networkRequest.setRawHeader("Accept", "application/json");
    networkRequest.setTransferTimeout(kRequestTimeoutMs);
    if (hasBody)
        networkRequest.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    if (request.options.authenticated && m_accessTokenProvider) {
        const QString token = m_accessTokenProvider();
        if (!token.isEmpty())
            networkRequest.setRawHeader("Authorization", "Bearer " + token.toUtf8());
    }

    QNetworkReply *reply = request.method == "GET"
        ? m_network.get(networkRequest)
        : m_network.sendCustomRequest(networkRequest, request.method, payload);
    request.reply = reply;
    m_pending.insert(id, std::move(request));
    connect(reply, &QNetworkReply::finished, this, [this, id] { onRequestFinished(id); });
}

void ApiClient::onRequestFinished(quint64 id)
{
    if (!m_pending.contains(id))
        return;  // cancelled: handle dropped it
    PendingRequest &request = m_pending[id];
    QNetworkReply *reply = request.reply;
    reply->deleteLater();
    request.reply = nullptr;

    const int httpStatus = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    const QByteArray body = reply->readAll();

    if (reply->error() == QNetworkReply::OperationCanceledError) {
        m_pending.remove(id);
        return;
    }

    ApiError error = ApiErrorFactory::fromReply(
        static_cast<int>(reply->error()), httpStatus, body, request.options.name);

    // 401 with a refresh token available: try the single-flight refresh first.
    if (error.code == ApiErrorCode::Unauthorized && request.method == "GET"
        && request.options.authenticated && !request.refreshed) {
        handleUnauthorized(id);
        return;
    }

    const bool retryableFailure = request.method == "GET" && error.isRetryable()
        && request.options.retryable
        && request.attempt + 1 < request.options.maxAttempts;
    if (retryableFailure) {
        scheduleRetry(id);
        return;
    }

    if (httpStatus == 0 || httpStatus < 200 || httpStatus >= 300) {
        finishRequest(id, error, {});
        return;
    }

    if (body.trimmed().isEmpty()) {
        finishRequest(id, ApiError{}, {});
        return;
    }

    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(body, &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        finishRequest(id, ApiErrorFactory::parse(request.options.name), {});
        return;
    }
    finishRequest(id, ApiError{}, document.object());
}

void ApiClient::scheduleRetry(quint64 id)
{
    PendingRequest &request = m_pending[id];
    request.attempt += 1;
    const int index = qMin(request.attempt - 1, m_retryDelaysMs.size() - 1);
    const int delay = m_retryDelaysMs.at(index) + QRandomGenerator::global()->bounded(250);
    QTimer::singleShot(delay, this, [this, id] {
        if (!m_pending.contains(id))
            return;  // cancelled while waiting
        PendingRequest request = m_pending.take(id);
        request.reply = nullptr;
        sendRequest(std::move(request));
    });
}

void ApiClient::finishRequest(quint64 id, const ApiError &error, const QJsonObject &payload)
{
    const PendingRequest request = m_pending.take(id);
    if (request.callback)
        request.callback(error, payload);
}

void ApiClient::handleUnauthorized(quint64 id)
{
    const bool refreshPossible = m_refreshTokenProvider && !m_refreshTokenProvider().isEmpty();
    if (!refreshPossible) {
        finishRequest(id, ApiError{ApiErrorCode::Unauthorized, 401,
                                   tr("登录已过期，请重新登录。"), QStringLiteral("auth")},
                     {});
        return;
    }
    if (m_refreshState == RefreshState::InFlight) {
        m_refreshWaiters.append(id);
        return;
    }
    // The triggering request waits alongside any others that hit 401 meanwhile.
    m_refreshWaiters.append(id);
    startRefresh();
}

void ApiClient::startRefresh()
{
    m_refreshState = RefreshState::InFlight;

    QJsonObject body;
    body.insert(QStringLiteral("refresh_token"), m_refreshTokenProvider());
    QNetworkRequest request(m_environment->apiUrl(QStringLiteral("auth/refresh")));
    request.setRawHeader("Accept", "application/json");
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    request.setTransferTimeout(kRequestTimeoutMs);
    // Never auto-retried: a replayed rotation POST would trip server-side
    // reuse detection and revoke the whole session family.
    m_refreshReply = m_network.post(request, QJsonDocument(body).toJson(QJsonDocument::Compact));

    connect(m_refreshReply, &QNetworkReply::finished, this, [this] {
        QNetworkReply *reply = m_refreshReply;
        m_refreshReply = nullptr;
        reply->deleteLater();

        const int httpStatus = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const QByteArray bodyBytes = reply->readAll();
        if (reply->error() == QNetworkReply::OperationCanceledError) {
            m_refreshState = RefreshState::Idle;
            replayRefreshWaiters(false);
            return;
        }
        if ((httpStatus < 200 || httpStatus >= 300)) {
            const bool definiteRejection = httpStatus == 401 || httpStatus == 400 || httpStatus == 403;
            m_refreshState = RefreshState::Idle;
            if (definiteRejection) {
                emit authSessionExpired();
                replayRefreshWaiters(false);
            } else {
                // Server/network trouble during refresh: stay logged in offline.
                const ApiError error = ApiErrorFactory::fromReply(static_cast<int>(reply->error()),
                                                                  httpStatus, bodyBytes,
                                                                  QStringLiteral("auth/refresh"));
                for (const quint64 id : std::as_const(m_refreshWaiters)) {
                    if (m_pending.contains(id))
                        finishRequest(id, error, {});
                }
                m_refreshWaiters.clear();
            }
            return;
        }

        QJsonParseError parseError;
        const QJsonDocument document = QJsonDocument::fromJson(bodyBytes, &parseError);
        const auto login = document.isObject() ? parseLogin(document.object()) : std::nullopt;
        if (parseError.error != QJsonParseError::NoError || !login) {
            m_refreshState = RefreshState::Idle;
            for (const quint64 id : std::as_const(m_refreshWaiters)) {
                if (m_pending.contains(id))
                    finishRequest(id, ApiErrorFactory::parse(QStringLiteral("auth/refresh")), {});
            }
            m_refreshWaiters.clear();
            return;
        }
        if (m_accessTokenSink)
            m_accessTokenSink(login->token);
        if (m_refreshTokenSink)
            m_refreshTokenSink(login->refreshToken);
        m_refreshState = RefreshState::Idle;
        emit sessionRefreshed();
        replayRefreshWaiters(true);
    });
}

void ApiClient::replayRefreshWaiters(bool succeeded)
{
    const QVector<quint64> waiters = std::exchange(m_refreshWaiters, {});
    for (const quint64 id : waiters) {
        if (!m_pending.contains(id))
            continue;
        if (succeeded) {
            PendingRequest request = m_pending.take(id);
            request.refreshed = true;  // one replay only; second 401 is final
            sendRequest(std::move(request));
        } else {
            finishRequest(id, ApiError{ApiErrorCode::Unauthorized, 401,
                                       tr("登录已过期，请重新登录。"), QStringLiteral("auth")},
                          {});
        }
    }
}

std::optional<QString> ApiClient::parseStatus(const QJsonObject &json)
{
    const QString status = json.value(QStringLiteral("status")).toString();
    return status.isEmpty() ? std::nullopt : std::optional(status);
}

std::optional<LoginDto> ApiClient::parseLogin(const QJsonObject &json)
{
    LoginDto value;
    value.token = json.value(QStringLiteral("token")).toString();
    value.refreshToken = json.value(QStringLiteral("refresh_token")).toString();
    value.username = json.value(QStringLiteral("username")).toString();
    value.role = json.value(QStringLiteral("role")).toString();
    const QString expiresAt = json.value(QStringLiteral("expires_at")).toString();
    if (!expiresAt.isEmpty())
        value.expiresAtMs = QDateTime::fromString(expiresAt, Qt::ISODateWithMs).toMSecsSinceEpoch();
    // refresh_token absent = legacy server without token lifecycle; still usable.
    if (value.token.isEmpty() || value.username.isEmpty() || value.role.isEmpty())
        return std::nullopt;
    return value;
}

std::optional<UserDto> ApiClient::parseUser(const QJsonObject &json)
{
    UserDto value{json.value(QStringLiteral("id")).toInteger(),
                  json.value(QStringLiteral("username")).toString(),
                  json.value(QStringLiteral("role")).toString()};
    if (value.id <= 0 || value.username.isEmpty() || value.role.isEmpty())
        return std::nullopt;
    return value;
}
