#include "dashboard/DashboardStore.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QUrlQuery>
#include <QtMath>

#include "app/AppEnvironment.h"
#include "cache/CacheStore.h"
#include "network/ApiClient.h"
#include "network/SseStream.h"

namespace {
constexpr auto kCacheKey = "dashboard:v1";
constexpr qint64 kStaleAfterSeconds = 10 * 60;

double numberOrNan(const QJsonValue &value)
{
    return value.isDouble() ? value.toDouble() : qQNaN();
}
}

DashboardStore::DashboardStore(AppEnvironment *environment, ApiClient *api, CacheStore *cache,
                               std::function<QByteArray()> tokenProvider, QObject *parent)
    : QObject(parent), m_environment(environment), m_api(api), m_cache(cache),
      m_tokenProvider(std::move(tokenProvider)), m_stream(new SseStream(&m_streamNetwork, this)),
      m_quotes(this)
{
    m_refreshTimer.setInterval(5 * 60 * 1000);
    connect(&m_refreshTimer, &QTimer::timeout, this, &DashboardStore::refresh);
    m_ageTimer.setInterval(60 * 1000);
    connect(&m_ageTimer, &QTimer::timeout, this, &DashboardStore::changed);
    connect(m_stream, &SseStream::eventReceived, this, &DashboardStore::handleStreamEvent);
    connect(m_stream, &SseStream::stateChanged, this, [this](SseStream::State state) {
        switch (state) {
        case SseStream::State::Connecting: m_streamStatus = QStringLiteral("connecting"); break;
        case SseStream::State::Connected: m_streamStatus = QStringLiteral("connected"); break;
        case SseStream::State::Reconnecting: m_streamStatus = QStringLiteral("reconnecting"); break;
        case SseStream::State::Completed: m_streamStatus = QStringLiteral("completed"); break;
        case SseStream::State::Failed: m_streamStatus = m_active ? QStringLiteral("fallback") : QStringLiteral("idle"); break;
        case SseStream::State::Idle: m_streamStatus = QStringLiteral("idle"); break;
        }
        emit changed();
    });
    connect(m_stream, &SseStream::connectionError, this, [this](const QString &) {
        m_streamStatus = QStringLiteral("fallback");
        emit changed();
    });
    connect(m_api, &ApiClient::sessionRefreshed, this, [this] {
        if (m_active) {
            stopStream();
            restartStream();
        }
    });
}

bool DashboardStore::stale() const
{
    return m_failedSinceLastGood || (m_fetchedAtMs > 0 && freshnessAgeSeconds() >= kStaleAfterSeconds);
}

qint64 DashboardStore::freshnessAgeSeconds() const
{
    return m_fetchedAtMs > 0 ? qMax<qint64>(0, (QDateTime::currentMSecsSinceEpoch() - m_fetchedAtMs) / 1000) : -1;
}

void DashboardStore::setActive(bool active)
{
    if (m_active == active)
        return;
    m_active = active;
    if (active) {
        loadLastGood();
        refresh();
        m_refreshTimer.start();
        m_ageTimer.start();
    } else {
        m_refreshTimer.stop();
        m_ageTimer.stop();
        stopStream();
    }
    emit changed();
}

void DashboardStore::refresh()
{
    if (m_busy)
        return;
    m_busy = true;
    m_error.clear();
    ++m_requestCount;
    emit changed();
    m_request = m_api->get(QStringLiteral("dashboard"),
        [this](const ApiError &error, const QJsonObject &json) {
            m_busy = false;
            if (!error.message.isEmpty() || error.httpStatus != 0) {
                m_error = error.toDisplayString();
                m_failedSinceLastGood = m_fetchedAtMs > 0;
                emit changed();
                return;
            }
            const qint64 now = QDateTime::currentMSecsSinceEpoch();
            applyDashboard(json, now, false);
            if (m_fetchedAtMs != now) {
                m_error = tr("Dashboard 响应缺少必要字段。");
                m_failedSinceLastGood = hasData();
                emit changed();
                return;
            }
            m_cache->insert(QString::fromLatin1(kCacheKey),
                            QJsonDocument(json).toJson(QJsonDocument::Compact), {}, 0);
        },
        {.name = QStringLiteral("dashboard"), .retryable = true});
}

void DashboardStore::loadLastGood()
{
    if (m_fetchedAtMs > 0)
        return;
    const auto entry = m_cache->lookup(QString::fromLatin1(kCacheKey));
    if (!entry)
        return;
    const QJsonDocument document = QJsonDocument::fromJson(entry->payload);
    if (document.isObject())
        applyDashboard(document.object(), entry->fetchedAtMs, true);
}

void DashboardStore::applyDashboard(const QJsonObject &json, qint64 fetchedAtMs, bool fromCache)
{
    bool marketOpen = false;
    QDateTime checkedAt;
    QVector<WatchlistQuoteRow> rows;
    if (!parseDashboard(json, &marketOpen, &checkedAt, &rows))
        return;
    m_marketOpen = marketOpen;
    m_marketCheckedAt = checkedAt;
    m_quotes.replaceRows(rows);
    m_fetchedAtMs = fetchedAtMs;
    m_failedSinceLastGood = fromCache;
    m_error.clear();
    if (m_active)
        restartStream();
    emit changed();
}

bool DashboardStore::parseDashboard(const QJsonObject &json, bool *marketOpen,
                                    QDateTime *marketCheckedAt, QVector<WatchlistQuoteRow> *rows)
{
    if (!json.value(QStringLiteral("market")).isObject()
        || !json.value(QStringLiteral("stocks")).isArray())
        return false;
    const QJsonObject market = json.value(QStringLiteral("market")).toObject();
    const QDateTime checked = QDateTime::fromString(
        market.value(QStringLiteral("checked_at")).toString(), Qt::ISODate);
    if (!market.value(QStringLiteral("is_open")).isBool() || !checked.isValid())
        return false;

    QVector<WatchlistQuoteRow> parsed;
    const QJsonArray stocks = json.value(QStringLiteral("stocks")).toArray();
    parsed.reserve(stocks.size());
    for (const QJsonValue &value : stocks) {
        if (!value.isObject())
            continue;
        const QJsonObject stock = value.toObject();
        WatchlistQuoteRow row;
        row.ticker = stock.value(QStringLiteral("ticker")).toString().trimmed().toUpper();
        if (row.ticker.isEmpty())
            continue;
        row.companyName = stock.value(QStringLiteral("company_name")).toString();
        row.price = numberOrNan(stock.value(QStringLiteral("price")));
        row.previousClose = numberOrNan(stock.value(QStringLiteral("previous_close")));
        row.volume = numberOrNan(stock.value(QStringLiteral("volume")));
        row.volumeRatio = numberOrNan(stock.value(QStringLiteral("volume_ratio")));
        row.volumeLabel = stock.value(QStringLiteral("volume_label")).toString();
        row.priceSource = stock.value(QStringLiteral("price_source")).toString();
        row.baseUpdatedAtMs = timestampMs(stock.value(QStringLiteral("updated_at")));
        parsed.append(std::move(row));
    }
    *marketOpen = market.value(QStringLiteral("is_open")).toBool();
    *marketCheckedAt = checked;
    *rows = std::move(parsed);
    return true;
}

void DashboardStore::restartStream()
{
    // The current server contract accepts at most 50 symbols per stream.
    const QString symbols = m_quotes.tickers().mid(0, 50).join(QLatin1Char(','));
    if (symbols.isEmpty()) {
        stopStream();
        return;
    }
    if (symbols == m_streamSymbols && (m_stream->state() == SseStream::State::Connected
                                       || m_stream->state() == SseStream::State::Connecting
                                       || m_stream->state() == SseStream::State::Reconnecting))
        return;
    m_stream->stop();
    m_streamSymbols = symbols;
    QUrl url = m_environment->apiUrl(QStringLiteral("market/realtime/stream"));
    QUrlQuery query;
    query.addQueryItem(QStringLiteral("symbols"), symbols);
    url.setQuery(query);
    m_stream->start(url, m_tokenProvider ? m_tokenProvider() : QByteArray());
}

void DashboardStore::stopStream()
{
    m_streamSymbols.clear();
    m_stream->stop();
    m_streamStatus = QStringLiteral("idle");
}

void DashboardStore::handleStreamEvent(const QString &eventType, const QString &data)
{
    const QJsonDocument document = QJsonDocument::fromJson(data.toUtf8());
    if (!document.isObject())
        return;
    QJsonObject object = document.object();
    if (eventType == QLatin1String("quote_update")) {
        if (object.value(QStringLiteral("authoritative_quote")).isObject())
            object = object.value(QStringLiteral("authoritative_quote")).toObject();
        const QString provider = object.value(QStringLiteral("provider")).toString();
        const QString feed = object.value(QStringLiteral("feed")).toString();
        m_quotes.applyRealtimeQuote(
            object.value(QStringLiteral("symbol")).toString(),
            numberOrNan(object.value(QStringLiteral("price"))),
            numberOrNan(object.value(QStringLiteral("previous_close"))),
            numberOrNan(object.value(QStringLiteral("volume"))),
            feed.isEmpty() ? provider : provider + QLatin1Char(':') + feed,
            timestampMs(object.value(QStringLiteral("timestamp"))));
        return;
    }
    if (eventType == QLatin1String("market_event")) {
        QVariantMap event;
        event.insert(QStringLiteral("symbol"), object.value(QStringLiteral("symbol")).toString());
        event.insert(QStringLiteral("eventType"), object.value(QStringLiteral("event_type")).toString());
        event.insert(QStringLiteral("severity"), object.value(QStringLiteral("severity")).toString());
        event.insert(QStringLiteral("timestamp"), object.value(QStringLiteral("timestamp")).toString());
        m_recentEvents.prepend(event);
        while (m_recentEvents.size() > 5)
            m_recentEvents.removeLast();
        emit changed();
    } else if (eventType == QLatin1String("provider_status")
               && object.value(QStringLiteral("connected")).isBool()
               && !object.value(QStringLiteral("connected")).toBool()) {
        m_streamStatus = QStringLiteral("fallback");
        emit changed();
    }
}

qint64 DashboardStore::timestampMs(const QJsonValue &value)
{
    if (value.isDouble()) {
        const double raw = value.toDouble();
        return static_cast<qint64>(raw > 10'000'000'000.0 ? raw : raw * 1000.0);
    }
    const QDateTime parsed = QDateTime::fromString(value.toString(), Qt::ISODate);
    return parsed.isValid() ? parsed.toMSecsSinceEpoch() : 0;
}
