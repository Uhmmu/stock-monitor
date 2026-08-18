#include "app/AppEnvironment.h"
#include "network/ApiClient.h"
#include "network/RequestHandle.h"
#include "network/SseParser.h"
#include "network/SseStream.h"

#include <QNetworkAccessManager>
#include <QSignalSpy>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTest>

#include "MockHttpServer.h"

class NetworkTest final : public QObject
{
    Q_OBJECT

private slots:
    // ---- SseParser: chunk boundary invariants ----

    void sseParsesSingleEvent()
    {
        SseParser parser;
        QVector<SseEvent> events;
        parser.feed("event: quote\ndata: {\"p\":1}\n\n", &events);
        QCOMPARE(events.size(), 1);
        QCOMPARE(events[0].eventType, QString("quote"));
        QCOMPARE(events[0].data, QString("{\"p\":1}"));
    }

    void sseJoinsMultilineDataWithNewline()
    {
        SseParser parser;
        QVector<SseEvent> events;
        parser.feed("data: line1\ndata: line2\ndata:\n\n", &events);
        QCOMPARE(events.size(), 1);
        QCOMPARE(events[0].data, QString("line1\nline2\n"));
        QCOMPARE(events[0].eventType, QString("message"));
    }

    void sseHandlesArbitraryChunkBoundaries()
    {
        const QByteArray raw =
            "event: bar\ndata: a\n\n: heartbeat\n\ndata: b\r\n\r\nid: 1\ndata: c\n\n";
        for (int split = 0; split <= raw.size(); ++split) {
            SseParser parser;
            QVector<SseEvent> events;
            parser.feed(raw.left(split), &events);
            parser.feed(raw.mid(split), &events);
            parser.feed("\n", &events);
            QVector<SseEvent> dataEvents;
            for (const auto &event : events)
                if (!event.isComment)
                    dataEvents.append(event);
            QCOMPARE(dataEvents.size(), 3);
            QCOMPARE(dataEvents[0].eventType, QString("bar"));
            QCOMPARE(dataEvents[1].eventType, QString("message"));
            QCOMPARE(dataEvents[2].data, QString("c"));
        }
    }

    void sseSplitsUtf8CharactersAcrossChunks()
    {
        const QString text = QString::fromUtf8("成本 €100 → 收益");
        QByteArray payload = ("event: news\ndata: " + text.toUtf8() + "\n\n");
        for (int split = 1; split < text.toUtf8().size(); split += 7) {
            SseParser parser;
            QVector<SseEvent> events;
            parser.feed(payload.left(split), &events);
            parser.feed(payload.mid(split), &events);
            QCOMPARE(events.size(), 1);
            QCOMPARE(events[0].data, text);
            QCOMPARE(events[0].eventType, QString("news"));
        }
    }

    void sseCommentsAreHeartbeatsNotData()
    {
        SseParser parser;
        QVector<SseEvent> events;
        parser.feed(": ping 12345\n\n", &events);
        QCOMPARE(events.size(), 1);
        QVERIFY(events[0].isComment);
        QCOMPARE(events[0].data, QString("ping 12345"));
    }

    void sseWithoutTrailingBlankLineDoesNotDispatch()
    {
        SseParser parser;
        QVector<SseEvent> events;
        parser.feed("data: partial", &events);
        QVERIFY(events.isEmpty());
        parser.reset();
        parser.feed("\n\n", &events);
        QVERIFY(events.isEmpty());  // reset dropped the partial event
    }

    void sseIgnoresUnknownFields()
    {
        SseParser parser;
        QVector<SseEvent> events;
        parser.feed("retry: 100\nid: 42\nprogress: 50%\ndata: ok\n\n", &events);
        QCOMPARE(events.size(), 1);
        QCOMPARE(events[0].data, QString("ok"));
    }

    // ---- SseStream: reconnect + terminal semantics ----

    void sseStreamReconnectsAndStopsOnTerminal()
    {
        QTcpServer server;
        QVERIFY(server.listen(QHostAddress::LocalHost));
        QVector<int> connections;
        QObject::connect(&server, &QTcpServer::newConnection, &server, [&server, &connections] {
            auto *socket = server.nextPendingConnection();
            connections.append(1);
            QObject::connect(socket, &QTcpSocket::readyRead, socket,
                             [socket, &connections] {
                socket->readAll();  // consume request
                socket->write("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                              "Connection: close\r\n\r\n");
                socket->write("event: quote\ndata: {\"p\":1}\n\n");
                socket->flush();
                // First connection ends without terminal -> must reconnect.
                if (connections.size() >= 2) {
                    socket->write("event: done\ndata: final\n\n");
                    socket->flush();
                }
                socket->disconnectFromHost();
            });
        });

        QNetworkAccessManager network;
        SseStream stream(&network);
        stream.setBackoffSchedule({0});
        stream.setTerminalEvents({QStringLiteral("done")});
        QSignalSpy eventSpy(&stream, &SseStream::eventReceived);
        QSignalSpy stateSpy(&stream, &SseStream::stateChanged);
        stream.start(QUrl(QStringLiteral("http://127.0.0.1:%1/api/market/realtime/stream")
                              .arg(server.serverPort())));
        QTRY_COMPARE_WITH_TIMEOUT(stream.state(), SseStream::State::Completed, 5000);
        QVERIFY(connections.size() >= 2);
        QCOMPARE(eventSpy.count(), 3);
        QCOMPARE(eventSpy.at(2).at(0).toString(), QString("done"));
        QVERIFY(stateSpy.count() > 0);
    }

    // ---- ApiClient: retry, refresh single-flight, cancellation ----

    void retriesIdempotentGetsWithBackoff()
    {
        int attempts = 0;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &) -> MockHttpServer::Response {
            attempts += 1;
            if (attempts < 3)
                return {500, R"({"detail":"boom"})"};
            return {200, R"({"status":"ok"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setEnvironment(&environment);
        api.setRetryDelays({0, 0});
        int calls = 0;
        RequestHandle handle = api.get(
            QStringLiteral("flaky"),
            [&](const ApiError &error, const QJsonObject &json) {
                calls += 1;
                QCOMPARE(error.code, ApiErrorCode::Unknown);
                QCOMPARE(json.value("status").toString(), QString("ok"));
            },
            {.name = QStringLiteral("flaky"), .authenticated = false, .retryable = true});
        QVERIFY(handle.isActive());
        QTRY_COMPARE(calls, 1);
        QCOMPARE(attempts, 3);
    }

    void doesNotRetryPostMutations()
    {
        int attempts = 0;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &) -> MockHttpServer::Response {
            attempts += 1;
            return {500, R"({"detail":"boom"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setEnvironment(&environment);
        api.setRetryDelays({0, 0});
        int failures = 0;
        api.post(QStringLiteral("mutate"), QJsonObject{},
                 [&](const ApiError &error, const QJsonObject &) {
                     failures += 1;
                     QCOMPARE(error.code, ApiErrorCode::ServerError);
                 },
                 {.name = QStringLiteral("mutate"), .authenticated = false});
        QTRY_COMPARE(failures, 1);
        QCOMPARE(attempts, 1);
    }

    void unauthorizedTriggersSingleFlightRefreshAndReplay()
    {
        QString currentAccess = "A1";
        QString currentRefresh = "R1";
        int refreshCalls = 0;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (request.startsWith("POST /api/auth/refresh ")) {
                refreshCalls += 1;
                if (!request.contains("R" + QByteArray::number(refreshCalls)))
                    return {401, R"({"detail":"stale refresh token"})"};
                currentAccess = "A" + QByteArray::number(refreshCalls + 1);
                currentRefresh = "R" + QByteArray::number(refreshCalls + 1);
                return {200, "{\"token\":\"" + currentAccess.toUtf8() + "\",\"refresh_token\":\""
                             + currentRefresh.toUtf8() + "\",\"username\":\"alice\",\"role\":\"user\"}"};
            }
            if (request.startsWith("GET /api/data ")) {
                // The client's stored A1 is stale; only the rotated A2 works.
                if (request.contains("Authorization: Bearer A2"))
                    return {200, R"({"value":42})"};
                return {401, R"({"detail":"token expired"})"};
            }
            return {401, R"({"detail":"token expired"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setEnvironment(&environment);
        api.setRetryDelays({0});
        QString access = "A1";
        QString refresh = "R1";
        api.setAccessTokenProvider([&] { return access; });
        api.setRefreshTokenProvider([&] { return refresh; });
        api.setAccessTokenSink([&](const QString &token) { access = token; });
        api.setRefreshTokenSink([&](const QString &token) { refresh = token; });

        int successes = 0;
        api.get(QStringLiteral("data"),
                [&](const ApiError &error, const QJsonObject &json) {
                    QCOMPARE(error.code, ApiErrorCode::Unknown);
                    QCOMPARE(json.value("value").toInt(), 42);
                    successes += 1;
                },
                {.name = QStringLiteral("data")});
        api.get(QStringLiteral("data"),
                [&](const ApiError &error, const QJsonObject &json) {
                    QCOMPARE(error.code, ApiErrorCode::Unknown);
                    QCOMPARE(json.value("value").toInt(), 42);
                    successes += 1;
                },
                {.name = QStringLiteral("data2")});
        QTRY_COMPARE(successes, 2);
        QCOMPARE(refreshCalls, 1);  // single-flight despite two parallel 401s
        QCOMPARE(access, QString("A2"));
        QCOMPARE(refresh, QString("R2"));
    }

    void definiteRefreshFailureEmitsSessionExpired()
    {
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (request.startsWith("POST /api/auth/refresh "))
                return {401, R"({"detail":"refresh token revoked"})"};
            return {401, R"({"detail":"token expired"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setEnvironment(&environment);
        api.setRetryDelays({0});
        api.setAccessTokenProvider([] { return QString("stale"); });
        api.setRefreshTokenProvider([] { return QString("revoked"); });

        QSignalSpy expiredSpy(&api, &ApiClient::authSessionExpired);
        int failures = 0;
        api.get(QStringLiteral("data"),
                [&](const ApiError &error, const QJsonObject &) {
                    failures += 1;
                    QCOMPARE(error.code, ApiErrorCode::Unauthorized);
                },
                {.name = QStringLiteral("data")});
        QTRY_COMPARE(expiredSpy.count(), 1);
        QTRY_COMPARE(failures, 1);
    }

    void cancelledRequestsNeverInvokeCallbacks()
    {
        MockHttpServer server;
        QVERIFY(server.start([](const QByteArray &) -> MockHttpServer::Response {
            return {200, R"({"status":"ok"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setEnvironment(&environment);
        api.setRetryDelays({0});
        int calls = 0;
        RequestHandle handle = api.get(
            QStringLiteral("slow"),
            [&](const ApiError &, const QJsonObject &) { calls += 1; },
            {.name = QStringLiteral("slow"), .authenticated = false});
        handle.cancel();
        QTest::qWait(300);
        QCOMPARE(calls, 0);
    }

    void generationCounterGuardsStaleSelections()
    {
        GenerationCounter counter;
        const quint64 first = counter.next();
        const quint64 second = counter.next();
        QVERIFY(first != second);
        QCOMPARE(counter.current(), second);
    }
};

QTEST_MAIN(NetworkTest)
#include "tst_network.moc"
