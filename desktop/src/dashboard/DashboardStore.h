#pragma once

#include <QDateTime>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QObject>
#include <QTimer>
#include <QVariantList>
#include <functional>

#include "models/WatchlistQuoteModel.h"
#include "network/RequestHandle.h"

struct PortfolioSummaryData {
    QString baseCurrency;
    int positionCount = 0;
    int pricedCount = 0;
    double totalMarketValue = qQNaN();
    double netAssetValue = qQNaN();
    double cash = qQNaN();
    double totalUnrealizedPnl = qQNaN();
    bool hasUnpricedPositions = false;
    bool hasUnconvertedPositions = false;
    QVector<WatchlistQuoteRow> rows;
};

class ApiClient;
class AppEnvironment;
class CacheStore;
class SseStream;

class DashboardStore final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool active READ active NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool loaded READ loaded NOTIFY changed)
    Q_PROPERTY(bool hasData READ hasData NOTIFY changed)
    Q_PROPERTY(bool stale READ stale NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(QString streamStatus READ streamStatus NOTIFY changed)
    Q_PROPERTY(qint64 freshnessAgeSeconds READ freshnessAgeSeconds NOTIFY changed)
    Q_PROPERTY(int requestCount READ requestCount NOTIFY changed)
    Q_PROPERTY(QString baseCurrency READ baseCurrency NOTIFY changed)
    Q_PROPERTY(int positionCount READ positionCount NOTIFY changed)
    Q_PROPERTY(int pricedCount READ pricedCount NOTIFY changed)
    Q_PROPERTY(double totalMarketValue READ totalMarketValue NOTIFY changed)
    Q_PROPERTY(double netAssetValue READ netAssetValue NOTIFY changed)
    Q_PROPERTY(double cash READ cash NOTIFY changed)
    Q_PROPERTY(double totalUnrealizedPnl READ totalUnrealizedPnl NOTIFY changed)
    Q_PROPERTY(bool hasUnpricedPositions READ hasUnpricedPositions NOTIFY changed)
    Q_PROPERTY(bool hasUnconvertedPositions READ hasUnconvertedPositions NOTIFY changed)
    Q_PROPERTY(WatchlistQuoteModel *quotes READ quotes CONSTANT)
    Q_PROPERTY(QVariantList recentEvents READ recentEvents NOTIFY changed)

public:
    DashboardStore(AppEnvironment *environment, ApiClient *api, CacheStore *cache,
                   std::function<QByteArray()> tokenProvider, QObject *parent = nullptr);

    bool active() const { return m_active; }
    bool busy() const { return m_busy; }
    bool loaded() const { return m_fetchedAtMs > 0; }
    bool hasData() const { return m_quotes.rowCount() > 0; }
    bool stale() const;
    QString error() const { return m_error; }
    QString streamStatus() const { return m_streamStatus; }
    qint64 freshnessAgeSeconds() const;
    int requestCount() const { return m_requestCount; }
    QString baseCurrency() const { return m_summary.baseCurrency; }
    int positionCount() const { return m_summary.positionCount; }
    int pricedCount() const { return m_summary.pricedCount; }
    double totalMarketValue() const { return m_summary.totalMarketValue; }
    double netAssetValue() const { return m_summary.netAssetValue; }
    double cash() const { return m_summary.cash; }
    double totalUnrealizedPnl() const { return m_summary.totalUnrealizedPnl; }
    bool hasUnpricedPositions() const { return m_summary.hasUnpricedPositions; }
    bool hasUnconvertedPositions() const { return m_summary.hasUnconvertedPositions; }
    WatchlistQuoteModel *quotes() { return &m_quotes; }
    QVariantList recentEvents() const { return m_recentEvents; }

    Q_INVOKABLE void refresh();
    Q_INVOKABLE void setActive(bool active);

    static bool parsePortfolioSummary(const QJsonObject &json, PortfolioSummaryData *summary);

signals:
    void changed();

private:
    void applySummary(const QJsonObject &json, qint64 fetchedAtMs, bool fromCache);
    void loadLastGood();
    void restartStream();
    void stopStream();
    void handleStreamEvent(const QString &eventType, const QString &data);
    static qint64 timestampMs(const QJsonValue &value);

    AppEnvironment *m_environment;
    ApiClient *m_api;
    CacheStore *m_cache;
    std::function<QByteArray()> m_tokenProvider;
    QNetworkAccessManager m_streamNetwork;
    SseStream *m_stream;
    WatchlistQuoteModel m_quotes;
    PortfolioSummaryData m_summary;
    RequestHandle m_request;
    QTimer m_refreshTimer;
    QTimer m_ageTimer;
    QVariantList m_recentEvents;
    qint64 m_fetchedAtMs = 0;
    QString m_streamSymbols;
    QString m_streamStatus = QStringLiteral("idle");
    QString m_error;
    int m_requestCount = 0;
    bool m_active = false;
    bool m_busy = false;
    bool m_failedSinceLastGood = false;
};
