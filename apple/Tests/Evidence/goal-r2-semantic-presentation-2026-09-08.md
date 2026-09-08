# Goal R2 semantic presentation evidence

Date: 2026-09-08
Plan: `docs/plans/macos-native-readability-improvement-plan.md` Goal R2（R2.0/R2.1/R2.2）

## Scope

- R2.0 typed presentation model：新增 `SemanticPresentation`（WorkspacePresentation/PresentationList/Section/Field）、`SemanticPresentationBuilder`、`GoalM5PresentationCatalog`；全部 86 个 M5 端点登记 semantic key（`WorkspaceEndpoint.semantic`，穿透 `resolving()`），服务层继续容忍 additive JSON。
- R2.1 字段目录与证据分层：`SemanticFieldCatalog` + `SemanticDomainFields`（18 个业务域、约 700 条中文字段登记：名称/单位/精度/解释/业务排序）+ `SemanticEvidenceView`（首层证据 → 更多字段 → 诊断折叠）；替换 M4 全部 26 处 `JSONEvidenceView` 主路径调用（组件保留为显式 Debug fallback，0 处使用）。
- R2.2 状态/动作/反馈：`ResourcePresentationState` 新增 `partial`；`WorkspaceJobPhase`/`JobStateBadge`（queued/running/completed/failed/canceled，映射服务端 20+ 种状态串）；`MutationFeedbackPhase`/`MutationFeedbackView`（pending/confirmed/failed + 服务端回读）；`WorkspaceAction.requiresConfirmation` 只对不可逆或产生费用的操作确认（运行发现、生成信号、重建持仓、修复对账、重置）。
- 技术文案清理：工作台 chrome 不再显示 `Phase M5.x`；查询参数默认折叠且使用中文标签（标的 ID/运行 ID…）；AI Chat 消息改为按角色分层的 typed 渲染（用户/助手/系统/工具徽标 + 正文 + 模型/引用/Token/时间 + 富内容折叠），深度搜索档位中文化。
- raw JSON 退出主路径：`JSONDocumentView` 更名 `RawJSONDiagnosticsView`，只存在于"诊断 · 原始响应"折叠区（默认关闭）与测试 Before 快照。

## R2.0 exit assessment

- 非调试主页面不再出现 `#1` GroupBox / 英文 snake_case label / 递归 JSON 树：`verify-readability-r2.sh` 源级 gate（`JSONEvidenceView(value:` = 0、`JSONDocumentView` = 0、`Phase \(descriptor.phase` = 0、semantic keys ≥ 80）。
- contract fixtures 覆盖 presentation mapping：`SemanticPresentationTests` 对 portfolio summary/positions、trade-logs、admin users（裸数组）、quant backtests / paper orders（items 分页）、crypto latest（字符串数字）、ibkr status（分区）、discovery latest（嵌套 run/result + limitations + job phase）、paper account（账户边界）断言中文列头、行标识、诊断区与"无 snake_case 泄漏"。
- AI Chat 消息列表不再渲染递归 JSON 树（`AIConversationMessagesView`）。

## R2.1 exit assessment

- 每个域的字段目录有中文名称、单位与解释，同域不重名、按业务排序（测试 `everyDomainCatalogHasEntriesAndBusinessOrder`）。
- compare、options、SEC、ownership 页面在 R1 审计中即无 `JSONEvidenceView` 调用点（已全部是 typed 中文表格，`OptionsViews`/`GoalM4OwnershipViews` 不引用 `JSONValue`），因此字段目录按实际 raw-JSON 存在的域建立：valuation（含 Graham）、financials（三表科目）、macro、mood、industry、technical（camelCase）、congress、journal 与全部 M5 域。
- 证据三层（primary 8 项 → 更多字段 → 诊断）由测试锁定（macro/technical fixtures）；正常/缺失样本：null → "数据不足"、`not_applicable` → "不适用"、`provider_failed` → "数据源失败"、`stale` → "旧数据"、`not_collected` → "尚未采集"，同级 status/stale 提示参与推断（测试 `missingDataKeepsDistinctSemantics`）。
- 技术分析域 camelCase（generatedAt/rsi14/weeklyTrend）单独登记。

## R2.2 exit assessment

- 状态统一：读取失败保留 last-good 并在内容顶部明示"以下仍显示上次有效数据"；刷新指示器位于 page chrome（不遮挡首屏）；空态使用每个端点的中文空态提示。
- 任务状态由 `WorkspaceJobPhase` 统一映射（pending/QUEUED → 已排队；importing/reconciling/rebuilding → 运行中；success/partial_failed → 已完成；…），徽标含非颜色编码（图标 + 文案）。
- mutation：明确动词 + pending/confirmed/failed + 回读后展示最新状态；只有不可逆或产生费用的操作确认（测试 `onlyIrreversibleOrCostlyActionsRequireConfirmation`）。

## Verification

- `StockMonitorCore` 36 passed；`StockMonitorDesign` 5 passed；`StockMonitorFeatures` 59 passed（新增 17 项：contract fixtures 10、目录/证据 4、状态 2、确认语义 1）。
- swiftformat --lint 0 违例；`verify-readability-baseline.sh`（R1 guard）与新增 `verify-readability-r2.sh` 均通过；SwiftLint 当前基线见下方最终验收说明。
- 根包 `swift build -c release --arch arm64` 与 Xcode workspace Release 构建通过。
- 视觉证据：`Tests/VisualBaselines/R2/` 8 张 Before/After 截图（同一 fixture、1180×820、light/dark × comfortable/compact），由确定性离屏渲染生成并字节级比对；Before（snake_case JSON 树）与 After（中文语义页）经视觉检查确认渲染正常、主内容区无 snake_case、无重叠/截断。
- 性能：展示层为纯客户端映射，无新增网络请求/定时器；R1 的 31 路由快照回归全部通过（无视觉漂移引入）。
- Web/服务端核对：字段名与后端路由逐一比对（portfolio/performance.py、ibkr/formal_routes.py、discovery/service.py、crypto/latest.py、quant paper/signals、ai conversations schemas 等），未改变任何请求路径与请求体；`allReadEndpointsRemainAuthenticatedAPIPaths` 等既有契约测试保持通过。

### 2026-09-09 最终验收修正

- 人工检查多币种组合 Before/After 图时发现，本币现价曾错误沿用响应级基础币种；展示构建器现按行读取 `currency`/`quote_currency`，仅 `base_currency_*` 字段继续使用组合基础币种。
- contract fixture 新增双重断言：`1578.T.current_price` 显示 `JPY`，`base_currency_market_value` 显示 `USD`；light/comfortable 与 dark/compact 两张组合基线已重新生成并人工复核。
- 修正后重新通过 Core 36、Design 5、Features 59、R1/R2 source gate、arm64 Release build 与 unsigned Xcode `build-for-testing`。
- SwiftFormat 全量 lint 通过。SwiftLint 全量仍报告此前就存在的文件长度/旧格式债务；本次币种修正未扩大规则范围，R2 退出条件不以清理全仓旧 lint 债务为前提。

## 更新后的严重度清单

- M5 十二个 raw-JSON 路由（holdings/ai/decisions/discovery/journal/settings/administration/ibkr/ibkr-admin/crypto/quant/paper）的 R1 基线 P0 在 R2 层面关闭：主路径为语义页面 + 折叠诊断。`baselineSeverity` 保留为历史基线记录。
- 遗留（属后续 Goal，非 R2 范围）：
  - P1：`instrument_id` 等参数仍需手填数字 ID，R5.2 要求实体选择器（R2 已降级为折叠中文参数，不再常驻英文 snake_case）。
  - P1：动态列表为自绘 Grid（排序/列宽/窄窗 fallback 归 R6.0 表格专项）。
  - P2：AI Chat 完整 bubble/citation 抽屉重设计归 R5.0；R2 仅完成 typed 消息渲染。
  - P2：全路由真实账户截图矩阵与 VoiceOver 走查归 R6.2。
