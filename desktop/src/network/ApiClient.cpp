#include "ApiClient.h"

#include <QJsonDocument>
#include <QNetworkReply>
#include <QNetworkRequest>

ApiClient::ApiClient(QObject *parent)
    : QObject(parent)
{
}

void ApiClient::getStatus(const QUrl &url, const QString &expectedStatus, const QString &requestName)
{
    QNetworkRequest request(url);
    request.setRawHeader("Accept", "application/json");
    auto *reply = m_network.get(request);
    connect(reply, &QNetworkReply::finished, this, [=, this] {
        finishJson(reply, requestName, [=, this](const QJsonObject &json) {
            const auto status = parseStatus(json);
            if (!status || *status != expectedStatus) {
                emit requestFailed(requestName, tr("服务器返回了无效的状态。"));
                return;
            }
            emit statusSucceeded(requestName, *status);
        });
    });
}

void ApiClient::login(const QUrl &url, const QString &username, const QString &password, bool remember)
{
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    request.setRawHeader("Accept", "application/json");
    const QByteArray body = QJsonDocument(QJsonObject{
        {QStringLiteral("username"), username},
        {QStringLiteral("password"), password},
        {QStringLiteral("remember"), remember},
    }).toJson(QJsonDocument::Compact);
    auto *reply = m_network.post(request, body);
    connect(reply, &QNetworkReply::finished, this, [=, this] {
        finishJson(reply, QStringLiteral("login"), [this](const QJsonObject &json) {
            const auto login = parseLogin(json);
            if (!login) {
                emit requestFailed(QStringLiteral("login"), tr("登录响应缺少必要字段。"));
                return;
            }
            emit loginSucceeded(login->token);
        });
    });
}

void ApiClient::me(const QUrl &url, const QString &token)
{
    QNetworkRequest request(url);
    request.setRawHeader("Accept", "application/json");
    request.setRawHeader("Authorization", "Bearer " + token.toUtf8());
    auto *reply = m_network.get(request);
    connect(reply, &QNetworkReply::finished, this, [=, this] {
        finishJson(reply, QStringLiteral("me"), [this](const QJsonObject &json) {
            const auto user = parseUser(json);
            if (!user) {
                emit requestFailed(QStringLiteral("me"), tr("用户响应缺少必要字段。"));
                return;
            }
            emit userSucceeded(user->id, user->username, user->role);
        });
    });
}

std::optional<QString> ApiClient::parseStatus(const QJsonObject &json)
{
    const QString status = json.value(QStringLiteral("status")).toString();
    return status.isEmpty() ? std::nullopt : std::optional(status);
}

std::optional<LoginDto> ApiClient::parseLogin(const QJsonObject &json)
{
    LoginDto value{json.value(QStringLiteral("token")).toString(),
                   json.value(QStringLiteral("username")).toString(),
                   json.value(QStringLiteral("role")).toString()};
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

void ApiClient::finishJson(QNetworkReply *reply, const QString &requestName,
                           const std::function<void(const QJsonObject &)> &onSuccess)
{
    const QByteArray body = reply->readAll();
    const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    if (reply->error() != QNetworkReply::NoError || status < 200 || status >= 300) {
        emit requestFailed(requestName, errorMessage(reply, body));
        reply->deleteLater();
        return;
    }

    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(body, &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject())
        emit requestFailed(requestName, tr("服务器返回了无效 JSON。"));
    else
        onSuccess(document.object());
    reply->deleteLater();
}

QString ApiClient::errorMessage(QNetworkReply *reply, const QByteArray &body)
{
    const QJsonDocument document = QJsonDocument::fromJson(body);
    if (document.isObject()) {
        const QString detail = document.object().value(QStringLiteral("detail")).toString();
        if (!detail.isEmpty())
            return detail;
    }
    const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    return status > 0 ? tr("请求失败（HTTP %1）。").arg(status) : reply->errorString();
}
