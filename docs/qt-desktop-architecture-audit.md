# Stock Monitor Native Qt Desktop — Architecture Audit & Development Blueprint

审计日期：2026-08-18  
审计范围：本文是在旧 Linux checkout `/home/jiale/test/stock-monitor` 上完成的历史快照；当前 macOS checkout 为 `/Users/jiale/project/stock-monitor`，后续任务应以 `git rev-parse --show-toplevel` 的结果为准。审计只读检查源码、OpenAPI、前端调用、迁移、任务、部署与当时的 CachyOS/Arch 包元数据，不进入 Phase 1，不修改任何生产代码。

# 1. Executive Summary

保留当前 VPS FastAPI/Celery/PostgreSQL/Redis 作为唯一业务核心，在仓库新增 `desktop/`，以 Qt 6.8+、Qt Quick/QML、C++20、CMake 构建 Wayland-first 原生客户端；先复用现有 REST + SSE，只有测量证明必要时才新增聚合接口、任务事件流或下沉至 QSG/QRhi。

当前后端已经具备桌面端所需的大多数业务边界：审计时 FastAPI OpenAPI 含 **279 paths / 310 HTTP operations**，行情已有 Redis → SSE，AI 已有 POST-SSE，研究数据已有统一 `research/v1` gateway。Phase 1 不需要重构后端，也不需要 WebSocket、SQLite、图表引擎或自绘标题栏。

# 2. Current Repository Architecture

## 2.1 运行拓扑

```text
Providers (Yahoo/Finnhub/FMP/SEC/Alpaca/Tiingo/Alpha Vantage/Adanos/Exa/LLM/IBKR)
             │
             ▼
Celery beat ──► worker / sec-worker          market-stream
             │                                  │ upstream WS
             ├──────── PostgreSQL ◄─────────────┤
             └──────── Redis broker/cache/pubsub┘
                              │
                     FastAPI app.main:app
                      REST + SSE + files
                              │
                 frontend nginx / frontend-ios nginx
                              │
                            Caddy
                       HTTPS public origin
                    ┌─────────┴──────────┐
                 React Web          future Qt Desktop
```

`compose.yaml` 是规范服务拓扑：`postgres`、`redis`、`finnhub-mcp`、`api`、`worker`、`sec-worker`、`beat`、`market-stream`、`frontend`、`frontend-ios`、`caddy`。四个后端角色共享 `backend/` 镜像；`market-stream` 单独持有上游实时连接。Caddy 仅按 `/mobile/*` 分流，两个 nginx 都将 `/api/` 代理至 FastAPI，并关闭代理缓冲，适合 SSE。

## 2.2 Backend 模块审计

| 模块 | 真实路径 | 作用 / 调用者 | Desktop 直接使用 | 调整判断 |
|---|---|---|---|---|
| FastAPI entrypoint | `backend/app/main.py` | lifespan、注册全部 routers、初始化 seed/admin/provider；由 `uvicorn` 启动 | 间接使用 | Phase 1 无需改；启动时默认管理密码必须在发布前 fail-closed |
| Core routes | `backend/app/api/routes.py` | watchlist、dashboard、news、fundamentals、SEC、reports、settings 等；React `App.tsx` 主调用面 | 多数可用 | 1700+ 行且很多 dict response；只在触及接口时逐步 typed，不做大重构 |
| Domain routers | `backend/app/api/{portfolio,portfolio_analysis,discovery,investment,market,macro,mood,mood_validation,options,industry_pulse,compare,sentiment}_routes.py` | 各领域 HTTP 边界 | 是 | 保持兼容；补 freshness/分页/条件缓存应按端点做 |
| Research gateway | `backend/app/research/{router,service,repositories/gateway}.py` | 统一、只读、用户隔离、带 meta/source/freshness 的研究读取层；AI tools 使用 | **优先复用** | 最适合作为 Desktop 研究数据契约；响应内部仍多为 `dict`，需逐域收紧 schema |
| AI | `backend/app/ai/`、`backend/app/ai/conversations/` | 编排、工具循环、引用、会话、SSE；React `features/ai-chat` 使用 | 是 | Desktop 需复刻 SSE 状态机，不复制模型逻辑 |
| AI memory/decisions | `backend/app/ai_memory/` | 记忆、摘要、投资决策及审核 | 是 | 已有 typed schemas、cursor；直接复用 |
| External research | `backend/app/external_search/` | Exa search/deep-run、预算、事件记录 | 是 | 当前任务进度仍靠 polling；后期可统一 task-events SSE |
| IBKR | `backend/app/integrations/ibkr/` | Client Portal 管理测试、Flex 导入、规范化账户分析；专用 `ibkr` Celery queue | 是，只调用 VPS API | 严禁 Desktop 直连 IBKR；代理、凭据、浏览器登录全留服务端 |
| ORM / DB | `backend/app/models.py`、`backend/app/integrations/ibkr/db_models.py`、`backend/app/database.py` | 约 100 个业务模型、PostgreSQL session | 否 | Desktop 不连接 PostgreSQL |
| Migrations | `backend/alembic/versions/0001_initial.py` … `0061_mood_history_production.py` | 当前所有持久业务演进 | 否 | Desktop cache schema 独立；不可复用 Alembic/server tables |
| Background jobs | `backend/app/tasks/celery_app.py` | 行情、调查、新闻、财报、SEC、组合分析、IBKR、行业、期权、Mood 等 | 只观察状态 | Desktop 只触发现有安全 endpoint 和读状态，不运行任务 |
| Redis | `backend/app/services/realtime_market/state.py`、`stream.py`、搜索/预算/锁/cache 模块 | Celery、实时 quote/pubsub、锁、短缓存、预算 | 否 | 只能经 API/SSE；Desktop 不持有 Redis URL |
| Config/secrets | `backend/app/config.py`、VPS `.env` | provider keys、DB/Redis、LLM、IBKR、频率 | 否 | Desktop 仅保存 base URL、UI 设置和用户 token |
| Error handling | FastAPI `HTTPException` + `research/exceptions.py` + AI/External Search domain errors | 普通 API 有文本/异构错误；Research/AI 有稳定 code | 部分 | Desktop client 需先兼容两种形态；建议渐进统一 error envelope |

## 2.3 数据与任务边界

主要持久域由 `backend/app/models.py` 实证发现：证券/别名/自选与临时快照、价格/日内 bars/实时事件/价格告警、调查与新闻、历史行情/同步状态、公司资料/财报/估值、日历、SEC 全域、报告、国会议员/公众人物、用户、AI 会话/消息/工具/记忆/决策、Deep Search、组合/交易/lot/分析、股票机会发现、宏观、行业 Pulse、Options、Mood。IBKR 的同步、现金流、绩效、回转交易、分红和权威审计表位于 `backend/app/integrations/ibkr/db_models.py`。

`backend/app/tasks/celery_app.py` 的 beat 同时包含固定频率和 database-backed due check：行情 5 分钟、调查推进 1 分钟、新闻 15 分钟、市场新闻 1 小时、财报 12 小时、估值每日、SEC 6–24 小时、宏观/日历/IBKR/行业/Options/Mood 的廉价 due check 10–30 分钟。Desktop 不应改变这些采集频率。

## 2.4 现有客户端

- Desktop Web：`frontend/src/App.tsx` 是主壳与大量页面，领域页面位于 `Portfolio.tsx`、`TechnicalChart.tsx`、`OpportunityDiscovery.tsx`、`AIMoodConsole.tsx`、`IndustryPulse.tsx` 等。
- iOS Web：`frontend-ios/` 是独立信息架构，不是 CSS 缩放版。
- 共享 Web 层：`packages/shared/src/{api,types,format}.ts` 只服务两个 TypeScript 客户端；不能直接链接进 C++，但可作为行为与契约参考。
- 请求层：原生 `fetch` + TanStack Query，无 Axios/Redux；认证 token 存在 `localStorage`/`sessionStorage`。
- 图表：`lightweight-charts` 用于蜡烛、组合、宏观和期权；小图使用 SVG。Qt 不能复用 renderer，但可以复用服务端数据契约和交互语义。

# 3. Business Capability Map

| Capability | Current UI / frontend | Backend route | Service / tables / job | Provider | Desktop complexity |
|---|---|---|---|---|---|
| 登录/用户管理 | `App.tsx`、`AuthGate` | `/api/auth/*` | `auth.py`, `User` | local JWT | 中：安全存 token、过期处理 |
| Dashboard/市场状态 | `App.tsx` Overview、iOS Overview | `/api/dashboard`, `/indices` | market calendar/data, `PriceSnapshot` | Redis/Yahoo/Finnhub/etc | 低 |
| 自选/证券搜索/分组 | `App.tsx`, `SecuritySearchAutocomplete.tsx` | `/watchlist`, `/securities/*`, `/stock-management`, `/stock-groups` | securities/stock_management, Security/Watchlist | Yahoo/Finnhub mapping | 中 |
| 实时行情/事件 | `RealtimeMarket*`, `realtime.ts` | `/market/realtime/stream`, `/market/realtime`, `/market/events` | realtime_market + Redis + IntradayBar/Event | Alpaca/Tiingo/fallback | 中：SSE + model updates |
| 技术分析/告警/图表 | `TechnicalChart.tsx` | `/technical-analysis/*`, research technical endpoints | technical engine/context, HistoricalPrice/TechnicalAnalysis | cached Yahoo/FMP | 高：交互图表 |
| 新闻/调查/报告 | `App.tsx`, iOS Activity | `/news/*`, `/alerts`, `/investigations`, `/reports` | news/archive/alerting/LLM, NewsItem/Investigation/Report | Tiingo/Marketaux/Yahoo/Finnhub/LLM | 中 |
| 基本面/财报 | `App.tsx`, iOS Fundamentals | `/fundamentals`, `/financials`, `/financial-statements` | financials, QuarterlyFinancial/StatementSnapshot | Yahoo/Finnhub | 中 |
| 估值/同行/比较 | `App.tsx`, `StockCompare.tsx` | `/cross-model*`, `/peers/*`, `/compare/*` | cross_model/graham/stock_compare, ValuationSnapshot | persisted + Yahoo | 中高 |
| SEC/所有权 | `App.tsx`, `Ownership.tsx` | `/sec-*`, `/equity/{symbol}/ownership/*` | sec_edgar/extract/13f/ownership | SEC EDGAR | 中 |
| 公众人物交易 | `App.tsx` | `/congress/*`, research ownership | congress, CongressTrade/Figure* | public disclosures | 中 |
| 投资日历 | `InvestmentCalendar.tsx` | `/calendar/*` | investment_calendar, CalendarEvent/Source/Run | Yahoo/Finnhub | 中 |
| Portfolio/ledger | `Portfolio.tsx`, iOS Portfolio | `/portfolio/*` | portfolio services, Portfolio/Transaction/Position/Lot | IBKR authority + local | 高 |
| Portfolio analytics | `PortfolioAnalysis*`, Scenarios/MC/Optimization | `/portfolio/analysis/*` | portfolio_analysis, PortfolioAnalysisRun, Celery | server CPU | 高 UI，计算留 VPS |
| IBKR | `IbkrAccount.tsx`, `IbkrIntegrationTest.tsx` | `/ibkr/*`, `/admin/integrations/ibkr/*` | integrations/ibkr + db models + queue | IBKR through VPS SOCKS5H | 高；服务端专属 |
| Opportunity Discovery | `OpportunityDiscovery.tsx`, iOS Discovery | `/discovery/*` | discovery, 13 related tables, Celery | Perplexity/Yahoo/portfolio | 中高 |
| 美国宏观 | `MacroFundamentals.tsx`, iOS Dynamic | `/fundamentals/macro/us/*` | macro services/tables/job | Alpha Vantage | 中 |
| Industry Pulse | `IndustryPulse.tsx` | `/industry-pulse/*` | industry_pulse services/tables/job | Yahoo/Finnhub + AI | 高信息密度 |
| Options | `Options.tsx`, iOS Options | `/options/*` | options services/tables/job | Yahoo option chain | 高图表/表格 |
| Mood + Validation | `AIMoodConsole.tsx`, `MoodValidationLab.tsx` | `/mood/*`, `/mood-lab/*` | mood/history/validation tables/jobs | persisted multi-domain | 中高 |
| 舆情 | `Sentiment.tsx`, iOS Dynamic | `/sentiment/*` | adanos | Adanos | 中 |
| AI Chat/Research | `features/ai-chat`, iOS Chat | `/ai/v1/*`, `/research/v1/*`, `/external-search/v1/*` | AI orchestrator/tools/memory/search | configured LLM + Exa | 高：SSE/rich blocks |
| 交易日志/投资决策 | `App.tsx`, `features/ai-memory` | `/trade-logs/*`, `/ai/v1/investment-decisions/*` | TradeLog, AIInvestmentDecision* | local + LLM draft | 中 |
| 管理/数据源状态 | `App.tsx` Settings/admin views | `/settings`, `/admin/*`, `/market/providers/status` | AppSetting/provider sync state | all | 中；RBAC |

# 4. Existing API Inventory

## 4.1 Inventory 总况

运行 `PYTHONPATH=backend .venv/bin/python` 导入 `app.main:app` 并读取 `app.openapi()`：279 paths、310 HTTP operations、305 个 operation 带 Bearer security、52 个有 request body、38 个有 page/limit/offset/cursor 参数。只有 **112/310** 个 operation 在 OpenAPI 中有具体成功 JSON schema；这是“先验证契约、再考虑 codegen”的直接依据。

完整机器可读 inventory 的权威来源是运行中的 `GET /openapi.json`。本次审计同时固化了逐 operation 的 method/path/source/auth/request/response 清单：[`docs/qt-desktop-api-inventory.md`](qt-desktop-api-inventory.md)。当前没有 FastAPI WebSocket route；“实时”由服务端上游 WebSocket + 对客户端 SSE 完成。

## 4.2 重要 endpoint 逐项审计

| Method / Path | Source | Purpose / Request / Response | Auth | React caller | Desktop | Problem / recommendation |
|---|---|---|---|---|---|---|
| GET `/api/health` | `api/routes.py` | `{status}` liveness | public | compose health | A | Phase 1 连通性检查；另用 readiness 判断 DB |
| GET `/api/readiness` | `api/routes.py` | DB `select 1`, `{status}` | public | ops | A | 不要高频轮询 |
| POST `/api/auth/login` | `api/auth_routes.py` | username/password/remember → user + JWT | public | shared api | B | 无 refresh/revoke；公开 Desktop beta 前新增 token lifecycle |
| GET `/api/auth/me` | same | 当前用户/role | bearer | both web clients | A | 启动恢复会话 |
| GET `/api/dashboard` | `api/routes.py` | 市场状态 + watchlist quote aggregation | bearer | `App.tsx`, iOS detail | A | 已是 Dashboard 聚合；不要再造重复 endpoint |
| GET `/api/watchlist` | same | typed watchlist list | bearer | both | A | 与 SSE symbol subscription 合并 |
| GET `/api/securities/search` | same | `q,limit` → normalized candidates | bearer | autocomplete | A | 已有进程+Redis cache |
| GET `/api/market/realtime/stream?symbols=` | `api/market_routes.py` | Redis Pub/Sub SSE: ready/quote/bar/event/status + heartbeat | bearer | `realtime.ts` | A | Desktop 用一个合并连接；指数退避重连 |
| GET `/api/market/realtime?symbols=` | same | Redis quote，DB snapshot fallback | bearer | SSE fallback | A | 只在 stream error/offline recovery polling |
| GET `/api/market/intraday/{symbol}` | same | interval/date/limit → bars | bearer | realtime cards | B | 加 ETag/`last_updated`; 大历史优先 cursor/range |
| GET `/api/technical-analysis/{symbol}` | `api/routes.py` | cached analysis + chart series/events/portfolio cost | bearer | `App.tsx`, Portfolio | B | payload 大；允许按 layer/range 选择或研究 gateway typed 化 |
| GET `/api/research/v1/companies/{symbol}/prices/history` | `research/router.py` | bounded persisted history + meta/source/freshness | bearer | AI tools | **A/B 首选** | 统一语义好；data 仍是 dict schema |
| GET `/api/news/market` | `api/routes.py` | `limit,offset,sort` → items,total,last_updated,sources | bearer | both | A | 已分页；加 ETag/If-Modified-Since |
| GET `/api/news` | same | ticker/ranked news | bearer | both | B | 明确分页 envelope，避免无限列表 |
| POST `/api/news/{id}/summarize` | same | queue/return summary state | bearer | both | A | 客户端仅触发一次；状态事件流可后补 |
| GET `/api/fundamentals?ticker=` | same | Yahoo live metrics + source/fetched time | bearer | `App.tsx` | B | provider call/read latency；Desktop 短 TTL，不并发重复 |
| GET `/api/financial-statements` | same | cached annual/quarterly statements | bearer | `App.tsx` | A | 低频 cache + ETag |
| GET `/api/cross-model?ticker=` | same | persisted valuation payload | bearer | `App.tsx` | A | 不要 Desktop 重算估值 |
| GET `/api/portfolio/summary` | `api/portfolio_routes.py` | current portfolio, positions, base currency values | bearer/user-owned | desktop+iOS web | A | 现 Web 30s 后台轮询过密；Desktop 事件失效+5min refresh |
| GET `/api/portfolio/{performance,attribution,health,interpretation}` | same | typed/persisted derived views | bearer | `Portfolio.tsx` | A | 并行 lazy load，不必首屏全取 |
| POST `/api/portfolio/analysis/{stress-test,scenario-analysis,monte-carlo,optimize}` | `portfolio_analysis_routes.py` | create async job → job_id | bearer/user-owned | analysis pages | A | CPU 留 VPS；状态当前 2s polling，后期 task SSE |
| GET `/api/portfolio/analysis/jobs/{id}` | same | queued/running/terminal result | bearer/user-owned | 2s polling | B/D | active-only backoff 2→5s；统一 job event stream 是推荐非必需 |
| GET `/api/ibkr/overview` | `integrations/ibkr/formal_routes.py` | persisted account overview | bearer/user-owned | `IbkrAccount.tsx` | A | Desktop 永不接触 Flex/CP credentials |
| POST `/api/ibkr/sync` + GET `/sync/{id}` | same | queue authorized Flex sync / status | bearer | IBKR web | B/D | 1.5s polling 可改统一 task events；服务器仍 fail-closed proxy |
| GET `/api/discovery/latest` | `api/discovery_routes.py` | latest successful/in-progress run aggregation | bearer/user-owned | desktop+iOS web | A | 30s cache；运行时 8s polling可退避 |
| GET `/api/options/overview` | `api/options_routes.py` | typed bounded universe rankings | bearer | both | A | 5min refresh 与 server 6h数据频率不匹配；用 freshness/ETag |
| GET `/api/mood/{overview,report}` | `api/mood_routes.py` | persisted Mood aggregates/report | bearer | AI Mood | A | 1min staleTime足够；EOD数据不需要秒级 |
| GET `/api/industry-pulse/{overview,focus,taxonomy,status}` | `industry_pulse_routes.py` | persisted daily pulse read models | bearer | `IndustryPulse.tsx` | A | 5–10min cache，支持 range |
| GET `/api/fundamentals/macro/us/*` | `macro_routes.py` | persisted overview/series/curve/explanation/status | bearer | desktop+iOS web | A | 15min+ refresh；不用实时流 |
| POST `/api/ai/v1/conversations/{id}/messages` | `ai/conversations/router.py` | JSON request，`stream=true` 返回 SSE event sequence | bearer/user-owned | AI chat | A | Desktop 实现严格 incremental SSE parser/state machine |
| GET `/api/ai/v1/conversations` / `messages` | same | typed paged conversation/message history | bearer/user-owned | both | A | 直接复用 pagination |
| `/api/ai/v1/memories*` / `investment-decisions*` | `ai_memory/router.py` | typed cursor CRUD/state transitions | bearer/user-owned | memory/decision pages | A | 可直接复用；离线不要缓存敏感全文 |
| `/api/research/v1/*` | `research/router.py` | 35 个稳定只读 research operations | bearer/user-owned | AI tools | A/B | Desktop 新研究页面优先这里，逐步补具体 Pydantic data model |

分类：A direct reuse；B minor adaptation；C aggregation recommended；D streaming recommended；E unsuitable。

## 4.3 按域的完整 route family

以下覆盖当前 OpenAPI 的所有业务 route family；花括号代表同一路由组内已审计的 operation，不是建议的新路径。

| Domain | Existing operations | Class |
|---|---|---|
| auth | `/api/auth/{login,register,me,reddit/callback,admin/users...}` | A/B |
| core/security | `/api/{health,readiness,securities/*,snapshots/*,watchlist/*,stock-management,stock-groups/*,settings}` | A |
| dashboard/monitor | `/api/{dashboard,indices,alerts,investigations,reports/*,stocks/*/price-snapshot/latest}` | A |
| market | `/api/market/{realtime, realtime/{symbol}, realtime/stream, intraday/{symbol}, intraday/{symbol}/summary, events, providers/status}` | A/B/D |
| company research | `/api/{company-profile/*,fundamentals,financials,financial-statements,cross-model*,peers/*,compare/*,technical-analysis/*}` | A/B/C |
| news/SEC/ownership | `/api/{news/*,sec-filings*,sec-events,sec-financials,sec-insider,sec-13f*,equity/*/ownership/*,congress/*}` | A/B |
| calendar/macro/sentiment | `/api/{calendar/*,fundamentals/macro/us/*,sentiment/*}` | A |
| portfolio | `/api/portfolio/{summary,performance,attribution,benchmark,positions/*,health,strategy-profile,interpretation,transactions/*,completed-trades,open-lots,rebuild}` | A |
| portfolio analysis | `/api/portfolio/analysis/{metrics/*,scenarios/presets,stress-test,scenario-analysis,expected-return,monte-carlo,optimization-presets,optimize,jobs/*,history}` | A/D |
| discovery | `/api/discovery/{latest,runs/*,history/*,refresh,settings,candidates/*,usage}` | A/D |
| industry/options/mood | `/api/{industry-pulse/*,options/*,mood/*,mood-lab/*}` | A/D |
| IBKR | `/api/ibkr/*` and admin-only `/api/admin/integrations/ibkr/*` | A/E for direct-provider access |
| AI | `/api/ai/v1/{respond,config,health,metrics,conversations/*,memories/*,investment-decisions/*}` | A/D |
| research/tool/search | `/api/research/v1/*`, `/api/ai-tools/v1/*`, `/api/external-search/v1/*` | A/D |
| admin providers | `/api/admin/{fmp/*,technical-analysis/*,integrations/alpha-vantage/*}` | A for admin UI only |

# 5. React → API → Service Mapping

| Web page | Frontend hook/service | API | Backend route → service → data/provider |
|---|---|---|---|
| App shell/Overview | `App.tsx` TanStack queries | dashboard, indices, alerts, investigations, reports, settings | `api/routes.py` → market calendar/price snapshots + ORM; quotes from persisted/Redis/provider routing |
| Watchlist/Search | `App.tsx`, `SecuritySearchAutocomplete.tsx` | watchlist, securities/search/resolve, stock groups | routes → `securities.py`, `stock_management.py` → Security/Watchlist + Yahoo/Finnhub mapping/cache |
| Realtime cards | `realtime.ts` | market SSE; REST fallback/status/events | `market_routes.py` → Redis pubsub/state + price snapshot/intraday repository |
| Technical | `App.tsx`, `TechnicalChart.tsx` | technical-analysis detail/chart/alerts | routes → technical chart context/engine → cached HistoricalPrice/TechnicalAnalysis |
| Portfolio | `Portfolio.tsx` | portfolio summary/performance/health/etc | `portfolio_routes.py` → performance/health/ledger/fx/technical → Portfolio/Transaction/Position |
| Portfolio simulations | `PortfolioScenarios.tsx`, `PortfolioMonteCarlo.tsx`, `PortfolioOptimization.tsx` | analysis create + jobs polling | analysis routes → jobs/Celery → numpy/scipy + persisted run cache |
| IBKR | `IbkrAccount.tsx` | ibkr overview/records/analytics/sync | formal routes → repository/sync → normalized IBKR tables; Flex via proxied VPS job |
| News/Activity | `App.tsx`, iOS `ActivityPage.tsx` | news list/detail/refresh/summarize/archive | routes → news/news_store/archive/LLM → NewsItem + providers |
| Fundamentals/Valuation | `App.tsx`, iOS Fundamentals | fundamentals/financials/statements/cross-model/peers | routes → financials/market_data/cross_model/graham → persisted snapshots + bounded live Yahoo |
| Comparison | `StockCompare.tsx` | compare metrics/run/history | compare routes → `stock_compare.py` → persisted research data |
| Calendar | `InvestmentCalendar.tsx` | calendar capabilities/status/events/summary/symbol | investment routes → investment_calendar → event/source/sync tables |
| Macro | `MacroFundamentals.tsx` | macro overview/series/curve/status | macro routes → views/sync/derived → macro tables/Alpha Vantage |
| Discovery | `OpportunityDiscovery.tsx` | discovery latest/run/candidate/settings/refresh | discovery routes → discovery service → portfolio context + Perplexity/Yahoo + tables |
| Industry | `IndustryPulse.tsx` | overview/focus/taxonomy/node/status | industry routes → industry service → daily synthetic/constituent snapshots |
| Options | `Options.tsx` | overview/symbol/history | options routes → options service → snapshots/chain cache/Yahoo |
| Mood | `AIMoodConsole.tsx`, `MoodValidationLab.tsx` | mood report/overview/detail/history; lab runs/results | mood routes → mood/history/validation → persisted snapshots/runs |
| AI Chat | `features/ai-chat/api/*`, `useAIStream.ts` | conversation CRUD + POST-SSE message/regenerate | AI conversation router/service → orchestrator/tools/research gateway → LLM/providers |
| AI memory/decisions | `features/ai-memory/api.ts` | memories/settings/candidates/decisions/reviews | AI memory router/service → typed user-owned tables |

当前 polling 实证：Overview 的 dashboard/alerts/investigations 30s、indices 60s；Portfolio summary 30s 且 background；实时 SSE 失败时 REST 30s；market events 30s/provider status 60s；Options 5min；Macro overview 15min/admin status 30s；异步 job 1.5–2s；Discovery 运行态 8s；新闻 AI processing 2s；AI memory/decision 生成态 2s。Qt 不应照抄这些频率。

# 6. Server vs Local Placement Matrix

| Feature | Current | Recommended | Reason | Server / network / Desktop impact |
|---|---|---|---|---|
| quote/provider routing | server | SERVER ONLY | keys、统一 authority、订阅上限、持久证据 | 维持一套上游连接；Desktop 仅 SSE delta |
| historical prices | server DB | HYBRID | 服务端权威；本地缓存可加速图表/离线 | range/ETag 降流量；本地反序列化/渲染 |
| technical indicators | server | SERVER ONLY calculation; LOCAL render/hit test | 避免多客户端公式漂移 | Desktop 只做坐标转换 |
| fundamentals/valuation/Mood | server | SERVER ONLY | provider key、共享模型、确定性语义 | 低频缓存，几乎无新增负担 |
| portfolio/IBKR | server | SERVER ONLY data/business; LOCAL presentation | 权威账本、代理、隐私与一致性 | 禁止直连 IBKR/DB |
| news/SEC/calendar/industry/options | server | SERVER ONLY collection/normalization; LOCAL view cache | provider/任务/幂等均已存在 | 只读增量/分页 |
| AI/Deep Search | server | SERVER ONLY orchestration; LOCAL stream rendering | keys、预算、工具权限、审计 | 每次用户动作一条 SSE |
| charts | Web JS | LOCAL ONLY rendering | GPU、交互、缩放和命中需本地低延迟 | 降服务端静态图需求；增加 Desktop GPU |
| table filter/sort | mixed | HYBRID | 当前页小集合本地；大表/跨页服务端 | 避免全量下载与 DB 重复查询 |
| security search | server + browser | HYBRID | server canonical resolver，Desktop debounce/result cache | 少量请求，本地最近搜索 |
| cache | browser/Redis/DB | BOTH, different authority | server shared; local only acceleration/last-good | 明确 TTL/version，绝不复制 server DB |
| notifications | none/browser-local | HYBRID | server detects durable event；Desktop presents OS notification | 流事件触发，本地去重 |
| settings | server AppSetting + browser theme | BOTH | 业务/用户策略服务端；窗口/主题/快捷键本地 | QSettings 非敏感数据 |
| background refresh | web query timers | HYBRID | 服务端负责采集；Desktop 仅 active-view refresh/SSE | 闲置几乎不发 GET |
| exports | server data + browser | HYBRID | server 提供规范数据/大导出；Desktop 保存文件/打印 | 避免大数据内存复制 |
| image/static chart generation | server technical image | HYBRID then LOCAL | 保留兼容/分享图；Desktop 交互图本地 | 不因 Desktop 增加 matplotlib job |
| window/layout/motion/hover/shortcuts | web | LOCAL ONLY | 平台交互 | 零 VPS 负担 |

## SERVER / DESKTOP / BOTH 总表

| Capability | VPS | Desktop | Both | Protocol | Cache | Notes |
|---|:---:|:---:|:---:|---|---|---|
| Business data + calculations | ✓ | | | HTTPS REST | server DB/Redis | 唯一 authority |
| Realtime normalization | ✓ | | | upstream WS → SSE | Redis + local latest | Desktop 不开 provider WS |
| UI/render/input | | ✓ | | local | GPU/memory | QML/QSG |
| Historical chart data | ✓ | ✓ | ✓ | ranged REST | PostgreSQL + local SQLite | server authoritative |
| User/business settings | ✓ | | | REST | DB | strategy/watchlist etc. |
| Appearance/window settings | | ✓ | | local | QSettings | non-secret |
| Auth | ✓ | ✓ | ✓ | HTTPS Bearer | keyring only | token not QSettings/SQLite |
| Notifications | ✓ | ✓ | ✓ | SSE + desktop portal/DBus | local dedupe | detection server, display local |
| AI | ✓ | ✓ | ✓ | POST-SSE | server history | render locally |
| Export | ✓ | ✓ | ✓ | REST/file | chosen path | server canonical, local UX |

# 7. Backend Changes Required

## REQUIRED

1. **Phase 1：无业务 API 改动。** 现有 `/api/health`、`/api/readiness`、`/api/auth/login`、`/api/auth/me` 足够验收基础连接。
2. **公开 Desktop beta 前：认证配置 fail-closed。** `backend/app/auth.py` 当前 `JWT_SECRET` 默认 `change-me`；`backend/app/main.py` 当前 `ADMIN_INIT_PASSWORD` 有源码默认值。生产启动必须拒绝默认/空值。Web 影响：仅错误配置环境会拒绝启动；Desktop 原因：可分发客户端扩大登录入口；资源变化：无；migration：无。
3. **公开 Desktop beta 前：token lifecycle。** 增加短 access token + 可撤销 refresh/session endpoint，保持旧 Bearer access token 兼容一个迁移期。Web 影响：shared client 可后续迁移；Desktop 原因：不能把 7/30 天不可撤销 token 当长期凭据；资源：每次 refresh 少量 DB/Redis；migration：很可能需要 session/refresh-token 表。

## RECOMMENDED

- 为 Desktop 会用到的 legacy dict endpoint 补 `response_model`、统一 error envelope、`generated_at/data_version/freshness`；优先扩展 `backend/app/research/schemas.py` 和 gateway，而非另建 Desktop service。
- 对历史、新闻、财报、Options、Industry、Mood 等低频 GET 加 `ETag`/`Last-Modified`、`Cache-Control: private` 和 304；无 migration，Web 透明受益。
- 为 `/technical-analysis/{symbol}` 增加可选 `range/layers` 或优先使用 research history endpoints，避免每次携带全部图层。
- 当 Phase 6 的测量显示一次 stock detail 需要 5+ 重查询时，在 `backend/app/research/router.py` 增加通用 `/companies/{symbol}/overview`，内部只组合现有 gateway/service；不要命名为 desktop endpoint。
- 当异步 job polling 成为可测负担时，增加一个 authenticated `/api/tasks/stream?ids=` SSE，覆盖 portfolio/IBKR/discovery/mood validation；保留现有 GET status 作为恢复路径。

## OPTIONAL

- HTTP/2/3、响应压缩和服务端 rate limiting 的专项调优；Caddy 已可处理公网传输，先测量。
- 从完整 typed OpenAPI 生成 C++ DTO；在 198 个 success schema 仍不具体的 operation 上直接 codegen 收益低。
- WebSocket 下行通道。现有 SSE 单向需求完全匹配；只有需要高频双向订阅变更或大量并发时再引入。

## AVOID

- Desktop 直连 PostgreSQL、Redis、provider、IBKR Gateway/TWS/Client Portal。
- 打包 FastAPI/Celery/PostgreSQL/Redis 或复制 Mood/估值/portfolio 算法。
- 为 Desktop 大改 `backend/app/api/routes.py`、批量改 URL、批量改 response shape。
- 同时维护 REST、SSE、WebSocket 三套等价实时协议。

# 8. VPS Load Analysis

## 8.1 当前基线

仅 Overview 常驻就可能产生 dashboard 120/h + alerts 120/h + investigations 120/h + indices 60/h，即约 **420 GET/h/浏览器**，还未计 market events、provider status 和其它页面。Portfolio summary 当前 120 GET/h 且允许 background。运行中任务还有 1.5–8 秒 polling。实时行情本身已经有 SSE，但 Web 页面仍保留多个独立轮询源。

## 8.2 Desktop 目标流量模型

- 每个进程最多 1 条 market SSE，合并当前 watchlist/visible symbols；symbol 集变化才重连。
- AI 仅在一次生成期间打开 1 条 POST-SSE。
- 活跃 Overview：低频 metadata refresh 5 分钟一次；价格与 market event 走 SSE。
- 非活跃页面不刷新；窗口 hidden/minimized 后停止非必要 GET。
- job polling：2s 起步，10s 后升至 5s，后台升至 15s；终态立即停止。
- reconnect：1s、2s、4s、8s、16s、上限 30s，加 0–500ms jitter；恢复先取一次 REST snapshot，再接 SSE。
- 本地 last-good + ETag：未变响应走 304；断网显示明确 stale age，不把 cache 冒充 live。

目标为常驻 Overview **<30 普通 GET/h + 1 SSE**，相对当前 420 GET/h 基线减少约 93% 的定时 HTTP 请求。单个 SSE 增加一个 FastAPI connection、一个 Redis Pub/Sub subscription 和 15 秒 heartbeat；对当前个人/少量客户端是轻负担。若未来 100+ 并发客户端，再评估 fan-out gateway，而不是现在添加基础设施。

## 8.3 Cache / invalidation

| Data | Local TTL | Invalidation |
|---|---:|---|
| realtime latest | session only, stale 45–180s | SSE sequence/timestamp; reconnect snapshot |
| dashboard/watchlist | 5min last-good | watchlist mutation + market event |
| company profile/fundamentals | 15–60min | ETag/data_version/manual refresh |
| statements/valuation/SEC | 6–24h | server updated_at/ETag |
| news list | 2–5min | refresh/summarize event or explicit action |
| macro/industry/options/Mood | 10–60min based on server freshness | data version / latest run id |
| chart history | 24h immutable segments; latest segment 5min | last trading date + ETag |
| portfolio | 5min, memory first | transaction/IBKR sync completion + foreground |
| AI/IBKR sensitive content | memory only by default | logout/close |

不建议 cache stampede 控制、离线写队列、CRDT 或客户端数据库同步；当前产品没有对应需求。

# 9. Qt Technology Decision

## 9.1 Version strategy

- **Minimum source compatibility：Qt 6.8。** 它是当前 Qt 6 LTS 基线，已具备本项目所需的 Qt Quick、scene graph、CMake/QML module、Wayland、HiDPI 和 accessibility 基础。
- **Recommended development/runtime on CachyOS：发行版当前 Qt 6.11.x。** 本机 `pacman` 在 2026-08-18 提供/安装 `qt6-base 6.11.1`、`qt6-declarative 6.11.1`、`qt6-wayland 6.11.1`；官方在线文档当前为 6.11.2。CMake 写 `find_package(Qt6 6.8 REQUIRED ...)`，不锁 6.11.1 patch。
- Arch 是 rolling release；PKGBUILD 依赖模块包名并随仓库重编译，不 vendoring Qt，不打静态 Qt。

依据：[Qt Releases](https://doc.qt.io/qt-6/qt-releases.html)、[Supported Platforms](https://doc.qt.io/qt-6/supported-platforms.html)、[Arch qt6-base package](https://archlinux.org/packages/extra/x86_64/qt6-base/)。

## 9.2 Module decisions

| Module/API | Decision | Use |
|---|---|---|
| Qt Core/Gui/Qml/Quick | REQUIRED Phase 1 | event loop、QML、window、scene graph、JSON、models |
| Qt Quick Controls + Layouts | REQUIRED | controls/layout；使用 Basic style 作为可控基础 |
| Qt Network | REQUIRED | HTTPS、QNetworkAccessManager、QNetworkDiskCache/SSE reply |
| Qt Sql | Phase 3 | SQLite bounded cache only |
| Qt Concurrent | OPTIONAL | 仅经 profiling 证明 JSON/geometry 转换阻塞 UI 时用；普通网络不需要 |
| Qt SVG | Phase 2 optional | 品牌/少量矢量资源；简单图标优先 QML path/预编译资源 |
| Qt ShaderTools / Qt Quick Effects | Phase 2/7 optional | 离线 shader bake、MultiEffect；不要用 blur 装饰所有容器 |
| Qt WebSockets | NOT NOW | 服务端没有 client WebSocket endpoint；SSE 由 Qt Network 足够 |
| Qt Widgets | Phase 11 optional | `QSystemTrayIcon`；主 UI 仍为 Qt Quick |
| QQuickItem/QSGGeometryNode | Phase 7 | portable scene-graph chart renderer |
| QRhi / GuiPrivate | AVOID initially | 官方明确有限兼容且无 source/binary guarantee；只有 benchmark 后隔离使用 |
| Qt WebEngine | PROHIBITED as primary UI | 不嵌 React；仅未来外部网页预览有明确需求时另议 |

Qt Quick 通过 scene graph 在 render thread 构建图形，适合高刷新率 UI；QML/C++ 的官方集成模型也与本项目分层一致：[Qt Quick](https://doc.qt.io/qt-6/qtquick-index.html)、[Scene Graph](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html)、[QML/C++ Integration](https://doc.qt.io/qt-6/qtqml-cppintegration-overview.html)。[QRhi 官方文档](https://doc.qt.io/qt-6/qrhi.html) 明确要求 `Qt::GuiPrivate` 并不给兼容保证，因此不是通用图表 API。

## 9.3 Wayland / HiDPI / accessibility

- 不强制 `QT_QPA_PLATFORM`; Wayland session 让 Qt 自动选 Wayland，X11 session 自动 fallback xcb。测试可显式 `QT_QPA_PLATFORM=wayland`。
- 不固定 devicePixelRatio，不把 physical pixels 写进 layout；所有 geometry 使用 device-independent pixels，渲染层读取有效 DPR。
- 文本使用系统 font/fallback、QML font metrics 与 optical hierarchy；不打包未经许可的 Apple 字体。
- 所有自定义 control 提供 `Accessible.name/role/description`、键盘 focus、清晰 focus ring、minimum hit target；表格必须可键盘导航。
- 遵从 reduced motion/transparency 的应用设置；Linux 没有完全统一的系统 reduced-motion API，Phase 2 提供显式设置并可接桌面环境 hints。

参考：[Wayland and Qt](https://doc.qt.io/qt-6/wayland-and-qt.html)、[High DPI](https://doc.qt.io/qt-6/highdpi.html)。

# 10. Desktop Architecture

```text
main.cpp / AppEnvironment
  ├── SessionStore ─────────────── token/keyring + auth state
  ├── ApiClient ───────────────── QNetworkAccessManager + JSON + errors
  │     ├── SseStream             incremental parser/retry
  │     └── CacheStore            memory + bounded SQLite (Phase 3)
  ├── Domain stores/models
  │     ├── DashboardStore / WatchlistModel
  │     ├── StockDetailStore / ChartSeriesModel
  │     ├── PortfolioStore
  │     └── ... added per phase, never speculative
  ├── QML presentation
  │     ├── shell/navigation
  │     ├── design tokens/controls/motion
  │     └── pages
  └── rendering
        └── ChartItem (Phase 7 QSG; QRhi only if benchmark forces it)
```

一条原则贯穿：Store 表示远端资源状态，不成为第二业务核心。状态统一为 `idle/loading/ready/refreshing/stale/error`，同时保留 last-good data 和 safe error。每个 store 只暴露 UI 所需 command 与 model，不把 QNetworkReply 或原始数据库概念暴露给 QML。

不引入依赖注入框架、service locator、Redux clone、repository interface-per-class 或通用 plugin system。`main.cpp` 组装少量长生命周期对象已经足够。

# 11. Proposed Repository Structure

```text
stock-monitor/
├── backend/                    # unchanged business core
├── frontend/                   # retained Web client
├── frontend-ios/               # retained mobile Web client
├── packages/shared/            # retained TypeScript sharing
├── desktop/
│   ├── CMakeLists.txt
│   ├── src/
│   │   ├── main.cpp
│   │   ├── app/                # AppEnvironment, SessionStore
│   │   ├── network/            # ApiClient, SseStream, ApiError
│   │   ├── models/             # only actual QAbstract* models
│   │   ├── stores/             # page/domain remote state
│   │   ├── cache/              # Phase 3 SQLite cache
│   │   ├── platform/           # Phase 11 notifications/tray/xdg
│   │   └── rendering/          # Phase 7 ChartItem/geometry
│   ├── qml/
│   │   ├── StockMonitor/
│   │   │   ├── Main.qml
│   │   │   ├── shell/
│   │   │   ├── pages/
│   │   │   ├── components/
│   │   │   ├── controls/
│   │   │   ├── theme/
│   │   │   ├── motion/
│   │   │   └── charts/
│   │   └── playground/         # Phase 2 Design System Playground
│   ├── assets/                 # icons/fonts only with license metadata
│   ├── tests/
│   │   ├── unit/
│   │   ├── qml/
│   │   ├── contract/
│   │   └── benchmarks/
│   └── packaging/arch/         # created only Phase 13
└── docs/qt-desktop-architecture-audit.md
```

不用先创建所有空目录。每个 Phase 只创建实际用到的最小子集。QML 使用 `qt_add_qml_module` 编入资源，避免运行时依赖源码目录；参考 [Building a QML application with CMake](https://doc.qt.io/qt-6/cmake-build-qml-application.html)。

# 12. C++ / QML Boundary

| QML owns | C++ owns |
|---|---|
| layout、visual state、binding | HTTP/SSE、auth header、TLS policy |
| controls、focus/hover/pressed | JSON validation/mapping、stable error codes |
| navigation/page transitions | QAbstractListModel/QObject data models |
| theme/material/motion tokens | SQLite/cache eviction/versioning |
| small presentation formatting | large series transform/decimation |
| visible sorting/filtering of small lists | server-side query construction for large/paged lists |
| chart overlay/crosshair labels | hit-test index、geometry、QSG renderer |
| loading/empty/stale/error presentation | platform notification/tray/keyring integration |

禁止在 QML JavaScript 里实现估值、Mood、portfolio accounting、SSE parser、token refresh、cache schema 或大数组转换。也不把每个纯值对象都做成 QObject；列表行可用 role/value types，只有需要 signals/lifetime 的对象才 QObject。

# 13. Networking / State / Cache Architecture

## 13.1 API client

- 全应用一个 `QNetworkAccessManager`，由 UI thread 持有；启用系统 proxy/TLS defaults，不忽略 `sslErrors`。
- `ApiClient` 输入 method/path/query/body/expected type，统一添加 `Accept: application/json`、Bearer、request id；只允许 production `https://`，开发模式仅允许显式 loopback HTTP。
- `QJsonDocument/QJsonObject/QJsonArray` 足够；先写小而明确的 mapper + required-field checks，不添加 JSON 第三方库。
- HTTP 401：暂停新请求 → 尝试一次 refresh（Phase 3 token lifecycle 后）→ 成功重放一次；失败清 keyring/session/cache-private data 并回登录页。禁止无限 retry。
- 网络/5xx：只对幂等 GET 使用带 jitter 的 bounded retry；POST mutation 不自动重放，除非 endpoint 有 idempotency key。
- 取消：页面离开取消无用 reply；mutation 和 server job 不因 UI 取消而谎称服务端已停止。

## 13.2 SSE / WebSocket

用 `QNetworkReply::readyRead` 增量读取，维护跨 chunk buffer，支持 `event:`、多行 `data:`、comment heartbeat、空行 flush、UTF-8 尾片段、未知事件忽略和 terminal event。现有 React parser 位于 `frontend/src/features/ai-chat/api/stream.ts`，realtime parser 位于 `frontend/src/realtime.ts`；Desktop 测试 fixtures 应复用其事件语义，而不是复制 TypeScript 代码。

WebSocket 暂不使用。若未来服务端确实新增双向 endpoint，再加入 Qt WebSockets；不要仅因“桌面应用通常用 WS”而部署一套新协议。

## 13.3 Models / stores

- `QAbstractListModel`：watchlist、news、positions、messages、options rows 等虚拟化列表。
- QObject value/store：session、dashboard summary、selected stock、connection state。
- C++ singleton：Theme 不需要；设计 tokens 应为 QML singleton。`SessionStore`/`AppEnvironment` 可注册为只读 singleton instance。
- 每个 request 使用 generation/request token，旧 reply 不得覆盖新 selection。
- list delta 按 stable id/symbol 定位；只发精确 `dataChanged/rowsInserted/rowsRemoved`，不在每个 tick resetModel。

## 13.4 Local cache

采用三级最小模型：

1. memory cache：所有 session 热数据；
2. Qt Network disk cache：图片/可安全 HTTP assets（服务端 cache header 合适时）；
3. SQLite (`Qt Sql`)：Phase 3 后只缓存 JSON response metadata、近期历史 bars 和 last-good read models。

SQLite 建议只有 `cache_entries(key, schema_version, etag, fetched_at, expires_at, last_accessed_at, payload)` 与按需 `chart_bars(symbol, interval, timestamp, o,h,l,c,v, data_version)`；不要镜像 server 表。目录使用 `QStandardPaths::CacheLocation`，大小初始 256 MiB，LRU 清理至 80%，启动异步/空闲清理。schema 不兼容直接清 cache，不做复杂迁移。logout 清 user-private entries；AI/IBKR/credential 默认不落 SQLite。

`QSettings` 只保存 base URL profile、theme、window geometry、motion/transparency、快捷键等非 secret；参考 [QSettings](https://doc.qt.io/qt-6/qsettings.html)。

# 14. Design System Architecture

采用 **Qt Quick Controls Basic + StockMonitor 自有 controls/tokens**。Qt 官方说明 Basic style 轻量且可在任何平台运行，适合完全自定义；不继承 Material/Universal 后再与其内部 metrics 对抗。参考 [Styling Qt Quick Controls](https://doc.qt.io/qt-6/qtquickcontrols-styles.html)。

QML singleton tokens：

```text
Theme.color.{canvas,surface,elevated,textPrimary,textSecondary,accent,
             positive,negative,warning,separator,focus}
Type.{display,title,body,caption,monoNumeric}
Space.{2,4,6,8,12,16,20,24,32}
Radius.{small,medium,large,pill}
Elevation.{none,raised,floating}
```

- 金融密度：8px 基础网格，但表格 row height/column density 有 compact/comfortable 两档；数字使用 tabular figures，可复制、可键盘选中。
- Material：多数 surface 用实色 + 1px separator；半透明只用于 sidebar/header/sheet，避免多层 blur。
- Shadow：少层、宽而低 alpha；不能用 shadow 代替 hierarchy。
- Dark first，不把 light mode 的 token 写死进组件；Phase 2 Playground 同时展示 dark/light/high-contrast/reduced-transparency。
- Controls 必须覆盖 default/hover/pressed/focus/disabled/selected/error/loading；pointer 和 keyboard 同等可用。

# 15. Motion Architecture

`qml/StockMonitor/motion/Motion.qml` 为 singleton：

```text
fast = 90ms       normal = 180ms      slow = 300ms
standard = OutCubic
emphasized = OutQuart
springSoft = SpringAnimation(spring≈2.2, damping≈0.28)
springSnappy = SpringAnimation(spring≈3.6, damping≈0.36)
```

具体参数必须在 Phase 2 真机 60/120/165Hz Playground 调整；上值是起点，不是品牌定律。实现选择：

- hover/press/focus：`Behavior` + Color/NumberAnimation，按压 60–90ms，位移/缩放极小；
- navigation：`StackView`/显式 enter-exit transitions，位移 + opacity，不做全屏大 blur；
- list insert/remove/move：ListView transitions；
- expand cards/sidebar：animate transform/opacity，避免持续动画 layout-heavy width/height；
- spring：Qt Quick `SpringAnimation`/`SmoothedAnimation`，参考 [SpringAnimation](https://doc.qt.io/qt-6/qml-qtquick-springanimation.html)；
- number transition：保留数值语义，短滚动/交叉淡化；realtime 高频更新做 coalescing，不每 tick 从零动画；
- shared element：Qt 没有应被全局依赖的通用 hero primitive；Phase 2 只做一个受控 overlay prototype，Phase 4 不以它为导航前提。

120Hz 不是把 duration 除以二；动画必须 time-based、可中断、无 JS frame timers。reduced motion 下保留状态反馈但将大位移/弹簧改为短 opacity 或 immediate。

# 16. Chart Architecture

## 16.1 当前 Web 证据

`frontend/src/TechnicalChart.tsx` 使用 lightweight-charts 的 Candlestick/Histogram/Line + SVG drawing overlay；`Portfolio.tsx`、`PortfolioAnalysis.tsx`、`MacroFundamentals.tsx`、`Options.tsx` 也使用 lightweight-charts；行业/Mood/compare/AI rich content 的小图主要是 SVG。Desktop 需要重做 renderer，但服务端已经提供 candles、volume、MA、zones、events、portfolio cost 等数据。

## 16.2 GPU roadmap

| Stage | Implementation | Use | Exit criterion |
|---|---|---|---|
| Phase 2–4 | QML Rectangle/Text + Qt Quick Shapes for tiny sparklines | dashboard micro charts, <=200 points | frame budget不满足或需要 hit test |
| Phase 6 | C++ data transform + simple QML overlay | stock overview preview | 完整 K-line interaction 开始 |
| Phase 7 baseline | custom `QQuickItem::updatePaintNode` + `QSGGeometryNode` | candle/line/volume/indicators；批次 geometry | 10k–100k visible primitives benchmark |
| Phase 7 interaction | C++ viewport/index/hit test；QML crosshair/tooltip | pan/zoom/selection/annotations | interaction latency > budget |
| Later only | isolated `QSGRenderNode` or QRhi adapter | very large heatmap/compute/custom pipeline | profiler证明 QSG batching 仍不足 |

数据路径：server ranged history → local SQLite segment cache → C++ series model/decimator → QSG geometry；viewport 变化只重建 visible geometry。蜡烛 body/wick、volume、line/area、grid 分独立 material/batch；文本/tooltip 留 QML。命中用时间索引二分搜索，annotations 保存本地 presentation metadata，业务信号仍来自 server。

QRhi 的兼容风险使它只能被隔离在 `desktop/src/rendering/rhi/` 且有 QSG fallback；Phase 7 前严禁创建该目录。QQuickPaintedItem/Canvas 可用于 prototype/小图，不作为高频 K-line 最终 renderer，避免 CPU raster + texture upload。

# 17. Security Model

1. **Transport**：production base URL 仅 HTTPS；使用系统 CA，绝不调用 `ignoreSslErrors()`，不做脆弱证书 pinning。CORS 与 native client 无关。
2. **Auth**：login/password 只发 VPS；access token 放 memory，refresh token（实现后）放 OS credential store。推荐 `qtkeychain-qt6`（BSD-3-Clause；Linux 使用 Secret Service，Windows/macOS 有相应后端）；若用户拒绝第三方，Phase 3 可先做 Linux-only `libsecret` adapter，但会增加平台分支。
3. **At rest**：token 不进 QSettings/SQLite/log/core dump；logout 删除 keyring entry、私有 cache 和 memory models。无可用 Secret Service 时 fail closed 或提供“仅本次运行”，不明文 fallback。
4. **Server secrets**：provider、DB、Redis、JWT、IBKR proxy/credential encryption keys 永不进入 package/config UI。
5. **IBKR**：Desktop 只调用 `/api/ibkr/*`。所有真实 IBKR 流量继续由 VPS `socks5h://127.0.0.1:10808` fail-closed；不得在桌面实现 direct fallback。
6. **RBAC/ownership**：服从 `/auth/me` role 和 server 403；UI 隐藏不是 authorization。每个 local cache key 包含 server profile + user subject。
7. **Logging**：只记录 method、redacted path template、status、duration、request id；去掉 Authorization、password、AI private content、account identifiers。
8. **Rich content**：AI markdown/rich blocks 用原生受控 renderer；外链交给系统 browser 并显示目标域，不执行 HTML/JS。

发布 Desktop 前必须解决的现状：`backend/app/auth.py` 的 JWT default 和 `backend/app/main.py` 的 admin password default。它们不是 Desktop 自身 bug，但可分发登录客户端会扩大风险面。

# 18. Testing Strategy

| Layer | Tool / location | Minimum evidence |
|---|---|---|
| C++ unit | Qt Test + CTest, `desktop/tests/unit/` | JSON mapper、SSE chunk boundary、retry、model delta、cache eviction |
| QML unit | Qt Quick Test, `desktop/tests/qml/` | control states、keyboard/focus、navigation、reduced motion |
| API contract | Qt Test + checked fixtures/OpenAPI, `desktop/tests/contract/` | auth/dashboard/research/error/SSE shapes；unknown additive fields tolerated |
| Backend compatibility | existing `backend/tests/` + narrow contract tests | Web response compatibility、ownership、freshness、pagination |
| Visual regression | deterministic QML screenshot harness | Playground + key pages at 1x/1.5x/2x, dark/light/high contrast；small tolerance |
| Integration | Weston headless + real Wayland desktop smoke | launch/login/mock API/SSE reconnect/window resize |
| Performance | QTest benchmark, QML Profiler, `QSG_RENDER_TIMING`, perf/heaptrack/hyperfine | startup/RSS/frame time/chart/large list/network count |
| Packaging | clean `makepkg`, `namcap`, desktop/appstream validators | install/run/uninstall paths，无 undeclared deps |

每个非平凡 parser/state/cache 逻辑至少留一个可运行 check。测试不直接访问付费 provider 或生产 secrets；HTTP/SSE 使用本地 fixture server。视觉测试不能取代 accessibility tree/键盘测试。性能回归记录硬件、Qt、compositor、DPR、refresh rate 和 build type，否则数字不可比较。

# 19. Development Dependencies

## 19.1 CachyOS / Arch packages

Phase 1 最小开发环境：

```bash
sudo pacman -S --needed base-devel cmake ninja \
  qt6-base qt6-declarative qt6-wayland qt6-tools
```

Phase 3/7/13 按需追加，不应在 Phase 1 一次装全：

```bash
sudo pacman -S --needed qtkeychain-qt6 qt6-svg qt6-shadertools \
  desktop-file-utils appstream
```

可选开发/诊断工具：

```bash
sudo pacman -S --needed clang clazy gdb qtcreator gammaray \
  heaptrack valgrind perf hyperfine weston wayland-utils
```

这些包名已通过当前 CachyOS/Arch pacman metadata 验证。`qt6-websockets` 只有后端新增真实 WS 后再装。`qtcreator` 自身会拉入 Qt WebEngine，但应用 runtime 不因此依赖 WebEngine；不想要这组额外包可只用编辑器 + CMake/Ninja。

## 19.2 Runtime / build / optional

- Runtime Phase 1：`qt6-base`、`qt6-declarative`、Wayland 环境下 `qt6-wayland`。
- Runtime Phase 3：`qtkeychain-qt6`；Qt Sql/Network/DBus 来自 `qt6-base`。
- Runtime Phase 7：仅实际使用 SVG/shader 时才依赖 `qt6-svg`/`qt6-shadertools`。
- Build：`base-devel`、`cmake`、`ninja`、`qt6-tools`。
- Optional developer：clang/clazy、gdb、Qt Creator、GammaRay、heaptrack/valgrind/perf/hyperfine、Weston/wayland-utils。

## 19.3 Arch packaging plan

Phase 13 才创建 `desktop/packaging/arch/PKGBUILD`。遵循 [Creating packages](https://wiki.archlinux.org/title/Creating_packages) 与 [PKGBUILD](https://wiki.archlinux.org/title/PKGBUILD)：源码构建、明确 `depends/makedepends/checkdepends`、`cmake --install` 到 `$pkgdir`、不下载未校验 blob、不写 `/usr` 外的包内状态。

目标安装：

```text
/usr/bin/stock-monitor
/usr/lib/stock-monitor/                 # only if non-standard private runtime files exist
/usr/share/applications/com.jiale.StockMonitor.desktop
/usr/share/icons/hicolor/.../apps/com.jiale.StockMonitor.*
/usr/share/metainfo/com.jiale.StockMonitor.metainfo.xml
/usr/share/licenses/stock-monitor/...   # after project license is decided
```

当前仓库没有 `LICENSE` 文件，这是 Phase 13 blocker；必须先由项目所有者选择许可证。Arch debug package 采用 makepkg 的标准 debug option，不自写 strip 脚本。版本来自单一 CMake/project tag，不从运行中后端版本猜。

# 20. API Migration Matrix

| Feature | Existing Endpoint | Reuse | Modify | New Endpoint | WS/SSE | Priority |
|---|---|---:|---|---|---|---|
| Phase 1 health/auth | health/readiness/auth login/me | Yes | none | none | none | P0 |
| Dashboard | dashboard + realtime SSE | Yes | ETag/freshness later | none | existing SSE | P0 |
| Watchlist | watchlist + securities search | Yes | none | none | market SSE | P1 |
| Stock detail | company/fundamentals/statements/technical/research | Yes | typed schemas, range/layers | generic research company overview only if measured | existing market SSE | P1/P2 |
| Chart history | research prices/history + technical | Yes | ETag/range/cursor | none initially | no | P1 |
| Portfolio | portfolio summary/performance/health/etc | Yes | freshness/ETag | none initially | task stream optional | P1 |
| IBKR | ibkr overview/records/sync | Yes | status freshness | none | task stream recommended | P2 |
| News | news market/company/detail | Yes | consistent pagination/ETag | none | summarize task events optional | P1 |
| Macro/Industry/Options/Mood | current domain routes | Yes | ETag, align refresh to data cadence | none | only task status optional | P2 |
| Discovery | discovery routes | Yes | active run backoff | none | task stream recommended | P2 |
| AI Chat | conversation CRUD + POST-SSE | Yes | none required | none | existing SSE | P1 |
| AI memory/decisions | typed current routes | Yes | none | none | no | P2 |
| Unified async tasks | separate job status GETs | Yes fallback | common status envelope | `/api/tasks/stream?ids=` | SSE | P2 after measurement |
| Authentication | auth login + long JWT | transitional | access/refresh/revoke | `/api/auth/refresh`, `/sessions` | no | P0 before public beta |
| Error contract | mixed HTTP text/domain JSON | Yes initially | stable envelope | none | applies to SSE error | P1 incremental |
| OpenAPI client | `/openapi.json` 112 concrete schemas/310 ops | validate | type important data | none | n/a | P2 |

OpenAPI strategy：Phase 1 手写 4 个 tiny DTO；Phase 3 在 CI 保存/compare 所用 endpoint schema；只有关键接口都具备具体 `response_model` 且生成器输出经过 review 后，才考虑生成 DTO。生成 network runtime、业务 store 或 QML API 属于过度生成，应避免。

# 21. Desktop Dependency Matrix

| Dependency | Why | Required | Alternative | License | Arch Package |
|---|---|:---:|---|---|---|
| Qt Core/Gui/Network/Sql/DBus | app/network/cache/platform | Yes | none sensible | LGPL-3.0/GPL-3.0/commercial | `qt6-base` |
| Qt Qml/Quick/Controls/Layouts/Quick Effects | native UI/scene graph | Yes | Qt Widgets lowers target quality | LGPL-3.0/GPL-3.0/commercial | `qt6-declarative` |
| Qt Wayland client plugin | Wayland-first | Linux runtime | xcb fallback | LGPL-3.0/GPL-3.0/commercial | `qt6-wayland` |
| QtKeychain | secure cross-platform token store | Phase 3 recommended | libsecret-only adapter / session-only | BSD-3-Clause | `qtkeychain-qt6` |
| Qt SVG | licensed vector assets | Optional | QML Path/PNG | LGPL-3.0/GPL-3.0/commercial | `qt6-svg` |
| Qt ShaderTools | baked custom shaders | Optional Phase 7 | standard scene graph materials | LGPL-3.0/GPL-3.0/commercial | `qt6-shadertools` |
| Qt WebSockets | only future WS | No now | QNetworkReply SSE | LGPL-3.0/GPL-3.0/commercial | `qt6-websockets` |
| SQLite | bounded cache | Phase 3 | filesystem JSON (worse querying/eviction) | Public domain | transitively used by Qt/`sqlite` |
| CMake | build/install/package config | Build | none | BSD-3-Clause | `cmake` |
| Ninja | fast deterministic builds | Build recommended | Make | Apache-2.0 | `ninja` |

未选择：Boost、nlohmann/json、RxCpp、SQLite ORM、DI framework、chart library、WebEngine、animation library。Qt + standard library 已覆盖 Phase 1–7 的已知需求。

# 22. Performance Budget

基准机需记录 CPU/GPU、Wayland compositor、DPR、刷新率。以下 TARGET 是 release build 的通过线；STRETCH 是优化方向，不是 Phase 1 blocker。

| Metric | TARGET | STRETCH | Measurement |
|---|---:|---:|---|
| cold startup to interactive shell | <1.5s | <0.8s | hyperfine + app marker，网络不计 |
| warm startup | <0.8s | <0.4s | same |
| first cached Dashboard | <0.5s after shell | <0.2s | QElapsedTimer |
| idle CPU, connected SSE | <1% one core equivalent | <0.3% | 5min perf sample |
| idle RSS after Dashboard | <180 MiB | <120 MiB | `/proc`/heaptrack |
| normal frame p95 @120Hz | <8.3ms | <6ms | QML profiler/render timing |
| worst interaction frame p99 | <16.7ms; none >33ms | <10ms | same |
| input-to-crosshair response | <16ms | <8ms | timestamp instrumentation |
| window resize smooth frames | >95% within refresh budget | >99% | compositor capture/render timing |
| list scroll | 10k logical rows, only visible delegates, p95 <8.3ms | 50k | benchmark fixture |
| initial chart | 5k candles <100ms load, frame p95 <8.3ms | 20k <100ms | Chart benchmark |
| large chart viewport | 100k cached bars, pan p95 <8.3ms after decimation | raw 100k | Phase 7 only |
| active Overview HTTP requests | <30 GET/h + 1 SSE | <15 GET/h | client metrics |
| SSE connections | 1 market + 1 active AI maximum | same | connection registry |
| reconnect storm | max 1 attempt/30s after backoff | same | fault test |
| authenticated shell transfer | <1 MiB excluding images/history | <500 KiB | network metrics |
| local cache | <=256 MiB, cleanup to <=205 MiB | <=128 MiB | cache unit/integration |

165Hz 的单帧预算约 6.06ms；并非所有复杂页面都必须锁满 165fps，但输入、hover、scroll、resize 不应被 60Hz timer 或主线程 JSON 工作人为限制。

# 23. Phase-by-Phase Development Plan

## Phase 0 — Architecture Audit

- **Objective**：完成当前仓库、API、调用链、placement、Qt/Arch、性能与路线审计。
- **Files expected to be added**：`docs/qt-desktop-architecture-audit.md`（本文）。
- **Existing files expected to change**：无。
- **Backend changes**：无。
- **Desktop changes**：无 `desktop/`。
- **Dependencies**：只读本机工具与官方文档。
- **Risks**：生产配置/流量未读取；动态运行状态可能不同于仓库。
- **Tests**：导入 FastAPI OpenAPI；静态 route/frontend/model/task inventory；核对 pacman metadata。
- **Acceptance Criteria**：25 节齐全；真实路径可追溯；279/310 inventory 统计可复现；无生产代码改动。
- **Do not proceed until**：用户明确发送“开始 Phase 1”。

## Phase 1 — Qt Foundation

- **Objective**：Qt project builds；Wayland launch；native navigation shell；可配置 dev/prod base URL；读取 health/readiness，完成 login/me；无 WebView。
- **Files expected to be added**：`desktop/CMakeLists.txt`、`desktop/src/{main.cpp,app/AppEnvironment.*,network/ApiClient.*,app/SessionStore.*}`、`desktop/qml/StockMonitor/{Main.qml,shell/AppShell.qml,pages/ConnectionPage.qml}`、最小 `desktop/tests/unit/`。
- **Existing files expected to change**：仓库根 README 仅增加 build/run 入口；根 Makefile 可选增加 `desktop-*` targets，非必需。
- **Backend changes**：无。
- **Desktop changes**：最小 C++/QML module、QNAM、health/auth DTO、错误/loading 状态、3 个占位 navigation destinations。
- **Dependencies**：qt6-base/declarative/wayland/tools、CMake、Ninja；不加 QtKeychain/Sql/WebSockets/ShaderTools。
- **Risks**：生产 base URL/TLS 配置、QML module/resource 路径、Wayland/xcb 差异。
- **Tests**：C++ health/login JSON mapper；mock HTTPS/API；Wayland launch smoke；keyboard navigation；`ctest`。
- **Acceptance Criteria**：`stock-monitor-desktop` release 编译；`QT_QPA_PLATFORM=wayland` 启动；无 WebEngine；连接 dev/prod health；登录并显示 `/auth/me`；错误可恢复；X11 session 可启动；无业务逻辑复制。
- **Do not proceed until**：以上全部通过且 architecture 没有被页面需求绑死；不得用假 Dashboard 掩盖连接失败。

## Phase 2 — Design System

- **Objective**：先建立可验证的主题、controls、typography、material、focus 和 motion playground。
- **Files expected to be added**：`desktop/qml/StockMonitor/{theme,controls,motion,playground}/`，token/controls 的 QML tests 和 screenshot harness。
- **Existing files expected to change**：Phase 1 shell 只改用正式 controls/tokens。
- **Backend changes**：无。
- **Desktop changes**：dark/light/high-contrast/reduced-motion/transparency；button/input/menu/sidebar/table row/card/sheet/tooltip/loading/empty/error；motion tokens。
- **Dependencies**：现有 Qt；SVG/ShaderTools 只有实际 asset/effect 需要才加入。
- **Risks**：过度 blur、模仿 macOS 而破坏 Linux、视觉值散落、focus/accessibility 被自绘吃掉。
- **Tests**：QML state/keyboard/accessibility properties；1x/1.5x/2x screenshots；60/120/165Hz 手感与 profiler。
- **Acceptance Criteria**：Playground 覆盖所有 control states；无 magic color/spacing 跨组件；键盘完整；reduced motion 生效；frame p95 达预算。
- **Do not proceed until**：控件/页面作者无需自定义一套 hover/press/focus/motion 才能工作。

## Phase 3 — Data Infrastructure

- **Objective**：完整 API/auth/model/store/SSE/cache/retry/offline 基础，供后续页面复用。
- **Files expected to be added**：`desktop/src/network/{SseStream,ApiError,RequestHandle}.*`、`desktop/src/cache/CacheStore.*`、实际需要的 models/stores、contract fixtures；若做 token lifecycle，则新增后端 auth session model/schema/migration/tests。
- **Existing files expected to change**：`backend/app/{auth.py,main.py}`、`backend/app/api/auth_routes.py`（安全门槛范围内）；`desktop/CMakeLists.txt`。
- **Backend changes**：生产默认 secret/password fail-closed；access/refresh/revoke session，旧 access Bearer 兼容迁移。其它业务 API 不动。
- **Desktop changes**：QtKeychain、401 single-flight refresh、SSE parser、memory + 256MiB SQLite cache、offline/stale、request cancellation/generation guard。
- **Dependencies**：Qt Sql、`qtkeychain-qt6`；不加 ORM/JSON/Reactive framework。
- **Risks**：token rotation/replay、明文 fallback、cache cross-user leakage、旧 reply overwrite、SSE chunk edge cases。
- **Tests**：auth expiry/rotation/revoke/logout；no-keyring session-only；SSE arbitrary chunks/UTF-8/multiline/reconnect；cache TTL/version/LRU/user isolation；API contract tests。
- **Acceptance Criteria**：token 不在文件/QSettings；断网显示 stale age；恢复只 replay safe GET；SSE 不丢/重放 terminal；cache 可整体丢弃重建；Web auth 仍兼容。
- **Do not proceed until**：安全测试与 backend migration upgrade/downgrade/upgrade（PostgreSQL）通过；任何 credential 明文 fallback 必须移除。

## Phase 4 — Dashboard

- **Objective**：第一个真实业务页，验证集成、密度、responsive layout、cards/tables/micro charts 和 realtime updates。
- **Files expected to be added**：`DashboardStore.*`、`WatchlistQuoteModel.*`、`qml/pages/DashboardPage.qml`、Dashboard components/tests。
- **Existing files expected to change**：shell navigation；不改 React。
- **Backend changes**：无；复用 `/dashboard` + market SSE。只在缺 freshness 的实证阻塞时做 additive field。
- **Desktop changes**：last-good dashboard、market status、watchlist quote cards/table、event/alert summary、SSE coalescing。
- **Dependencies**：Phase 1–3 only；小图先 QML Shapes。
- **Risks**：照搬 Web、每 tick reset model、首屏请求爆发、低数据状态不明确。
- **Tests**：empty/partial/stale/error；100 symbols delta；resize/DPR；SSE reconnect；request count/frame budget。
- **Acceptance Criteria**：首屏请求受控；价格更新不重置列表；keyboard/HiDPI/Wayland 流畅；常驻 <30 GET/h + 1 SSE；明确 source/freshness。
- **Do not proceed until**：Dashboard 达到性能预算并证明 store/control 基础可复用。

## Phase 5 — Watchlist

- **Objective**：原生自选、证券搜索、分组、排序、过滤和实时价格。
- **Files expected to be added**：`WatchlistStore.*`、`SecuritySearchModel.*`、`WatchlistPage.qml`、search/group controls/tests。
- **Existing files expected to change**：Dashboard/open-stock navigation；shared Desktop models only。
- **Backend changes**：无，复用 watchlist/securities/stock-management/groups。
- **Desktop changes**：virtualized list、debounced search、optimistic UI 仅用于可回滚 mutation、SSE subscription set。
- **Dependencies**：无新增。
- **Risks**：symbol provider mapping 被客户端猜测、排序导致实时更新跳动、mutation 重放。
- **Tests**：international symbols、duplicate/add/remove rollback、10k fixture scroll、keyboard multi-column navigation。
- **Acceptance Criteria**：不猜 Yahoo/Finnhub symbol；最多一个 search request in flight；列表无全 reset；所有 mutation server-authoritative。
- **Do not proceed until**：搜索/分组/实时更新和失败回滚均通过。

## Phase 6 — Stock Detail

- **Objective**：公司资料、quote、fundamentals、statements、valuation、technical summary、news/SEC 的 desktop-native workspace；验证 aggregation 是否真的需要。
- **Files expected to be added**：`StockDetailStore.*`、领域子 models、`StockDetailPage.qml` 与 panels/tests。
- **Existing files expected to change**：watchlist/dashboard navigation；若测量成立，`backend/app/research/{router,service,schemas}.py` 及 focused tests。
- **Backend changes**：默认无；若 5+ 重复 DB calls/明显 latency，新增 generic research company overview 聚合，调用现有 gateway，不复制 service。
- **Desktop changes**：lazy tabs/panels、visible-only requests、cached last-good、basic chart preview。
- **Dependencies**：无新增。
- **Risks**：巨大 payload、多个 panel 同时拉取、legacy/research shape 混用、temporary snapshot 生命周期。
- **Tests**：international/non-US/ETF/data-insufficient；request trace；tab cancellation；schema/freshness；aggregation compatibility if added。
- **Acceptance Criteria**：每个 panel source/freshness 清晰；首屏只取可见数据；未证明前不新增 aggregation；Web 不受影响。
- **Do not proceed until**：有实测 request/latency 报告决定“保留并行 REST”或“增加一个聚合 endpoint”。

## Phase 7 — Native Chart Engine

- **Objective**：可交互 K-line/line/volume/indicators/crosshair/zoom/pan/hit testing/selection/annotations，达到性能预算。
- **Files expected to be added**：`desktop/src/rendering/{ChartItem,ChartGeometry,Viewport,HitIndex}.*`、`qml/charts/`、fixtures/benchmarks。
- **Existing files expected to change**：StockDetail/Portfolio chart adapters；CMake。
- **Backend changes**：仅 bounded range/ETag/layer filters，若 Phase 6 证据需要；不改指标公式。
- **Desktop changes**：QQuickItem + QSGGeometryNode renderer、C++ transforms/decimation、QML overlay/a11y summary。
- **Dependencies**：Qt scene graph；不直接用 QRhi/GuiPrivate。
- **Risks**：render-thread ownership、DPR、geometry churn、text overdraw、GPU driver differences、accessibility of graphical data。
- **Tests**：5k/20k/100k datasets；60/120/165Hz；Vulkan/OpenGL fallback；resize/DPR；hit accuracy；memory leak；textual chart summary。
- **Acceptance Criteria**：5k initial <100ms；pan/crosshair frame/input budgets；无 UI-thread large transforms；QSG resources obey render-thread lifecycle；fallback/empty state可靠。
- **Do not proceed until**：只有 profiler 证明 QSG baseline 不足，才提出独立 QRhi ADR；否则禁止 `Qt::GuiPrivate`。

## Phase 8 — Portfolio / IBKR

- **Objective**：持仓、绩效、归因、健康、策略、ledger、analysis jobs 与 IBKR read/sync workspace。
- **Files expected to be added**：Portfolio/IBKR stores/models/pages、job status component、chart adapters/tests。
- **Existing files expected to change**：navigation；可选 backend common task event route及 tests。
- **Backend changes**：复用现有 portfolio/IBKR；仅测量证明 polling 负担时添加 generic task SSE。
- **Desktop changes**：currency/source/coverage-aware views、paged records、job recovery、sensitive-data memory policy。
- **Dependencies**：无新增。
- **Risks**：金额/币种语义、IBKR authority、CPU job overlap、敏感 cache、proxy bypass temptation。
- **Tests**：多币种/缺 FX、partial coverage、ownership/403、job reconnect/terminal、IBKR unavailable；server proxy remains fail-closed。
- **Acceptance Criteria**：不在本地重算会计/估值/Monte Carlo；IBKR 零 direct traffic；金额 source/coverage 可见；jobs 不无限 polling。
- **Do not proceed until**：财务语义 fixture 与生产兼容 contract 通过，且没有 IBKR/provider secret 进入 Desktop。

## Phase 9 — Mood / News / AI

- **Objective**：Mood、新闻、AI Chat/Deep Search 的原生高密度体验与可靠 streaming。
- **Files expected to be added**：Mood/News/Chat stores/models/pages、native safe markdown/rich block renderer、citation/source panels/tests。
- **Existing files expected to change**：navigation；必要时仅 additive API schema/freshness。
- **Backend changes**：不复制 orchestrator；复用 conversation POST-SSE、memory/decision/search routes。
- **Desktop changes**：AI stream state machine、tool activity、citations、cancel/recover、news pagination/summarize state、Mood history/detail。
- **Dependencies**：不加 WebEngine；markdown 先支持当前服务端实际 subset，未知 block 安全 fallback。
- **Risks**：富文本注入、partial stream persistence、重复消息、2s status polling、超长内容性能。
- **Tests**：所有已知 SSE events、unknown event/block、cancel/network cut/recover、markdown sanitization、10k message list、citation target safety。
- **Acceptance Criteria**：无 HTML/JS execution；partial/error truthfully shown；server persisted state wins after reconnect；AI content 不默认落 local cache。
- **Do not proceed until**：与 React event fixtures 的 contract parity 通过，未知 rich content 可安全降级。

## Phase 10 — Remaining Business Features

- **Objective**：按 Business Capability Map 迁移 calendar、macro、discovery、options、industry、SEC/ownership/congress、sentiment、compare、reports、journal、decisions、settings/admin。
- **Files expected to be added**：每个被批准 capability 的 store/model/page/test；一次只做一域。
- **Existing files expected to change**：navigation、复用 controls；对应 backend route/schema 仅窄改。
- **Backend changes**：按 REQUIRED/RECOMMENDED/OPTIONAL/AVOID policy；无“大一统 Desktop API”。
- **Desktop changes**：typed/paged views，复用 chart/table/job primitives。
- **Dependencies**：原则上无；每个新 dependency 必须单独 ADR 和 package/license 验证。
- **Risks**：Phase 变成大爆炸、页面照抄 Web、低频数据被高频刷新、admin capability 越权。
- **Tests**：每域 contract/empty/stale/permission/performance；Web regression。
- **Acceptance Criteria**：每个 capability 独立完成/验收，source/freshness/coverage 保留；未迁移功能继续由 Web 提供。
- **Do not proceed until**：当前域通过后才开下一域；不要求 Phase 10 一次清空所有 Web 功能。

## Phase 11 — Desktop Integration

- **Objective**：notifications、tray、shortcuts、deep links、XDG、window integration、settings。
- **Files expected to be added**：`desktop/src/platform/`、desktop file/metainfo/icon prototypes、URL handler/settings UI tests。
- **Existing files expected to change**：main/session/settings；不正式创建 PKGBUILD。
- **Backend changes**：通知仍由 existing server event/alert detection；必要时只加 stable event id。
- **Desktop changes**：native decoration first；system move/resize；local notification dedupe；tray optional；portal-aware shortcut/deep link。
- **Dependencies**：Qt DBus/Widgets optional；desktop-file-utils/appstream validators。
- **Risks**：GNOME tray 不保证显示、Wayland global shortcuts/activation token 限制、frameless resize/accessibility regressions。
- **Tests**：GNOME Wayland + Weston + X11 fallback；multi-monitor/DPR；maximize/minimize/fullscreen；notification click/deep link；single-instance routing。
- **Acceptance Criteria**：默认 native decorations；无私有 Wayland hack；关闭窗口/托盘语义明确；缺 tray/portal 时核心 app 正常。
- **Do not proceed until**：Wayland 行为优先正确，不能为 macOS 外观牺牲 resize/focus/accessibility。

## Phase 12 — Performance & Polish

- **Objective**：以预算和 profiler 消除可测瓶颈，完成高刷新率、启动、内存、resize、网络审计。
- **Files expected to be added**：benchmark reports/scripts、performance fixtures、必要的 targeted optimizations。
- **Existing files expected to change**：只改 profiler 指向的 Desktop/有限 backend hotspot。
- **Backend changes**：仅有 query trace/metrics 证明的索引、ETag、aggregation/stream changes；schema change需 migration。
- **Desktop changes**：delegate pooling、model delta、geometry batching、lazy load、cache tuning。
- **Dependencies**：perf/heaptrack/GammaRay/QML profiler；不因优化默认上 QRhi。
- **Risks**：优化 benchmark 非真实 workload、牺牲 correctness/a11y、driver-specific hack。
- **Tests**：第 22 节全部指标，至少目标硬件 + 一套 xcb/另一 GPU smoke；长时 soak/offline/reconnect。
- **Acceptance Criteria**：所有 TARGET 达标或有用户批准的书面 exception；无不必要 polling；无持续内存增长。
- **Do not proceed until**：性能报告可复现，未达项有明确 root cause，不用“感觉流畅”代替数据。

## Phase 13 — Pacman Packaging

- **Objective**：`makepkg` 生成可安装/升级/卸载的 `stock-monitor-x.y.z-1-x86_64.pkg.tar.zst`。
- **Files expected to be added**：`desktop/packaging/arch/{PKGBUILD,.SRCINFO}`、final desktop entry/AppStream/icons/license install rules；release docs。
- **Existing files expected to change**：CMake install/export/version；root LICENSE（用户先选择许可证）；CI release job optional。
- **Backend changes**：无；绝不打包 backend。
- **Desktop changes**：release update/channel behavior 只指向版本信息，不自写 package manager。
- **Dependencies**：makepkg/base-devel、namcap、desktop-file-utils、appstream；runtime matrix 中实际使用的 Qt modules。
- **Risks**：缺 LICENSE、undeclared runtime dependency、wrong RPATH、absolute build paths、Qt rolling rebuild、secret/config 混入 package。
- **Tests**：clean chroot makepkg；namcap；`desktop-file-validate`；`appstreamcli validate`；install/run/upgrade/uninstall；package content/secret scan；debug symbols。
- **Acceptance Criteria**：package paths符合第19节；无 bundled Qt/backend/secret；Wayland launch + xcb fallback；pacman clean uninstall 不删 user data。
- **Do not proceed until**：项目许可证、app id、versioning 和 release signing policy 已由用户确认。

# 24. Risks / Unknowns

| Risk / unknown | Current evidence | Resolution gate |
|---|---|---|
| Production auth defaults是否已覆盖 | 仓库 defaults 不安全；本轮未读 VPS `.env` | Phase 3 read-only config assertion，不打印值 |
| Live API 与本地 OpenAPI drift | 本文基于当前本地 commit/worktree | Phase 1 对 dev/prod health/auth contract smoke |
| 实际 VPS request/DB load | 仅从代码频率建模，无 production metrics | Phase 4 client counters + server sampled metrics |
| Qt 6.8 minimum compile | 当前机器是 6.11.1 | CI/container 建 6.8 compile job后才正式承诺 |
| GNOME system tray | GNOME 可能无原生 tray surface | Phase 11 optional feature，不作核心导航 |
| Wayland global shortcuts | 受 compositor/portal 限制 | Phase 11 probe portal；无支持则禁用并说明 |
| blur/material portability | compositor blur 非统一 | app-local MultiEffect/opaque fallback，Phase 2 measure |
| QRhi compatibility | 官方无 source/binary guarantees | 默认不用；Phase 7 ADR + isolated fallback |
| OpenAPI type coverage | 112/310 concrete success schemas | 逐 endpoint typed；不先 codegen |
| API response size/aggregation benefit | 尚未抓真实 payload/SQL trace | Phase 6 measured decision |
| QtKeychain backend availability | Arch package存在，用户 session Secret Service 未验证 | Phase 3 detect + session-only fail-closed |
| Accessibility on GNOME/AT-SPI | 设计要求已列，实际 tree 未验证 | Phase 2 Orca/keyboard test |
| App license | 仓库没有 LICENSE | Phase 13 blocker，必须用户决定 |
| Windows/macOS | 架构保留 Qt abstraction，未建立 CI | Linux/Wayland 达标后单独扩展，不拖 Phase 1 |
| Caddy/HTTP2/public routing | Caddy 在前，nginx 反代 API；未做协议抓包 | Phase 4 network trace；不先改 deploy |

# 25. Final Recommendation

1. **是否继续使用当前 VPS Backend？** 是。它必须继续是唯一业务与数据 authority；Qt 通过 HTTPS REST/SSE 使用它。
2. **Backend 哪些地方必须修改？** Phase 1 无需改。公开 Desktop beta 前必须让 JWT/admin credential 配置 fail-closed，并提供可撤销 access/refresh session；其余 typed response、ETag、aggregation、task SSE 都按测量渐进做。
3. **哪些功能新增在本地？** 窗口/导航/布局、design/motion、QML/QSG 图表、hit testing、快捷键、OS notification、secure token storage、bounded read cache、离线 last-good 和本地展示设置。
4. **Desktop 会增加多少服务器负担？** 一条 market SSE + active AI stream，目标 <30 GET/h 的常驻 Overview；相比现 Web Overview 约 420 GET/h 定时请求，设计正确时反而可减少约 93% polling。真实值在 Phase 4 测量。
5. **Qt Quick 是否仍是最合理的 Native Desktop 技术？** 是。Qt Quick + Controls Basic + C++ models/network + scene graph 是 Wayland、高 DPI、高刷新率、自定义 motion 和未来 QSG 图表之间最平衡的方案；QRhi 不是初始基础。
6. **第一阶段到底做什么？** 只建立可编译/可启动的 `desktop/`、native shell、Wayland/X11 smoke、QNAM、health/readiness、login/me、基础 navigation/error state 和最小测试。
7. **第一阶段明确禁止什么？** 禁止 Dashboard 业务迁移、图表引擎、SQLite cache、WebSocket、QRhi、frameless window、tray/notifications、OpenAPI codegen、backend 重构、WebView、打包 backend、生产部署和 Phase 2 提前设计。

结论：**停止在 Phase 0。等待用户明确指令“开始 Phase 1”。**
