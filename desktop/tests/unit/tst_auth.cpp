#include "app/AppEnvironment.h"
#include "app/SessionStore.h"
#include "app/TokenVault.h"
#include "cache/CacheStore.h"
#include "network/ApiClient.h"

#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include "MockHttpServer.h"

// Full auth lifecycle against a stateful mock backend.
class AuthTest final : public QObject
{
    Q_OBJECT

    struct ServerState {
        QString access = "A1";
        QString refresh = "R1";
        int refreshCalls = 0;
        int logoutCalls = 0;
        bool refreshRevoked = false;
        bool offline = false;
    };

private slots:
    void remembersSessionInVaultAcrossRestart()
    {
        ServerState state;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (state.offline)
                return {503, R"({"detail":"unavailable"})"};
            if (request.startsWith("POST /api/auth/login "))
                return {200, "{\"token\":\"" + state.access.toUtf8()
                             + "\",\"refresh_token\":\"" + state.refresh.toUtf8()
                             + "\",\"username\":\"alice\",\"role\":\"user\"}"};
            if (request.startsWith("POST /api/auth/refresh ")) {
                state.refreshCalls += 1;
                if (state.refreshRevoked)
                    return {401, R"({"detail":"revoked"})"};
                state.access = "A2";
                state.refresh = "R2";
                return {200, R"({"token":"A2","refresh_token":"R2","username":"alice","role":"user"})"};
            }
            if (request.startsWith("GET /api/auth/me ")) {
                if (!request.contains("Authorization: Bearer " + state.access.toUtf8()))
                    return {401, R"({"detail":"invalid token"})"};
                return {200, R"({"id":7,"username":"alice","role":"user"})"};
            }
            return {400, R"({"detail":"unexpected"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        QTemporaryDir cacheDir;
        TokenVault vault(TokenVault::Backend::Memory);
        CacheStore cache;
        cache.setCacheDirectory(cacheDir.path());

        // First run: login with remember -> vault keeps R1.
        {
            ApiClient api;
            api.setRetryDelays({0});
            SessionStore session(&environment, &api, &vault, &cache);
            session.login("alice", "secret", true);
            QTRY_VERIFY(session.authenticated());
            QCOMPARE(vault.memorySecret(), QString("R1"));
        }

        // Second run: new process objects; restore from vault memory copy.
        {
            ApiClient api;
            api.setRetryDelays({0});
            SessionStore session(&environment, &api, &vault, &cache);
            session.restoreSession();
            QTRY_VERIFY(session.authenticated());
            QCOMPARE(session.username(), QString("alice"));
        }
    }

    void restoresExpiredSessionThroughRefreshRotation()
    {
        ServerState state;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (request.startsWith("POST /api/auth/refresh ")) {
                state.refreshCalls += 1;
                state.access = "A2";
                return {200, R"({"token":"A2","refresh_token":"R2","username":"alice","role":"user"})"};
            }
            if (request.startsWith("GET /api/auth/me ")) {
                // Stored access token A1 is long gone server-side.
                if (!request.contains("Authorization: Bearer A2"))
                    return {401, R"({"detail":"expired"})"};
                return {200, R"({"id":7,"username":"alice","role":"user"})"};
            }
            return {400, R"({"detail":"unexpected"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        QTemporaryDir cacheDir;
        TokenVault vault(TokenVault::Backend::Memory);
        const QString account = QStringLiteral("server:") + environment.baseUrl().section("//", -1);
        vault.store(account, "R1");
        CacheStore cache;
        cache.setCacheDirectory(cacheDir.path());

        ApiClient api;
        api.setRetryDelays({0});
        SessionStore session(&environment, &api, &vault, &cache);
        QSignalSpy refreshed(&api, &ApiClient::sessionRefreshed);
        session.restoreSession();
        QTRY_VERIFY(session.authenticated());
        QCOMPARE(refreshed.count(), 1);  // 401 -> refresh -> replayed me
    }

    void revokedRefreshLogsOutAndClearsVault()
    {
        ServerState state;
        state.refreshRevoked = true;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (request.startsWith("POST /api/auth/refresh "))
                return {401, R"({"detail":"refresh token revoked"})"};
            return {401, R"({"detail":"expired"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        QTemporaryDir cacheDir;
        TokenVault vault(TokenVault::Backend::Memory);
        const QString account = QStringLiteral("server:") + environment.baseUrl().section("//", -1);
        vault.store(account, "R1");
        CacheStore cache;
        cache.setCacheDirectory(cacheDir.path());

        ApiClient api;
        api.setRetryDelays({0});
        SessionStore session(&environment, &api, &vault, &cache);
        QSignalSpy expired(&session, &SessionStore::authExpired);
        session.restoreSession();
        QTRY_COMPARE(expired.count(), 1);
        QVERIFY(!session.authenticated());
        QCOMPARE(vault.memorySecret(), QString(""));  // cleared, not just ignored
    }

    void logoutRevokesServerSessionAndClearsLocalState()
    {
        ServerState state;
        MockHttpServer server;
        QVERIFY(server.start([&](const QByteArray &request) -> MockHttpServer::Response {
            if (request.startsWith("POST /api/auth/login "))
                return {200, R"({"token":"A1","refresh_token":"R1","username":"alice","role":"user"})"};
            if (request.startsWith("POST /api/auth/logout ")) {
                state.logoutCalls += 1;
                if (!request.contains("R1"))
                    return {400, R"({"detail":"wrong token"})"};
                return {200, R"({"message":"ok"})"};
            }
            if (request.startsWith("GET /api/auth/me ")
                     && request.contains("Authorization: Bearer A1"))
                return {200, R"({"id":7,"username":"alice","role":"user"})"};
            return {400, R"({"detail":"unexpected"})"};
        }));

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl(server.baseUrl()));
        QTemporaryDir cacheDir;
        TokenVault vault(TokenVault::Backend::Memory);
        CacheStore cache;
        cache.setCacheDirectory(cacheDir.path());
        ApiClient api;
        api.setRetryDelays({0});
        SessionStore session(&environment, &api, &vault, &cache);

        session.login("alice", "secret", true);
        QTRY_VERIFY(session.authenticated());
        cache.setOwnerScope("host|user:alice");
        cache.insert("private", "data", "", 3600);

        session.logout();
        QTRY_COMPARE(state.logoutCalls, 1);
        QVERIFY(!session.authenticated());
        QCOMPARE(vault.memorySecret(), QString(""));
        // Private cache scope purged for the next user.
        QVERIFY(!cache.lookup("private").has_value());
    }

    void networkFailureKeepsSessionForLaterRetry()
    {
        // Restore attempt while the server is unreachable: the refresh copy in
        // the vault must survive so a later run can resume.
        QTemporaryDir cacheDir;
        TokenVault vault(TokenVault::Backend::Memory);
        vault.store("server:127.0.0.1", "R1");
        CacheStore cache;
        cache.setCacheDirectory(cacheDir.path());

        AppEnvironment environment;
        QVERIFY(environment.setBaseUrl("http://127.0.0.1:1"));  // nothing listens
        ApiClient api;
        api.setRetryDelays({0});
        SessionStore session(&environment, &api, &vault, &cache);
        QSignalSpy expired(&session, &SessionStore::authExpired);
        session.restoreSession();
        QTRY_VERIFY(session.offline());
        QVERIFY(!session.authenticated());
        QVERIFY(!session.busy());
        QCOMPARE(vault.memorySecret(), QString("R1"));  // vault copy survives
        QCOMPARE(expired.count(), 0);  // network failure is not an auth failure
        QVERIFY(session.error().contains(tr("无法连接服务器")));
    }

    void vaultDegradesToSessionOnlyWithoutKeyring()
    {
        // Memory backend models a missing Secret Service: no plaintext fallback.
        TokenVault vault(TokenVault::Backend::Memory);
        QCOMPARE(vault.mode(), TokenVault::Mode::SessionOnly);
        QVERIFY(!vault.persistSupported());
        QSignalSpy loadedSpy(&vault, &TokenVault::loaded);
        vault.store("server:127.0.0.1", "R1");
        QCOMPARE(vault.memorySecret(), QString("R1"));
        vault.load("server:127.0.0.1");
        QTRY_COMPARE(loadedSpy.count(), 1);
        QCOMPARE(loadedSpy.at(0).at(1).toString(), QString("R1"));
        vault.clear("server:127.0.0.1");
        QVERIFY(vault.memorySecret().isEmpty());
    }
};

QTEST_MAIN(AuthTest)
#include "tst_auth.moc"
