<p align="center">
  <img src="frontend/public/logo.png" width="96" alt="Stock Monitor logo">
</p>

<h1 align="center">Stock Monitor</h1>

<p align="center">
  自托管的美股监控、研究与投资组合分析工作台
</p>

Stock Monitor 把行情、自选股、新闻、SEC 披露、基本面、估值、投资组合、交易日志和 AI 研究集中在一个响应式仪表盘中。数据、账户和 API Key 都保留在自己的服务器上，适合个人投资者或小团队部署。

> 本项目是研究与记录工具，不提供投资建议，也不会自动下单。历史数据、模型结果和模拟结果不代表未来表现。

## 核心能力

- **市场雷达**：聚合 Alpaca、Tiingo、Finnhub 和 Yahoo 行情，保存标准化快照，通过 SSE 推送实时价格与盘中事件。
- **行业板块检测（桌面端）**：以 11/50/229 的基础行业分类和 5/25/92 的 AI 产业链图谱组织 64 个 ETF 代理；按日优先 yfinance、失败回退 Finnhub，持久化确定性 Pulse / Heat / Risk / Focus / Relative Strength 快照，AI 摘要可选，页面只读已保存结果，不在加载时调用 Provider 或 AI。
- **异动与新闻**：监控自选股价格和成交量变化，聚合公司新闻、市场新闻及调查上下文，并支持按需 AI 总结。
- **基本面研究**：提供财务报表、公司资料、分析师评级、SEC 8-K / 10-Q / 10-K、Form 4、13F、技术分析和个股横向比较。
- **估值与宏观**：包含 DCF、多模型估值、ROIC、Piotroski F-Score、Altman Z-Score，以及可选的美国宏观数据。
- **投资组合中心**：支持多币种折算、权威交易流水、持仓重建、收益归因、组合健康、策略画像和大盘基准对比。
- **组合量化分析**：提供风险体检、压力测试、情景分析、蒙特卡洛模拟和约束组合优化；结果每周后台预计算，也保留手动刷新。
- **AI 研究助手**：支持流式多轮对话、只读研究工具、引用、长期记忆、投资决策记录，以及可选的 Exa 联网研究。
- **机会发现与舆情**：可选 Perplexity / Exa 机会发现和 Adanos 多源舆情，带本地验证、预算限制和持久化历史。
- **桌面与 iPhone 前端**：桌面端位于 `/`，独立 iPhone PWA 位于 `/mobile/`，两端共用同一套认证和 API。
- **多用户与管理**：JWT 登录、注册审核、管理员设置和按用户隔离的数据访问。

外部数据缺失或覆盖不足时，界面会明确显示“数据不足”，不会把缺失值当作 0，也不会编造财务数据。

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面与移动前端 | React 19、TypeScript、Vite、TanStack Query |
| API | FastAPI、SQLAlchemy 2、Alembic、Pydantic Settings |
| 后台任务 | Celery、Redis |
| 数据库 | PostgreSQL 16 |
| 数据处理 | pandas、NumPy、SciPy、yfinance、edgartools |
| 网关 | nginx、Caddy |
| 部署 | Docker Compose |

## 架构

```mermaid
flowchart LR
    U[浏览器 / PWA] --> C[Caddy]
    C --> D[桌面前端]
    C --> M[iPhone 前端]
    D --> A[FastAPI]
    M --> A
    A --> P[(PostgreSQL)]
    A --> R[(Redis)]
    R --> W[Celery Worker]
    R --> S[SEC / IBKR Worker]
    B[Celery Beat] --> R
    Q[Market Stream] --> R
    A --> F[Finnhub MCP]
    A --> E[外部行情 / 新闻 / AI / SEC]
    W --> E
    S --> E
```

## 快速开始

### 环境要求

- Docker Engine
- Docker Compose v2
- 建议至少 4 GB 内存

所有第三方 Provider 都是可选项。没有 API Key 时应用仍可启动，对应功能会降级或显示数据不足。

行业板块检测使用 yfinance 批量日线，单个标的失败时回退 Finnhub；分析按低频批次写入数据库，页面读取持久化结果，不会在加载时触发上游行情或 AI。AI 摘要由 `INDUSTRY_PULSE_AI_ENABLED` 控制。

### 1. 获取代码

```bash
git clone https://github.com/Uhmmu/stock-monitor.git
cd stock-monitor
cp .env.example .env
```

### 2. 设置基础配置

编辑 `.env`，至少修改以下值：

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

`POSTGRES_PASSWORD` 和 `DATABASE_URL` 中的密码必须一致。可以使用 `openssl rand -hex 32` 生成随机密钥。

### 3. 启动本地环境

```bash
docker compose up -d --build
docker compose ps
```

打开 <http://127.0.0.1:8080>。API 健康检查：

```bash
curl http://127.0.0.1:8080/api/health
```

API 启动时会自动执行数据库迁移。首次启动且数据库中没有管理员时，会使用 `ADMIN_USERNAME` 和 `ADMIN_INIT_PASSWORD` 创建管理员账户。

## 可选 Provider

按需要在 `.env` 中启用，不要把真实 Key 提交到 Git：

| 能力 | 主要配置 |
|---|---|
| Finnhub 行情与新闻 | `FINNHUB_API_KEY` |
| Alpaca 实时行情 | `ALPACA_MARKET_DATA_ENABLED`、`ALPACA_API_KEY`、`ALPACA_API_SECRET` |
| Tiingo 行情与新闻 | `TIINGO_MARKET_DATA_ENABLED`、`TIINGO_API_TOKEN`、`TIINGO_NEWS_ENABLED` |
| FMP 公司资料与历史日线 | `FMP_API_KEY` |
| Tavily / Marketaux 新闻 | `TAVILY_API_KEY`、`MARKETAUX_API_KEY` |
| AI 总结与报告 | `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL_*` |
| AI 对话 | `AI_ENABLED`、`AI_API_BASE`、`AI_API_KEY`、`AI_MODEL` |
| Exa 联网研究 | `EXA_ENABLED`、`EXA_API_KEY` |
| Perplexity 机会发现 | `PERPLEXITY_API_KEY` |
| Adanos 舆情 | `ADANOS_API_KEY` 或 `ADANOS_API_KEYS` |
| Alpha Vantage 宏观数据 | `ALPHA_VANTAGE_ENABLED`、`ALPHA_VANTAGE_API_KEY` |
| 行业板块检测 | `INDUSTRY_PULSE_*`；Finnhub 回退时使用 `FINNHUB_API_KEY` |
| IBKR 只读账户同步 | `IBKR_CP_*` 或 `IBKR_FLEX_*`，参见 [IBKR 文档](docs/integrations/ibkr.md) |

AI、搜索、机会发现和舆情 Key 只由服务端读取，浏览器不会接触这些凭据。IBKR 集成必须使用经过验证的 `socks5h` 代理并采用 fail-closed 配置，禁止代理失败后直连。

## 生产部署

设置生产域名后，使用不包含本地 override 的 Compose 文件启动完整栈：

```env
SITE_DOMAINS="stocks.example.com, www.stocks.example.com"
```

```bash
docker compose -f compose.yaml up -d --build
docker compose -f compose.yaml ps
```

Caddy 会负责 HTTPS，并将 `/`、`/mobile/` 和 `/api` 分别路由到桌面前端、iPhone 前端和 FastAPI。

后端代码或依赖变化时，`api`、`worker`、`sec-worker`、`beat` 和 `market-stream` 使用同一个构建上下文，需要一起重建。生产升级前请先备份 PostgreSQL 和持久卷。

## 常用命令

```bash
make up       # 构建并启动本地环境
make down     # 停止服务
make logs     # 查看日志
make migrate  # 执行数据库迁移
make test     # 运行后端与桌面前端测试
make backup   # 备份 PostgreSQL
```

单独验证各部分：

```bash
docker compose run --rm api pytest

cd frontend
npm ci
npm test
npm run build

cd ../frontend-ios
npm ci
npm test
npm run build
```

## 项目结构

```text
stock-monitor/
├── backend/
│   ├── app/api/                 # FastAPI 路由
│   ├── app/services/            # 行情、新闻、SEC、组合与分析服务
│   ├── app/tasks/               # Celery 任务与调度
│   ├── app/research/            # 只读 Research Data Gateway
│   ├── app/ai*/                 # AI 对话、工具、记忆与富内容
│   ├── alembic/versions/        # 数据库迁移
│   └── tests/                   # 后端测试
├── frontend/                    # 桌面 React 应用
├── frontend-ios/                # iPhone PWA
├── packages/shared/             # 两端共享 API、类型与格式化
├── finnhub-mcp/                 # Finnhub MCP sidecar
├── docs/                        # 架构与集成文档
├── compose.yaml                 # 生产服务拓扑
└── compose.override.yaml        # 本地预览覆盖
```

## 深入文档

- [Research Data Gateway](docs/research-data-gateway.md)
- [AI 工具层](docs/ai-tool-layer.md)
- [AI Orchestrator](docs/ai-orchestrator.md)
- [AI 对话](docs/ai-conversations.md)
- [AI 长期记忆](docs/ai-long-term-memory.md)
- [投资决策记录](docs/ai-investment-decisions.md)
- [Exa 联网研究](docs/external-search.md)
- [Exa Deep Search](docs/exa-deep-search.md)
- [iPhone 前端](docs/frontend-ios.md)
- [组合交易流水](docs/portfolio-ledger.md)
- [IBKR 集成](docs/integrations/ibkr.md)

## 安全与数据说明

- `.env`、数据库备份、API Key、Token、账户凭据和私钥不得提交到仓库。
- 生产环境必须修改数据库密码、`JWT_SECRET`、管理员初始密码和 `SEC_USER_AGENT`。
- PostgreSQL、Redis 和内部服务不应直接暴露到公网。
- 外部 Provider 的覆盖、延迟、配额和字段口径会影响结果；使用数据前请核对来源与时间。
- 组合分析基于历史数据和用户假设，仅用于研究，不构成收益承诺或交易建议。

## 项目状态

这是一个持续迭代的个人项目，数据库迁移、API 和界面可能随版本变化。生产升级前请阅读提交记录、执行测试并保留可恢复备份。
