#include "app/AppEnvironment.h"
#include "app/SessionStore.h"
#include "app/TokenVault.h"
#include "cache/CacheStore.h"
#include "network/ApiClient.h"

#include <QJsonObject>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include "MockHttpServer.h"

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
            {"token", "jwt"}, {"refresh_token", "r1"}, {"username", "alice"},
            {"role", "user"}, {"expires_at", "2026-08-18T12:00:00Z"}, {"future", 1}});
        QVERIFY(login);
        QCOMPARE(login->token, QString("jwt"));
        QCOMPARE(login->refreshToken, QString("r1"));
        QVERIFY(login->expiresAtMs > 0);
        QVERIFY(!ApiClient::parseLogin({{"token", "jwt"}}));
        // Legacy servers without token lifecycle must still parse.
        const auto legacy = ApiClient::parseLogin({
            {"token", "jwt"}, {"username", "alice"}, {"role", "user"}});
        QVERIFY(legacy && legacy->refreshToken.isEmpty() && legacy->expiresAtMs == 0);

        const auto user = ApiClient::parseUser({
            {"id", 7}, {"username", "alice"}, {"role", "admin"}, {"future", true}});
        QVERIFY(user);
        QCOMPARE(user->id, 7);
        QVERIFY(!ApiClient::parseUser({{"id", 0}, {"username", "alice"}, {"role", "user"}}));
    }

    void runsFullSessionFlow()
    {
        QString accessToken;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (request.startsWith("GET /api/health "))
                return {200, R"({"status":"ok"})"};
            if (request.startsWith("GET /api/readiness "))
                return {200, R"({"status":"ready"})"};
            if (request.startsWith("POST /api/auth/login "))
                return {200, R"({"token":"A1","refresh_token":"R1","expires_at":"2026-12-01T00:00:00Z","username":"alice","role":"user"})"};
            if (request.startsWith("POST /api/auth/logout "))
                return {200, R"({"message":"已退出登录"})"};
            if (request.startsWith("GET /api/auth/me ")
                     && request.contains("Authorization: Bearer A1"))
                return {200, R"({"id":7,"username":"alice","role":"user"})"};
            return {400, R"({"detail":"unexpected request"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        ApiClient api;
        api.setRetryDelays({0});
        TokenVault vault(TokenVault::Backend::Memory);
        QTemporaryDir cacheDir;
        CacheStore cache;
        cache.setCacheDirectory(cacheDir.path());
        SessionStore session(&environment, &api, &vault, &cache);

        session.testConnection();
        QTRY_VERIFY(session.connected());
        session.login("alice", "secret", false);
        QTRY_VERIFY(session.authenticated());
        QCOMPARE(session.username(), QString("alice"));
        QCOMPARE(session.role(), QString("user"));
        QCOMPARE(vault.memorySecret(), QString(""));  // remember=false -> nothing stored
        QCOMPARE(cache.ownerScope(), QString("http://127.0.0.1:%1|user:alice").arg(server.port()));

        session.logout();
        QVERIFY(!session.authenticated());
        QCOMPARE(vault.memorySecret(), QString(""));
    }
};

QTEST_MAIN(FoundationTest)
#include "tst_foundation.moc"
