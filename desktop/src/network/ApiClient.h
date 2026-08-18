#pragma once

#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QObject>
#include <functional>
#include <optional>

struct LoginDto {
    QString token;
    QString username;
    QString role;
};

struct UserDto {
    qint64 id = 0;
    QString username;
    QString role;
};

class ApiClient final : public QObject
{
    Q_OBJECT

public:
    explicit ApiClient(QObject *parent = nullptr);

    void getStatus(const QUrl &url, const QString &expectedStatus, const QString &requestName);
    void login(const QUrl &url, const QString &username, const QString &password, bool remember);
    void me(const QUrl &url, const QString &token);

    static std::optional<QString> parseStatus(const QJsonObject &json);
    static std::optional<LoginDto> parseLogin(const QJsonObject &json);
    static std::optional<UserDto> parseUser(const QJsonObject &json);

signals:
    void statusSucceeded(const QString &requestName, const QString &status);
    void loginSucceeded(const QString &token);
    void userSucceeded(qint64 id, const QString &username, const QString &role);
    void requestFailed(const QString &requestName, const QString &message);

private:
    void finishJson(QNetworkReply *reply, const QString &requestName,
                    const std::function<void(const QJsonObject &)> &onSuccess);
    static QString errorMessage(QNetworkReply *reply, const QByteArray &body);

    QNetworkAccessManager m_network;
};
