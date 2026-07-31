# Stock Monitor

一个可自托管的美股监控与研究工作台。它把实时行情、异动提醒、新闻与 SEC 披露、基本面数据、AI 研究助手、交易日志和多模型指标集中在一个响应式仪表盘中。

项目面向希望自己掌握数据、API 密钥和部署环境的个人投资者与小团队。它提供研究辅助，不构成投资建议。

## 功能

- **实时行情与自选股**：按计划轮询自选标的，展示价格、涨跌幅、市场状态和 TradingView 图表。
- **异动提醒与调查**：按 20 分钟、1 小时和日内阈值检测异常波动，并自动收集相关新闻与上下文。
- **新闻与 SEC 数据**：个股新闻聚合 Yahoo、Finnhub、Marketaux 与 Tavily；“新闻中心”的紫色“全市场”入口以 Finnhub 市场新闻为主、Marketaux 为补充，并用本地规则过滤、事件聚类、重要度排序和主题均衡，不消耗 LLM 筛选额度。市场新闻与个股新闻都支持按卡片请求 AI 总结。
- **基本面、股权与估值**：展示财报、分析师评级、季度数据、股本/空头统计、SEC 内部人交易、延迟 13F 申报、DCF 情景和同行估值比较。
- **投资日历**：以持仓和自选股为中心聚合财报、除息/支付和拆股日期，保留来源、预计/确认状态、冲突与数据新鲜度，并以确定性规则标记组合相关影响。
- **轻量技术分析**：从 FMP 缓存最多约五年的日线 OHLCV，在本地聚合周线、计算指标与关键区域，并生成可持久化的静态 WebP 图表。
- **多模型交叉**：根据行业与公司特征组合模型权重，并计算 Forward P/E、PEG、EV/Sales、DCF、ROIC、Piotroski F-Score、Altman Z-Score 等指标。计算结果会显示公式、数据来源、缺失字段和适用性，不把缺失数据伪装成 0 分。
- **多用户登录**：支持注册申请、登录、JWT 会话、管理员审核/删除用户和管理员权限控制。
- **交易日志区**：按用户记录交易计划、买卖方向、数量、价格、标签、图片和复盘内容，并可调用 AI 生成总结。
- **多币种持仓**：记录本币成本与行情，组合总市值、盈亏、权重和行业暴露通过 Yahoo 外汇报价折算到组合基础币种；汇率缺失时明确排除并提示，不按 1:1 混算。
- **机会发现**：仅手动触发，可在“Perplexity Search API + `gpt-5.6-sol`”低成本模式与“`finance_search` + Perplexity GPT-5.4”深度 Agent 模式间切换；两种模式都会结合 Yahoo、FMP、Finnhub、SEC、持仓、股票池以及新闻标题和概要，结果、本地验证、来源与历史报告均持久化。
- **AI 研究助手**：内置多轮对话页面（`/ai/new`、`/ai/{id}`），支持 SSE 流式输出、会话归档/软删除/恢复、重新生成、停止生成、引用抽屉和工具活动展示。回答只使用已入库数据，缺数据时明确标注。
- **只读 AI 工具层**：44 个版本化只读工具建立在 Research Data Gateway 之上，覆盖组合、新闻、SEC、公司、行情与技术数据。工具不写库、不调用上游 API、不递归调用，全部执行都有预算、超时、压缩和审计。
- **AI 长期记忆与投资决策**：跨会话的用户偏好/约束记忆需显式确认才生效，推断内容停留在 proposed；投资决策记录动作、期限、论点、催化剂、风险和失效条件，草稿必须用户确认后才转为正式，执行状态只是日志，不下单。
- **富内容回答**：模型只选择服务端生成的候选块 ID，指标网格、对比表、迷你走势、新闻聚类、风险面板、SEC 摘要等组件由确定性工厂产出，并始终附带完整 Markdown 回退。
- **可选联网研究**：Exa 普通 Search 与五档 Agent Deep Search，默认关闭；私有记忆和决策上下文不会发送到外部搜索。
- **标准化行情快照**：`price_snapshots` 记录真实行情时间戳、OHLC、涨跌、10/20 日均量与相对量、盘口时段、来源和原始载荷，通过 `snapshot_key` 保证幂等，只有新快照才触发异动评估。
- **交易日志与持仓同步**：已执行的日志记录通过稳定 source key 幂等同步为权威交易流水并重建派生持仓，编辑和删除都可对账。
- **SEC 官方数据**：支持 8-K、10-Q、10-K、内幕交易和 13F 持仓信息。
- **数据缺口提示**：当外部数据覆盖不足时明确显示缺少的字段，方便排错和判断模型可信度。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19、TypeScript、Vite、TanStack Query、react-markdown、remark-gfm |
| 后端 | FastAPI、SQLAlchemy 2、Alembic、Pydantic Settings |
| 后台任务 | Celery、Redis |
| 数据库 | PostgreSQL 16 |
| 数据源 | yfinance、Finnhub MCP、FMP（仅历史日线与公司资料）、Tavily、SEC EDGAR / edgartools |
| AI | 可配置的 OpenAI-compatible API（对话、工具调用、总结、记忆抽取）、可选 Exa 联网搜索 |
| 网关 | Caddy（HTTPS 和 Basic Auth） |
| 部署 | Docker Compose |

## 快速开始

### 环境要求

- Docker Engine 与 Docker Compose
- Finnhub API Key
- Tavily API Key
- OpenAI-compatible API Key 和 Base URL

### 1. 获取代码并配置环境变量

```bash
git clone https://github.com/Uhmmu/stock-monitor.git
cd stock-monitor
cp .env.example .env
```

至少填写以下配置：

```env
POSTGRES_PASSWORD=change-this
DATABASE_URL=postgresql+psycopg://stock:change-this@postgres:5432/stock_monitor

FINNHUB_API_KEY=your-finnhub-key
TAVILY_API_KEY=your-tavily-key
MARKETAUX_API_KEY=                  # 可选；用于补充市场/个股新闻
MARKETAUX_ENABLED=true
MARKET_NEWS_ENABLED=true
FINNHUB_MARKET_NEWS_ENABLED=true
MARKETAUX_MARKET_NEWS_ENABLED=true
MARKET_NEWS_POLL_MINUTES=60
MARKETAUX_MARKET_REQUESTS_RESERVE=12
MARKET_NEWS_MAX_ITEMS=20
FMP_API_KEY=your-fmp-key
FMP_DAILY_REQUEST_LIMIT=150
FMP_REQUEST_RESERVE=10
FMP_SYNC_ENABLED=true
FMP_PROFILE_SYNC_ENABLED=true
FMP_PRICE_SYNC_ENABLED=true
FMP_TRANSLATION_ENABLED=true

OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL_SIMPLE=gpt-5.4-mini
MODEL_MEDIUM=gpt-5.6-luna
MODEL_IMPORTANT=gpt-5.6-sol

# 可选：启用手动机会发现
PERPLEXITY_API_KEY=your-perplexity-key
PERPLEXITY_SEARCH_URL=https://api.perplexity.ai/search
PERPLEXITY_MAX_MONTHLY_BUDGET_USD=10
PERPLEXITY_MAX_RUN_COST_USD=1

# 可选：启用 Reddit、X.com、新闻与 Polymarket 聚合舆情
ADANOS_API_KEY=your-adanos-key
# 可选：多个 Key 轮询分流，遇到限流或上游错误时自动切换
ADANOS_API_KEYS=your-adanos-key-1,your-adanos-key-2
ADANOS_API_BASE_URL=https://api.adanos.org

# 生产环境必须修改
JWT_SECRET=generate-a-long-random-secret
ADMIN_INIT_PASSWORD=generate-a-strong-admin-password

SITE_DOMAINS="stocks.example.com, www.stocks.example.com"
AUTH_USER=admin
AUTH_PASSWORD_HASH=   # caddy hash-password 生成
```

不要把 `.env`、API Key、JWT 密钥或真实密码提交到 GitHub。

Adanos Key 仅由 FastAPI 服务端读取。登录后的“舆情”板块通过后端并发查询四个来源，
单个来源失败不会影响其余来源；成功结果缓存 5 分钟，浏览器不会接触 Key。配置
`ADANOS_API_KEYS` 时，四个来源会在 Key 池中轮询分流；单个 Key 返回
401、403、429 或可重试的 5xx 时，会自动尝试池中的下一个 Key。

### 可选：AI 研究助手

AI 对话、工具层、总结、长期记忆、投资决策和富内容默认开启，但 `AI_API_KEY` 与 `AI_API_BASE` 只能由服务端配置，浏览器不会接触密钥。若不打算启用，请显式设置 `AI_ENABLED=false`，不要依赖"有表无配置"的隐式状态：

```env
AI_ENABLED=true
AI_API_BASE=https://api.openai.com/v1
AI_API_KEY=your-key
AI_MODEL=gpt-5.6-sol
```

对话上下文由会话摘要、最近未摘要消息、已确认记忆和活跃决策组成，三类记录相互独立且可分别关闭。模型没有写工具：记忆和决策的落库都需要用户显式确认。

### 可选：AI 对话联网研究

AI 对话支持“不联网”、Exa 普通 Search，以及 Minimal、Low、Medium、High、X-High 五档 Exa Agent Deep Search。默认关闭且默认模式为“不联网”；启用时只在服务端设置 `EXA_API_KEY`，浏览器不会接触 Key、API Base、内部预算或 Provider Run ID。High 与 X-High 默认需要费用确认，X-High 不会被自动选择。

普通搜索和 Deep Search 是两条独立链路：普通搜索调用 `/search` 并由当前主模型组织答案；Deep Search 创建持久化 `/agent/runs`，支持刷新恢复与主动取消，完成后再交给当前主模型轻量整理。生产配置、费用、隐私边界和测试命令见 [docs/external-search.md](docs/external-search.md) 与 [docs/exa-deep-search.md](docs/exa-deep-search.md)。

### 2. 启动服务

```bash
docker compose up -d --build
docker compose ps
```

API 容器启动时会自动执行 Alembic migration。生产环境中，后端代码变化后需要重建所有共享后端构建上下文的服务：`api`、`worker`、`sec-worker`、`beat`。

```bash
docker compose build api worker sec-worker beat
docker compose up -d api worker sec-worker beat
docker compose build frontend
docker compose up -d frontend
```

配置 Caddy 域名后，访问 `SITE_DOMAINS` 中的任一 HTTPS 地址。多个域名使用英文逗号和空格分隔；旧的 `SITE_DOMAIN` 配置仍然兼容。本地开发可以使用：

```bash
docker compose -f compose.yaml -f compose.override.yaml up -d
```

### 3. 创建用户

首次启动时，应用会根据 `ADMIN_INIT_PASSWORD` 创建管理员账号。普通用户可以在登录页申请注册，管理员在“系统设置”中审核账号。

### 4. 添加自选股

登录后进入“自选股”，添加股票代码，例如 `AAPL`、`MSFT` 或 `NVDA`。后台任务会逐步拉取行情、财报、新闻和模型快照。

FMP 配额按 UTC 自然日记账。每次 HTTP 尝试都会先原子预留并持久化，实际可用量为 `FMP_DAILY_REQUEST_LIMIT - FMP_REQUEST_RESERVE`；耗尽后保存当前队列位置，下一 UTC 日从未完成股票继续。公开读取接口只访问数据库与图表缓存，不会触发 FMP 请求。公司资料默认按 180 天长缓存处理，Yahoo 仍是财务报表来源。

“基本面 → 股权与股本”的股本统计使用 Yahoo 24 小时缓存；上游失败时保留并标记最近一次有效缓存。SEC Form 4 与 13F 继续复用现有 SEC 同步任务，13F 会明确提示季度申报的天然滞后。投资日历由后台每 12 小时同步 Yahoo 的财报、分红和拆股结构化数据，页面请求不会直接调用上游。当前版本不会声称支持尚未验证的 IPO、公司活动、宏观日历、政府交易或付费 FMP 端点，也不需要新增环境变量。

### 新闻采集与总结

- “全市场”新闻默认每小时处理一次，Finnhub 是主源；Marketaux 是补充源，按独立状态和每日预留额度运行。没有 `MARKETAUX_API_KEY` 时，Finnhub 市场新闻仍可正常工作。
- 个股新闻按现有轮询周期采集。所有新闻先经过字段校验、追踪参数清理、精确去重、相似事件聚类、质量/重要度评分和软性多样性重排，再写入数据库。
- 市场新闻重点覆盖宏观经济、央行利率、美股市场、政策监管、地缘政治、能源和科技等主题；个股新闻会提高财报、并购、监管、管理层变化和融资等事件的优先级，并降低标题党内容的排序。
- 新闻卡片不下载或展示图片。点击“AI 总结”后才会对单条已入库新闻调用配置的 OpenAI-compatible 模型；AI 失败不会影响新闻抓取和入库。

## 常用命令

```bash
make up       # 构建并启动
make down     # 停止服务
make logs     # 查看日志
make migrate  # 执行数据库迁移
make test     # 运行后端测试
make backup   # 备份 PostgreSQL
```

前端本地验证：

```bash
cd frontend
npm test
npm run build
```

后端专项测试：

```bash
docker compose run --rm api pytest
```

## 多模型指标说明

年度损益表、资产负债表和现金流量表优先由 yfinance 拉取并统一字段名，再由应用计算：

- **ROIC**：NOPAT ÷ 投入资本，优先使用当前/上一年度平均投入资本。
- **Piotroski F-Score**：九项会计信号。缺失信号不会直接计为失败，界面会显示例如 `6/8`。
- **Altman Z-Score**：经典上市制造业模型。银行、保险等金融企业不适用；软件和 REIT 会标记较低适用性。

模型页面会同时展示公式、计算口径、警告、来源和缺失字段。不同公司的财报口径与行业特征不同，请结合原始披露理解结果。

## 项目结构

```text
stock-monitor/
├── backend/
│   ├── app/api/             # FastAPI 路由、认证、交易日志、多模型 API
│   ├── app/services/        # 行情、新闻、SEC、LLM、多模型计算
│   ├── app/research/        # 只读 Research Data Gateway
│   ├── app/ai/              # 无状态 AI Orchestrator 与会话层
│   ├── app/ai_tools/        # 只读 AI 工具适配、策略与执行器
│   ├── app/ai_memory/       # 长期记忆与投资决策
│   ├── app/ai_rich_content/ # 确定性富内容块工厂
│   ├── app/external_search/ # 可选 Exa Search / Agent Deep Search
│   ├── app/tasks/           # Celery 定时任务和后台同步
│   ├── alembic/versions/    # 数据库迁移
│   └── tests/               # 后端测试
├── frontend/src/            # React 单页应用
├── frontend/src/features/   # AI 对话与记忆前端模块
├── docs/                    # AI、搜索与 Gateway 边界文档
├── finnhub-mcp/             # Finnhub MCP sidecar
├── compose.yaml
├── Caddyfile
└── .env.example
```

各模块的边界、配置、隐私约束和测试命令见 `docs/`：
[research-data-gateway](docs/research-data-gateway.md)、
[ai-tool-layer](docs/ai-tool-layer.md)、
[ai-orchestrator](docs/ai-orchestrator.md)、
[ai-conversations](docs/ai-conversations.md)、
[ai-conversation-summary](docs/ai-conversation-summary.md)、
[ai-long-term-memory](docs/ai-long-term-memory.md)、
[ai-investment-decisions](docs/ai-investment-decisions.md)、
[ai-rich-content](docs/ai-rich-content.md)、
[ai-chat-frontend](docs/ai-chat-frontend.md)、
[external-search](docs/external-search.md)、
[exa-deep-search](docs/exa-deep-search.md)。

## 数据与安全

- 外部 API 的覆盖范围、限流和字段完整性会影响页面结果。
- 计算指标缺失时会明确显示“数据不足”，应用不会补造财务数据。
- 生产环境请设置强密码、随机 `JWT_SECRET`、真实 `SEC_USER_AGENT`，并限制数据库与 Redis 的网络暴露。
- 运行 `make backup` 定期备份 PostgreSQL；升级前建议先保留数据库和源码回滚副本。

## License

MIT
