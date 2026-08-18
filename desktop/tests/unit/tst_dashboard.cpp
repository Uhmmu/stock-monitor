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
    void parsesPartialPortfolioSummary()
    {
        const QJsonObject json{
            {"base_currency", "usd"},
            {"position_count", 2},
            {"priced_count", 1},
            {"total_market_value", 1500.0},
            {"net_asset_value", 1700.0},
            {"cash", 200.0},
            {"total_unrealized_pnl", 100.0},
            {"has_unpriced_positions", true},
            {"has_unconverted_positions", false},
            {"positions", QJsonArray{
                QJsonObject{{"symbol", " aapl "}, {"total_quantity", 10.0}, {"currency", "usd"},
                            {"current_price", 150.0}, {"previous_close", 148.0},
                            {"daily_change_percent", 1.35}, {"market_value", 1500.0},
                            {"portfolio_weight", 100.0}, {"valuation_available", true},
                            {"day_volume", 2500.0}, {"price_source", "snapshot"},
                            {"price_as_of", "2026-08-19T01:59:00Z"}},
                QJsonObject{{"symbol", "MSFT"}, {"total_quantity", 5.0}, {"currency", "USD"},
                            {"current_price", QJsonValue::Null}, {"previous_close", QJsonValue::Null},
                            {"daily_change_percent", -0.5}, {"market_value", QJsonValue::Null},
                            {"portfolio_weight", QJsonValue::Null}, {"valuation_available", false}},
                QJsonObject{{"price", 1.0}},
            }},
        };
        PortfolioSummaryData summary;
        QVERIFY(DashboardStore::parsePortfolioSummary(json, &summary));
        QCOMPARE(summary.baseCurrency, QString("USD"));
        QCOMPARE(summary.positionCount, 2);
        QCOMPARE(summary.pricedCount, 1);
        QCOMPARE(summary.totalMarketValue, 1500.0);
        QCOMPARE(summary.netAssetValue, 1700.0);
        QCOMPARE(summary.cash, 200.0);
        QVERIFY(summary.hasUnpricedPositions);
        QVERIFY(!summary.hasUnconvertedPositions);
        QCOMPARE(summary.rows.size(), 2);
        QCOMPARE(summary.rows.first().ticker, QString("AAPL"));
        QCOMPARE(summary.rows.first().currency, QString("USD"));
        QCOMPARE(summary.rows.first().quantity, 10.0);
        QCOMPARE(summary.rows.first().marketValue, 1500.0);
        QCOMPARE(summary.rows.first().baselineChangePercent, 1.35);
        QVERIFY(qIsNaN(summary.rows.at(1).price));
        QCOMPARE(summary.rows.at(1).baselineChangePercent, -0.5);
    }

    void rejectsInvalidPortfolioSummary()
    {
        PortfolioSummaryData summary;
        QVERIFY(!DashboardStore::parsePortfolioSummary(QJsonObject{{"positions", QJsonArray{}}},
                                                       &summary));
    }

    void acceptsEmptyPortfolioSummary()
    {
        PortfolioSummaryData summary;
        const QJsonObject json{
            {"base_currency", "USD"},
            {"positions", QJsonArray{}},
        };
        QVERIFY(DashboardStore::parsePortfolioSummary(json, &summary));
        QCOMPARE(summary.positionCount, 0);
        QVERIFY(summary.rows.isEmpty());
    }

    void keepsStaleLastGoodOnRefreshError()
    {
        MockHttpServer server;
        QByteArray request;
        QVERIFY(server.start([&request](const QByteArray &received) -> MockHttpServer::Response {
            request = received;
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
            {"base_currency", "USD"},
            {"position_count", 1},
            {"priced_count", 1},
            {"positions", QJsonArray{QJsonObject{{"symbol", "AAPL"}, {"current_price", 230.0}}}},
        };
        cache.insert("portfolio-summary:v1", QJsonDocument(cached).toJson(QJsonDocument::Compact), {}, 0);

        DashboardStore store(&environment, &api, &cache, [] { return QByteArray("token"); });
        store.setActive(true);
        QVERIFY(store.hasData());
        QVERIFY(store.stale());
        QCOMPARE(store.requestCount(), 1);
        QTRY_VERIFY_WITH_TIMEOUT(!store.busy(), 3000);
        QVERIFY(!store.error().isEmpty());
        QVERIFY(store.hasData());
        QVERIFY(request.startsWith("GET /api/portfolio/summary "));
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

    void usesBaselineChangeAndLiveMarketValue()
    {
        WatchlistQuoteModel model;
        model.setCoalesceIntervalMs(0);
        WatchlistQuoteRow row;
        row.ticker = "AAPL";
        row.quantity = 2;
        row.price = 100;
        row.baselineChangePercent = 3.5;
        row.marketValue = 200;
        model.replaceRows({row});
        QCOMPARE(model.data(model.index(0), WatchlistQuoteModel::ChangePercentRole).toDouble(), 3.5);
        QCOMPARE(model.data(model.index(0), WatchlistQuoteModel::MarketValueRole).toDouble(), 200.0);
        model.applyRealtimeQuote("AAPL", 110, 105, qQNaN(), "live", 2000);
        QCOMPARE(model.data(model.index(0), WatchlistQuoteModel::ChangePercentRole).toDouble(),
                 (110.0 - 105.0) / 105.0 * 100.0);
        QCOMPARE(model.data(model.index(0), WatchlistQuoteModel::MarketValueRole).toDouble(), 220.0);
    }
};

QTEST_GUILESS_MAIN(DashboardTest)
#include "tst_dashboard.moc"
