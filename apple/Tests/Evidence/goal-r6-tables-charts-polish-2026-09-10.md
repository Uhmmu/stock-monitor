# macOS 可读性 Goal R6 验收记录

日期：2026-09-10
范围：R6.0 Table / Chart / 数据比较专项；R6.1 材质、动效与微交互 polish；R6.2 Accessibility 与全量验收
边界：计划文档只读；未改变服务端算法、数据通路、权限、IBKR 代理约束或内部 PAPER 边界。本 Goal 只关闭跨域一致性、表格/图表、动效、辅助功能和验收问题，不补功能。

## R6.0 — Table、Chart 与数据比较专项

- 建立全 App 表格审计目录 `R6TableAuditCatalog`（`ReadabilityR6.swift`）：20 张原生 Table 逐张登记列角色（主列/比较列/元数据/操作列）、默认排序、对齐、最小/理想列宽、窄窗策略、选择能力与行数上限；条目 id 即视图上的 accessibilityIdentifier，测试强制「每表恰一个主列 + 数值列右对齐 tabular + 有列宽 + 有窄窗策略」。
- 15 张 M3/M4 时代的临时表接入原生 `Table(_:sortOrder:)` 排序：13F（市值降序）、内部人/国会/SEC 文件/图表事件（日期降序）、SEC 财务（财年降序）、期权链（行权价升序）、行业概览（脉冲降序）、Mood 任务（创建降序）、价格提醒（目标价升序）、估值指标（可选按数值/同行中位）；估值指标默认保持业务语义分组顺序。
- 新增 Design 表格基础组件（`TableFoundation.swift`）：`NumericTableCell`（右对齐 + tabular figures + 缺失值「数据不足」降级 + a11y 合并）、`MainTableCell`（身份 + 副标题）、`TableTruncationFooter`（前 N 条/数据截至的统一可恢复脚注）、`TableColumnSpec` / `TableColumnRole` / `TableNarrowStrategy` 规范类型。所有升级表格补齐列宽、alternating rows 与表格级 accessibilityIdentifier。
- 图表统一 chrome：新增 `ChartPanel`（title、单位、区间控件、来源、数据截至、显式不可用态）与 `ChartProvenanceFooter`；K 线主图、宏观序列、ATM IV、对比 indexed、历史 P/E、收益率曲线六类生产图表全部经 ChartPanel 或等价 chrome 呈现（`R6ChartSurfaceCatalog` 九要素门禁：unit/source/asOf/legend/tooltip/dataSummary/unavailable/palette/nonColorEncoding）。
- `LineSeriesChart` 升级：系列颜色由 `StockMonitorChartPalette` 按序号分配（不再散落 accent/indigo 硬编码）、每系列形状标记（circle/square/triangle/diamond/cross/asterisk）+ 线型（前两支实线、其后虚线族）双编码；十字光标 tooltip（`SeriesValueTooltip`：日期 + 各系列最近值）；图例改为「形状 + 颜色 + 名称」；X 轴统一 year-month 格式；默认内嵌「图表数据摘要（非视觉访问）」表（`ChartSeriesSummaryTable`：每序列最新/最低/最高/观测区间）。
- 宏观收益率曲线从裸 Chart 重写为共享 `YieldCurveChart`：palette 双编码、期限 tooltip、图例含观察日、数据摘要表、a11y 标签。
- 图表等价文本：`LineSeriesSummaryBuilder` 纯函数构建序列摘要；K 线图沿用 R4 的最近 30 根 OHLCV 摘要披露。
- 降采样可解释性验证：`CandlePreparation.downsample` 保持在 ≤420 渲染预算内且始终保留首尾关键点（新增守卫测试）。

## R6.1 — Material、motion 与微交互 polish

- 材质分层审计 `MaterialPolicyCatalog`：sidebar/toolbar 由系统控件提供材质；内容层（正文卡片、图表、数据表）零系统材质，靠留白/分隔线/surface 建层级；transient 层唯一自定义材质是 K 线十字光标 tooltip（regularMaterial）。测试硬门禁：内容层登记任何系统材质即失败。
- 正文层 GroupBox 复核：业务主路径无 GroupBox；仅 R5 raw-JSON 诊断 fallback（默认关闭）与测试 fixture 保留。
- 动效克制：新增 `StockMonitorMotionAudit`——5 条高频路径（表格排序、路由切换、Command-K、列宽拖动、watchlist 选中/刷新）零装饰动画；3 个有动画表面（密度切换、DisclosureGroup、Design Lab 拖拽）全部使用可中断 spring token 并声明 Reduce Motion 降级；`StockMonitorMotion.stateChange`（0.12s cross-fade）作为 Reduce Motion 下的状态切换标准。
- 微交互：`subtleHoverHighlight()`（仅亮度提升 5%，无位移缩放）应用于对比页证券卡、国会代码/人物按钮；`ImmediatePressButtonStyle()` 提供即时按压反馈。表格行、快捷键与高频导航不引入 scale 或慢动画。

## R6.2 — Accessibility 与整体验收

- `R6AccessibilityCatalog`：31 个路由逐页登记根 accessibilityIdentifier、首屏 VoiceOver 阅读顺序锚点（navigation.title → page.header → 路由根 → 域内关键区域 → metadata.strip）、全键盘路径说明。测试保证 31/31 覆盖且锚点序列稳定。
- `R6IssueLedger`：R1 审计问题的 P0–P3 关闭台账。18 项问题中 17 项 resolved（含 R6 关闭的表格排序、图表 chrome、非颜色编码、材质分层、hover 反馈、截断脚注）；1 项 P3 accepted（对比矩阵极窄窗口依赖横向滚动，已记录后续方向）。P0/P1 open = 0。
- `R6AcceptanceCatalog`：31 路由 × 五层 parity（data/task/readability/accessibility/visual）全部 verified；3 个路由带备注（compare 窄窗策略、crypto/quant/paper 的 R5 语义工作区与 PAPER 边界、moodLab 截断脚注）。
- 视觉矩阵（`ReadabilityR6SnapshotTests`，69 张确定性像素基线）：7 张图表/表格 golden（chart-before、charts-after light/dark、charts narrow、table standard/narrow/compact，before/after 共享同一数据源）+ 62 张路由矩阵（31 路由 dark-standard-normal + 31 路由按序号轮换 empty-narrow-light / stale-wide-dark / error-standard-light）。
- VoiceOver / Full Keyboard Access / Increase Contrast / Reduce Motion / Reduce Transparency 抽查记录：阅读顺序锚点与键盘路径集中在目录中逐页可查；对比度由 Design surface 的 `colorSchemeContrast == .increased` 分隔线增强分支 + 系统动态颜色承担；Reduce Motion/Transparency 由系统控件与 surface 完全不透明降级承担。离屏渲染无法注入只读的 `colorSchemeContrast` 环境值（实测 accessibilityHighContrastAqua 外观渲染与浅色逐字节一致），因此高对比快照不作为证据，相关行为记录在组件代码分支与人工抽查说明。
- Web/Mac 五层 parity 沿用 GoalM6 parity 基线与本 Goal 的 `R6AcceptanceCatalog`；真实账户 golden flow 的运行时验证保持 M6 既有记录（本机 Accessibility automation 系统阻塞未解除，见 R3/R5 记录），不以「数据已显示」作为任何可读性问题的豁免。

## 数据与性能边界

- 未新增网络请求、轮询、LLM 调用或数据通路变化；图表与摘要全部由已加载的客户端数据纯函数计算。
- 排序为 `KeyPathComparator` 原生 Table 排序（系统实现，零自定义动画）；行数上限继续由服务端分页 + 客户端前缀截断（120/150 条）承担并统一脚注。
- 图表数据准备（解析/归一/降采样）保持纯函数且有界（渲染预算 420 点）；R6 未改数据通路，启动/帧/内存沿用 M6 性能门禁基线，无新增 Instruments 回归项。

## 自动化结果

- StockMonitorCore：36 passed。
- StockMonitorDesign：10 passed（新增 R6 token 4 项：表格角色、palette 非颜色编码、材质分层、动效审计）。
- StockMonitorFeatures：101 passed（其中 R6 专项 10 项逻辑测试 + 69 场景像素比较）。
- `swift build --package-path apple -c release --arch arm64`：passed。
- `xcodebuild -project apple/StockMonitor.xcodeproj -scheme StockMonitorMac CODE_SIGNING_ALLOWED=NO build-for-testing`：TEST BUILD SUCCEEDED。
- `verify-readability-r6.sh`：passed，串行保留 baseline/R2–R5 全部 source gates（69 张基线计数校验包含在内）。
- 门禁适配说明：图表图例标记使用语义 `caption2.weight(.bold)`（不引入自定义字号）；特性层系列颜色统一经 `StockMonitorChartPalette.chartTint` 入口（不在页面层散落 Color 字面量），baseline 计数门禁保持不变。

## 问题清单

- P0：0。P1：0。
- P2：0（R6 范围内新增问题）。
- P3：1 项 accepted——对比矩阵在极窄窗口依赖横向滚动 + 首列固定；后续可在下一轮提供 inspector 详情降级。
- 遗留（非本 Goal 引入）：原生 XCTest runtime UI 测试仍受本机 Accessibility automation 系统状态阻塞（R3 起记录）；UI test target 持续保持 build-for-testing 通过，确定性像素门禁为当前视觉回归权威。
