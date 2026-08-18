#pragma once

#include <QAbstractListModel>
#include <QHash>
#include <QtMath>
#include <QTimer>
#include <QVector>
#include <cmath>

// One dashboard quote/holding row. Base values come from the portfolio
// summary; live values overlay them from the market SSE stream / realtime
// snapshot. Display always prefers live over base and never fabricates
// missing numbers (invalid numeric roles mean "数据不足").
struct WatchlistQuoteRow {
    QString ticker;
    QString companyName;
    double quantity = qQNaN();
    QString currency;
    double price = qQNaN();            // dashboard last-good price
    double previousClose = qQNaN();
    double baselineChangePercent = qQNaN(); // persisted daily return when close is unavailable
    double marketValue = qQNaN();
    double portfolioWeight = qQNaN();
    bool valuationAvailable = false;
    double volume = qQNaN();
    double volumeRatio = qQNaN();
    QString volumeLabel;               // 放量/缩量/正常 or empty
    QString priceSource;               // e.g. "yfinance:delayed"
    qint64 baseUpdatedAtMs = 0;        // provider/market timestamp of base data

    // Live overlay (SSE quote_update or realtime REST catch-up).
    bool hasLive = false;
    double livePrice = qQNaN();
    double livePreviousClose = qQNaN();
    double liveVolume = qQNaN();
    QString liveSource;                // "provider:feed" or "provider"
    qint64 liveUpdatedAtMs = 0;

    double displayPrice() const { return hasLive && std::isfinite(livePrice) ? livePrice : price; }
    double displayPreviousClose() const;
    double displayMarketValue() const;
    double displayVolume() const { return hasLive && std::isfinite(liveVolume) ? liveVolume : volume; }
    QString displaySource() const { return hasLive && std::isfinite(livePrice) ? liveSource : priceSource; }
    qint64 displayUpdatedAtMs() const;
    double change() const;
    double changePercent() const;
};

// QAbstractListModel for the Dashboard quote cards/table. Price ticks arrive
// as applyRealtimeQuote(); rows are only marked dirty there and flushed as
// contiguous dataChanged ranges on a short coalescing timer, so a quote burst
// never resets the list (scroll/selection/flicker stay stable). A dashboard
// reload that keeps the same ticker order updates rows in place instead of
// resetting the model.
class WatchlistQuoteModel final : public QAbstractListModel
{
    Q_OBJECT

public:
    enum Roles {
        TickerRole = Qt::UserRole + 1,
        CompanyRole,
        QuantityRole,
        CurrencyRole,
        PriceRole,
        PreviousCloseRole,
        ChangeRole,
        ChangePercentRole,
        MarketValueRole,
        PortfolioWeightRole,
        ValuationAvailableRole,
        VolumeRole,
        VolumeRatioRole,
        VolumeLabelRole,
        SourceRole,
        UpdatedAtMsRole,
        HasLiveRole,
        HasDataRole,
    };

    explicit WatchlistQuoteModel(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    void replaceRows(const QVector<WatchlistQuoteRow> &rows);
    // Apply one realtime quote. Out-of-order timestamps (older than what the
    // row already shows) are ignored, mirroring the web client semantics.
    void applyRealtimeQuote(const QString &symbol, double price, double previousClose,
                            double volume, const QString &source, qint64 timestampMs);
    void setCoalesceIntervalMs(int ms);  // test hook; <=0 disables coalescing
    int coalescedFlushCount() const { return m_flushCount; }
    QStringList tickers() const;
    QString tickerAt(int row) const;

private:
    void flushDirtyRows();

    QVector<WatchlistQuoteRow> m_rows;
    QHash<QString, int> m_rowByTicker;
    QVector<int> m_dirtyRows;
    QTimer m_flushTimer;
    int m_coalesceIntervalMs = 120;
    int m_flushCount = 0;
};
