#include "network/RequestHandle.h"

#include <QNetworkReply>

void RequestHandle::cancel()
{
    if (m_reply) {
        if (m_owner)
            m_reply->disconnect(m_owner);
        m_reply->abort();
        m_reply->deleteLater();
        m_reply = nullptr;
    }
}

bool RequestHandle::isActive() const
{
    return m_reply && !m_reply->isFinished();
}
