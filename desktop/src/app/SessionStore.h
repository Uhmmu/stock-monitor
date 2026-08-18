#pragma once

#include <QObject>

class ApiClient;
class AppEnvironment;

class SessionStore final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool connected READ connected NOTIFY changed)
    Q_PROPERTY(bool authenticated READ authenticated NOTIFY changed)
    Q_PROPERTY(QString statusText READ statusText NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(QString username READ username NOTIFY changed)
    Q_PROPERTY(QString role READ role NOTIFY changed)

public:
    SessionStore(AppEnvironment *environment, ApiClient *api, QObject *parent = nullptr);

    bool busy() const;
    bool connected() const;
    bool authenticated() const;
    QString statusText() const;
    QString error() const;
    QString username() const;
    QString role() const;

    Q_INVOKABLE void testConnection();
    Q_INVOKABLE void login(const QString &username, const QString &password, bool remember);
    Q_INVOKABLE void logout();

signals:
    void changed();

private:
    void fail(const QString &message);

    AppEnvironment *m_environment;
    ApiClient *m_api;
    QString m_token;
    QString m_username;
    QString m_role;
    QString m_statusText;
    QString m_error;
    bool m_busy = false;
    bool m_connected = false;
    bool m_authenticated = false;
};
