# macOS 可读性 Goal R5 验收记录

日期：2026-09-10
范围：R5.0 AI Chat / Deep Search / 记忆 / 机会发现；R5.1 Portfolio / 分析 / Journal / IBKR；R5.2 Crypto / Quant / 内部 PAPER / Settings / Admin
边界：计划文档只读；未改变服务端算法、权限、IBKR 代理约束或内部 PAPER 边界。Mac 继续只通过认证 API/SSE 读取及回写服务端权威状态。

## R5.0 — AI、记忆与机会发现

- AI 对话改为角色化消息气泡：用户消息靠右，助手/工具/系统消息靠左；正文限制在舒适阅读宽度，Markdown 以标题、段落和列表分块显示，长回答不再铺满窗口。
- composer 固定在底部，输入与发送保持主路径；模型和搜索模式收入来源明确的系统 popover。Deep Search 的高预算等级仍在发送前确认，普通对话不受打断。
- stream 中的部分回答始终保留；当前进度与工具活动使用可折叠 timeline。消息内引用、工具活动、代码/丰富内容各自分层，可复制并能打开有效 URL。
- 机会发现新增“原始候选 → 本地验证 → 组合过滤 → 最终分组”漏斗与成本/状态/候选数量首屏摘要；运行、历史、候选详情和设置改为任务分组，不再是平铺 API 列表。
- 记忆与投资决策按“记忆 / 决策 / 设置”分组；服务端新增字段仍只进入默认关闭的诊断区。

## R5.1 — Portfolio、分析、Journal 与 IBKR

- Portfolio 首屏先显示总市值、浮动盈亏、收益、风险和覆盖率。持仓使用原生 `Table`，证券价格明确使用行级本币，市值/盈亏/权重使用响应基础币种。
- `valuation_available=false` 时，缺失币种（夹具覆盖 `1578.T` / JPY）紧邻首屏显示；缺 FX 的基础币种市值、盈亏和权重保持“— / 数据不足”，不按 1:1 猜测或进入汇总。
- 分析历史与任务详情通过实体选择器进入；任务详情将提交、开始、完成/失败组织为 timeline，参数、结果、警告、限制和来源仍由语义 presentation 展开。
- Journal 使用 master list + detail 编辑。交易事实与复盘正文分区；IBKR 同步事实只读，用户仅编辑主观复盘；保存走 `PATCH /api/trade-logs/{id}` 并回读，AI 总结因可能产生模型费用而显式确认。
- IBKR 按“账户概览 → 绩效与交易 → 现金、费用与 FX → 数据与同步”组织。完整代理/凭据安全说明只在状态页保留，其余页面使用短边界提示；Mac 不接触凭据或代理配置。

## R5.2 — Crypto、Quant、PAPER、Settings 与 Admin

- 删除普通用户路径中的手填 `instrument_id / asset_id / job_id / run_id / candidate_id / history_id`。详情入口只有在从服务端实体列表解析出可读名称后才出现；ID 仅作为传输值。
- Crypto 以标的选择器驱动“市场概览 / 行情与图表 / 基本面与衍生品 / 新闻与研究”分区；窄窗口指标自动降为两列，无占位 ID 输入。
- Quant 显示“定义 → 特征 → 信号 → 回测 → PAPER 部署”研究流程，并突出当前阶段；回测批次由实体选择器进入。
- PAPER 首屏明确“内部 PAPER · 不连接真实交易”，账户、订单、成交、账本、运行和对账按任务分组；危险修复/重置操作独立放入菜单的“危险操作”区域并保持确认。
- Settings 使用 macOS grouped Form 区分客户端外观、服务端配置、数据源与 AI；Admin/执行控制按角色与风险分区，普通用户仍由目录和服务端双重门控。

## Route / State checklist

- R5 路由：AI、记忆与决策、机会发现、持仓、Journal、IBKR、IBKR 管理、Crypto、Quant、PAPER、Settings、Admin，共 12 个复杂工作区全部接入 R5 任务结构。
- normal：11 张 R5 确定性像素基线覆盖 Before、AI、Discovery、Portfolio、Journal、IBKR、Crypto narrow、Quant compact、PAPER dark、Settings、Admin。
- empty / partial / stale / loading / error / permission denied：继续由 R1 的 31 路由 × 7 状态矩阵，以及 `EmptyState`、last-good + `InlineError`、刷新 chrome、管理员目录过滤共同覆盖。
- 长中文、Markdown、代码、国际代码、多币种、负值、缺失值、暗色、compact 与 narrow 均进入 R5 夹具。

## Visual / Accessibility / Motion

- 视觉抽查确认 AI 阅读列与角色方向、Discovery 漏斗、Portfolio 本币/基础币列和缺口提示、Journal 时间线、Quant 流程在对应宽度无重叠或不可恢复截断。
- 新增的页面头、指标、表格、timeline、状态和边界提示均使用系统控件与 `StockMonitorDesign` token；关键状态同时使用图标、文字和颜色。
- 消息、来源、错误、限制、复盘与代码均可选择；实体选择器、消息、持仓表、流程和边界提示具有 accessibility label/identifier。
- 未增加装饰动画。popover、系统 Table/List、Reduce Motion、Reduce Transparency 与 Increase Contrast 行为由系统及既有 Design surface 继承。
- 原生 UI test target 已成功 `build-for-testing`；本机 Accessibility hierarchy 自动化仍沿用 R3 记录的系统阻塞，未把编译成功表述成 runtime UI test 通过。当前视觉门禁为确定性离屏像素比较。

## 数据与性能边界

- 不新增轮询、LLM 自动调用、直接数据库/Redis/供应商访问。AI 继续复用原 SSE；Journal 仅在用户保存或确认总结时写请求。
- 实体选择器读取既有列表端点；同一工作区中共享同一来源的字段（例如 Crypto instrument/asset）在一次加载中复用 payload，避免重复请求。
- 排序、分组、实体名称解析、漏斗指标和 timeline 全部为客户端纯函数；最多解析 100 个可选实体和 100 条 Journal 记录。

## 自动化结果

- StockMonitorCore：36 passed。
- StockMonitorDesign：6 passed。
- StockMonitorFeatures：91 passed（其中 R5 专项 10 项，包含 11 场景像素比较）。
- `swift build --package-path apple -c release --arch arm64`：passed；仅有 R4 既有 Optional interpolation warning。
- `xcodebuild ... CODE_SIGNING_ALLOWED=NO build-for-testing`：`TEST BUILD SUCCEEDED`。
- `verify-readability-r5.sh`：passed，并串行保留 R1–R4 source gates。
- SwiftFormat：0 diff；本 Goal 新增/重构 UI 文件的 line/statement/whitespace 定向 SwiftLint：0 error；`git diff --check`：passed。

## 问题清单

- P0：0（本 Goal 范围）。
- P1：0（本 Goal 范围）。
- P2：原生 XCTest runtime 仍受本机 Accessibility automation 状态阻塞；R5 UI test target 已编译，确定性像素门禁通过。
- P3：服务端若返回不含可读 identity 的孤立详情 ID，该详情不会出现在实体选择器中；这比回退为手填数字 ID 更安全，原始记录仍可在诊断区追溯。
