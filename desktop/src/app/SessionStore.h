#pragma once

#include <QByteArray>
#include <QObject>

#include "app/TokenVault.h"

class ApiClient;
class AppEnvironment;
class CacheStore;

// Authentication state machine. The access token lives in memory only; the
// refresh token additionally lives in the OS keyring when the user asked to
// be remembered and a Secret Service is available (fail-closed: otherwise
// session-only, never a plaintext file).
class SessionStore final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool connected READ connected NOTIFY changed)
    Q_PROPERTY(bool authenticated READ authenticated NOTIFY changed)
    Q_PROPERTY(bool restoring READ restoring NOTIFY changed)
    Q_PROPERTY(bool offline READ offline NOTIFY changed)
    Q_PROPERTY(bool sessionOnly READ sessionOnly NOTIFY changed)
    Q_PROPERTY(QString statusText READ statusText NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(QString username READ username NOTIFY changed)
    Q_PROPERTY(QString role READ role NOTIFY changed)

public:
    SessionStore(AppEnvironment *environment, ApiClient *api, TokenVault *vault,
                 CacheStore *cache, QObject *parent = nullptr);

    bool busy() const { return m_busy; }
    bool connected() const { return m_connected; }
    bool authenticated() const { return m_authenticated; }
    bool restoring() const { return m_restoring; }
    bool offline() const { return m_offline; }
    bool sessionOnly() const { return m_vaultMode == TokenVault::Mode::SessionOnly; }
    QString statusText() const { return m_statusText; }
    QString error() const { return m_error; }
    QString username() const { return m_username; }
    QString role() const { return m_role; }
    QByteArray accessToken() const { return m_accessToken.toUtf8(); }

    Q_INVOKABLE void testConnection();
    Q_INVOKABLE void login(const QString &username, const QString &password, bool remember);
    Q_INVOKABLE void logout();
    // Startup path: ask the vault for a stored refresh token and resume.
    void restoreSession();

signals:
    void changed();
    void authExpired();  // refresh definitively rejected; UI returns to login

private:
    void wireVault();
    void fetchMe();
    void handleAuthExpired();
    void handleNetworkError(const QString &message);
    void fail(const QString &message);
    void resetUserState();
    QString vaultAccount() const;

    AppEnvironment *m_environment;
    ApiClient *m_api;
    TokenVault *m_vault;
    CacheStore *m_cache;
    QString m_accessToken;
    QString m_refreshToken;
    QString m_username;
    QString m_role;
    QString m_statusText;
    QString m_error;
    TokenVault::Mode m_vaultMode = TokenVault::Mode::SessionOnly;
    bool m_busy = false;
    bool m_connected = false;
    bool m_authenticated = false;
    bool m_restoring = false;
    bool m_offline = false;
    bool m_remember = false;
    bool m_expiredHandled = false;
};
