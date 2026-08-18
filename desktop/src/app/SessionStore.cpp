#include "app/SessionStore.h"

#include <QUrl>

#include "app/AppEnvironment.h"
#include "cache/CacheStore.h"
#include "network/ApiClient.h"

SessionStore::SessionStore(AppEnvironment *environment, ApiClient *api, TokenVault *vault,
                           CacheStore *cache, QObject *parent)
    : QObject(parent), m_environment(environment), m_api(api), m_vault(vault), m_cache(cache)
{
    api->setEnvironment(environment);
    api->setAccessTokenProvider([this] { return m_accessToken; });
    api->setRefreshTokenProvider([this] { return m_refreshToken; });
    api->setAccessTokenSink([this](const QString &token) { m_accessToken = token; });
    api->setRefreshTokenSink([this](const QString &token) {
        m_refreshToken = token;
        if (m_remember)
            m_vault->store(vaultAccount(), token);  // rotate the keyring copy
    });
    connect(api, &ApiClient::authSessionExpired, this, &SessionStore::handleAuthExpired);
    connect(api, &ApiClient::sessionRefreshed, this, [this] {
        m_statusText = tr("会话已自动续期。");
        emit changed();
    });

    m_vaultMode = m_vault->mode();
    connect(m_vault, &TokenVault::modeChanged, this, [this] {
        m_vaultMode = m_vault->mode();
        emit changed();
    });
    wireVault();
}

QString SessionStore::vaultAccount() const
{
    // One stored session per server host; single-user desktop assumption.
    return QStringLiteral("server:") + m_environment->baseUrl().section("//", -1);
}

void SessionStore::testConnection()
{
    m_busy = true;
    m_connected = false;
    m_offline = false;
    m_error.clear();
    m_statusText = tr("正在连接服务…");
    emit changed();
    m_api->get(QStringLiteral("health"),
               [this](const ApiError &error, const QJsonObject &json) {
                   const auto status = ApiClient::parseStatus(json);
                   if (error.code != ApiErrorCode::Cancelled && (!status || *status != QLatin1String("ok"))) {
                       if (error.isNetworkLevel())
                           handleNetworkError(error.toDisplayString());
                       else
                           fail(tr("服务返回了意外状态。"));
                       return;
                   }
                   m_statusText = tr("服务在线，正在检查数据库…");
                   emit changed();
                   m_api->get(QStringLiteral("readiness"),
                              [this](const ApiError &readyError, const QJsonObject &readyJson) {
                                  const auto ready = ApiClient::parseStatus(readyJson);
                                  if (readyError.code != ApiErrorCode::Cancelled
                                      && (!ready || *ready != QLatin1String("ready"))) {
                                      if (readyError.isNetworkLevel())
                                          handleNetworkError(readyError.toDisplayString());
                                      else
                                          fail(tr("数据库未就绪。"));
                                      return;
                                  }
                                  m_busy = false;
                                  m_connected = true;
                                  m_offline = false;
                                  m_error.clear();
                                  m_statusText = tr("服务和数据库均已就绪。");
                                  emit changed();
                              },
                              {.name = QStringLiteral("readiness"), .authenticated = false});
               },
               {.name = QStringLiteral("health"), .authenticated = false});
}

void SessionStore::login(const QString &username, const QString &password, bool remember)
{
    if (username.trimmed().isEmpty() || password.isEmpty()) {
        fail(tr("请输入用户名和密码。"));
        return;
    }
    m_busy = true;
    m_remember = remember;
    m_expiredHandled = false;
    m_error.clear();
    m_statusText = tr("正在登录…");
    emit changed();

    QJsonObject body;
    body.insert(QStringLiteral("username"), username.trimmed());
    body.insert(QStringLiteral("password"), password);
    body.insert(QStringLiteral("remember"), remember);
    m_api->post(QStringLiteral("auth/login"), body,
                [this](const ApiError &error, const QJsonObject &json) {
                    const auto login = ApiClient::parseLogin(json);
                    if (!login) {
                        if (error.code == ApiErrorCode::Cancelled)
                            return;  // superseded; leave state untouched
                        if (error.isNetworkLevel()) {
                            handleNetworkError(error.toDisplayString());
                            return;
                        }
                        fail(error.code == ApiErrorCode::Unauthorized
                             ? error.toDisplayString() : tr("登录响应缺少必要字段。"));
                        return;
                    }
                    m_accessToken = login->token;
                    m_refreshToken = login->refreshToken;
                    m_username = login->username;
                    m_role = login->role;
                    if (m_remember && !login->refreshToken.isEmpty())
                        m_vault->store(vaultAccount(), login->refreshToken);
                    m_statusText = tr("正在读取当前用户…");
                    emit changed();
                    fetchMe();
                },
                {.name = QStringLiteral("login"), .authenticated = false});
}

void SessionStore::restoreSession()
{
    m_restoring = true;
    m_expiredHandled = false;
    m_statusText = tr("正在恢复上次会话…");
    emit changed();
    m_vault->load(vaultAccount());
}

void SessionStore::wireVault()
{
    connect(m_vault, &TokenVault::loaded, this,
            [this](const QString &account, const QString &secret) {
                if (account != vaultAccount() || !m_restoring)
                    return;
                if (secret.isEmpty()) {
                    m_restoring = false;
                    m_statusText.clear();
                    emit changed();
                    return;
                }
                m_refreshToken = secret;
                m_remember = true;
                fetchMe();
            });
}

void SessionStore::fetchMe()
{
    m_api->get(QStringLiteral("auth/me"),
               [this](const ApiError &error, const QJsonObject &json) {
                   const auto user = ApiClient::parseUser(json);
                   if (!user) {
                       if (error.isNetworkLevel()) {
                           handleNetworkError(error.toDisplayString());
                           return;
                       }
                       if (error.code == ApiErrorCode::Unauthorized) {
                           handleAuthExpired();
                           return;
                       }
                       fail(tr("用户响应缺少必要字段。"));
                       return;
                   }
                   m_busy = false;
                   m_restoring = false;
                   m_expiredHandled = false;
                   m_connected = true;
                   m_authenticated = true;
                   m_offline = false;
                   m_username = user->username;
                   m_role = user->role;
                   m_error.clear();
                   m_statusText = tr("已登录。");
                   m_cache->setOwnerScope(QStringLiteral("%1|user:%2")
                                              .arg(m_environment->baseUrl(), user->username));
                   emit changed();
               },
               {.name = QStringLiteral("me")});
}

void SessionStore::logout()
{
    // Server-side revocation is best-effort; local state is cleared regardless.
    if (!m_refreshToken.isEmpty()) {
        QJsonObject body;
        body.insert(QStringLiteral("refresh_token"), m_refreshToken);
        m_api->post(QStringLiteral("auth/logout"), body, [](const ApiError &, const QJsonObject &) {},
                    {.name = QStringLiteral("logout"), .authenticated = false});
    }
    m_vault->clear(vaultAccount());
    m_cache->clearOwner();
    m_accessToken.clear();
    m_refreshToken.clear();
    resetUserState();
    m_statusText = tr("已退出。令牌已从系统钥匙串与内存中清除。");
    m_error.clear();
    emit changed();
}

void SessionStore::handleAuthExpired()
{
    const bool firstNotification = !m_expiredHandled;
    m_expiredHandled = true;  // refresh path + request callback may both arrive
    m_vault->clear(vaultAccount());
    m_cache->clearOwner();
    m_accessToken.clear();
    m_refreshToken.clear();
    resetUserState();
    m_statusText.clear();
    m_error = tr("登录已过期，请重新登录。");
    emit changed();
    if (firstNotification)
        emit authExpired();
}

void SessionStore::handleNetworkError(const QString &message)
{
    m_busy = false;
    m_restoring = false;
    m_offline = true;
    m_connected = false;
    m_error = message;
    m_statusText = tr("离线：无法连接服务器。本地会话已保留，恢复网络后可继续使用。");
    emit changed();
}

void SessionStore::resetUserState()
{
    m_authenticated = false;
    m_busy = false;
    m_restoring = false;
    m_connected = false;
    m_offline = false;
    m_username.clear();
    m_role.clear();
}

void SessionStore::fail(const QString &message)
{
    m_busy = false;
    m_restoring = false;
    m_error = message;
    m_statusText.clear();
    emit changed();
}
