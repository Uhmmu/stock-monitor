#include "watchlist/WatchlistStore.h"

#include <QDateTime>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <QSet>
#include <QUrlQuery>
#include <QtMath>

#include <algorithm>
#include <cmath>
#include <utility>

#include "app/AppEnvironment.h"
#include "network/ApiClient.h"
#include "network/SseStream.h"

namespace {

QString normalizedTicker(const QString &value)
{
    return value.trimmed().toUpper();
}

QVariant optionalNumber(const QJsonValue &value)
{
    if (!value.isDouble() || !std::isfinite(value.toDouble()))
        return {};
    return value.toDouble();
}

QVariant optionalInteger(const QJsonValue &value)
{
    if (!value.isDouble())
        return {};
    return value.toInteger();
}

QVariantMap parseManagedItem(const QJsonObject &object, bool matched)
{
    QVariantMap row;
    const QString ticker = normalizedTicker(object.value(QStringLiteral("ticker")).toString());
    if (ticker.isEmpty())
        return row;
    row.insert(QStringLiteral("id"), optionalInteger(object.value(QStringLiteral("watchlist_id"))));
    if (!row.value(QStringLiteral("id")).isValid())
        row.insert(QStringLiteral("id"), optionalInteger(object.value(QStringLiteral("id"))));
    row.insert(QStringLiteral("ticker"), ticker);
    row.insert(QStringLiteral("companyName"), object.value(QStringLiteral("company_name")).toString());
    row.insert(QStringLiteral("officialSector"), object.value(QStringLiteral("official_sector")).toString());
    row.insert(QStringLiteral("officialIndustry"), object.value(QStringLiteral("official_industry")).toString());
    row.insert(QStringLiteral("userGroupId"), optionalInteger(object.value(QStringLiteral("user_group_id"))));
    row.insert(QStringLiteral("displayOrder"), object.value(QStringLiteral("display_order")).toInt());
    row.insert(QStringLiteral("isWatchlisted"), object.value(QStringLiteral("is_watchlisted")).toBool(!matched));
    row.insert(QStringLiteral("isPeerReferenced"), object.value(QStringLiteral("is_peer_referenced")).toBool(false));
    row.insert(QStringLiteral("peerReferencedBy"), object.value(QStringLiteral("peer_referenced_by")).toVariant());
    row.insert(QStringLiteral("price"), optionalNumber(object.value(QStringLiteral("price"))));
    row.insert(QStringLiteral("changePercent"), optionalNumber(object.value(QStringLiteral("change_percent"))));
    row.insert(QStringLiteral("alertEnabled"), object.value(QStringLiteral("alert_enabled")).toBool(true));
    row.insert(QStringLiteral("threshold20m"), optionalNumber(object.value(QStringLiteral("threshold_20m"))));
    row.insert(QStringLiteral("threshold1h"), optionalNumber(object.value(QStringLiteral("threshold_1h"))));
    row.insert(QStringLiteral("thresholdDay"), optionalNumber(object.value(QStringLiteral("threshold_day"))));
    row.insert(QStringLiteral("quoteUpdatedAtMs"), qint64(0));
    return row;
}

QVariantMap parseGroup(const QJsonObject &object)
{
    QVariantMap group;
    const qint64 id = object.value(QStringLiteral("id")).toInteger();
    const QString name = object.value(QStringLiteral("name")).toString().trimmed();
    if (id <= 0 || name.isEmpty())
        return group;
    group.insert(QStringLiteral("id"), id);
    group.insert(QStringLiteral("name"), name);
    group.insert(QStringLiteral("displayOrder"), object.value(QStringLiteral("display_order")).toInt());
    return group;
}

bool isSuccessful(const ApiError &error)
{
    return error.message.isEmpty() && error.httpStatus == 0;
}

QString displayError(const ApiError &error, const QString &fallback)
{
    const QString text = error.toDisplayString();
    return text.isEmpty() ? fallback : text;
}

} // namespace

WatchlistItemModel::WatchlistItemModel(QObject *parent)
    : QAbstractListModel(parent)
{
}

int WatchlistItemModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_rows.size();
}

QVariant WatchlistItemModel::roleValue(const QVariantMap &row, const char *key)
{
    return row.value(QString::fromLatin1(key));
}

bool WatchlistItemModel::finiteNumber(const QVariant &value)
{
    return value.isValid() && value.canConvert<double>() && std::isfinite(value.toDouble());
}

QVariant WatchlistItemModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_rows.size())
        return {};
    const QVariantMap &row = m_rows.at(index.row());
    switch (role) {
    case IdRole: return roleValue(row, "id");
    case TickerRole: return roleValue(row, "ticker");
    case CompanyNameRole: return roleValue(row, "companyName");
    case OfficialSectorRole: return roleValue(row, "officialSector");
    case OfficialIndustryRole: return roleValue(row, "officialIndustry");
    case UserGroupIdRole: return roleValue(row, "userGroupId");
    case DisplayOrderRole: return roleValue(row, "displayOrder");
    case IsWatchlistedRole: return roleValue(row, "isWatchlisted");
    case IsPeerReferencedRole: return roleValue(row, "isPeerReferenced");
    case PeerReferencedByRole: return roleValue(row, "peerReferencedBy");
    case PriceRole: return roleValue(row, "price");
    case ChangePercentRole: return roleValue(row, "changePercent");
    case AlertEnabledRole: return roleValue(row, "alertEnabled");
    case Threshold20mRole: return roleValue(row, "threshold20m");
    case Threshold1hRole: return roleValue(row, "threshold1h");
    case ThresholdDayRole: return roleValue(row, "thresholdDay");
    case HasPriceRole: return finiteNumber(roleValue(row, "price"));
    case SectionNameRole: return roleValue(row, "sectionName");
    default: return {};
    }
}

QHash<int, QByteArray> WatchlistItemModel::roleNames() const
{
    return {
        {IdRole, "id"},
        {TickerRole, "ticker"},
        {CompanyNameRole, "companyName"},
        {OfficialSectorRole, "officialSector"},
        {OfficialIndustryRole, "officialIndustry"},
        {UserGroupIdRole, "userGroupId"},
        {DisplayOrderRole, "displayOrder"},
        {IsWatchlistedRole, "isWatchlisted"},
        {IsPeerReferencedRole, "isPeerReferenced"},
        {PeerReferencedByRole, "peerReferencedBy"},
        {PriceRole, "price"},
        {ChangePercentRole, "changePercent"},
        {AlertEnabledRole, "alertEnabled"},
        {Threshold20mRole, "threshold20m"},
        {Threshold1hRole, "threshold1h"},
        {ThresholdDayRole, "thresholdDay"},
        {HasPriceRole, "hasPrice"},
        {SectionNameRole, "sectionName"},
    };
}

void WatchlistItemModel::replaceRows(const QVariantList &rows)
{
    QVector<QVariantMap> normalized;
    normalized.reserve(rows.size());
    for (const QVariant &value : rows) {
        QVariantMap row = value.toMap();
        const QString ticker = normalizeTicker(row.value(QStringLiteral("ticker")).toString());
        if (ticker.isEmpty())
            continue;
        row.insert(QStringLiteral("ticker"), ticker);
        normalized.append(std::move(row));
    }

    bool sameLayout = normalized.size() == m_rows.size();
    if (sameLayout) {
        for (int i = 0; i < normalized.size(); ++i) {
            const QVariantMap &left = normalized.at(i);
            const QVariantMap &right = m_rows.at(i);
            const QVariant leftId = left.value(QStringLiteral("id"));
            const QVariant rightId = right.value(QStringLiteral("id"));
            const QString leftTicker = left.value(QStringLiteral("ticker")).toString();
            const QString rightTicker = right.value(QStringLiteral("ticker")).toString();
            if ((leftId.isValid() && rightId.isValid() && leftId != rightId)
                || (leftTicker != rightTicker)) {
                sameLayout = false;
                break;
            }
        }
    }

    if (!sameLayout) {
        beginResetModel();
        m_rows = std::move(normalized);
        m_byTicker.clear();
        for (int i = 0; i < m_rows.size(); ++i) {
            m_byTicker.insert(normalizeTicker(m_rows.at(i).value(QStringLiteral("ticker")).toString()), i);
        }
        endResetModel();
        return;
    }

    m_rows = std::move(normalized);
    m_byTicker.clear();
    for (int i = 0; i < m_rows.size(); ++i) {
        m_byTicker.insert(normalizeTicker(m_rows.at(i).value(QStringLiteral("ticker")).toString()), i);
    }
    if (!m_rows.isEmpty())
        emit dataChanged(index(0), index(m_rows.size() - 1));
}

void WatchlistItemModel::applyQuote(const QString &symbol, double price, double previousClose,
                                    qint64 timestampMs)
{
    const QString ticker = normalizeTicker(symbol);
    const auto found = m_byTicker.constFind(ticker);
    if (found == m_byTicker.constEnd())
        return;
    const int rowIndex = found.value();
    QVariantMap &row = m_rows[rowIndex];
    const qint64 previousTimestamp = row.value(QStringLiteral("quoteUpdatedAtMs")).toLongLong();
    if (timestampMs > 0 && previousTimestamp > 0 && timestampMs < previousTimestamp)
        return;
    if (timestampMs <= 0 && previousTimestamp > 0)
        return;

    bool changed = false;
    const QVariant oldPrice = row.value(QStringLiteral("price"));
    if (std::isfinite(price) && (!oldPrice.isValid() || !std::isfinite(oldPrice.toDouble())
                                 || oldPrice.toDouble() != price)) {
        row.insert(QStringLiteral("price"), price);
        changed = true;
    }
    if (std::isfinite(previousClose)) {
        const QVariant oldClose = row.value(QStringLiteral("previousClose"));
        if (!oldClose.isValid() || !std::isfinite(oldClose.toDouble())
            || oldClose.toDouble() != previousClose) {
            row.insert(QStringLiteral("previousClose"), previousClose);
            changed = true;
        }
    }
    const QVariant closeValue = row.value(QStringLiteral("previousClose"));
    const QVariant currentValue = row.value(QStringLiteral("price"));
    const double close = closeValue.toDouble();
    const double current = currentValue.toDouble();
    if (closeValue.isValid() && currentValue.isValid() && std::isfinite(current)
        && std::isfinite(close) && close != 0.0) {
        const double change = (current - close) / close * 100.0;
        if (!row.value(QStringLiteral("changePercent")).isValid()
            || row.value(QStringLiteral("changePercent")).toDouble() != change) {
            row.insert(QStringLiteral("changePercent"), change);
            changed = true;
        }
    }
    if (timestampMs > 0 && previousTimestamp != timestampMs) {
        row.insert(QStringLiteral("quoteUpdatedAtMs"), timestampMs);
        changed = true;
    }
    if (changed)
        emit dataChanged(index(rowIndex), index(rowIndex),
                         {PriceRole, ChangePercentRole, HasPriceRole});
}

QStringList WatchlistItemModel::symbols() const
{
    QStringList result;
    result.reserve(m_rows.size());
    for (const QVariantMap &row : m_rows)
        result.append(normalizeTicker(row.value(QStringLiteral("ticker")).toString()));
    return result;
}

QVariantMap WatchlistItemModel::itemAt(int row) const
{
    return row >= 0 && row < m_rows.size() ? m_rows.at(row) : QVariantMap{};
}

int WatchlistItemModel::findByTicker(const QString &ticker) const
{
    return m_byTicker.value(normalizeTicker(ticker), -1);
}

QString WatchlistItemModel::normalizeTicker(const QString &ticker)
{
    return normalizedTicker(ticker);
}

WatchlistStore::WatchlistStore(AppEnvironment *environment, ApiClient *api,
                               std::function<QByteArray()> tokenProvider, QObject *parent)
    : QObject(parent), m_environment(environment), m_api(api),
      m_tokenProvider(std::move(tokenProvider)), m_stream(new SseStream(&m_streamNetwork, this)),
      m_watchlisted(this), m_matched(this)
{
    m_searchTimer.setSingleShot(true);
    m_searchTimer.setInterval(300);
    connect(&m_searchTimer, &QTimer::timeout, this, [this] {
        const quint64 generation = m_searchGeneration;
        const QString query = m_searchQuery;
        QUrlQuery params;
        params.addQueryItem(QStringLiteral("q"), query);
        params.addQueryItem(QStringLiteral("limit"), QStringLiteral("8"));
        m_searchRequest = m_api->get(
            QStringLiteral("securities/search"),
            [this, generation](const ApiError &error, const QJsonObject &json) {
                if (generation != m_searchGeneration)
                    return;
                m_searchBusy = false;
                if (!isSuccessful(error)) {
                    m_searchError = displayError(error, tr("搜索失败，请稍后重试。"));
                    m_searchResults.clear();
                    emit searchChanged();
                    return;
                }
                const QJsonValue results = json.value(QStringLiteral("results"));
                if (!results.isArray()) {
                    m_searchError = tr("搜索响应缺少候选列表。");
                    m_searchResults.clear();
                } else {
                    m_searchResults = parseSearchResults(json);
                    for (QVariant &candidate : m_searchResults) {
                        QVariantMap item = candidate.toMap();
                        const QString yahoo = normalizedTicker(item.value(QStringLiteral("yahoo_symbol")).toString());
                        const QString finnhub = normalizedTicker(item.value(QStringLiteral("finnhub_symbol")).toString());
                        const QString display = normalizedTicker(item.value(QStringLiteral("display_symbol")).toString());
                        const bool duplicate = (m_watchlisted.findByTicker(yahoo) >= 0)
                            || (m_watchlisted.findByTicker(finnhub) >= 0)
                            || (m_watchlisted.findByTicker(display) >= 0);
                        item.insert(QStringLiteral("is_duplicate"), duplicate);
                        candidate = item;
                    }
                    m_searchError.clear();
                }
                emit searchChanged();
            },
            {.name = QStringLiteral("securities/search"), .retryable = true,
             .maxAttempts = 3, .query = params});
    });

    connect(m_stream, &SseStream::eventReceived, this, &WatchlistStore::handleStreamEvent);
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

void WatchlistStore::setActive(bool active)
{
    if (m_active == active)
        return;
    m_active = active;
    if (active) {
        refresh();
    } else {
        stopStream();
    }
    emit changed();
}

void WatchlistStore::refresh()
{
    if (m_busy)
        return;
    m_busy = true;
    m_error.clear();
    const quint64 generation = ++m_refreshGeneration;
    emit changed();
    m_request = m_api->get(
        QStringLiteral("stock-management"),
        [this, generation](const ApiError &error, const QJsonObject &json) {
            if (generation != m_refreshGeneration)
                return;
            m_busy = false;
            if (!isSuccessful(error)) {
                m_error = displayError(error, tr("无法加载自选股，请稍后重试。"));
                m_failedSinceLastGood = m_fetchedAtMs > 0;
                emit changed();
                return;
            }
            QVariantList groups;
            QVariantList watchlisted;
            QVariantList matched;
            if (!parseStockManagement(json, &groups, &watchlisted, &matched)) {
                m_error = tr("自选股响应缺少必要字段。");
                m_failedSinceLastGood = m_fetchedAtMs > 0;
                emit changed();
                return;
            }
            m_groups = std::move(groups);
            m_watchlisted.replaceRows(watchlisted);
            m_matched.replaceRows(matched);
            QSet<QString> sections;
            for (const QVariant &value : watchlisted) {
                const QVariantMap row = value.toMap();
                const QVariant groupId = row.value(QStringLiteral("userGroupId"));
                QString section;
                if (groupId.isValid()) {
                    section = QStringLiteral("group:%1").arg(groupId.toInt());
                } else {
                    section = row.value(QStringLiteral("officialSector")).toString().trimmed()
                        + QStringLiteral(" · ")
                        + row.value(QStringLiteral("officialIndustry")).toString().trimmed();
                    if (section == QStringLiteral(" · "))
                        section = QStringLiteral("uncategorized");
                }
                sections.insert(section);
            }
            m_sectionCount = sections.size();
            m_fetchedAtMs = QDateTime::currentMSecsSinceEpoch();
            m_failedSinceLastGood = false;
            m_error.clear();
            restartStream();
            emit changed();
        },
        {.name = QStringLiteral("stock-management"), .retryable = true,
         .maxAttempts = 3});
}

void WatchlistStore::search(const QString &query)
{
    const QString normalized = query.trimmed();
    m_searchQuery = normalized;
    ++m_searchGeneration;
    m_searchTimer.stop();
    m_searchRequest.cancel();
    m_searchResults.clear();
    m_searchError.clear();
    m_searchBusy = !normalized.isEmpty();
    if (!normalized.isEmpty())
        m_searchTimer.start();
    emit searchChanged();
}

void WatchlistStore::clearSearch()
{
    search(QString());
}

void WatchlistStore::addSecurity(const QVariantMap &security)
{
    QJsonObject body;
    const int securityId = security.value(QStringLiteral("security_id")).toInt();
    if (securityId > 0)
        body.insert(QStringLiteral("security_id"), securityId);
    const QString source = security.value(QStringLiteral("source")).toString();
    if (source == QLatin1String("yahoo") || source == QLatin1String("finnhub"))
        body.insert(QStringLiteral("source"), source);
    const QString yahoo = security.value(QStringLiteral("yahoo_symbol")).toString().trimmed();
    const QString finnhub = security.value(QStringLiteral("finnhub_symbol")).toString().trimmed();
    if (!yahoo.isEmpty())
        body.insert(QStringLiteral("yahoo_symbol"), yahoo);
    if (!finnhub.isEmpty())
        body.insert(QStringLiteral("finnhub_symbol"), finnhub);
    if (body.value(QStringLiteral("security_id")).toInt() <= 0
        && !body.contains(QStringLiteral("yahoo_symbol"))
        && !body.contains(QStringLiteral("finnhub_symbol"))) {
        m_error = tr("候选证券缺少可验证的数据源，请重新搜索。");
        emit changed();
        return;
    }
    mutate(QStringLiteral("watchlist"), body, QStringLiteral("watchlist/add"));
}

void WatchlistStore::promoteMatched(const QString &ticker)
{
    const QString normalized = normalizedTicker(ticker);
    if (normalized.isEmpty())
        return;
    mutate(QStringLiteral("watchlist"), {{QStringLiteral("ticker"), normalized}},
           QStringLiteral("watchlist/promote"));
}

void WatchlistStore::createGroup(const QString &name)
{
    const QString normalized = name.trimmed();
    if (normalized.isEmpty()) {
        m_error = tr("分区名称不能为空。");
        emit changed();
        return;
    }
    mutate(QStringLiteral("stock-groups"), {{QStringLiteral("name"), normalized}},
           QStringLiteral("stock-groups/create"));
}

void WatchlistStore::renameGroup(int groupId, const QString &name)
{
    const QString normalized = name.trimmed();
    if (groupId <= 0 || normalized.isEmpty())
        return;
    mutate(QStringLiteral("stock-groups/%1").arg(groupId),
           {{QStringLiteral("name"), normalized}}, QStringLiteral("stock-groups/rename"));
}

void WatchlistStore::deleteGroup(int groupId)
{
    if (groupId > 0)
        mutateDelete(QStringLiteral("stock-groups/%1").arg(groupId),
                     QStringLiteral("stock-groups/delete"));
}

void WatchlistStore::moveGroup(int groupId, int displayOrder)
{
    if (groupId > 0)
        mutate(QStringLiteral("stock-groups/%1").arg(groupId),
               {{QStringLiteral("display_order"), qMax(0, displayOrder)}},
               QStringLiteral("stock-groups/order"));
}

void WatchlistStore::updateWatchlist(int itemId, const QVariantMap &fields)
{
    if (itemId <= 0 || fields.isEmpty())
        return;
    static const QSet<QString> allowed{
        QStringLiteral("enabled"), QStringLiteral("alert_enabled"),
        QStringLiteral("user_group_id"), QStringLiteral("display_order"),
        QStringLiteral("threshold_20m"), QStringLiteral("threshold_1h"),
        QStringLiteral("threshold_day")};
    QJsonObject body;
    for (auto it = fields.constBegin(); it != fields.constEnd(); ++it) {
        if (allowed.contains(it.key()))
            body.insert(it.key(), QJsonValue::fromVariant(it.value()));
    }
    if (!body.isEmpty())
        mutate(QStringLiteral("watchlist/%1").arg(itemId), body,
               QStringLiteral("watchlist/update"));
}

void WatchlistStore::moveWatchlist(int itemId, int displayOrder)
{
    updateWatchlist(itemId, {{QStringLiteral("display_order"), qMax(0, displayOrder)}});
}

void WatchlistStore::removeWatchlist(int itemId)
{
    if (itemId > 0)
        mutateDelete(QStringLiteral("watchlist/%1").arg(itemId), QStringLiteral("watchlist/delete"));
}

void WatchlistStore::mutate(const QString &path, const QJsonObject &body,
                            const QString &requestName)
{
    if (m_busy) {
        m_error = tr("正在同步服务器数据，请稍后再试。");
        emit changed();
        return;
    }
    if (m_mutationBusy)
        return;
    m_mutationBusy = true;
    m_error.clear();
    emit changed();
    m_mutationRequest = (path == QLatin1String("watchlist") || path == QLatin1String("stock-groups"))
        ? m_api->post(path, body,
                      [this](const ApiError &error, const QJsonObject &) {
                          if (!isSuccessful(error)) { failMutation(error); return; }
                          finishMutation();
                      }, {.name = requestName})
        : m_api->patch(path, body,
                       [this](const ApiError &error, const QJsonObject &) {
                           if (!isSuccessful(error)) { failMutation(error); return; }
                           finishMutation();
                       }, {.name = requestName});
}

void WatchlistStore::mutateDelete(const QString &path, const QString &requestName)
{
    if (m_busy) {
        m_error = tr("正在同步服务器数据，请稍后再试。");
        emit changed();
        return;
    }
    if (m_mutationBusy)
        return;
    m_mutationBusy = true;
    m_error.clear();
    emit changed();
    m_mutationRequest = m_api->remove(path,
                                      [this](const ApiError &error, const QJsonObject &) {
                                          if (!isSuccessful(error)) { failMutation(error); return; }
                                          finishMutation();
                                      }, {.name = requestName});
}

void WatchlistStore::finishMutation()
{
    m_mutationBusy = false;
    emit changed();
    refresh();
}

void WatchlistStore::failMutation(const ApiError &error)
{
    m_mutationBusy = false;
    m_error = displayError(error, tr("保存失败，已保留当前服务器数据。"));
    emit changed();
}

void WatchlistStore::restartStream()
{
    if (!m_active) {
        stopStream();
        return;
    }
    const QString symbols = m_watchlisted.symbols().mid(0, 50).join(QLatin1Char(','));
    if (symbols.isEmpty()) {
        stopStream();
        return;
    }
    const auto state = m_stream->state();
    if (symbols == m_streamSymbols
        && (state == SseStream::State::Connected || state == SseStream::State::Connecting
            || state == SseStream::State::Reconnecting))
        return;
    m_stream->stop();
    m_streamSymbols = symbols;
    QUrl url = m_environment->apiUrl(QStringLiteral("market/realtime/stream"));
    QUrlQuery query;
    query.addQueryItem(QStringLiteral("symbols"), symbols);
    url.setQuery(query);
    m_stream->start(url, m_tokenProvider ? m_tokenProvider() : QByteArray());
}

void WatchlistStore::stopStream()
{
    m_streamSymbols.clear();
    m_stream->stop();
    m_streamStatus = QStringLiteral("idle");
}

void WatchlistStore::handleStreamEvent(const QString &eventType, const QString &data)
{
    if (eventType != QLatin1String("quote_update"))
        return;
    const QJsonDocument document = QJsonDocument::fromJson(data.toUtf8());
    if (!document.isObject())
        return;
    QJsonObject object = document.object();
    if (object.value(QStringLiteral("authoritative_quote")).isObject())
        object = object.value(QStringLiteral("authoritative_quote")).toObject();
    const QString symbol = object.value(QStringLiteral("symbol")).toString();
    if (symbol.isEmpty())
        return;
    const double price = object.value(QStringLiteral("price")).isDouble()
        ? object.value(QStringLiteral("price")).toDouble() : qQNaN();
    const double previousClose = object.value(QStringLiteral("previous_close")).isDouble()
        ? object.value(QStringLiteral("previous_close")).toDouble() : qQNaN();
    const qint64 timestamp = timestampMs(object.value(QStringLiteral("timestamp")));
    m_watchlisted.applyQuote(symbol, price, previousClose, timestamp);
    m_matched.applyQuote(symbol, price, previousClose, timestamp);
}

qint64 WatchlistStore::timestampMs(const QJsonValue &value)
{
    if (value.isDouble()) {
        const double raw = value.toDouble();
        return static_cast<qint64>(raw > 10'000'000'000.0 ? raw : raw * 1000.0);
    }
    const QDateTime parsed = QDateTime::fromString(value.toString(), Qt::ISODate);
    return parsed.isValid() ? parsed.toMSecsSinceEpoch() : 0;
}

bool WatchlistStore::parseStockManagement(const QJsonObject &json, QVariantList *groups,
                                          QVariantList *watchlisted, QVariantList *matched)
{
    if (!groups || !watchlisted || !matched
        || !json.value(QStringLiteral("groups")).isArray()
        || !json.value(QStringLiteral("watchlisted")).isArray()
        || !json.value(QStringLiteral("matched")).isArray())
        return false;

    QVariantList parsedGroups;
    for (const QJsonValue &value : json.value(QStringLiteral("groups")).toArray()) {
        if (!value.isObject())
            continue;
        const QVariantMap group = parseGroup(value.toObject());
        if (!group.isEmpty())
            parsedGroups.append(group);
    }
    std::sort(parsedGroups.begin(), parsedGroups.end(), [](const QVariant &left, const QVariant &right) {
        const QVariantMap a = left.toMap();
        const QVariantMap b = right.toMap();
        if (a.value(QStringLiteral("displayOrder")) != b.value(QStringLiteral("displayOrder")))
            return a.value(QStringLiteral("displayOrder")).toInt() < b.value(QStringLiteral("displayOrder")).toInt();
        return a.value(QStringLiteral("id")).toInt() < b.value(QStringLiteral("id")).toInt();
    });

    QVariantList parsedWatchlisted;
    for (const QJsonValue &value : json.value(QStringLiteral("watchlisted")).toArray()) {
        if (!value.isObject())
            continue;
        const QVariantMap item = parseManagedItem(value.toObject(), false);
        if (!item.isEmpty())
            parsedWatchlisted.append(item);
    }
    QHash<int, QString> groupNames;
    for (const QVariant &value : std::as_const(parsedGroups)) {
        const QVariantMap group = value.toMap();
        groupNames.insert(group.value(QStringLiteral("id")).toInt(),
                          group.value(QStringLiteral("name")).toString());
    }
    QStringList sectionOrder;
    QHash<QString, QVariantList> sectionRows;
    for (QVariant &value : parsedWatchlisted) {
        QVariantMap item = value.toMap();
        const QVariant groupId = item.value(QStringLiteral("userGroupId"));
        QString section;
        if (groupId.isValid() && groupNames.contains(groupId.toInt()))
            section = QStringLiteral("自定义 · ") + groupNames.value(groupId.toInt());
        else {
            const QString sector = item.value(QStringLiteral("officialSector")).toString().trimmed();
            const QString industry = item.value(QStringLiteral("officialIndustry")).toString().trimmed();
            section = sector.isEmpty() ? industry : industry.isEmpty() ? sector
                : sector + QStringLiteral(" · ") + industry;
            if (section.isEmpty())
                section = QStringLiteral("未分类");
        }
        item.insert(QStringLiteral("sectionName"), section);
        if (!sectionRows.contains(section))
            sectionOrder.append(section);
        sectionRows[section].append(item);
    }
    parsedWatchlisted.clear();
    for (const QString &section : std::as_const(sectionOrder))
        parsedWatchlisted.append(sectionRows.value(section));
    QVariantList parsedMatched;
    for (const QJsonValue &value : json.value(QStringLiteral("matched")).toArray()) {
        if (!value.isObject())
            continue;
        const QVariantMap item = parseManagedItem(value.toObject(), true);
        if (!item.isEmpty())
            parsedMatched.append(item);
    }
    *groups = std::move(parsedGroups);
    *watchlisted = std::move(parsedWatchlisted);
    *matched = std::move(parsedMatched);
    return true;
}

QVariantList WatchlistStore::parseSearchResults(const QJsonObject &json)
{
    QVariantList results;
    const QJsonArray array = json.value(QStringLiteral("results")).toArray();
    QSet<QString> seen;
    for (const QJsonValue &value : array) {
        if (!value.isObject())
            continue;
        QVariantMap result = value.toObject().toVariantMap();
        const QString symbol = result.value(QStringLiteral("display_symbol")).toString().trimmed();
        const QString key = result.value(QStringLiteral("provider_key")).toString().trimmed();
        const QString dedupeKey = !key.isEmpty() ? key : symbol.toUpper();
        if (symbol.isEmpty() || dedupeKey.isEmpty() || seen.contains(dedupeKey))
            continue;
        seen.insert(dedupeKey);
        result.insert(QStringLiteral("display_symbol"), symbol);
        result.insert(QStringLiteral("display_name"),
                     result.value(QStringLiteral("display_name")).toString().trimmed());
        results.append(result);
        if (results.size() >= 8)
            break;
    }
    return results;
}
