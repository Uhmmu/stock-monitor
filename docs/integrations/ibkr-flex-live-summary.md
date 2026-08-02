# IBKR Flex 真实返回总结（2026-08-01）

## 验证结论

- 生产 VPS 已启用 Flex Web Service，配置由 VPS `.env` 提供，未写入仓库。
- 请求经 `socks5h://host.docker.internal:10808` → Xray/VLESS 出口；实测出口为东京 AS2914 NTT。
- 官方 v3 两阶段调用成功：`SendRequest` 后第二次 `GetStatement` 完成。
- HTTP 状态为 200，上游累计耗时约 4.15 秒。
- 本次检查只输出标签、字段名和数量，没有输出 Token、ReferenceCode、账户号或字段值。

## 当前解析器已经归一化的区块

| 区块 | 行数 | 主要可用字段 |
| --- | ---: | --- |
| `open_positions` | 7 | `symbol`、`conid`、`position`、`markPrice`、`positionValue`、`costBasisPrice`、`costBasisMoney`、`fifoPnlUnrealized`、`percentOfNAV`、`currency`、`fxRateToBase`、`listingExchange` |
| `trades` | 242 | `tradeDate`、`dateTime`、`symbol`、`buySell`、`quantity`、`tradePrice`、`tradeMoney`、`proceeds`、`netCash`、`ibCommission`、`fifoPnlRealized`、`mtmPnl`、`orderType`、`exchange`、`currency` |
| `cash_transactions` | 55 | `dateTime`、`type`、`description`、`amount`、`currency`、`symbol`、`settleDate`、`transactionID` |
| `performance` | 262 | `reportDate`、`currency`、`total`/`totalLong`/`totalShort`、`stock`、`options`、`funds`、`cash`、`interestAccruals`、`dividendAccruals` 等分资产净值字段 |
| `account_information` | 0 | 当前 Flex 模板未返回该标签 |
| `dividends` | 0 | 实际股息数据出现在尚未归一化的股息变化标签中 |
| `fees` | 0 | 费用信息主要包含在现金报告及资金流水中 |
| `interest` | 0 | 利息信息主要包含在现金报告及净值/应计字段中 |
| `transfers` | 0 | 当前模板没有独立 `Transfer` 标签 |

空区块不等于账户没有相关活动，只表示当前解析器期待的 XML 标签没有出现。

## 已返回但尚未归一化的重要标签

| XML 标签 | 行数 | 前端价值 |
| --- | ---: | --- |
| `ConversionRate` | 12,207 | 历史每日汇率、统一基础币种折算 |
| `PriorPeriodPosition` | 1,884 | 历史持仓、持仓随时间变化 |
| `StatementOfFundsLine` | 678 | 完整资金流水、余额、借贷方向、交易关联 |
| `Order` | 233 | 历史订单、订单类型、交易所、API 订单标记 |
| `Lot` | 99 | 税务批次、成本、持有期和已实现盈亏 |
| `SymbolSummary` | 80 | 按证券汇总的活动与盈亏 |
| `ChangeInDividendAccrual` | 47 | 应计股息变化、税费、支付日 |
| `FIFOPerformanceSummaryUnderlying` | 43 | 按标的的已实现/未实现、长短期 FIFO 盈亏 |
| `SecurityInfo` | 38 | 证券元数据、ISIN/FIGI/CUSIP、交易所和币种 |
| `CashReportCurrency` | 6 | 按币种的期初/期末现金、交易、佣金、股息、利息、入出金 |
| `ChangeInPositionValue` | 4 | 期初/期末持仓价值及期间变化归因 |
| `AssetSummary` | 2 | 按资产类别汇总 |
| `ChangeInNAV` | 1 | 组合净值变化及收益归因 |
| `OpenDividendAccrual` | 1 | 尚未支付的应计股息 |

`FlexStatement` 还提供 `fromDate`、`toDate`、`period`、`whenGenerated`，应作为每次同步的元数据保存和展示。

## 正式前端前的后端准备

不要让正式前端读取 `raw XML` 或依赖 `unknown`。先建立稳定的 typed API：

1. 扩展 XML 标签映射，至少覆盖 statement metadata、NAV、cash report、positions、trades、orders、lots、funds ledger、dividends、FIFO performance、security info 和 conversion rates。
2. 区分“区块未包含”“区块存在但为空”“解析器不认识标签”，避免把数据缺口误显示为零。
3. 对金额、数量、日期、布尔值做类型转换；保留原币种金额与基础币种折算值，不能直接跨币种相加。
4. 用 `statement period + account + query` 建立幂等同步键，保存同步时间、生成时间和源报告期间；前端只读数据库快照，手动刷新才调用 Flex。
5. API 与日志统一清理 Token、ReferenceCode、账户号等敏感字段；正式前端不要返回原始 XML。
6. 对 12,207 条汇率和 1,884 条历史持仓采用分页/聚合，不把整份报告一次性发送给浏览器。

## 建议的正式前端信息架构

- **账户总览**：报告期间、净值、现金、当期盈亏、持仓数、基础币种、最后同步时间。
- **当前持仓**：证券、数量、成本、标记价、市值、未实现盈亏、NAV 占比、币种。
- **交易与订单**：成交和历史订单分开，支持日期、证券、买卖方向、账户与币种筛选。
- **资金流水**：交易资金、股息、利息、佣金、税费、入出金，提供分类汇总和明细。
- **收益分析**：NAV 变化、FIFO 已实现/未实现盈亏、按标的和资产类别归因。
- **股息**：已发生股息、应计变化、待收股息、税费和支付日。
- **多币种**：按币种现金报告及折算说明；历史汇率作为后端计算依据，不直接展示万行明细。
- **数据状态**：Flex 报告期间、生成时间、同步时间、缺失区块、未识别标签和刷新状态。

第一版正式 UI 建议先做“账户总览 + 当前持仓 + 交易/资金流水 + 同步状态”，再加入收益归因、股息和税务批次。

## 正式快照模块（2026-08-02）

- 维护结束后执行了一次新的 Flex Query，完整报告保存于持久 archive 的 `ibkr/flex/flex-report-20260802T064113Z.xml`，权限为 `0600`；后续解析、导入和页面读取均复用该文件。
- typed parser `ibkr-flex-v1` 实际解析 15,889 条记录，覆盖账户 NAV、分币种现金、当前/历史持仓、成交、订单、资金流水、股息应计、绩效、FIFO、税务批次、证券资料和历史汇率。本次没有独立 `CorporateAction` 记录，不能把其他账户活动伪装成公司活动。
- 迁移 `0044_ibkr_flex_snapshots` 新增幂等同步运行、规范化 Flex 记录及必要索引，并为证券和派生持仓增加 IBKR 权威字段。正式页面只读数据库快照，大表全部分页。
- 当前 7 条 IBKR 持仓与默认组合 7/7 匹配；1 条数量冲突及 7 条平均成本冲突已按 IBKR 纠正，无无法匹配或额外持仓。现有行情价格、技术分析、估值、新闻和 SEC 数据保持原来源。
- 正式入口为 `/ibkr`；管理员诊断入口继续保留在 `/admin/integrations/ibkr`。正式 API 使用 `/api/ibkr/*`，不返回 raw XML，不提供下单、改单或撤单。
- 生产备份位于 `/opt/stock-monitor/backups/deployments/20260802-1510-ibkr-formal`，回滚镜像标签为 `stock-monitor-{api,worker,sec-worker,beat,frontend}:pre-20260802-1510-ibkr-formal`。

## 账户分析层与全项目权威同步（0045）

### 权威边界

IBKR 是已匹配 Portfolio 持仓的数量、平均成本、成本基础、币种、持仓存在状态，以及成交、现金、股息、税费、已实现盈亏、税务批次和历史账户状态的最高事实源。项目行情系统仍是当前市场价格的权威来源。

当前持仓市值按“项目最新行情价格 × IBKR 权威数量”计算。只有项目行情完全缺失时，Portfolio 才展示 `ibkr_flex_fallback` 报告价格，并同时返回报告日期和 `price_is_report_fallback=true`；它不能伪装成实时行情，也不会反向修改数量或成本。

### 手动同步状态机

正式 `POST /api/ibkr/sync` 只创建一个后台只读同步；同一用户最多有一个 `queued/running` 运行，重复点击返回原运行。阶段为：

```text
requested → downloading → downloaded → parsing → importing
→ reconciling → rebuilding → completed / failed
```

网络请求不放进数据库长事务。XML 下载后以 `0600` 原子写入持久 archive，API 与日志不返回原始 XML、Token、完整账户号或 ReferenceCode。typed records 可先幂等导入；Portfolio 权威更新、冲突审计、现金传播、派生重建和最终成功状态使用同一数据库提交。后半段失败时运行返回 `partial_failed`，不会向用户声称同步成功。

完整的当前持仓 section 才允许关闭“上次由 IBKR 确认、但本次已不存在”的持仓；缺失或部分报告绝不批量关仓。每项数量、成本、币种或关闭变更写入 `ibkr_portfolio_authority_audits`，保存旧值、新值、来源、sync run、Flex record、匹配方法和应用结果。

同步成功会更新 Portfolio 的 IBKR 权威字段与基础币种现金，并重建派生分析。Redis 中每用户 `portfolio-authority-generation` 被精确递增，AI Tool 的私有 Portfolio 缓存键包含该代次；前端同时失效 Portfolio summary、health、interpretation、transactions、analysis history 和 IBKR 查询。Research Gateway/AI Tools 的 Portfolio summary/positions 继续共用 `build_summary`，成交历史在存在正式 IBKR 快照时优先读取 IBKR trades。

### 派生模型与计算规则

迁移 `0045_ibkr_account_analytics` 新增：

- `ibkr_normalized_cash_flows`：集中分类 deposit、withdrawal、trade settlement、dividend、withholding tax、commission、interest、margin interest、FX、broker fee、corporate action、payment in lieu 和 other；原始 code/description、规则版本和 warning 始终保留。
- `ibkr_account_daily_performance`：分离外部现金流与投资收益，保存 daily/cumulative return、drawdown、max drawdown、完整性和 calculation version。字段证据不足时保存 `NULL` 与 warning，不用差额伪造精确分项。
- `ibkr_trade_round_trips`：明确可关联的 IBKR FIFO/tax-lot 结果优先，否则使用标记为 `derived_fifo` 的 FIFO 推导；支持多次买入、部分卖出与重复开仓，不按相邻买卖配对。
- `ibkr_position_performance_daily`：保存证券日级贡献；历史价格只取 `date <= performance_date` 的项目行情，禁止 future price/look-ahead。
- `ibkr_dividend_events`：分开 accrued、received、reversed；到账汇总只统计 received，避免应计与到账重复。
- `ibkr_portfolio_authority_audits`：永久记录权威冲突应用。

当前收益恒等式按可用证据拆分。外部入金不计收益、出金不计亏损、证券结算不计外部现金流。证券本币、基础币种和 FX 贡献无法可靠拆分时返回数据缺口，不把证券价格收益与汇率收益混为一项。

### 正式只读 API

除原分页快照 API 外，0045 提供：

- `POST /api/ibkr/sync`、`GET /api/ibkr/sync/{id}`
- `GET /api/ibkr/performance/daily|monthly|attribution`
- `GET /api/ibkr/trades/round-trips`
- `GET /api/ibkr/cash-flows/summary`
- `GET /api/ibkr/dividends/summary`
- `GET /api/ibkr/fees/summary`
- `GET /api/ibkr/fx/exposure`
- `GET /api/ibkr/data-health`

所有查询按当前用户隔离，`sync_run_id` 不能跨用户读取。接口仍然没有下单、撤单、改单、转账或账户设置写操作。

### 恢复与回滚

失败运行可安全重试；同一源报告通过 hash 幂等复用，不复制 15,889 条历史事实。worker 超过两小时没有 heartbeat 的活动运行会在下一次请求前标记失败并恢复锁。数据库回滚先停止 api/worker/sec-worker/beat，使用迁移前已校验备份，再 downgrade 至 `0044_ibkr_flex_snapshots` 并切换五个回滚镜像；不得删除 archive、Redis 或持久卷。

### 生产上线验收（2026-08-02）

- 生产 PostgreSQL 已完成 `0045 → 0044 → 0045` 往返验证，当前为 `0045_ibkr_account_analytics (head)`；api healthy，worker 与 sec-worker 均可 ping，两个节点都注册 `sync_ibkr_flex_account`，beat 和 frontend 正常运行。
- 未发起新的 Flex Query。部署后复用当天现有 `0600` archive 与 sync run 1 重建派生层，得到 733 条规范化现金流、262 条账户日绩效、115 条交易闭环、43 条持仓日绩效和 48 条股息事件。
- 7 条 Portfolio 持仓全部保持 `authority_source=ibkr_flex`；市场价 7/7 来自项目行情，没有 IBKR 报告价 fallback。Portfolio 现金已传播；Research Gateway 与 AI Tools 均读取 7 条 IBKR 权威持仓，成交历史优先读取 IBKR trades。
- `/ibkr` 和 `/api/health` 公网 HTTPS 为 200，未鉴权 `/api/ibkr/overview` 为 401；最近 15 分钟 api/worker/sec-worker/beat 没有 `ERROR`、`Traceback` 或 `CRITICAL`。
- `ibkr_portfolio_authority_audits` 当前为 0：这次回填时既有 7 条持仓已经与 IBKR 一致，未发生需要落审计的字段变更。这不是审计缺失；后续同步检测到数量、成本、币种或关闭冲突时才写入。
- 迁移前备份位于 `/opt/stock-monitor/backups/deployments/20260802-1615-ibkr-account-analytics`，数据库压缩包已通过 gzip、表数和迁移版本校验，并保留源码、SHA256 与五个 `pre-20260802-1615-ibkr-account-analytics` 回滚镜像。
