#pragma once

#include <QNetworkReply>
#include <QPointer>

// Owning handle for one in-flight request. Copies share the reply: cancelling
// any copy aborts the underlying request and stops pending retries.
class RequestHandle
{
public:
    RequestHandle() = default;
    explicit RequestHandle(QNetworkReply *reply, quint64 id, QObject *owner)
        : m_reply(reply), m_id(id), m_owner(owner) {}

    // `owner` is the object receiving the reply's signals (the ApiClient);
    // only those connections are severed so QNAM internals stay intact.
    void cancel();
    bool isActive() const;
    quint64 id() const { return m_id; }

private:
    QPointer<QNetworkReply> m_reply;
    quint64 m_id = 0;
    QPointer<QObject> m_owner;
};

// Monotonic generation counter for "newest selection wins" guards: a store
// bumps the generation when state changes; stale replies compare unequal and
// must not overwrite newer results.
class GenerationCounter
{
public:
    quint64 next() { return ++m_value; }
    quint64 current() const { return m_value; }

private:
    quint64 m_value = 0;
};
