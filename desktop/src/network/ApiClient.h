#pragma once

#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QObject>
#include <functional>
#include <optional>
#include <QVector>

#include "network/ApiError.h"
#include "network/RequestHandle.h"

class AppEnvironment;

struct LoginDto {
    QString token;
    QString refreshToken;
    QString username;
    QString role;
    qint64 expiresAtMs = 0;  // 0 when the server omits expires_at
};

struct UserDto {
    qint64 id = 0;
    QString username;
    QString role;
};

// Generic HTTPS JSON transport for the FastAPI backend.
//
// - GET requests declared retryable get bounded exponential backoff with
//   jitter; POST mutations are never auto-replayed (no idempotency keys).
// - A 401 triggers a single-flight refresh-token POST; waiting GETs are
//   replayed exactly once with the new access token. A definite refresh
//   failure emits authSessionExpired() and fails the waiters.
// - A network-level refresh failure keeps the session intact (offline), it
//   never logs the user out.
class ApiClient final : public QObject
{
    Q_OBJECT

public:
    using JsonCallback = std::function<void(const ApiError &, const QJsonObject &)>;

    struct RequestOptions {
        QString name;               // stable label used in errors
        bool authenticated = true;  // attach Bearer access token
        bool retryable = false;     // only for idempotent GETs
        int maxAttempts = 3;
    };

    explicit ApiClient(QObject *parent = nullptr);

    void setEnvironment(AppEnvironment *environment);

    // Wired by SessionStore; keep the transport free of session state.
    void setAccessTokenProvider(std::function<QString()> provider);
    void setRefreshTokenProvider(std::function<QString()> provider);
    void setAccessTokenSink(std::function<void(const QString &)> sink);
    void setRefreshTokenSink(std::function<void(const QString &)> sink);

    RequestHandle get(const QString &path, const JsonCallback &callback);
    RequestHandle get(const QString &path, const JsonCallback &callback,
                      const RequestOptions &options);
    RequestHandle post(const QString &path, const QJsonObject &body, const JsonCallback &callback);
    RequestHandle post(const QString &path, const QJsonObject &body,
                       const JsonCallback &callback, const RequestOptions &options);

    // Test hooks.
    void setRetryDelays(QVector<int> delaysMs);

    static std::optional<QString> parseStatus(const QJsonObject &json);
    static std::optional<LoginDto> parseLogin(const QJsonObject &json);
    static std::optional<UserDto> parseUser(const QJsonObject &json);

signals:
    void authSessionExpired();  // refresh definitively rejected; UI must log out
    void sessionRefreshed();    // access/refresh tokens rotated via sink callbacks

private:
    struct PendingRequest {
        quint64 id = 0;
        QString path;
        QJsonObject body;
        bool isPost = false;
        RequestOptions options;
        JsonCallback callback;
        int attempt = 0;
        bool refreshed = false;
        QNetworkReply *reply = nullptr;
    };

    void sendRequest(PendingRequest request);
    void onRequestFinished(quint64 id);
    void scheduleRetry(quint64 id);
    void finishRequest(quint64 id, const ApiError &error, const QJsonObject &payload);
    void handleUnauthorized(quint64 id);
    void startRefresh();
    void finishRefresh(bool succeeded);
    void replayRefreshWaiters(bool succeeded);

    QNetworkAccessManager m_network;
    AppEnvironment *m_environment = nullptr;
    std::function<QString()> m_accessTokenProvider;
    std::function<QString()> m_refreshTokenProvider;
    std::function<void(const QString &)> m_accessTokenSink;
    std::function<void(const QString &)> m_refreshTokenSink;

    QHash<quint64, PendingRequest> m_pending;
    QVector<int> m_retryDelaysMs = {500, 1000, 2000};
    quint64 m_nextId = 1;

    enum class RefreshState { Idle, InFlight };
    RefreshState m_refreshState = RefreshState::Idle;
    QNetworkReply *m_refreshReply = nullptr;
    QVector<quint64> m_refreshWaiters;
};
