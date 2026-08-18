#include "app/AppEnvironment.h"
#include "app/SessionStore.h"
#include "network/ApiClient.h"

#include <QJsonObject>
#include <QSignalSpy>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTest>

class FoundationTest final : public QObject
{
    Q_OBJECT

private slots:
    void validatesBaseUrls()
    {
        QVERIFY(AppEnvironment::isAllowedBaseUrl(QUrl("https://stocks.example.com")));
        QVERIFY(AppEnvironment::isAllowedBaseUrl(QUrl("http://127.0.0.1:8080")));
        QVERIFY(AppEnvironment::isAllowedBaseUrl(QUrl("http://localhost:8000")));
        QVERIFY(!AppEnvironment::isAllowedBaseUrl(QUrl("http://stocks.example.com")));
        QVERIFY(!AppEnvironment::isAllowedBaseUrl(QUrl("ftp://127.0.0.1")));
        QVERIFY(!AppEnvironment::isAllowedBaseUrl(QUrl("https://user:secret@stocks.example.com")));
    }

    void mapsApiResponses()
    {
        QCOMPARE(*ApiClient::parseStatus({{"status", "ok"}}), QString("ok"));
        QVERIFY(!ApiClient::parseStatus({}));

        const auto login = ApiClient::parseLogin({
            {"token", "jwt"}, {"username", "alice"}, {"role", "user"}, {"future", 1}});
        QVERIFY(login);
        QCOMPARE(login->token, QString("jwt"));
        QVERIFY(!ApiClient::parseLogin({{"token", "jwt"}}));

        const auto user = ApiClient::parseUser({
            {"id", 7}, {"username", "alice"}, {"role", "admin"}, {"future", true}});
        QVERIFY(user);
        QCOMPARE(user->id, 7);
        QVERIFY(!ApiClient::parseUser({{"id", 0}, {"username", "alice"}, {"role", "user"}}));
    }

    void callsMockApi()
    {
        QTcpServer server;
        QVERIFY(server.listen(QHostAddress::LocalHost));
        connect(&server, &QTcpServer::newConnection, &server, [&server] {
            auto *socket = server.nextPendingConnection();
            QObject::connect(socket, &QTcpSocket::readyRead, socket, [socket] {
                const QByteArray request = socket->readAll();
                QByteArray body;
                if (request.startsWith("GET /api/health "))
                    body = R"({"status":"ok"})";
                else if (request.startsWith("GET /api/readiness "))
                    body = R"({"status":"ready"})";
                else if (request.startsWith("POST /api/auth/login "))
                    body = R"({"token":"jwt","username":"alice","role":"user"})";
                else if (request.startsWith("GET /api/auth/me ")
                         && request.contains("Authorization: Bearer jwt"))
                    body = R"({"id":7,"username":"alice","role":"user"})";
                else
                    body = R"({"detail":"unexpected request"})";
                const QByteArray status = body.contains("unexpected") ? "400 Bad Request" : "200 OK";
                socket->write("HTTP/1.1 " + status + "\r\nContent-Type: application/json\r\nContent-Length: "
                              + QByteArray::number(body.size()) + "\r\nConnection: close\r\n\r\n" + body);
                socket->disconnectFromHost();
            });
        });

        const QString origin = QStringLiteral("http://127.0.0.1:%1").arg(server.serverPort());
        ApiClient api;
        QSignalSpy failureSpy(&api, &ApiClient::requestFailed);
        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(origin));
        SessionStore session(&environment, &api);

        session.testConnection();
        QTRY_VERIFY(session.connected());
        session.login("alice", "secret", false);
        QTRY_VERIFY(session.authenticated());
        QCOMPARE(failureSpy.count(), 0);
        QCOMPARE(session.username(), QString("alice"));
        QCOMPARE(session.role(), QString("user"));
        session.logout();
        QVERIFY(!session.authenticated());
    }
};

QTEST_MAIN(FoundationTest)
#include "tst_foundation.moc"
