#pragma once

#include <QObject>

// OS credential store wrapper for the refresh token (QtKeychain / Secret
// Service). Fail-closed: when the keyring is unavailable the vault degrades
// to SessionOnly — secrets live in memory for this run and are never written
// to QSettings, SQLite, or any plaintext file.
class TokenVault final : public QObject
{
    Q_OBJECT

public:
    enum class Backend { Keychain, Memory };
    enum class Mode { Persistent, SessionOnly };

    explicit TokenVault(Backend backend, QObject *parent = nullptr);

    Mode mode() const { return m_mode; }
    bool persistSupported() const { return m_mode == Mode::Persistent; }
    QString memorySecret() const { return m_memory; }

    // All keyring operations are asynchronous; results arrive via signals.
    void store(const QString &account, const QString &secret);
    void load(const QString &account);
    void clear(const QString &account);

signals:
    void loaded(const QString &account, const QString &secret);  // empty secret = none stored
    void storeFinished(const QString &account, bool persisted);
    void cleared(const QString &account);
    void vaultUnavailable(const QString &reason);  // mode changed to SessionOnly
    void modeChanged();

private:
    void degradeToSessionOnly(const QString &reason);

    Backend m_backend;
    Mode m_mode = Mode::SessionOnly;
    QString m_memory;
};
