#include "AppEnvironment.h"

#include <QSettings>

namespace {
constexpr auto DefaultBaseUrl = "http://127.0.0.1:8080";
}

AppEnvironment::AppEnvironment(QObject *parent)
    : QObject(parent)
{
    QSettings settings;
    const QUrl saved(settings.value("connection/baseUrl", DefaultBaseUrl).toString());
    m_baseUrl = isAllowedBaseUrl(saved) ? saved : QUrl(DefaultBaseUrl);
}

QString AppEnvironment::baseUrl() const
{
    QString value = m_baseUrl.toString();
    if (value.endsWith('/'))
        value.chop(1);
    return value;
}

QString AppEnvironment::validationError() const
{
    return m_validationError;
}

QUrl AppEnvironment::apiUrl(const QString &path) const
{
    QUrl url = m_baseUrl;
    QString basePath = url.path();
    if (basePath.endsWith('/'))
        basePath.chop(1);
    QString apiPath = path.trimmed();
    while (apiPath.startsWith('/'))
        apiPath.remove(0, 1);
    url.setPath(basePath + QStringLiteral("/api/") + apiPath);
    url.setQuery({});
    url.setFragment({});
    return url;
}

bool AppEnvironment::setBaseUrl(const QString &value)
{
    QUrl url = QUrl::fromUserInput(value.trimmed());
    if (!isAllowedBaseUrl(url)) {
        setValidationError(tr("生产地址必须使用 HTTPS；HTTP 仅允许本机开发地址。"));
        return false;
    }

    url.setQuery({});
    url.setFragment({});
    if (url.path() == QStringLiteral("/"))
        url.setPath({});
    setValidationError({});
    if (url == m_baseUrl)
        return true;

    m_baseUrl = url;
    QSettings().setValue("connection/baseUrl", baseUrl());
    emit baseUrlChanged();
    return true;
}

bool AppEnvironment::isAllowedBaseUrl(const QUrl &url)
{
    if (!url.isValid() || url.host().isEmpty() || !url.userInfo().isEmpty())
        return false;
    if (url.scheme() == QStringLiteral("https"))
        return true;
    if (url.scheme() != QStringLiteral("http"))
        return false;
    const QString host = url.host().toLower();
    return host == QStringLiteral("localhost") || host == QStringLiteral("127.0.0.1")
        || host == QStringLiteral("::1");
}

void AppEnvironment::setValidationError(const QString &message)
{
    if (m_validationError == message)
        return;
    m_validationError = message;
    emit validationErrorChanged();
}
