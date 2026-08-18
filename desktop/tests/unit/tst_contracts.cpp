#include "network/ApiClient.h"
#include "network/ApiError.h"

#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkReply>
#include <QTest>

// Contract tests against checked-in fixtures that mirror the live backend's
// auth response shapes. Unknown additive fields must never break the client.
class ContractTest final : public QObject
{
    Q_OBJECT

    static QJsonObject loadFixture(const QString &name)
    {
        QFile file(QStringLiteral(STOCK_MONITOR_CONTRACT_FIXTURES_DIR) + QLatin1Char('/') + name);
        if (!file.open(QIODevice::ReadOnly)) {
            qFatal("fixture missing: %s", qPrintable(file.fileName()));
            return {};
        }
        return QJsonDocument::fromJson(file.readAll()).object();
    }

private slots:
    void loginContract()
    {
        const auto login = ApiClient::parseLogin(loadFixture(QStringLiteral("auth_login.json")));
        QVERIFY(login);
        QCOMPARE(login->token.size() > 20, true);
        QCOMPARE(login->refreshToken, QString("48-byte-urlsafe-refresh-token-example"));
        QCOMPARE(login->username, QString("alice"));
        QCOMPARE(login->role, QString("user"));
        // Python datetime.isoformat() uses +00:00 offsets; must parse to UTC ms.
        QCOMPARE(login->expiresAtMs > 0, true);
    }

    void meContract()
    {
        const auto user = ApiClient::parseUser(loadFixture(QStringLiteral("auth_me.json")));
        QVERIFY(user);
        QCOMPARE(user->id, 7);
        QCOMPARE(user->username, QString("alice"));
        QCOMPARE(user->role, QString("user"));
    }

    void refreshContract()
    {
        const auto rotated = ApiClient::parseLogin(loadFixture(QStringLiteral("auth_refresh.json")));
        QVERIFY(rotated);
        QCOMPARE(rotated->token, QString("rotated-access-jwt"));
        QCOMPARE(rotated->refreshToken, QString("rotated-refresh-token"));
        QVERIFY(rotated->expiresAtMs > 0);
    }

    void errorDetailContract()
    {
        const QJsonObject body = loadFixture(QStringLiteral("error_detail.json"));
        const ApiError error = ApiErrorFactory::fromReply(
            0, 401, QJsonDocument(body).toJson(QJsonDocument::Compact),
            QStringLiteral("login"));
        QCOMPARE(error.code, ApiErrorCode::Unauthorized);
        QCOMPARE(error.httpStatus, 401);
        QCOMPARE(error.message, QString("用户名或密码错误"));
        QCOMPARE(error.isRetryable(), false);
        QCOMPARE(error.toDisplayString(), QString("用户名或密码错误"));
    }

    void errorTaxonomyContract()
    {
        QCOMPARE(ApiErrorFactory::fromReply(0, 500, "", "x").code, ApiErrorCode::ServerError);
        QCOMPARE(ApiErrorFactory::fromReply(0, 429, "", "x").code, ApiErrorCode::RateLimited);
        QCOMPARE(ApiErrorFactory::fromReply(0, 404, "", "x").code, ApiErrorCode::NotFound);
        QCOMPARE(ApiErrorFactory::fromReply(0, 403, "", "x").code, ApiErrorCode::Forbidden);
        QVERIFY(ApiErrorFactory::fromReply(0, 503, "", "x").isRetryable());
        QVERIFY(!ApiErrorFactory::fromReply(0, 403, "", "x").isRetryable());
        QVERIFY(ApiErrorFactory::network(static_cast<int>(QNetworkReply::TimeoutError),
                                         "timed out", "x").isNetworkLevel());
    }
};

QTEST_MAIN(ContractTest)
#include "tst_contracts.moc"
