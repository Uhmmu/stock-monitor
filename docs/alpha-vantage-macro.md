# 美国宏观基本面

本模块把 Alpha Vantage 官方 REST API 的美国经济时间序列保存到
`macro_series`、`macro_observations`、`macro_sync_runs` 和 `macro_api_usage`。
前端只访问 stock-monitor 后端，不会把 API key 发送到浏览器。

## 配置

在服务端 `.env` 中配置：

```env
ALPHA_VANTAGE_ENABLED=false
ALPHA_VANTAGE_API_KEY=
ALPHA_VANTAGE_BASE_URL=https://www.alphavantage.co/query
ALPHA_VANTAGE_DAILY_REQUEST_LIMIT=25
ALPHA_VANTAGE_RESERVED_REQUESTS=3
ALPHA_VANTAGE_REQUEST_INTERVAL_SECONDS=15
ALPHA_VANTAGE_TIMEOUT_SECONDS=30
ALPHA_VANTAGE_MAX_RETRIES=3
ALPHA_VANTAGE_MACRO_SYNC_ENABLED=true
ALPHA_VANTAGE_MACRO_SYNC_HOUR_UTC=08
ALPHA_VANTAGE_MACRO_HISTORY_REFRESH_DAYS=7
```

未配置 key 时 API 和页面仍可用，会明确显示“未配置”，不会阻断应用启动。
真实 key 不得写入仓库、文档、前端 bundle、日志或错误响应。

## 数据序列与预算

首批固定同步 14 个原始序列：

- `REAL_GDP`、`REAL_GDP_PER_CAPITA`
- `TREASURY_YIELD` 的 `3month`、`2year`、`5year`、`10year`、`30year`
- `FEDERAL_FUNDS_RATE`、`CPI`、`INFLATION`
- `RETAIL_SALES`、`DURABLES`、`UNEMPLOYMENT`、`NONFARM_PAYROLL`

完整同步每个序列一次，因此最多 14 次请求。默认每日上限为 25 次，其中 3 次保留给管理员测试或手动操作，自动同步最多使用 22 次。请求严格串行，默认间隔 15 秒。每次请求都记入项目侧 UTC 日用量表；这个计数用于保护项目，不代表 Alpha Vantage 账单的绝对真值。

Celery Beat 每 10 分钟执行一次 due check，只有在配置的 UTC 小时、当天尚未成功同步且 key 已配置时才排队每日同步。打开页面不会触发上游请求。

## 数据与修订

`observation_date` 是经济指标所属日期，`last_fetched_at` 是系统抓取时间，两者不能混用。所有可解析历史行都会按 `series_id + observation_date` upsert；同一日期出现新值时更新 `value`、递增 `revision_number`，不会清空旧历史。缺失值 `.`、空字符串和 null 会被过滤，不会写成零。

单个序列失败只会让本次运行变成 `partial_success`，成功序列仍会提交，前端继续展示上次成功缓存。

## 派生指标

派生结果由 `MacroDerivedMetricsService` 在本地根据存储的原始序列计算，不额外消耗 API 调用：

- GDP 季度环比：`(本季度 / 上季度 - 1) × 100`
- GDP 同比：`(本季度 / 四季度前 - 1) × 100`
- CPI 月环比/同比：相邻 1 个月/12 个月指数的百分比变化
- CPI 三个月年化：`((本月指数 / 三个月前指数) ^ 4 - 1) × 100`
- 非农新增：本月非农总人数减上月总人数；三个月平均为最近三个月新增的平均
- 10Y-2Y、10Y-3M、30Y-5Y：长端收益率减短端收益率
- 失业率三个月均值和简化 Sahm Rule：最近三个月均值减过去十二个月内三个月均值的最低值；达到 0.50 个百分点只标记“衰退风险信号触发”，不宣布衰退

收益率曲线的“正常、趋平、倒挂、倒挂加深、倒挂修复、牛市陡峭化、熊市陡峭化”同时参考当前利差、20/60 个有效交易日前利差以及短长端方向，并在 API 中标记为 `derived`。

## API

需要登录的页面 API：

- `GET /api/fundamentals/macro/us/overview`
- `GET /api/fundamentals/macro/us/series?category=&frequency=&enabled=`
- `GET /api/fundamentals/macro/us/series/{series_key}?start_date=&end_date=&limit=`
- `GET /api/fundamentals/macro/us/series/{series_key}/explanation`
- `GET /api/fundamentals/macro/us/yield-curve`
- `GET /api/fundamentals/macro/us/sync-status`

管理员 API：

- `POST /api/admin/integrations/alpha-vantage/test`：只发一个 CPI 请求，并计入项目侧用量
- `POST /api/admin/integrations/alpha-vantage/macro/sync`：`{"mode":"full|selected","series_keys":[],"force":false}`

管理员设置页会展示 key 是否配置、今日调用、自动保护上限、最后成功同步、连接测试和手动全量同步。

## AI 上下文

`build_latest_us_macro_context()` 返回紧凑、JSON-safe 的增长、通胀、就业、利率、曲线和消费摘要，保留每个数据点的观察日期与警告。现有 Research Gateway 的 `get_market_context` 会附带 `us_macro`；报告 evidence 也会在有数据时加入一段宏观背景。不会发送完整历史序列、API key 或用户私有账户信息，也不会在没有一致预期数据时声称“超预期”。

## 排查与迁移

1. 先查看 `/api/fundamentals/macro/us/sync-status` 的 `runs`、`errors` 和 `usage`。
2. 检查服务器 UTC 时间是否进入 `ALPHA_VANTAGE_MACRO_SYNC_HOUR_UTC`。
3. 确认 key 只配置在服务端，并重启使用 backend 镜像的 `api`、`worker`、`sec-worker`、`beat`。
4. HTTP 429、网络超时和 5xx 会分类记录；无效 key 不会无限重试；完整请求 URL 和 key 不会进入日志。
5. 未来若迁移到 FRED，可保留 `macro_series`/`macro_observations` 的内部 key 和派生层，只替换 provider 与 source attribution，避免改动前端和 AI context 合约。

Alpha Vantage 页面会为部分经济序列标注底层统计机构和 FRED 取数说明；页面展示时保留 provider、source_name 和观察日期，不把 Alpha Vantage 误称为原始政府发布者。数据仅用于研究和信息展示，不构成投资建议。
