#pragma once

#include <QObject>
#include <QUrl>

class AppEnvironment final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString baseUrl READ baseUrl WRITE setBaseUrl NOTIFY baseUrlChanged)
    Q_PROPERTY(QString validationError READ validationError NOTIFY validationErrorChanged)

public:
    explicit AppEnvironment(QObject *parent = nullptr);

    QString baseUrl() const;
    QString validationError() const;
    QUrl apiUrl(const QString &path) const;

    Q_INVOKABLE bool setBaseUrl(const QString &value);
    static bool isAllowedBaseUrl(const QUrl &url);

signals:
    void baseUrlChanged();
    void validationErrorChanged();

private:
    void setValidationError(const QString &message);

    QUrl m_baseUrl;
    QString m_validationError;
};
