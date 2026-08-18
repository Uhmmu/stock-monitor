#include "app/TokenVault.h"

#ifdef STOCK_MONITOR_HAVE_QTKEYCHAIN
#include <qt6keychain/keychain.h>
#endif

#ifdef STOCK_MONITOR_HAVE_QTKEYCHAIN
namespace {
constexpr char kServiceName[] = "StockMonitorDesktop";
}
#endif

TokenVault::TokenVault(Backend backend, QObject *parent)
    : QObject(parent), m_backend(backend)
{
    if (m_backend == Backend::Keychain)
        m_mode = Mode::Persistent;
}

void TokenVault::store(const QString &account, const QString &secret)
{
    m_memory = secret;  // session copy always kept for reconnects within this run

#ifdef STOCK_MONITOR_HAVE_QTKEYCHAIN
    if (m_mode != Mode::Persistent || account.isEmpty() || secret.isEmpty()) {
        emit storeFinished(account, false);
        return;
    }
    auto *job = new QKeychain::WritePasswordJob(QString::fromLatin1(kServiceName), this);
    job->setAutoDelete(true);
    job->setKey(account);
    job->setTextData(secret);
    connect(job, &QKeychain::Job::finished, job, [this, job, account](QKeychain::Job *) {
        if (job->error() == QKeychain::Error::NoError) {
            emit storeFinished(account, true);
            return;
        }
        // Keyring broke after login: keep running on the in-memory copy.
        degradeToSessionOnly(job->errorString());
        emit storeFinished(account, false);
    });
    job->start();
#else
    emit storeFinished(account, false);
#endif
}

void TokenVault::load(const QString &account)
{
#ifdef STOCK_MONITOR_HAVE_QTKEYCHAIN
    if (m_mode == Mode::Persistent && !account.isEmpty()) {
        auto *job = new QKeychain::ReadPasswordJob(QString::fromLatin1(kServiceName), this);
        job->setAutoDelete(true);
        job->setKey(account);
        connect(job, &QKeychain::Job::finished, job, [this, job, account](QKeychain::Job *) {
            if (job->error() == QKeychain::Error::NoError) {
                m_memory = job->textData();
                emit loaded(account, m_memory);
                return;
            }
            if (job->error() == QKeychain::Error::EntryNotFound) {
                emit loaded(account, QString());
                return;
            }
            // No usable Secret Service (or access denied): fail closed to
            // session-only instead of inventing a plaintext store.
            degradeToSessionOnly(job->errorString());
            emit loaded(account, QString());
        });
        job->start();
        return;
    }
#else
    Q_UNUSED(account);
#endif
    emit loaded(account, m_mode == Mode::Persistent ? QString() : m_memory);
}

void TokenVault::clear(const QString &account)
{
    m_memory.clear();
#ifdef STOCK_MONITOR_HAVE_QTKEYCHAIN
    if (m_mode == Mode::Persistent && !account.isEmpty()) {
        auto *job = new QKeychain::DeletePasswordJob(QString::fromLatin1(kServiceName), this);
        job->setAutoDelete(true);
        job->setKey(account);
        connect(job, &QKeychain::Job::finished, job, [this, account](QKeychain::Job *) {
            // Missing entry is fine; other errors only mean an orphaned
            // keyring item that a future overwrite replaces.
            emit cleared(account);
        });
        job->start();
        return;
    }
#else
    Q_UNUSED(account);
#endif
    emit cleared(account);
}

void TokenVault::degradeToSessionOnly(const QString &reason)
{
    if (m_mode == Mode::SessionOnly)
        return;
    m_mode = Mode::SessionOnly;
    emit modeChanged();
    emit vaultUnavailable(reason);
}
