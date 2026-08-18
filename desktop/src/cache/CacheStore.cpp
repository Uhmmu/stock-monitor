#include "cache/CacheStore.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QSqlError>
#include <QSqlQuery>
#include <QStandardPaths>
#include <QTimer>
#include <QVariant>

namespace {
// Per-instance connection names keep several stores (app + tests) from
// colliding in Qt's global connection registry.
QBasicAtomicInt s_connectionCounter = Q_BASIC_ATOMIC_INITIALIZER(0);
}

CacheStore::CacheStore(QObject *parent)
    : QObject(parent)
{
    m_connectionName = QStringLiteral("stock-monitor-cache-%1-%2")
        .arg(QCoreApplication::instance() ? QCoreApplication::applicationPid() : 0)
        .arg(s_connectionCounter.fetchAndAddRelaxed(1));
}

CacheStore::~CacheStore()
{
    if (m_dbOpened)
        m_db.close();
    // Drop this member's reference before unregistering, otherwise
    // removeDatabase refuses and the underlying SQLite handle leaks locked.
    m_db = QSqlDatabase();
    if (!m_connectionName.isEmpty())
        QSqlDatabase::removeDatabase(m_connectionName);
}

void CacheStore::setOwnerScope(const QString &scope)
{
    if (m_scope == scope)
        return;
    // Previous user's private memory entries die with the scope switch.
    if (m_scope != QStringLiteral("anonymous"))
        m_memory.clear();
    m_scope = scope;
}

void CacheStore::setCacheDirectory(const QString &directory)
{
    m_directory = directory;
}

void CacheStore::setMaxDiskBytes(qint64 bytes)
{
    m_maxDiskBytes = qMax<qint64>(1, bytes);
    if (m_dbOpened)
        QTimer::singleShot(0, this, &CacheStore::evictIfNeeded);
}

QString CacheStore::diskPath() const
{
    return databaseFile();
}

QString CacheStore::databaseFile() const
{
    const QString base = m_directory.isEmpty()
        ? QStandardPaths::writableLocation(QStandardPaths::CacheLocation)
        : m_directory;
    return base + QStringLiteral("/response-cache.sqlite");
}

QString CacheStore::scopedKey(const QString &key) const
{
    return m_scope + QLatin1Char('|') + key;
}

bool CacheStore::ensureDatabase()
{
    if (m_dbOpened)
        return m_db.isValid();
    if (!QSqlDatabase::contains(m_connectionName))
        m_db = QSqlDatabase::addDatabase(QStringLiteral("QSQLITE"), m_connectionName);
    else
        m_db = QSqlDatabase::database(m_connectionName);
    const QString file = databaseFile();
    QDir().mkpath(QFileInfo(file).absolutePath());
    m_db.setDatabaseName(file);
    if (!m_db.open()) {
        m_db = QSqlDatabase();
        QSqlDatabase::removeDatabase(m_connectionName);
        return false;
    }
    m_dbOpened = true;

    // Scope the statement: an unfinished PRAGMA would raise SQLITE_LOCKED for
    // the DROP below on this same connection.
    int version = 0;
    {
        QSqlQuery versionQuery(m_db);
        versionQuery.exec(QStringLiteral("PRAGMA user_version"));
        if (versionQuery.next())
            version = versionQuery.value(0).toInt();
    }
    if (version != kSchemaVersion) {
        // Cache is disposable by design: unknown schema -> wipe and rebuild.
        QSqlQuery wipe(m_db);
        wipe.exec(QStringLiteral("DROP TABLE IF EXISTS cache_entries"));
        QSqlQuery setVersion(m_db);
        setVersion.prepare(QStringLiteral("PRAGMA user_version = %1").arg(kSchemaVersion));
        setVersion.exec();
    }
    QSqlQuery create(m_db);
    create.exec(QStringLiteral(
        "CREATE TABLE IF NOT EXISTS cache_entries ("
        "key TEXT PRIMARY KEY,"
        "schema_version INTEGER NOT NULL,"
        "etag TEXT,"
        "fetched_at INTEGER NOT NULL,"
        "expires_at INTEGER NOT NULL,"
        "last_accessed_at INTEGER NOT NULL,"
        "payload BLOB NOT NULL)"));
    if (create.lastError().isValid())
        return false;
    if (version != kSchemaVersion && !m_db.tables().contains(QStringLiteral("cache_entries")))
        return false;  // wipe failed (locked db): degrade to memory-only

    // Idle-time eviction keeps startup path free of cleanup work.
    QTimer::singleShot(0, this, &CacheStore::evictIfNeeded);
    return true;
}

std::optional<CacheEntry> CacheStore::lookup(const QString &key)
{
    const QString fullKey = scopedKey(key);
    const qint64 now = QDateTime::currentMSecsSinceEpoch();

    const auto memoryIt = m_memory.constFind(fullKey);
    if (memoryIt != m_memory.constEnd()) {
        if (memoryIt->entry.isStale(now))
            return std::nullopt;
        MemoryEntry updated = memoryIt.value();
        updated.lastAccessMs = now;
        m_memory.insert(fullKey, updated);
        return memoryIt->entry;
    }

    if (!ensureDatabase())
        return std::nullopt;
    QSqlQuery query(m_db);
    query.prepare(QStringLiteral(
        "SELECT etag, fetched_at, expires_at, payload FROM cache_entries WHERE key = ?"));
    query.addBindValue(fullKey);
    if (!query.exec() || !query.next())
        return std::nullopt;

    CacheEntry entry;
    entry.etag = query.value(0).toString();
    entry.fetchedAtMs = query.value(1).toLongLong();
    entry.expiresAtMs = query.value(2).toLongLong();
    entry.payload = query.value(3).toByteArray();
    if (entry.isStale(now)) {
        QSqlQuery remove(m_db);
        remove.prepare(QStringLiteral("DELETE FROM cache_entries WHERE key = ?"));
        remove.addBindValue(fullKey);
        remove.exec();
        return std::nullopt;
    }
    QSqlQuery touch(m_db);
    touch.prepare(QStringLiteral("UPDATE cache_entries SET last_accessed_at = ? WHERE key = ?"));
    touch.addBindValue(now);
    touch.addBindValue(fullKey);
    touch.exec();
    return entry;
}

void CacheStore::insert(const QString &key, const QByteArray &payload, const QString &etag,
                        qint64 ttlSeconds, bool memoryOnly)
{
    const QString fullKey = scopedKey(key);
    const qint64 now = QDateTime::currentMSecsSinceEpoch();

    MemoryEntry memory;
    memory.entry.payload = payload;
    memory.entry.etag = etag;
    memory.entry.fetchedAtMs = now;
    if (ttlSeconds > 0)
        memory.entry.expiresAtMs = now + ttlSeconds * 1000;
    else if (ttlSeconds < 0)
        memory.entry.expiresAtMs = now - 1;  // pre-expired (tests / forced stale)
    else
        memory.entry.expiresAtMs = 0;  // no expiry
    memory.lastAccessMs = now;
    m_memory.insert(fullKey, memory);

    if (!memoryOnly && ensureDatabase())
        QTimer::singleShot(0, this, &CacheStore::evictIfNeeded);
    if (memoryOnly || !ensureDatabase())
        return;
    QSqlQuery query(m_db);
    query.prepare(QStringLiteral(
        "INSERT INTO cache_entries (key, schema_version, etag, fetched_at, expires_at,"
        " last_accessed_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET schema_version=excluded.schema_version,"
        " etag=excluded.etag, fetched_at=excluded.fetched_at, expires_at=excluded.expires_at,"
        " last_accessed_at=excluded.last_accessed_at, payload=excluded.payload"));
    query.addBindValue(fullKey);
    query.addBindValue(kSchemaVersion);
    query.addBindValue(etag);
    query.addBindValue(memory.entry.fetchedAtMs);
    query.addBindValue(memory.entry.expiresAtMs);
    query.addBindValue(now);
    query.addBindValue(payload);
    query.exec();
}

void CacheStore::remove(const QString &key)
{
    const QString fullKey = scopedKey(key);
    m_memory.remove(fullKey);
    if (!ensureDatabase())
        return;
    QSqlQuery query(m_db);
    query.prepare(QStringLiteral("DELETE FROM cache_entries WHERE key = ?"));
    query.addBindValue(fullKey);
    query.exec();
}

void CacheStore::clearOwner()
{
    if (m_scope == QStringLiteral("anonymous")) {
        m_memory.clear();
        return;
    }
    const QString prefix = m_scope + QLatin1Char('|');
    for (auto it = m_memory.begin(); it != m_memory.end();) {
        if (it.key().startsWith(prefix))
            it = m_memory.erase(it);
        else
            ++it;
    }
    if (!ensureDatabase())
        return;
    QSqlQuery query(m_db);
    query.prepare(QStringLiteral("DELETE FROM cache_entries WHERE key LIKE ? ESCAPE '\\'"));
    // Scope strings are internal (host + user subject); escape LIKE wildcards anyway.
    QString pattern = prefix;
    pattern.replace(QLatin1Char('\\'), QStringLiteral("\\\\"))
           .replace(QLatin1Char('%'), QStringLiteral("\\%"))
           .replace(QLatin1Char('_'), QStringLiteral("\\_"))
           .append(QLatin1Char('%'));
    query.addBindValue(pattern);
    query.exec();
}

void CacheStore::clearAll()
{
    m_memory.clear();
    if (!ensureDatabase())
        return;
    QSqlQuery query(m_db);
    query.exec(QStringLiteral("DELETE FROM cache_entries"));
    query.exec(QStringLiteral("VACUUM"));
}

qint64 CacheStore::diskUsageBytes()
{
    if (!ensureDatabase())
        return 0;
    QSqlQuery query(m_db);
    query.exec(QStringLiteral("SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM cache_entries"));
    if (query.next())
        return query.value(0).toLongLong();
    return 0;
}

void CacheStore::evictIfNeeded()
{
    if (!m_dbOpened)
        return;
    qint64 usage = diskUsageBytes();
    if (usage <= m_maxDiskBytes)
        return;
    const qint64 target = m_maxDiskBytes * 8 / 10;  // evict down to 80%
    QSqlQuery select(m_db);
    select.exec(QStringLiteral(
        "SELECT key, LENGTH(payload) FROM cache_entries"
        " ORDER BY last_accessed_at ASC"));
    QVector<QPair<QString, qint64>> victims;
    qint64 projected = usage;
    while (select.next() && projected > target) {
        victims.append({select.value(0).toString(), select.value(1).toLongLong()});
        projected -= select.value(1).toLongLong();
    }
    if (victims.isEmpty())
        return;
    QSqlQuery remove(m_db);
    remove.prepare(QStringLiteral("DELETE FROM cache_entries WHERE key = ?"));
    for (const auto &[key, size] : victims) {
        remove.addBindValue(key);
        remove.exec();
        m_memory.remove(key);
    }
}
