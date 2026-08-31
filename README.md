<p align="center">
  <img src="frontend/public/logo.png" width="96" alt="Stock Monitor logo">
</p>

<h1 align="center">Stock Monitor</h1>

<p align="center">
  自托管的市场监控、投资研究与组合分析工作台
</p>

Stock Monitor 将行情、自选股、新闻、SEC 披露、基本面、估值、投资组合和 AI 研究集中在一个应用中。数据、账户信息和第三方 API Key 均由自己的服务器保存。

> 本项目只用于研究和记录，不提供投资建议，也不会自动下单。历史数据、模型结果和模拟结果不代表未来表现。

## 功能

- **行情与异动**：标准化多源报价、实时 SSE 更新、价格与成交量告警、调查记录。
- **研究数据**：公司新闻、财务报表、估值、技术分析、SEC 文件、Form 4、13F 和投资日历。
- **行业与期权**：持久化行业 Pulse、ETF/产业链代理，以及有明确数据质量和历史门槛的期权分析。
- **投资组合**：多币种持仓、交易流水、收益归因、健康检查、策略画像、压力测试、情景分析、蒙特卡洛和组合优化。
- **AI 研究**：带引用的流式对话、只读研究工具、长期记忆、投资决策记录，以及可选的 Exa、Perplexity 和 Pi Agent。
- **机会与舆情**：组合感知的股票机会发现、多源舆情、本地复核、成本预算和历史留存。
- **加载体验**：板块数据持久化在浏览器（IndexedDB），冷加载先渲染上次数据、后台刷新完成后自动切换为新数据；持续加载时顶部显示刷新进度条。
- **账号管理**：注册需管理员审核激活；管理面板支持创建、审核、备注和删除用户。
- **多端访问**：桌面 Web、Beta 市场工作台（`/beta/`）、独立 iPhone PWA，以及实验性的 Qt Quick 原生桌面客户端。

当上游数据缺失或样本不足时，应用会显示“数据不足”或对应原因，不会用 0 或猜测值填补。

## 架构

```mermaid
flowchart LR
    U["浏览器 / PWA"] --> G["Caddy / nginx"]
    G --> A["FastAPI"]
    A --> P[("PostgreSQL")]
    A --> R[("Redis")]
    R --> W["Celery workers"]
    B["Celery beat"] --> R
    M["Market stream"] --> R
    A --> F["Finnhub MCP"]
    A --> X["行情 / 新闻 / SEC / AI"]
    W --> X
    Q["Pi Agent"] --> A
```

| 层 | 技术 |
|---|---|
| Web / PWA | React 19、TypeScript、Vite、TanStack Query |
| API | FastAPI、SQLAlchemy 2、Alembic |
| 异步任务 | Celery、Redis |
| 数据库 | PostgreSQL 16 |
| 数据与计算 | pandas、NumPy、SciPy、yfinance、edgartools |
| 网关与部署 | nginx、Caddy、Docker Compose |
| 原生桌面实验 | Qt Quick、C++20、CMake |

## 快速开始

### 要求

- Docker Engine
- Docker Compose v2
- 建议至少 4 GB 内存

### 1. 获取代码

```bash
git clone https://github.com/Uhmmu/stock-monitor.git
cd stock-monitor
cp .env.example .env
```

### 2. 配置基础环境

编辑 `.env`，至少设置以下值：

```env
POSTGRES_DB=stock_monitor
POSTGRES_USER=stock
POSTGRES_PASSWORD=replace-with-a-strong-password
DATABASE_URL=postgresql+psycopg://stock:replace-with-a-strong-password@postgres:5432/stock_monitor

JWT_SECRET=replace-with-a-long-random-secret
ADMIN_USERNAME=admin
ADMIN_INIT_PASSWORD=replace-with-a-strong-admin-password
SEC_USER_AGENT=Stock Monitor admin@example.com
```

`POSTGRES_PASSWORD` 必须与 `DATABASE_URL` 中的密码一致。可用 `openssl rand -base64 48` 生成 `JWT_SECRET`。

### 3. 启动

```bash
docker compose up -d --build
docker compose ps
```

本地预览地址：<http://127.0.0.1:8080>

```bash
curl http://127.0.0.1:8080/api/health
```

API 启动时会自动执行 Alembic 迁移。数据库中没有管理员时，应用会使用 `ADMIN_USERNAME` 和 `ADMIN_INIT_PASSWORD` 创建首个管理员。通过注册入口申请的账号需要管理员审核激活后才能登录；管理员也可以在设置面板的用户管理中直接创建账号。

## 可选集成

应用没有第三方 Key 也能启动；对应功能会停用或显示数据不足。完整配置和默认值见 [`.env.example`](.env.example)。

| 能力 | 主要配置 |
|---|---|
| Finnhub | `FINNHUB_API_KEY` |
| Alpaca 实时行情 | `ALPACA_MARKET_DATA_ENABLED`、`ALPACA_API_KEY`、`ALPACA_API_SECRET` |
| Tiingo | `TIINGO_MARKET_DATA_ENABLED`、`TIINGO_API_TOKEN`、`TIINGO_NEWS_ENABLED` |
| FMP | `FMP_API_KEY` |
| 新闻搜索 | `TAVILY_API_KEY`、`MARKETAUX_API_KEY` |
| AI 对话与报告 | `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`AI_*`、`MODEL_*` |
| 深度研究 | `EXA_ENABLED`、`EXA_API_KEY`、`AGENT_GATEWAY_TOKEN` |
| 机会发现与舆情 | `PERPLEXITY_API_KEY`、`ADANOS_API_KEY` |
| 美国宏观数据 | `ALPHA_VANTAGE_ENABLED`、`ALPHA_VANTAGE_API_KEY` |
| IBKR 只读同步 | `IBKR_CP_*` 或 `IBKR_FLEX_*` |

所有 Key 仅由服务端读取。IBKR 连接必须使用经过验证的 `socks5h` 代理并 fail closed，禁止代理失败后直连；详见 [IBKR 集成文档](docs/integrations/ibkr.md)。

## 生产部署

设置域名和 Caddy Basic Auth：

```env
SITE_DOMAINS="jialenb.com, xn--fjq893a0q8b.com"
AUTH_USER=admin
AUTH_PASSWORD_HASH=replace-with-a-caddy-password-hash
```

使用基础 Compose 文件启动完整栈：

```bash
docker compose -f compose.yaml up -d --build
docker compose -f compose.yaml ps
```

Caddy 提供 HTTPS；桌面端位于 `/`，Beta 市场工作台位于 `/beta/`，iPhone PWA 位于 `/mobile/`，API 位于 `/api/`。生产升级前应备份 PostgreSQL 和持久卷。

后端代码或依赖变化时，需一起重建共享 `backend` 构建上下文的 `api`、`worker`、`sec-worker`、`beat` 和 `market-stream`。

## 开发与验证

```bash
# 后端
PYTHONPATH=backend .venv/bin/pytest

# 桌面 Web
cd frontend
npm ci
npm test
npm run build

# iPhone PWA
cd ../frontend-ios
npm ci
npm test
npm run build
```

常用 Compose 操作也可通过 `make up`、`make down`、`make logs`、`make migrate`、`make backup` 和 `make restore FILE=backup.sql.gz` 执行。

Qt 客户端需要 Qt 6.8+、CMake 和 Ninja：

```bash
cmake -S desktop -B desktop/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build desktop/build
ctest --test-dir desktop/build --output-on-failure
```

## 目录

```text
backend/         FastAPI、Celery、Alembic 与测试
frontend/        桌面 React 应用
frontend-ios/    iPhone PWA
packages/shared/ 两个 Web 前端共享的 API、类型与格式化
desktop/         Qt Quick 原生桌面实验
finnhub-mcp/     Finnhub MCP sidecar
pi-agent/        AI research sidecar
docs/            架构和集成文档
compose.yaml     完整生产拓扑
```

## 文档

- [更新日志](CHANGELOG.md)
- [Research Data Gateway](docs/research-data-gateway.md)
- [Options analytics](docs/options.md)
- [AI Orchestrator](docs/ai-orchestrator.md)
- [AI 对话与长期记忆](docs/ai-conversations.md)
- [Exa Deep Search](docs/exa-deep-search.md)
- [iPhone 前端](docs/frontend-ios.md)
- [组合交易流水](docs/portfolio-ledger.md)
- [IBKR 集成](docs/integrations/ibkr.md)
- [Qt 桌面架构](docs/qt-desktop-architecture-audit.md)

## 安全边界

- 不要提交 `.env`、API Key、Token、账户凭据、私钥或数据库备份。
- 生产环境必须设置强随机 `JWT_SECRET`、数据库密码和管理员初始密码。
- PostgreSQL、Redis、MCP sidecar 和 Agent gateway 不应暴露到公网。
- 外部数据的覆盖、延迟、配额和口径会影响结果，使用前应核对来源与时间。

这是持续迭代的个人项目。生产升级前请检查提交记录、执行相关测试并保留可恢复备份。
