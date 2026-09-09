# macOS 可读性 Goal R4 验收记录

日期：2026-09-10
范围：R4.0 总览/自选股/异动、R4.1 新闻/日历/报告、R4.2 公司研究与证券上下文
边界：计划文档只读；未修改服务端算法、数据、权限、IBKR 代理或 PAPER 边界。唯一新增客户端服务方法是复用既有只读契约 `GET /api/dashboard`（`ResearchWorkspaceService.dashboardSnapshot`），无新服务端端点。

## R4.0 — 总览、自选股与异动

- 总览重构为 PageHeader + 首屏四状态 `OverviewCoreStateStrip`（市场状态/组合回报/自选涨跌/最新异动），不滚动即可读取四类核心状态；旧的同权重双列卡片删除。
- 指数改用 `IndexMetricStrip`：名称/价格/涨跌点/涨跌百分比在同一 Grid 对齐；涨跌同时提供箭头符号、数值与可访问描述（`ChangeLabel` 重写为符号 + 数值 + accessibilityLabel，颜色不再是唯一编码）。
- 自选涨跌 breadth 由 `OverviewSummarizer` 纯函数计算（实时报价优先，回落快照；缺报价计入 unavailable 并明示），领涨/领跌单列。
- 自选股主表改为 `Table`：显式排序控件（自定义顺序=服务端 displayOrder/代码/价格/涨跌 + 升降序切换）、分组筛选、列宽、交替行背景、sticky selection、行级 context menu（打开/移动分组/提醒开关/移除）；来源与提醒状态降级为可扫读徽标。
- 阈值编辑从独立 Sheet 移入右侧 inspector（`WatchlistThresholdDraft` 内联草稿 + 校验提示），master list + detail 编辑不再弹层跳转；分组管理/新建分组保留为批量管理入口。
- 异动中心按严重度分组：需要关注（当日 ≥5%）/盘中异动/短时波动/目标价触发/其他周期；每行首句"发生了什么"（方向+幅度），调查状态（active/reporting/completed/failed 中文映射）作为徽标跟随证券；调查任务用 timeline 呈现。

## R4.1 — 新闻、日历与报告

- 新闻行标题主导（headline 两行），证券/来源/时间/AI 摘要状态为次级 metadata 行，摘要正文三行次级；AI 状态按 pending/ready/failed 区分徽标。
- 新闻详情分层：元信息（证券/来源/时间/原文外链确认）→ AI 摘要（标注"模型生成"，grouped surface）→ 原文摘要 → AI 分析，各自独立 disclosure；正文宽度受 `StockMonitorContentWidth.readable` 约束。
- 日历改为按日 agenda：日期 SectionHeader + 事件行；事件类型 = 符号 + 文字（财报/除息日/股息支付/拆股/反向拆股），影响度独立徽标，待确认/旧缓存进入首屏 summary 与行内徽标；空态明示"只覆盖已追踪证券，不是全市场"。
- 报告中心：列表搜索（标题/代码）、阅读视图含目录（markdown 1–3 级标题解析 + ScrollViewReader 锚点跳转）、复制全文、回到关联证券；"加载更多"只追加列表，不动阅读位置。

## R4.2 — 公司研究与证券上下文

- 新增统一 `CompanyHeaderView` + `CompanySummaryModel`：symbol、公司名、价格/涨跌、市场状态、自选身份、行情来源与更新时间；由 `GoalM4RouteView` 持有共享实例，基本面/财报/估值/SEC/机构持仓/技术分析六页接入；dashboard 快照一次拉取、失败仅降级公司头。
- 基本面按估值/盈利能力/成长性/资本效率/风险特征/其他分组（`FundamentalsMetricGroup` 映射服务端 label 契约），每组 `MetricGrid` + 来源摘要；数值按 label 约定格式化（百分比带符号、倍数带 ×、市值百万单位、Beta 裸值）。
- 财报季度指标改为 `FinancialMatrixTable`：指标为行、期间为列（最新在最左）、冻结左侧指标列、数字右对齐 tabular、同比仅在上年同季存在时计算并以微注标注，缺失显示"—/数据不足"而不是 0。
- 估值首屏 MetricGrid：模型适用性/共识公允价值/现价相对共识/模型分歧，先结论后展开模型信号、指标与同行对比、Graham 与其余快照字段。
- SEC 事件 tab 改为时间线（条目 → 表格/日期 → 中文摘要 → 原文链接），未映射即空态说明；13F 环比变化用箭头+数值（颜色非唯一编码）并补报告期/口径 metadata；技术分析改为图表主列 + 关键指标侧栏（最新收盘/区间高低/K 线数/持仓成本/生效提醒），操作说明降为图下 metadata。

## Route checklist（本 Goal 覆盖路由）

- 正常/空/部分缺失/stale/loading/error 状态沿用 R1 31 路由 × 7 状态矩阵；R4 六个 M3 路由与公司组路由的状态呈现改由共享组件（ResourceStateView/EmptyState/InlineError/FreshnessBadge）承担。
- 正常态证据：R4 快照基线 10 张（见下）；长中文标题、长英文标题、国际代码（1578.T）、负值、大金额、缺失值全部进入夹具数据。
- 权限：本 Goal 路由无新增管理员门槛；公司组仍受服务端自选门控（`CompanyTickerContext` 回退逻辑未动）。

## Visual / Accessibility / Motion

- `apple/Tests/VisualBaselines/R4`：11 张确定性基线 = before-overview、before-company（R4 前布局）+ after-overview/watchlist/alerts/calendar/reports/company(+narrow) + after-news-dark + after-overview-dark-compact（暗色 × compact 密度）。夹具与生产页面共用同一布局组件，数据为离线静态夹具。
- 涨跌/影响/调查/AI 状态全部符号+文字+颜色三重编码；指数条、异动行、日历行、公司头提供 accessibilityLabel 组合读法。
- 全部新 UI 使用 StockMonitorDesign 角色/间距/宽度 token；无新增 `.font(.system(size:)`、`Color(`、`.font(.caption2)`（R1 门禁计数下降：numeric padding 54→37，caption2 12→11）。
- 无新增动画；报告目录跳转使用可中断 `StockMonitorMotion.responsive`；Reduce Motion/Transparency、Increase Contrast 继续由共享 surface 与系统控件承担。

## 数据与性能边界

- 新增请求：公司组每窗口一次 `GET /api/dashboard`（只读、已有契约）；总览新增一次 `GET /api/investigations?limit=12`（非致命，失败仅缺调查徽标）。无轮询、无 LLM、无付费调用、无新缓存。
- 排序/筛选/搜索/目录解析均为客户端纯函数，不产生请求；报告复制走系统剪贴板。
- 未复制或重算任何服务端模型；估值/财报/SEC 数值全部来自既有响应。

## 自动化结果

- StockMonitorFeatures：81 passed（新增 R4 逻辑 16 项 + 视觉矩阵 1 项；R1/R2/R3 像素基线全部继续通过）。
- StockMonitorDesign：6 passed；StockMonitorCore：36 passed。
- `swift build --package-path apple -c release --arch arm64`：passed。
- swiftformat：0 diff；swiftlint（目标文件）：0 error。
- `verify-readability-r4.sh`：passed，并串行保留 R1/R2/R3 source gates。
- 快照基线经视觉模型抽查（总览四状态卡/对齐指数条、公司头/分组指标/财报矩阵）确认布局正确。

## 问题清单

- P0：0。
- P1：0（本 Goal 范围）。
- P2：原生 XCTest runtime 仍受本机 Accessibility automation 状态阻塞（R3 已记录，未变）；UI 测试 target 编译通过。
- P3：Watchlist 表头点击排序受 SwiftUI Optional keypath 列限制，改用显式排序控件（能力等价，交互成本略高）。
