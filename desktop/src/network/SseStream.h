#pragma once

#include <QObject>
#include <QPointer>
#include <QTimer>
#include <QUrl>

#include "network/SseParser.h"

class QNetworkAccessManager;
class QNetworkReply;

// One SSE connection with bounded exponential backoff + jitter reconnect.
// Terminal events (server says the logical stream is over) stop reconnection
// without losing the event itself.
class SseStream : public QObject
{
    Q_OBJECT

public:
    enum class State {
        Idle,
        Connecting,
        Connected,
        Reconnecting,
        Completed,  // terminal event received; will not reconnect
        Failed,     // stop() called or unrecoverable; will not reconnect
    };
    Q_ENUM(State)

    explicit SseStream(QNetworkAccessManager *network, QObject *parent = nullptr);
    ~SseStream() override;

    void start(const QUrl &url, const QByteArray &bearerToken = {});
    void stop();
    void setTerminalEvents(const QStringList &eventTypes);
    void setBackoffSchedule(QVector<int> delaysMs);  // test hook; default 1..30s
    State state() const { return m_state; }
    int reconnectAttempts() const { return m_attempts; }

signals:
    void eventReceived(const QString &eventType, const QString &data);
    void commentReceived(const QString &text);  // heartbeat
    void stateChanged(SseStream::State state);
    void connectionError(const QString &message);

private:
    void setState(State state);
    void connectOnce();
    void scheduleReconnect();
    void handleEvents(const QVector<SseEvent> &events);

    QPointer<QNetworkAccessManager> m_network;
    QNetworkReply *m_reply = nullptr;
    SseParser m_parser;
    QTimer m_reconnectTimer;
    QStringList m_terminalEvents;
    QVector<int> m_backoffMs = {1000, 2000, 4000, 8000, 16000, 30000};
    QUrl m_url;
    QByteArray m_bearer;
    State m_state = State::Idle;
    int m_attempts = 0;
    bool m_userStopped = true;
};
