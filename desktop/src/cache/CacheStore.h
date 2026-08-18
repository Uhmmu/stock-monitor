#pragma once

#include <QDateTime>
#include <QHash>
#include <QObject>
#include <QSqlDatabase>
#include <optional>
#include <QString>

// Three-tier read cache policy (memory -> SQLite disk) for last-good JSON
// payloads. Never a second business database: entries are disposable
// acceleration only and the whole store can be dropped and rebuilt at any time.
//
// Ownership isolation: every key is namespaced by the current owner scope
// (server host + user subject). clearOwner() is called on logout so private
// data of one user can never leak into another session. Sensitive content
// (AI conversations, IBKR records, tokens) must use memoryOnly=true and is
// never written to disk.
struct CacheEntry {
    QByteArray payload;
    QString etag;
    qint64 fetchedAtMs = 0;
    qint64 expiresAtMs = 0;

    bool isStale(qint64 nowMs) const { return expiresAtMs > 0 && nowMs >= expiresAtMs; }
    qint64 ageSeconds(qint64 nowMs) const { return fetchedAtMs > 0 ? (nowMs - fetchedAtMs) / 1000 : 0; }
};

class CacheStore final : public QObject
{
    Q_OBJECT

public:
    static constexpr int kSchemaVersion = 1;
    static constexpr qint64 kDefaultMaxDiskBytes = 256 * 1024 * 1024;

    // `directory` overrides the on-disk location (tests); empty uses
    // QStandardPaths::CacheLocation.
    explicit CacheStore(QObject *parent = nullptr);
    ~CacheStore() override;

    void setOwnerScope(const QString &scope);
    QString ownerScope() const { return m_scope; }
    void setCacheDirectory(const QString &directory);  // before first disk use
    void setMaxDiskBytes(qint64 bytes);

    std::optional<CacheEntry> lookup(const QString &key);
    void insert(const QString &key, const QByteArray &payload, const QString &etag,
                qint64 ttlSeconds, bool memoryOnly = false);
    void remove(const QString &key);
    void clearOwner();
    void clearAll();

    qint64 diskUsageBytes();
    QString diskPath() const;

private:
    struct MemoryEntry {
        CacheEntry entry;
        qint64 lastAccessMs = 0;
    };

    bool ensureDatabase();
    void evictIfNeeded();
    QString scopedKey(const QString &key) const;
    QString databaseFile() const;

    QHash<QString, MemoryEntry> m_memory;
    QSqlDatabase m_db;
    QString m_connectionName;
    QString m_directory;
    QString m_scope = QStringLiteral("anonymous");
    qint64 m_maxDiskBytes = kDefaultMaxDiskBytes;
    bool m_dbOpened = false;
};
