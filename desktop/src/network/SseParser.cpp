#include "network/SseParser.h"

void SseParser::feed(const QByteArray &chunk, QVector<SseEvent> *out)
{
    m_buffer.append(chunk);
    int start = 0;
    while (true) {
        const int newline = m_buffer.indexOf('\n', start);
        if (newline < 0)
            break;
        QByteArray line = m_buffer.mid(start, newline - start);
        if (line.endsWith('\r'))
            line.chop(1);
        processLine(line, out);
        start = newline + 1;
    }
    m_buffer.remove(0, start);
}

void SseParser::reset()
{
    m_buffer.clear();
    m_pendingData.clear();
    m_hasData = false;
    m_pendingEventType.clear();
    m_hasEventType = false;
}

void SseParser::processLine(const QByteArray &line, QVector<SseEvent> *out)
{
    if (line.isEmpty()) {
        dispatch(out);
        return;
    }
    if (line.startsWith(':')) {
        // Comment / heartbeat: surfaced as a non-data event so the stream can
        // reset its idle timer without disturbing a partially accumulated event.
        SseEvent comment;
        comment.isComment = true;
        comment.data = QString::fromUtf8(line.mid(1)).trimmed();
        out->append(std::move(comment));
        return;
    }

    QByteArray field = line;
    QByteArray value;
    const int colon = line.indexOf(':');
    if (colon >= 0) {
        field = line.left(colon);
        value = line.mid(colon + 1);
        if (value.startsWith(' '))
            value.remove(0, 1);
    }

    if (field == "event") {
        m_pendingEventType = value;
        m_hasEventType = true;
    } else if (field == "data") {
        if (m_hasData)
            m_pendingData.append('\n');
        m_pendingData.append(value);
        m_hasData = true;
    }
    // `id` and `retry` are accepted but ignored: no Last-Event-ID resume in v1.
}

void SseParser::dispatch(QVector<SseEvent> *out)
{
    if (m_hasData) {
        SseEvent event;
        event.eventType = m_hasEventType
            ? QString::fromUtf8(m_pendingEventType) : QStringLiteral("message");
        event.data = QString::fromUtf8(m_pendingData);
        out->append(std::move(event));
    }
    m_pendingData.clear();
    m_hasData = false;
    m_pendingEventType.clear();
    m_hasEventType = false;
}
