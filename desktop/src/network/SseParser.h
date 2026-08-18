#pragma once

#include <QByteArray>
#include <QString>
#include <QVector>

// Incremental Server-Sent Events parser operating on raw byte chunks.
//
// Chunk boundaries never split a line in the middle of a UTF-8 multi-byte
// sequence in a way that matters: SSE lines are delimited by '\n' (0x0A),
// which cannot appear inside a multi-byte character. Line payloads are
// accumulated as bytes and decoded as UTF-8 only when an event is complete.
struct SseEvent {
    QString eventType = QStringLiteral("message");
    QString data;
    bool isComment = false;  // heartbeat/comment lines, surfaced but not dispatched as data
};

class SseParser
{
public:
    // Feed one raw chunk; appends every completed event to `out`.
    void feed(const QByteArray &chunk, QVector<SseEvent> *out);
    // Discard buffered partial state (used on reconnect).
    void reset();

private:
    void processLine(const QByteArray &line, QVector<SseEvent> *out);
    void dispatch(QVector<SseEvent> *out);

    QByteArray m_buffer;
    QByteArray m_pendingData;   // joined with '\n' between data lines
    bool m_hasData = false;
    QByteArray m_pendingEventType;
    bool m_hasEventType = false;
};
