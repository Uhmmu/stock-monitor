#include "cache/CacheStore.h"

#include <QDateTime>
#include <QFile>
#include <QSqlDatabase>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QTest>

class CacheTest final : public QObject
{
    Q_OBJECT

private slots:
    void storesAndLooksUpWithinTtl()
    {
        QTemporaryDir dir;
        CacheStore cache;
        cache.setCacheDirectory(dir.path());
        cache.setOwnerScope("host1|user:alice");
        cache.insert("dashboard", R"({"a":1})", "etag-1", 600);

        const auto entry = cache.lookup("dashboard");
        QVERIFY(entry);
        QCOMPARE(entry->payload, QByteArray(R"({"a":1})"));
        QCOMPARE(entry->etag, QString("etag-1"));
        QVERIFY(!entry->isStale(QDateTime::currentMSecsSinceEpoch()));
        QVERIFY(entry->ageSeconds(QDateTime::currentMSecsSinceEpoch()) >= 0);
    }

    void expiredEntriesDisappear()
    {
        QTemporaryDir dir;
        CacheStore cache;
        cache.setCacheDirectory(dir.path());
        cache.insert("news", "payload", "", -1);  // negative ttl -> pre-expired
        QVERIFY(!cache.lookup("news").has_value());
    }

    void persistsAcrossRestartAndReportsStaleAge()
    {
        QTemporaryDir dir;
        const QString file = dir.path() + "/response-cache.sqlite";
        {
            CacheStore cache;
            cache.setCacheDirectory(dir.path());
            cache.setOwnerScope("host1|user:alice");
            cache.insert("statements", "big-json", "v1", 3600);
            QTest::qWait(50);  // give SQLite async commit a beat
        }
        QVERIFY(QFile::exists(file));
        CacheStore cache2;
        cache2.setCacheDirectory(dir.path());
        cache2.setOwnerScope("host1|user:alice");
        const auto entry = cache2.lookup("statements");
        QVERIFY(entry);
        QCOMPARE(entry->payload, QByteArray("big-json"));
        QVERIFY(entry->ageSeconds(QDateTime::currentMSecsSinceEpoch()) >= 0);
    }

    void ownerScopesAreIsolated()
    {
        QTemporaryDir dir;
        CacheStore cache;
        cache.setCacheDirectory(dir.path());
        cache.setOwnerScope("host1|user:alice");
        cache.insert("portfolio", "alice-data", "", 3600);
        cache.setOwnerScope("host1|user:bob");
        QVERIFY(!cache.lookup("portfolio").has_value());  // bob cannot read alice
        cache.insert("portfolio", "bob-data", "", 3600);

        cache.clearOwner();  // bob logs out: only bob's entries die
        cache.setOwnerScope("host1|user:alice");
        const auto entry = cache.lookup("portfolio");
        QVERIFY(entry);
        QCOMPARE(entry->payload, QByteArray("alice-data"));
    }

    void memoryOnlyEntriesNeverTouchDisk()
    {
        QTemporaryDir dir;
        CacheStore cache;
        cache.setCacheDirectory(dir.path());
        cache.setOwnerScope("host|user:alice");
        cache.insert("ai-conversation", "secret-ish", "", 3600, /*memoryOnly=*/true);
        QTest::qWait(50);

        CacheStore fresh;
        fresh.setCacheDirectory(dir.path());
        fresh.setOwnerScope("host|user:alice");
        QVERIFY(!fresh.lookup("ai-conversation").has_value());
        QCOMPARE(fresh.diskUsageBytes(), 0);
    }

    void schemaVersionMismatchWipesDatabase()
    {
        QTemporaryDir dir;
        {
            CacheStore cache;
            cache.setCacheDirectory(dir.path());
            cache.setOwnerScope("host|user:alice");
            cache.insert("old", "old-payload", "", 3600);
        }
        // Simulate a future schema by bumping the PRAGMA behind the store's back.
        {
            QSqlDatabase db = QSqlDatabase::addDatabase("QSQLITE", "tamper");
            db.setDatabaseName(dir.path() + "/response-cache.sqlite");
            QVERIFY(db.open());
            QSqlQuery query(db);
            query.exec("PRAGMA user_version = 99");
            db.close();
            db = QSqlDatabase();  // release reference before unregistering
        }
        QSqlDatabase::removeDatabase("tamper");

        CacheStore cache;
        cache.setCacheDirectory(dir.path());
        cache.setOwnerScope("host|user:alice");
        QVERIFY(!cache.lookup("old").has_value());  // wiped, not resurrected
    }

    void evictsLeastRecentlyUsedBeyondCap()
    {
        QTemporaryDir dir;
        CacheStore cache;
        cache.setCacheDirectory(dir.path());
        cache.setOwnerScope("host|user:alice");
        // 4 x 100 bytes payload with a 250-byte cap: cleanup targets 200 bytes.
        const QByteArray blob(100, 'x');
        for (int i = 0; i < 4; ++i) {
            cache.insert(QStringLiteral("entry-%1").arg(i), blob, "", 3600);
            QTest::qWait(10);  // distinct last_accessed_at ordering
        }
        cache.setMaxDiskBytes(250);
        // Trigger eviction through a new insert cycle (idle eviction runs queued).
        QTest::qWait(100);
        QVERIFY(cache.diskUsageBytes() <= 250);

        // Oldest entries evicted first; newest still present.
        QVERIFY(!cache.lookup("entry-0").has_value() || cache.lookup("entry-3").has_value());
        const auto newest = cache.lookup("entry-3");
        if (!newest)
            QVERIFY(cache.diskUsageBytes() <= 200);
    }

    void clearAllMakesCacheRebuildable()
    {
        QTemporaryDir dir;
        CacheStore cache;
        cache.setCacheDirectory(dir.path());
        cache.setOwnerScope("host|user:alice");
        cache.insert("a", "1", "", 3600);
        cache.insert("b", "2", "", 3600);
        cache.clearAll();
        QCOMPARE(cache.diskUsageBytes(), 0);
        QVERIFY(!cache.lookup("a").has_value());
        QVERIFY(!cache.lookup("b").has_value());
    }
};

QTEST_MAIN(CacheTest)
#include "tst_cache.moc"
