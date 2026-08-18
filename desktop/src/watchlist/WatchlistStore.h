#pragma once

#include <QAbstractListModel>
#include <QByteArray>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QObject>
#include <QTimer>
#include <QVariantList>
#include <QVector>
#include <functional>

#include "network/RequestHandle.h"

class ApiClient;
class AppEnvironment;
class SseStream;
struct ApiError;

// A stable, virtualized row model for both the user's watchlist and the
// read-only matched-peer list.  Mutations are deliberately applied only after
// the server response has been reloaded; quote ticks update rows in place.
class WatchlistItemModel final : public QAbstractListModel
{
    Q_OBJECT

public:
    enum Roles {
        IdRole = Qt::UserRole + 1,
        TickerRole,
        CompanyNameRole,
        OfficialSectorRole,
        OfficialIndustryRole,
        UserGroupIdRole,
        DisplayOrderRole,
        IsWatchlistedRole,
        IsPeerReferencedRole,
        PeerReferencedByRole,
        PriceRole,
        ChangePercentRole,
        AlertEnabledRole,
        Threshold20mRole,
        Threshold1hRole,
        ThresholdDayRole,
        HasPriceRole,
        SectionNameRole,
    };

    explicit WatchlistItemModel(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role = Qt::DisplayRole) const override;
    QHash<int, QByteArray> roleNames() const override;

    void replaceRows(const QVariantList &rows);
    void applyQuote(const QString &symbol, double price, double previousClose,
                    qint64 timestampMs);
    QStringList symbols() const;
    Q_INVOKABLE QVariantMap itemAt(int row) const;
    int findByTicker(const QString &ticker) const;

private:
    static QString normalizeTicker(const QString &ticker);
    static QVariant roleValue(const QVariantMap &row, const char *key);
    static bool finiteNumber(const QVariant &value);

    QVector<QVariantMap> m_rows;
    QHash<QString, int> m_byTicker;
};

class WatchlistStore final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool active READ active NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool mutationBusy READ mutationBusy NOTIFY changed)
    Q_PROPERTY(bool loaded READ loaded NOTIFY changed)
    Q_PROPERTY(bool hasData READ hasData NOTIFY changed)
    Q_PROPERTY(bool stale READ stale NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(QString streamStatus READ streamStatus NOTIFY changed)
    Q_PROPERTY(qint64 fetchedAtMs READ fetchedAtMs NOTIFY changed)
    Q_PROPERTY(int watchlistedCount READ watchlistedCount NOTIFY changed)
    Q_PROPERTY(int matchedCount READ matchedCount NOTIFY changed)
    Q_PROPERTY(int sectionCount READ sectionCount NOTIFY changed)
    Q_PROPERTY(QVariantList groups READ groups NOTIFY changed)
    Q_PROPERTY(WatchlistItemModel *watchlisted READ watchlisted CONSTANT)
    Q_PROPERTY(WatchlistItemModel *matched READ matched CONSTANT)
    Q_PROPERTY(QString searchQuery READ searchQuery NOTIFY searchChanged)
    Q_PROPERTY(bool searchBusy READ searchBusy NOTIFY searchChanged)
    Q_PROPERTY(QString searchError READ searchError NOTIFY searchChanged)
    Q_PROPERTY(QVariantList searchResults READ searchResults NOTIFY searchChanged)

public:
    WatchlistStore(AppEnvironment *environment, ApiClient *api,
                   std::function<QByteArray()> tokenProvider,
                   QObject *parent = nullptr);

    bool active() const { return m_active; }
    bool busy() const { return m_busy || m_mutationBusy; }
    bool mutationBusy() const { return m_mutationBusy; }
    bool loaded() const { return m_fetchedAtMs > 0; }
    bool hasData() const { return m_watchlisted.rowCount() > 0 || m_matched.rowCount() > 0; }
    bool stale() const { return m_failedSinceLastGood; }
    QString error() const { return m_error; }
    QString streamStatus() const { return m_streamStatus; }
    qint64 fetchedAtMs() const { return m_fetchedAtMs; }
    int watchlistedCount() const { return m_watchlisted.rowCount(); }
    int matchedCount() const { return m_matched.rowCount(); }
    int sectionCount() const { return m_sectionCount; }
    QVariantList groups() const { return m_groups; }
    WatchlistItemModel *watchlisted() { return &m_watchlisted; }
    WatchlistItemModel *matched() { return &m_matched; }
    QString searchQuery() const { return m_searchQuery; }
    bool searchBusy() const { return m_searchBusy; }
    QString searchError() const { return m_searchError; }
    QVariantList searchResults() const { return m_searchResults; }

    Q_INVOKABLE void refresh();
    Q_INVOKABLE void setActive(bool active);
    Q_INVOKABLE void search(const QString &query);
    Q_INVOKABLE void clearSearch();
    Q_INVOKABLE void addSecurity(const QVariantMap &security);
    Q_INVOKABLE void promoteMatched(const QString &ticker);
    Q_INVOKABLE void createGroup(const QString &name);
    Q_INVOKABLE void renameGroup(int groupId, const QString &name);
    Q_INVOKABLE void deleteGroup(int groupId);
    Q_INVOKABLE void moveGroup(int groupId, int displayOrder);
    Q_INVOKABLE void updateWatchlist(int itemId, const QVariantMap &fields);
    Q_INVOKABLE void moveWatchlist(int itemId, int displayOrder);
    Q_INVOKABLE void removeWatchlist(int itemId);

    // Pure parsers are public so focused tests can validate real backend
    // response shapes without making a network request.
    static bool parseStockManagement(const QJsonObject &json, QVariantList *groups,
                                     QVariantList *watchlisted, QVariantList *matched);
    static QVariantList parseSearchResults(const QJsonObject &json);

signals:
    void changed();
    void searchChanged();

private:
    void finishMutation();
    void failMutation(const ApiError &error);
    void mutate(const QString &path, const QJsonObject &body,
                const QString &requestName);
    void mutateDelete(const QString &path, const QString &requestName);
    void restartStream();
    void stopStream();
    void handleStreamEvent(const QString &eventType, const QString &data);
    static qint64 timestampMs(const QJsonValue &value);

    AppEnvironment *m_environment;
    ApiClient *m_api;
    std::function<QByteArray()> m_tokenProvider;
    QNetworkAccessManager m_streamNetwork;
    SseStream *m_stream;
    WatchlistItemModel m_watchlisted;
    WatchlistItemModel m_matched;
    QVariantList m_groups;
    QVariantList m_searchResults;
    RequestHandle m_request;
    RequestHandle m_mutationRequest;
    RequestHandle m_searchRequest;
    QTimer m_searchTimer;
    QString m_searchQuery;
    QString m_searchError;
    QString m_error;
    QString m_streamSymbols;
    QString m_streamStatus = QStringLiteral("idle");
    qint64 m_fetchedAtMs = 0;
    quint64 m_refreshGeneration = 0;
    quint64 m_searchGeneration = 0;
    bool m_active = false;
    bool m_busy = false;
    bool m_mutationBusy = false;
    bool m_searchBusy = false;
    int m_sectionCount = 0;
    bool m_failedSinceLastGood = false;
};
