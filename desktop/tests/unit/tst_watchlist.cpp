#include <QJsonArray>
#include <QJsonDocument>
#include <QSignalSpy>
#include <QTest>

#include "app/AppEnvironment.h"
#include "network/ApiClient.h"
#include "watchlist/WatchlistStore.h"
#include "MockHttpServer.h"

namespace {

QJsonObject managementFixture()
{
    return {
        {"groups", QJsonArray{QJsonObject{{"id", 4}, {"name", "芯片"}, {"display_order", 0}}}},
        {"watchlisted", QJsonArray{
            QJsonObject{{"ticker", "7203.T"}, {"company_name", "Toyota"},
                         {"official_sector", "Consumer Cyclical"}, {"official_industry", "Auto"},
                         {"display_order", 0}, {"is_watchlisted", true}, {"watchlist_id", 7},
                         {"price", 2500.0}, {"change_percent", 1.2}, {"alert_enabled", true}},
        }},
        {"matched", QJsonArray{
            QJsonObject{{"ticker", "MSFT"}, {"company_name", "Microsoft"},
                         {"peer_referenced_by", QJsonArray{"7203.T"}}, {"is_watchlisted", false}},
        }},
    };
}

} // namespace

class WatchlistTest final : public QObject
{
    Q_OBJECT

private slots:
    void parsesInternationalManagementAndSearchLimit()
    {
        QVariantList groups;
        QVariantList watchlisted;
        QVariantList matched;
        QVERIFY(WatchlistStore::parseStockManagement(managementFixture(), &groups, &watchlisted, &matched));
        QCOMPARE(groups.size(), 1);
        QCOMPARE(watchlisted.size(), 1);
        QCOMPARE(watchlisted.first().toMap().value(QStringLiteral("ticker")).toString(), QString("7203.T"));
        QCOMPARE(watchlisted.first().toMap().value(QStringLiteral("sectionName")).toString(),
                 QString("Consumer Cyclical · Auto"));
        QCOMPARE(matched.first().toMap().value(QStringLiteral("peerReferencedBy")).toStringList(), QStringList{"7203.T"});

        QJsonArray candidates;
        for (int i = 0; i < 12; ++i)
            candidates.append(QJsonObject{{"provider_key", QStringLiteral("yahoo:%1").arg(i)},
                                          {"display_symbol", QStringLiteral("INTL%1.T").arg(i)},
                                          {"display_name", "International"}, {"source", "yahoo"}});
        const QVariantList results = WatchlistStore::parseSearchResults({{"results", candidates}});
        QCOMPARE(results.size(), 8);
        QCOMPARE(results.first().toMap().value(QStringLiteral("display_symbol")).toString(), QString("INTL0.T"));
    }

    void quoteDeltaDoesNotResetRowsOrInventMissingPrice()
    {
        WatchlistItemModel model;
        QSignalSpy resets(&model, &QAbstractItemModel::modelReset);
        const QVariantMap row{{QStringLiteral("id"), 7}, {QStringLiteral("ticker"), "7203.T"},
                              {QStringLiteral("price"), QVariant()}};
        model.replaceRows({row});
        QCOMPARE(resets.count(), 1);
        model.applyQuote("7203.T", qQNaN(), 2500.0, 1000);
        QVERIFY(!model.data(model.index(0), WatchlistItemModel::HasPriceRole).toBool());
        model.applyQuote("7203.T", 2525.0, 2500.0, 2000);
        QCOMPARE(resets.count(), 1);
        QCOMPARE(model.data(model.index(0), WatchlistItemModel::PriceRole).toDouble(), 2525.0);
        QCOMPARE(model.data(model.index(0), WatchlistItemModel::ChangePercentRole).toDouble(), 1.0);
    }

    void keepsTenThousandRowsStableDuringQuoteUpdates()
    {
        WatchlistItemModel model;
        QVariantList rows;
        rows.reserve(10'000);
        for (int i = 0; i < 10'000; ++i)
            rows.append(QVariantMap{{QStringLiteral("id"), i + 1},
                                    {QStringLiteral("ticker"), QStringLiteral("T%1").arg(i)},
                                    {QStringLiteral("price"), 100.0}});
        QSignalSpy resets(&model, &QAbstractItemModel::modelReset);
        model.replaceRows(rows);
        QCOMPARE(model.rowCount(), 10'000);
        QCOMPARE(resets.count(), 1);
        model.applyQuote(QStringLiteral("T9999"), 101.0, 100.0, 2000);
        QCOMPARE(resets.count(), 1);
        QCOMPARE(model.data(model.index(9999), WatchlistItemModel::PriceRole).toDouble(), 101.0);
    }

    void addUsesProviderFieldsAndMutationFailureKeepsRows()
    {
        QByteArray addBody;
        int managementCalls = 0;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (request.startsWith("GET /api/stock-management ")) {
                ++managementCalls;
                return {200, QJsonDocument(managementFixture()).toJson(QJsonDocument::Compact)};
            }
            if (request.startsWith("POST /api/watchlist ")) {
                addBody = request;
                return {201, R"({"id":8,"ticker":"7203.T"})"};
            }
            if (request.startsWith("PATCH /api/watchlist/7 "))
                return {500, R"({"detail":"write failed"})"};
            return {404, R"({"detail":"unexpected"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setEnvironment(&environment);
        api.setRetryDelays({0});
        WatchlistStore store(&environment, &api, [] { return QByteArray(); });
        store.refresh();
        QTRY_VERIFY_WITH_TIMEOUT(store.loaded(), 3000);
        QCOMPARE(store.watchlistedCount(), 1);

        store.addSecurity({{"display_symbol", "7203.T"}, {"source", "yahoo"},
                           {"yahoo_symbol", "7203.T"}, {"security_id", 17}});
        QTRY_VERIFY_WITH_TIMEOUT(!store.mutationBusy(), 3000);
        QTRY_VERIFY_WITH_TIMEOUT(!store.busy(), 3000);
        QVERIFY(addBody.contains("\"security_id\":17"));
        QVERIFY(addBody.contains("\"source\":\"yahoo\""));
        QVERIFY(addBody.contains("\"yahoo_symbol\":\"7203.T\""));
        QVERIFY(!addBody.contains("finnhub_symbol"));
        QVERIFY(managementCalls >= 2); // successful mutation is followed by server reload

        store.updateWatchlist(7, {{QStringLiteral("alert_enabled"), false}});
        QTRY_VERIFY_WITH_TIMEOUT(!store.mutationBusy(), 3000);
        QCOMPARE(store.watchlistedCount(), 1); // failed mutation never removes/edits the row locally
        QVERIFY(!store.error().isEmpty());
    }

    void createGroupUsesPost()
    {
        bool posted = false;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (request.startsWith("POST /api/stock-groups ")) {
                posted = true;
                return {201, R"({"id":9,"name":"Cloud","display_order":1})"};
            }
            return {404, R"({"detail":"unexpected"})"};
        }));
        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setEnvironment(&environment);
        WatchlistStore store(&environment, &api, [] { return QByteArray(); });
        store.createGroup("Cloud");
        QTRY_VERIFY_WITH_TIMEOUT(!store.mutationBusy(), 3000);
        QVERIFY(posted);
    }
};

QTEST_GUILESS_MAIN(WatchlistTest)
#include "tst_watchlist.moc"
