#include <QJsonArray>
#include <QJsonDocument>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include "app/AppEnvironment.h"
#include "cache/CacheStore.h"
#include "dashboard/DashboardStore.h"
#include "network/ApiClient.h"
#include "MockHttpServer.h"

class DashboardTest final : public QObject
{
    Q_OBJECT

private slots:
    void parsesPartialDashboard()
    {
        const QJsonObject json{
            {"market", QJsonObject{{"is_open", true}, {"checked_at", "2026-08-19T02:00:00+00:00"}}},
            {"stocks", QJsonArray{
                QJsonObject{{"ticker", " aapl "}, {"price", 230.5}, {"previous_close", 228.0},
                            {"price_source", "alpaca:iex"}, {"updated_at", "2026-08-19T01:59:00Z"}},
                QJsonObject{{"ticker", "MSFT"}, {"price", QJsonValue::Null}},
                QJsonObject{{"price", 1.0}},
            }},
        };
        bool open = false;
        QDateTime checked;
        QVector<WatchlistQuoteRow> rows;
        QVERIFY(DashboardStore::parseDashboard(json, &open, &checked, &rows));
        QVERIFY(open);
        QCOMPARE(rows.size(), 2);
        QCOMPARE(rows.first().ticker, QString("AAPL"));
        QVERIFY(qIsNaN(rows.at(1).price));
    }

    void rejectsInvalidDashboard()
    {
        bool open = false;
        QDateTime checked;
        QVector<WatchlistQuoteRow> rows;
        QVERIFY(!DashboardStore::parseDashboard(QJsonObject{{"stocks", QJsonArray{}}},
                                                &open, &checked, &rows));
    }

    void acceptsEmptyDashboard()
    {
        bool open = true;
        QDateTime checked;
        QVector<WatchlistQuoteRow> rows;
        const QJsonObject json{
            {"market", QJsonObject{{"is_open", false}, {"checked_at", "2026-08-19T02:00:00Z"}}},
            {"stocks", QJsonArray{}},
        };
        QVERIFY(DashboardStore::parseDashboard(json, &open, &checked, &rows));
        QVERIFY(!open);
        QVERIFY(rows.isEmpty());
    }

    void keepsStaleLastGoodOnRefreshError()
    {
        MockHttpServer server;
        QVERIFY(server.start([](const QByteArray &) -> MockHttpServer::Response {
            return {500, R"({"detail":"offline"})"};
        }));
        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setEnvironment(&environment);
        api.setRetryDelays({0});
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        CacheStore cache;
        cache.setCacheDirectory(directory.path());
        const QJsonObject cached{
            {"market", QJsonObject{{"is_open", false}, {"checked_at", "2026-08-19T02:00:00Z"}}},
            {"stocks", QJsonArray{QJsonObject{{"ticker", "AAPL"}, {"price", 230.0}}}},
        };
        cache.insert("dashboard:v1", QJsonDocument(cached).toJson(QJsonDocument::Compact), {}, 0);

        DashboardStore store(&environment, &api, &cache, [] { return QByteArray("token"); });
        store.setActive(true);
        QVERIFY(store.hasData());
        QVERIFY(store.stale());
        QCOMPARE(store.requestCount(), 1);
        QTRY_VERIFY_WITH_TIMEOUT(!store.busy(), 3000);
        QVERIFY(!store.error().isEmpty());
        QVERIFY(store.hasData());
        store.setActive(false);
    }

    void coalescesHundredSymbolDeltasWithoutReset()
    {
        WatchlistQuoteModel model;
        model.setCoalesceIntervalMs(1);
        QVector<WatchlistQuoteRow> rows;
        for (int i = 0; i < 100; ++i) {
            WatchlistQuoteRow row;
            row.ticker = QStringLiteral("T%1").arg(i, 3, 10, QLatin1Char('0'));
            row.price = 100.0;
            row.previousClose = 99.0;
            row.baseUpdatedAtMs = 1000;
            rows.append(row);
        }
        QSignalSpy resets(&model, &QAbstractItemModel::modelReset);
        QSignalSpy changes(&model, &QAbstractItemModel::dataChanged);
        model.replaceRows(rows);
        QCOMPARE(resets.count(), 1);
        for (int i = 0; i < 100; ++i)
            model.applyRealtimeQuote(rows.at(i).ticker, 101.0 + i, 99.0, 1000 + i,
                                     "test", 2000 + i);
        QCOMPARE(resets.count(), 1);
        QTRY_COMPARE(model.coalescedFlushCount(), 1);
        QCOMPARE(changes.count(), 1);
        model.applyRealtimeQuote("T000", 1.0, 99.0, 1.0, "old", 1500);
        QCOMPARE(model.data(model.index(0), WatchlistQuoteModel::PriceRole).toDouble(), 101.0);
    }

    void preservesNewerLiveValueAcrossDashboardRefresh()
    {
        WatchlistQuoteModel model;
        model.setCoalesceIntervalMs(0);
        WatchlistQuoteRow row;
        row.ticker = "aapl";
        row.price = 100;
        row.baseUpdatedAtMs = 1000;
        model.replaceRows({row});
        model.applyRealtimeQuote("AAPL", 105, qQNaN(), qQNaN(), "live", 3000);
        row.ticker = "AAPL";
        row.price = 101;
        row.baseUpdatedAtMs = 2000;
        model.replaceRows({row});
        QCOMPARE(model.data(model.index(0), WatchlistQuoteModel::PriceRole).toDouble(), 105.0);
    }
};

QTEST_GUILESS_MAIN(DashboardTest)
#include "tst_dashboard.moc"
