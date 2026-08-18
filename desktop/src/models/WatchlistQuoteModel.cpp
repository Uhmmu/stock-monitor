#include "models/WatchlistQuoteModel.h"

#include <QtMath>
#include <algorithm>

double WatchlistQuoteRow::displayPreviousClose() const
{
    return (hasLive && std::isfinite(livePreviousClose)) ? livePreviousClose : previousClose;
}

double WatchlistQuoteRow::displayMarketValue() const
{
    if (hasLive && std::isfinite(livePrice) && std::isfinite(quantity))
        return quantity * livePrice;
    return marketValue;
}

qint64 WatchlistQuoteRow::displayUpdatedAtMs() const
{
    if (hasLive && std::isfinite(livePrice) && liveUpdatedAtMs > 0)
        return liveUpdatedAtMs;
    return baseUpdatedAtMs;
}

double WatchlistQuoteRow::change() const
{
    const double current = displayPrice();
    const double close = displayPreviousClose();
    if (!std::isfinite(current) || !std::isfinite(close) || close == 0)
        return qQNaN();
    return current - close;
}

double WatchlistQuoteRow::changePercent() const
{
    if (hasLive && std::isfinite(livePrice) && std::isfinite(livePreviousClose)
        && livePreviousClose != 0)
        return (livePrice - livePreviousClose) / livePreviousClose * 100.0;
    const double current = displayPrice();
    const double close = displayPreviousClose();
    if (std::isfinite(current) && std::isfinite(close) && close != 0)
        return (current - close) / close * 100.0;
    return baselineChangePercent;
}

WatchlistQuoteModel::WatchlistQuoteModel(QObject *parent)
    : QAbstractListModel(parent)
{
    m_flushTimer.setSingleShot(true);
    m_flushTimer.setInterval(m_coalesceIntervalMs);
    connect(&m_flushTimer, &QTimer::timeout, this, &WatchlistQuoteModel::flushDirtyRows);
}

int WatchlistQuoteModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_rows.size();
}

QVariant WatchlistQuoteModel::data(const QModelIndex &index, int role) const
{
    if (index.row() < 0 || index.row() >= m_rows.size())
        return {};
    const WatchlistQuoteRow &row = m_rows.at(index.row());
    const auto number = [](double value) -> QVariant {
        return std::isfinite(value) ? QVariant(value) : QVariant();
    };
    switch (role) {
    case TickerRole: return row.ticker;
    case CompanyRole: return row.companyName;
    case QuantityRole: return number(row.quantity);
    case CurrencyRole: return row.currency;
    case PriceRole: return number(row.displayPrice());
    case PreviousCloseRole: return number(row.displayPreviousClose());
    case ChangeRole: return number(row.change());
    case ChangePercentRole: return number(row.changePercent());
    case MarketValueRole: return number(row.displayMarketValue());
    case PortfolioWeightRole: return number(row.portfolioWeight);
    case ValuationAvailableRole: return row.valuationAvailable;
    case VolumeRole: return number(row.displayVolume());
    case VolumeRatioRole: return number(row.volumeRatio);
    case VolumeLabelRole: return row.volumeLabel;
    case SourceRole: return row.displaySource();
    case UpdatedAtMsRole: return row.displayUpdatedAtMs();
    case HasLiveRole: return row.hasLive && std::isfinite(row.livePrice);
    case HasDataRole: return !qIsNaN(row.displayPrice());
    }
    return {};
}

QHash<int, QByteArray> WatchlistQuoteModel::roleNames() const
{
    return {
        {TickerRole, "ticker"},
        {CompanyRole, "company"},
        {QuantityRole, "quantity"},
        {CurrencyRole, "currency"},
        {PriceRole, "price"},
        {PreviousCloseRole, "previousClose"},
        {ChangeRole, "change"},
        {ChangePercentRole, "changePercent"},
        {MarketValueRole, "marketValue"},
        {PortfolioWeightRole, "portfolioWeight"},
        {ValuationAvailableRole, "valuationAvailable"},
        {VolumeRole, "volume"},
        {VolumeRatioRole, "volumeRatio"},
        {VolumeLabelRole, "volumeLabel"},
        {SourceRole, "source"},
        {UpdatedAtMsRole, "updatedAtMs"},
        {HasLiveRole, "hasLive"},
        {HasDataRole, "hasData"},
    };
}

void WatchlistQuoteModel::replaceRows(const QVector<WatchlistQuoteRow> &rows)
{
    QVector<WatchlistQuoteRow> normalized = rows;
    for (WatchlistQuoteRow &row : normalized)
        row.ticker = row.ticker.trimmed().toUpper();
    bool sameLayout = normalized.size() == m_rows.size();
    if (sameLayout) {
        for (int i = 0; i < normalized.size(); ++i) {
            if (normalized.at(i).ticker != m_rows.at(i).ticker) {
                sameLayout = false;
                break;
            }
        }
    }
    if (!sameLayout) {
        beginResetModel();
        m_rows = normalized;
        m_rowByTicker.clear();
        for (int i = 0; i < m_rows.size(); ++i)
            m_rowByTicker.insert(m_rows.at(i).ticker, i);
        m_dirtyRows.clear();
        m_flushTimer.stop();
        endResetModel();
        return;
    }

    // Same tickers, same order: keep model identity (view scroll/selection
    // survive) and update every row in place.
    for (int i = 0; i < normalized.size(); ++i) {
        const WatchlistQuoteRow &old = m_rows.at(i);
        if (old.hasLive && old.liveUpdatedAtMs >= normalized[i].baseUpdatedAtMs) {
            normalized[i].hasLive = true;
            normalized[i].livePrice = old.livePrice;
            normalized[i].livePreviousClose = old.livePreviousClose;
            normalized[i].liveVolume = old.liveVolume;
            normalized[i].liveSource = old.liveSource;
            normalized[i].liveUpdatedAtMs = old.liveUpdatedAtMs;
        }
    }
    m_rows = normalized;
    m_rowByTicker.clear();
    for (int i = 0; i < m_rows.size(); ++i)
        m_rowByTicker.insert(m_rows.at(i).ticker, i);
    if (!m_rows.isEmpty())
        emit dataChanged(index(0), index(m_rows.size() - 1));
}

void WatchlistQuoteModel::applyRealtimeQuote(const QString &symbol, double price,
                                             double previousClose, double volume,
                                             const QString &source, qint64 timestampMs)
{
    const QString normalized = symbol.trimmed().toUpper();
    const auto found = m_rowByTicker.constFind(normalized);
    if (found == m_rowByTicker.constEnd())
        return;
    const int row = found.value();
    WatchlistQuoteRow &current = m_rows[row];

    const qint64 effectiveMs = current.displayUpdatedAtMs();
    if (timestampMs > 0 && effectiveMs > 0 && timestampMs < effectiveMs)
        return;  // stale/out-of-order tick; never regress displayed data
    if (timestampMs <= 0 && effectiveMs > 0)
        return;  // unparseable timestamp cannot be proven newer

    bool changed = false;
    auto applyNumber = [&changed](double &field, double value) {
        if (value != value || qFuzzyCompare(field, value))
            return;
        field = value;
        changed = true;
    };
    applyNumber(current.livePrice, price);
    applyNumber(current.livePreviousClose, previousClose);
    applyNumber(current.liveVolume, volume);
    if (!current.hasLive)
        changed = true;
    if (!source.isEmpty() && source != current.liveSource) {
        current.liveSource = source;
        changed = true;
    }
    if (!changed && timestampMs == current.liveUpdatedAtMs)
        return;
    current.hasLive = true;
    if (timestampMs > 0)
        current.liveUpdatedAtMs = timestampMs;

    if (!m_dirtyRows.contains(row))
        m_dirtyRows.append(row);
    if (m_coalesceIntervalMs <= 0) {
        flushDirtyRows();
    } else if (!m_flushTimer.isActive()) {
        m_flushTimer.start();
    }
}

void WatchlistQuoteModel::setCoalesceIntervalMs(int ms)
{
    m_coalesceIntervalMs = ms;
    m_flushTimer.setInterval(qMax(0, ms));
}

QStringList WatchlistQuoteModel::tickers() const
{
    QStringList result;
    result.reserve(m_rows.size());
    for (const WatchlistQuoteRow &row : m_rows)
        result.append(row.ticker);
    return result;
}

QString WatchlistQuoteModel::tickerAt(int row) const
{
    return (row >= 0 && row < m_rows.size()) ? m_rows.at(row).ticker : QString();
}

void WatchlistQuoteModel::flushDirtyRows()
{
    if (m_dirtyRows.isEmpty())
        return;
    std::sort(m_dirtyRows.begin(), m_dirtyRows.end());
    int rangeStart = m_dirtyRows.first();
    int previous = rangeStart;
    for (int i = 1; i < m_dirtyRows.size(); ++i) {
        const int row = m_dirtyRows.at(i);
        if (row == previous + 1) {
            previous = row;
            continue;
        }
        emit dataChanged(index(rangeStart), index(previous));
        rangeStart = row;
        previous = row;
    }
    emit dataChanged(index(rangeStart), index(previous));
    ++m_flushCount;
    m_dirtyRows.clear();
}
