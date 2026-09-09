# macOS 可读性 Goal R3 验收记录

日期：2026-09-09
范围：R3.0 Sidebar/Command-K/工作区、R3.1 页面 anatomy、R3.2 adaptive layout/密度与恢复
边界：计划文档只读；未修改服务端算法、数据、权限、IBKR 代理或 PAPER 边界。

## R3.0 — 导航与工作区

- 保留 7 个业务 section，改为系统 `DisclosureGroup`；默认展开概览与当前 section。
- 新增收藏、最近使用、section 内用户排序，并将收藏、最近、顺序、展开状态、sidebar、inspector 与 density 写入本地恢复状态。
- 管理员和高风险路由带独立盾牌提示，不与日常入口使用同一视觉权重；服务端权限校验保持不变。
- Command-K 按功能、股票、会话、报告分组。打开搜索时并发读取 dashboard 自选证券、最近 40 份报告与会话列表；任何索引失败都只降级对应搜索，不阻塞功能/股票代码导航。
- Company、Portfolio、AI、Crypto 有常驻二级导航；证券与研究窗口标题包含实际 symbol/identifier。

## R3.1 — 页面 anatomy

- `RoutePageAnatomy` 为 31/31 路由固定 navigation title、对象身份、primary summary、primary action、provenance 与 workspace。
- `PageHeader`、`SectionHeader` 使用 `ViewThatFits`，窄窗口把操作移到标题下方；标题只在 page header 中形成主强调，来源/限制保持在末端。
- `PageScaffold` 保持正文最大宽度，宽表/图表仍可使用 wide content；页面边距由 density 与宽度共同决定。
- 5 秒扫描 fixture 的顺序为：对象 → 结论 → 核心指标 → 主内容/动作 → 来源与限制。

## R3.2 — Adaptive 与密度

- 明确 breakpoints：`narrow < 760`、`standard 760..<1280`、`wide >= 1280`。
- narrow 隐藏 sidebar 主列，metric 最多两列；`FinancialTable` 降级为逐项纵向比较，Timeline 标题/时间可纵向换行，不缩小正文保列。
- compact 只改变 row、control、padding 和 section rhythm；正文语义字号不变。
- “恢复默认布局”恢复 comfortable density、sidebar、inspector、收藏、最近、排序和 section 展开状态。

## Visual / route checklist

Before/After 在 `apple/Tests/VisualBaselines/R3`：

- Before：31 个平级入口、重复标题。
- After：narrow light comfortable、standard light comfortable、wide dark compact、Command-K dark。
- 正常、empty、partial/stale、error、permission、loading 继续由 R1 的 31 路由 + 7 状态矩阵覆盖；R2 语义页面基线同步更新并重新比较。
- 长中文、长英文、国际代码、负号/大金额/多币种沿用 R1/R2 fixture；R3 另加入超长公司名称与来源/时间条。

## Accessibility / appearance / motion

- 所有导航和搜索项保留系统 Button/List/DisclosureGroup/toolbar 行为，Command-K 是 Scene command；关键目标提供 accessibility label/identifier。
- light/dark、compact/comfortable、narrow/standard/wide 均进入确定性像素矩阵。
- 本 Goal 没有新增导航动画；Reduce Motion 无空间位移。搜索浮层使用系统 material，正文保持 content layer；Reduce Transparency 继续由共享 surface 处理。
- 原生 UI test target 的 R3 路径已编译。运行时 XCTest 能启动 app 和建立 automation session，但本机 Accessibility hierarchy 无法发现应用窗口/语义元素，测试在首个 `waitForExistence` 失败；按既有系统阻塞记录，确定性 off-screen pixel comparison 是当前执行门禁。

## 数据与性能边界

- 导航、收藏、最近、排序、宽度和 density 都是本地状态，不增加后台请求。
- 只有用户打开 Command-K 时并发增加 3 个已有 authenticated GET（dashboard、reports、conversations）；关闭/普通导航不轮询，也不触发 provider、LLM 或付费调用。
- 没有复制或重算服务端值；搜索结果只携带 route、symbol、标题和上下文。
- 无持续动画、计时器或新缓存；Release arm64 构建没有出现新的编译警告，现有 GoalM4 optional interpolation 警告保持不变。

## 自动化结果

- StockMonitorCore：36 passed。
- StockMonitorDesign：6 passed。
- StockMonitorFeatures：64 passed，包含 R1/R2/R3 pixel comparisons。
- `swift build --package-path apple -c release --arch arm64`：passed。
- unsigned Xcode `build-for-testing`：passed（UI test target included）。
- targeted SwiftFormat：0；targeted SwiftLint：0。
- `verify-readability-r3.sh`：passed，并串行保留 R1/R2 source gates。
- `git diff --check`：passed。

## 问题清单

- P0：0。
- P1：0（本 Goal 范围）。
- P2：原生 XCTest runtime 受当前 macOS Accessibility automation 状态阻塞；UI 测试代码与 target 均已编译，恢复系统能力后可直接重跑。
- P3：无。
