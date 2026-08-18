#include "SessionStore.h"

#include "AppEnvironment.h"
#include "network/ApiClient.h"

SessionStore::SessionStore(AppEnvironment *environment, ApiClient *api, QObject *parent)
    : QObject(parent), m_environment(environment), m_api(api)
{
    connect(api, &ApiClient::statusSucceeded, this,
            [this](const QString &requestName, const QString &) {
        if (requestName == QStringLiteral("health")) {
            m_statusText = tr("服务在线，正在检查数据库…");
            emit changed();
            m_api->getStatus(m_environment->apiUrl(QStringLiteral("readiness")),
                             QStringLiteral("ready"), QStringLiteral("readiness"));
            return;
        }
        if (requestName == QStringLiteral("readiness")) {
            m_busy = false;
            m_connected = true;
            m_error.clear();
            m_statusText = tr("服务和数据库均已就绪。");
            emit changed();
        }
    });
    connect(api, &ApiClient::loginSucceeded, this, [this](const QString &token) {
        m_token = token;
        m_statusText = tr("正在读取当前用户…");
        emit changed();
        m_api->me(m_environment->apiUrl(QStringLiteral("auth/me")), m_token);
    });
    connect(api, &ApiClient::userSucceeded, this,
            [this](qint64, const QString &username, const QString &role) {
        m_busy = false;
        m_connected = true;
        m_authenticated = true;
        m_username = username;
        m_role = role;
        m_error.clear();
        m_statusText = tr("已登录。");
        emit changed();
    });
    connect(api, &ApiClient::requestFailed, this,
            [this](const QString &, const QString &message) { fail(message); });
}

bool SessionStore::busy() const { return m_busy; }
bool SessionStore::connected() const { return m_connected; }
bool SessionStore::authenticated() const { return m_authenticated; }
QString SessionStore::statusText() const { return m_statusText; }
QString SessionStore::error() const { return m_error; }
QString SessionStore::username() const { return m_username; }
QString SessionStore::role() const { return m_role; }

void SessionStore::testConnection()
{
    m_busy = true;
    m_connected = false;
    m_error.clear();
    m_statusText = tr("正在连接服务…");
    emit changed();
    m_api->getStatus(m_environment->apiUrl(QStringLiteral("health")),
                     QStringLiteral("ok"), QStringLiteral("health"));
}

void SessionStore::login(const QString &username, const QString &password, bool remember)
{
    if (username.trimmed().isEmpty() || password.isEmpty()) {
        fail(tr("请输入用户名和密码。"));
        return;
    }
    m_busy = true;
    m_error.clear();
    m_statusText = tr("正在登录…");
    emit changed();
    m_api->login(m_environment->apiUrl(QStringLiteral("auth/login")), username.trimmed(), password, remember);
}

void SessionStore::logout()
{
    m_token.clear();
    m_username.clear();
    m_role.clear();
    m_authenticated = false;
    m_statusText = tr("已退出。令牌未写入磁盘。");
    m_error.clear();
    emit changed();
}

void SessionStore::fail(const QString &message)
{
    m_busy = false;
    m_error = message;
    m_statusText.clear();
    emit changed();
}
