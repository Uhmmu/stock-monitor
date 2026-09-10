<p align="center">
  <img src="frontend/public/logo.png" width="96" alt="Stock Monitor logo">
</p>

<h1 align="center">Stock Monitor</h1>

<p align="center">
  A self-hosted market monitoring, investment research, and portfolio analytics workbench
</p>

<p align="center">
  <a href="https://github.com/Uhmmu/stock-monitor/actions/workflows/macos-native.yml">
    <img src="https://github.com/Uhmmu/stock-monitor/actions/workflows/macos-native.yml/badge.svg" alt="macOS native foundation">
  </a>
</p>

Stock Monitor brings quotes, watchlists, news, SEC filings, fundamentals,
valuations, portfolio analytics, and AI-assisted research together in a single
self-hosted application. Your data, your accounts, and your third-party API
keys stay on your own infrastructure.

> This project is for personal research and record-keeping only. It does not
> provide investment advice and never places orders automatically. Historical
> data, model output, and simulated results are not indicative of future
> performance.

## Features

- **Market data & alerts** — standardized multi-source quotes, live SSE updates, price and volume alerts, and investigation records.
- **Research data** — company news, financial statements, valuations, technical analysis, SEC filings, Form 4, 13F holdings, and an investment calendar.
- **Sectors & options** — a persistent industry pulse with ETF and supply-chain proxies, plus options analytics gated behind explicit data-quality and history thresholds.
- **Portfolio** — multi-currency holdings, a transaction ledger, return attribution, health check, strategy profile, stress tests, scenario analysis, Monte Carlo, and portfolio optimization.
- **AI research** — streaming chat with citations, read-only research tools, long-term memory, an investment decision journal, and optional Exa, Perplexity, and Pi Agent engines.
- **Discovery & sentiment** — portfolio-aware stock opportunity discovery, multi-source sentiment, local re-verification, cost budgets, and history retention.
- **Fast cold loads** — view data is persisted in the browser (IndexedDB); switching sections renders the last known data immediately and swaps in fresh results after the background refresh completes, with a slim progress bar during sustained refreshes.
- **Accounts** — registration requires admin activation; an admin panel supports creating, reviewing, annotating, and removing users.
- **Multiple clients** — desktop web, a beta market workspace (`/beta/`), a standalone iPhone PWA, and an experimental Qt Quick native desktop client.

When upstream data is missing or samples are too small, the app shows an
explicit "insufficient data" state rather than filling gaps with zeros or
guesses.

## Architecture

```mermaid
flowchart LR
    U["Browser / PWA"] --> G["Caddy / nginx"]
    G --> A["FastAPI"]
    A --> P[("PostgreSQL")]
    A --> R[("Redis")]
    R --> W["Celery workers"]
    B["Celery beat"] --> R
    M["Market stream"] --> R
    A --> F["Finnhub MCP"]
    A --> X["Quotes / News / SEC / AI"]
    W --> X
    Q["Pi Agent"] --> A
```

| Layer | Technology |
|---|---|
| Web / PWA | React 19, TypeScript, Vite, TanStack Query |
| API | FastAPI, SQLAlchemy 2, Alembic |
| Background jobs | Celery, Redis |
| Database | PostgreSQL 16 |
| Data & computation | pandas, NumPy, SciPy, yfinance, edgartools |
| Gateway & deployment | nginx, Caddy, Docker Compose |
| Native desktop (experimental) | Qt Quick, C++20, CMake |

## Getting Started

Requirements for native development:

- An Apple Silicon or Intel Mac
- Homebrew
- 8 GB of RAM recommended

Local development runs Python, Node, PostgreSQL, Redis, FastAPI, Celery, and
Vite natively — no Docker or Linux VM required. Docker Compose is reserved for
Linux/VPS production deployments and explicit parity checks.

### 1. Clone the repository

```bash
git clone https://github.com/Uhmmu/stock-monitor.git
cd stock-monitor
```

### 2. Install native dependencies

```bash
make native-bootstrap
make native-services
```

`native-bootstrap` creates an arm64 `.venv` with Python 3.12, installs
`backend/requirements.txt`, sets up an isolated venv for the Finnhub MCP
sidecar and the local execution agent, and installs Playwright's native
Chromium. Node dependencies always install from the lockfile via `npm ci`.

PostgreSQL matches production (16.x). Homebrew currently ships Redis 8.x,
which is backward compatible; production stays on `redis:7-alpine`.

### 3. Configure the local environment

The first bootstrap creates a `.env.macos` (never committed) from
`.env.macos.example`. The local launcher reads optional API keys from an
existing `.env` first, then lets `.env.macos` override database, Redis, path,
and safety-gate settings. Do not point `.env.macos` at a production database.

The default local baseline is:

```env
APP_ENV=development
DATABASE_URL=postgresql+psycopg://stock:stock@127.0.0.1:5432/stock_monitor
REDIS_URL=redis://127.0.0.1:6379/15
ADMIN_USERNAME=admin
ADMIN_INIT_PASSWORD=stock-monitor-local-dev
```

Run the migrations and the environment check:

```bash
make native-migrate
make native-doctor
```

### 4. Start local development processes

Run each in its own terminal:

```bash
make native-api       # http://127.0.0.1:8000
make native-worker    # default Celery queue
make native-beat      # safe local schedule: heartbeat only
make native-frontend  # http://127.0.0.1:5173
```

Optional Finnhub MCP sidecar:

```bash
./scripts/dev-macos finnhub
```

When the database has no administrator, the app creates the first one from
`ADMIN_USERNAME` / `ADMIN_INIT_PASSWORD`. Accounts created through the
registration flow still require admin activation.

## Optional Integrations

The app starts fine without any third-party keys; the corresponding features
simply disable themselves or report insufficient data. Full configuration and
defaults live in [`.env.example`](.env.example).

| Capability | Main settings |
|---|---|
| Finnhub | `FINNHUB_API_KEY` |
| Alpaca realtime quotes | `ALPACA_MARKET_DATA_ENABLED`, `ALPACA_API_KEY`, `ALPACA_API_SECRET` |
| Tiingo | `TIINGO_MARKET_DATA_ENABLED`, `TIINGO_API_TOKEN`, `TIINGO_NEWS_ENABLED` |
| FMP | `FMP_API_KEY` |
| News search | `TAVILY_API_KEY`, `MARKETAUX_API_KEY` |
| AI chat & reports | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `AI_*`, `MODEL_*` |
| Deep research | `EXA_ENABLED`, `EXA_API_KEY`, `AGENT_GATEWAY_TOKEN` |
| Discovery & sentiment | `PERPLEXITY_API_KEY`, `ADANOS_API_KEY` |
| US macro data | `ALPHA_VANTAGE_ENABLED`, `ALPHA_VANTAGE_API_KEY` |
| IBKR read-only sync | `IBKR_CP_*` or `IBKR_FLEX_*` |

All keys are read server-side only. IBKR connections must go through a
verified `socks5h` proxy and fail closed — direct fallback after a proxy
failure is forbidden. See the [IBKR integration doc](docs/integrations/ibkr.md)
for details.

## Production Deployment

Production runs on Linux with Dockerfiles and `compose.yaml`. The macOS native
configuration is never copied to production and does not change in-container
service names, volumes, or `/data` paths.

Create the production `.env` from `.env.example` and set strong secrets:

```bash
cp .env.example .env
```

Set the domain and Caddy basic auth:

```env
SITE_DOMAINS="your-domain.com"
AUTH_USER=admin
AUTH_PASSWORD_HASH=replace-with-a-caddy-password-hash
```

Start the full stack:

```bash
docker compose -f compose.yaml up -d --build
docker compose -f compose.yaml ps
```

Caddy terminates HTTPS. The desktop client is served at `/`, the beta market
workspace at `/beta/`, the iPhone PWA at `/mobile/`, and the API at `/api/`.
Back up PostgreSQL and the persistent volumes before upgrading.

When backend code or dependencies change, rebuild every role that shares the
`backend` build context: `api`, `worker`, `sec-worker`, `beat`, and
`market-stream`.

## Development & Verification

```bash
# Full native web-stack verification
make native-test

# Individually
./scripts/dev-macos test-backend
./scripts/dev-macos test-frontend

# iPhone PWA
cd frontend-ios
npm ci
npm test
npm run build
```

`make up`, `make down`, `make logs`, `make migrate`, `make backup`, and
`make restore FILE=backup.sql.gz` remain available as Docker/production
commands; they are not the default local-development path.

The Qt client needs Qt 6.8+, CMake, and Ninja:

```bash
cmake -S desktop -B desktop/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build desktop/build
ctest --test-dir desktop/build --output-on-failure
```

## Project Layout

```text
backend/         FastAPI, Celery, Alembic, and tests
frontend/        Desktop React application
frontend-ios/    iPhone PWA
packages/shared/ API, types, and formatting shared by both web frontends
desktop/         Experimental Qt Quick native desktop client
finnhub-mcp/     Finnhub MCP sidecar
pi-agent/        AI research sidecar
docs/            Architecture and integration docs
compose.yaml     Full production topology
```

## Documentation

- [Changelog](CHANGELOG.md)
- [Research Data Gateway](docs/research-data-gateway.md)
- [Options analytics](docs/options.md)
- [AI Orchestrator](docs/ai-orchestrator.md)
- [AI conversations & long-term memory](docs/ai-conversations.md)
- [Exa Deep Search](docs/exa-deep-search.md)
- [iPhone frontend](docs/frontend-ios.md)
- [Portfolio transaction ledger](docs/portfolio-ledger.md)
- [IBKR integration](docs/integrations/ibkr.md)
- [Qt desktop architecture](docs/qt-desktop-architecture-audit.md)

The linked docs are currently written in Chinese.

## License

The source code in this repository is published for viewing only. **All
rights reserved — no license is granted** to use, copy, modify, or
redistribute it without the author's explicit written permission. See
[LICENSE](LICENSE) for details.
