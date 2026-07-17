# Stock Monitor

A self-hosted stock monitoring dashboard with AI-powered analysis, real-time alerts, SEC filings integration, and institutional holdings tracking.

## Features

- **Real-time price monitoring** — polls configurable watchlist stocks every few minutes, triggers alerts on abnormal moves (20m / 1h / daily thresholds)
- **TradingView charts** — embedded interactive charts for each stock
- **Prediction charts** — visualize forecast overlays alongside price history
- **Market overview** — major indices (SPY, QQQ, DJI, etc.) with open/close status
- **AI investigation** — automatically kicks off when an alert fires; pulls news, summarizes with LLM, produces a report
- **Multi-source news** — Tavily web search + SEC EDGAR filings; filters and scores by relevance and sentiment
- **SEC integration** — fetches 8-K, 10-Q, 10-K filings via EDGAR; surfaces material disclosures alongside news
- **Analyst ratings visualization** — aggregated buy/hold/sell ratings displayed as a visual breakdown
- **KOL / institutional holdings** — SEC 13-F filings parsed to show what major funds hold
- **Data gap reporting** — flags missing price or fundamental data so you know when coverage is incomplete
- **Appearance polish** — dark-themed responsive UI with smooth transitions

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, TanStack Query |
| Backend | FastAPI, Celery, SQLAlchemy, Alembic |
| Database | PostgreSQL 16 |
| Queue / Cache | Redis 7 |
| Data sources | yfinance, Finnhub MCP, Tavily, SEC EDGAR (edgartools) |
| AI | OpenAI-compatible API (configurable model per task tier) |
| Reverse proxy | Caddy (HTTPS + basic auth out of the box) |
| Deployment | Docker Compose |

## Quick Start

### Prerequisites

- Docker + Docker Compose
- API keys: Finnhub, Tavily, OpenAI-compatible endpoint

### 1. Clone and configure

```bash
git clone https://github.com/Uhmmu/stock-monitor.git
cd stock-monitor
cp .env.example .env
```

Edit `.env` and fill in:

```env
POSTGRES_PASSWORD=your-secure-password
DATABASE_URL=postgresql+psycopg://stock:your-secure-password@postgres:5432/stock_monitor

FINNHUB_API_KEY=your-finnhub-key
TAVILY_API_KEY=your-tavily-key

OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL_SIMPLE=gpt-4o-mini
MODEL_MEDIUM=gpt-4o
MODEL_IMPORTANT=gpt-4o

SITE_DOMAIN=stocks.yourdomain.com
AUTH_USER=admin
AUTH_PASSWORD_HASH=   # generate with: caddy hash-password
```

### 2. Start

```bash
docker compose up -d
```

The dashboard will be available at `https://stocks.yourdomain.com` (or `http://localhost` for local use with the override file).

### 3. Add stocks to watch

Open the dashboard → click **Add** → enter a ticker symbol (e.g. `AAPL`).

## Configuration Reference

Key `.env` settings:

| Variable | Default | Description |
|---|---|---|
| `PRICE_POLL_MINUTES` | `5` | How often to fetch prices |
| `DEFAULT_THRESHOLD_20M` | `2.0` | % move in 20 min to trigger alert |
| `DEFAULT_THRESHOLD_1H` | `4.0` | % move in 1 h to trigger alert |
| `DEFAULT_THRESHOLD_DAY` | `6.0` | % daily move to trigger alert |
| `ALERT_COOLDOWN_MINUTES` | `60` | Min gap between repeated alerts for same ticker |
| `INVESTIGATION_DURATION_MINUTES` | `120` | How long to keep collecting news after an alert |
| `NEWS_POLL_MINUTES` | `15` | News refresh interval |
| `EARNINGS_LOOKAHEAD_DAYS` | `7` | Days ahead to flag upcoming earnings |
| `MARKET_TIMEZONE` | `America/New_York` | Exchange timezone |

## Project Structure

```
stock-monitor/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes
│   │   ├── tasks/        # Celery workers (price poll, news, SEC, LLM)
│   │   ├── models.py     # DB models
│   │   └── schemas.py    # Pydantic schemas
│   └── tests/
├── frontend/
│   └── src/
│       ├── App.tsx       # Main dashboard
│       ├── Sheet.tsx     # Stock detail sheet
│       └── PipCard.tsx   # Price pip component
├── finnhub-mcp/          # Finnhub MCP server sidecar
├── compose.yaml
├── Caddyfile
└── .env.example
```

## Changelog

### v0.2
- Added TradingView embedded charts
- Added prediction / forecast chart overlay
- Added SEC EDGAR as a news and filing source
- Added analyst ratings visualization
- Added KOL / institutional holdings via SEC 13-F
- Added market overview panel (major indices)
- Improved data gap reporting
- UI appearance polish

### v0.1
- Initial release: watchlist, price alerts, AI investigation reports, multi-source news

## License

MIT
