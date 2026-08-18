#pragma once

#include <QTcpServer>
#include <QTcpSocket>
#include <QByteArray>
#include <functional>
#include <QPair>

// Minimal local HTTP/1.1 server for transport tests. The handler receives the
// full request (request line + headers + body) and returns {status, body}
// (or, for streaming responses, writes raw bytes itself and returns a null
// status). No Q_OBJECT: only lambda-based connections are used.
class MockHttpServer final : public QObject
{
public:
    struct Response {
        int status = 0;          // 0 = handler already wrote a raw streaming response
        QByteArray body;
        QByteArray contentType = "application/json";
    };
    using Handler = std::function<Response(const QByteArray &request)>;

    bool start(Handler handler)
    {
        m_handler = std::move(handler);
        if (!m_server.listen(QHostAddress::LocalHost))
            return false;
        connect(&m_server, &QTcpServer::newConnection, this, [this] {
            auto *socket = m_server.nextPendingConnection();
            connect(socket, &QTcpSocket::readyRead, this, [this, socket] {
                m_buffers[socket].append(socket->readAll());
                tryRespond(socket);
            });
            connect(socket, &QTcpSocket::disconnected, socket, &QTcpSocket::deleteLater);
        });
        return true;
    }

    quint16 port() const { return m_server.serverPort(); }
    QString baseUrl() const { return QStringLiteral("http://127.0.0.1:%1").arg(port()); }

private:
    void tryRespond(QTcpSocket *socket)
    {
        QByteArray &buffer = m_buffers[socket];
        const int headerEnd = buffer.indexOf("\r\n\r\n");
        if (headerEnd < 0)
            return;
        const QByteArray headers = buffer.left(headerEnd);
        int contentLength = 0;
        const int lengthPos = headers.indexOf("Content-Length:");
        if (lengthPos >= 0) {
            const int lineEnd = headers.indexOf("\r\n", lengthPos);
            contentLength = headers.mid(lengthPos + 15, lineEnd - lengthPos - 15).trimmed().toInt();
        }
        if (buffer.size() < headerEnd + 4 + contentLength)
            return;

        const QByteArray request = buffer.left(headerEnd + 4 + contentLength);
        buffer.remove(0, headerEnd + 4 + contentLength);
        const Response response = m_handler ? m_handler(request) : Response{400, "no handler"};
        if (response.status == 0)
            return;  // streaming handler already wrote bytes
        QByteArray statusText;
        switch (response.status) {
        case 200: statusText = "OK"; break;
        case 204: statusText = "No Content"; break;
        case 400: statusText = "Bad Request"; break;
        case 401: statusText = "Unauthorized"; break;
        case 403: statusText = "Forbidden"; break;
        case 404: statusText = "Not Found"; break;
        case 500: statusText = "Internal Server Error"; break;
        default: statusText = "Status"; break;
        }
        socket->write("HTTP/1.1 " + QByteArray::number(response.status) + " " + statusText
                      + "\r\nContent-Type: " + response.contentType
                      + "\r\nContent-Length: " + QByteArray::number(response.body.size())
                      + "\r\nConnection: close\r\n\r\n" + response.body);
        socket->flush();
        socket->disconnectFromHost();
        m_buffers.remove(socket);
    }

    QTcpServer m_server;
    Handler m_handler;
    QHash<QTcpSocket *, QByteArray> m_buffers;
};
