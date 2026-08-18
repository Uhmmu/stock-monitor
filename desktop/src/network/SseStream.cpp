#include "network/SseStream.h"

#include <QNetworkReply>
#include <QNetworkRequest>
#include <QRandomGenerator>

SseStream::SseStream(QNetworkAccessManager *network, QObject *parent)
    : QObject(parent), m_network(network)
{
    m_reconnectTimer.setSingleShot(true);
    connect(&m_reconnectTimer, &QTimer::timeout, this, &SseStream::connectOnce);
}

SseStream::~SseStream()
{
    stop();
}

void SseStream::start(const QUrl &url, const QByteArray &bearerToken)
{
    m_url = url;
    m_bearer = bearerToken;
    m_userStopped = false;
    m_attempts = 0;
    m_reconnectTimer.stop();
    connectOnce();
}

void SseStream::stop()
{
    m_userStopped = true;
    m_reconnectTimer.stop();
    if (m_reply) {
        m_reply->disconnect(this);
        m_reply->abort();
        m_reply->deleteLater();
        m_reply = nullptr;
    }
    if (m_state != State::Idle && m_state != State::Failed)
        setState(State::Failed);
}

void SseStream::setTerminalEvents(const QStringList &eventTypes)
{
    m_terminalEvents = eventTypes;
}

void SseStream::setBackoffSchedule(QVector<int> delaysMs)
{
    m_backoffMs = delaysMs.isEmpty() ? QVector<int>{0} : delaysMs;
}

void SseStream::connectOnce()
{
    if (!m_network || m_userStopped)
        return;

    QNetworkRequest request(m_url);
    request.setRawHeader("Accept", "text/event-stream");
    request.setRawHeader("Cache-Control", "no-cache");
    if (!m_bearer.isEmpty())
        request.setRawHeader("Authorization", "Bearer " + m_bearer);
    // Timeouts are handled by the heartbeat/idle logic, not a hard reply timer:
    // an SSE response is intentionally long-lived.
    request.setTransferTimeout(0);

    m_parser.reset();
    setState(m_attempts == 0 ? State::Connecting : State::Reconnecting);
    m_reply = m_network->get(request);

    connect(m_reply, &QNetworkReply::readyRead, this, [this] {
        if (state() != State::Connected)
            setState(State::Connected);
        QVector<SseEvent> events;
        m_parser.feed(m_reply->readAll(), &events);
        handleEvents(events);
    });
    connect(m_reply, &QNetworkReply::finished, this, [this] {
        // Flush any tail bytes the parser has not seen (server closed mid-line).
        QVector<SseEvent> events;
        m_parser.feed("\n", &events);
        handleEvents(events);
        m_reply->deleteLater();
        m_reply = nullptr;
        if (m_state == State::Completed || m_userStopped)
            return;
        // Server closed a healthy stream without a terminal event: reconnect.
        emit connectionError(tr("连接中断，正在重连…"));
        scheduleReconnect();
    });
}

void SseStream::scheduleReconnect()
{
    const int index = qMin(m_attempts, m_backoffMs.size() - 1);
    const int base = m_backoffMs.at(index);
    const int jitter = QRandomGenerator::global()->bounded(500);
    m_attempts += 1;
    setState(State::Reconnecting);
    m_reconnectTimer.start(base + jitter);
}

void SseStream::handleEvents(const QVector<SseEvent> &events)
{
    for (const SseEvent &event : events) {
        if (event.isComment) {
            emit commentReceived(event.data);
            continue;
        }
        emit eventReceived(event.eventType, event.data);
        if (m_terminalEvents.contains(event.eventType)) {
            // Deliver the terminal event, then stop permanently.
            if (m_reply) {
                m_reply->disconnect(this);
                m_reply->abort();
                m_reply->deleteLater();
                m_reply = nullptr;
            }
            setState(State::Completed);
            return;
        }
    }
}

void SseStream::setState(State state)
{
    if (m_state == state)
        return;
    m_state = state;
    emit stateChanged(m_state);
}
