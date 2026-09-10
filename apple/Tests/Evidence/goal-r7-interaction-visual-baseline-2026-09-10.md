# macOS 操作与视觉升级 R7 基线

日期：2026-09-10  
环境：macOS 26.5，SwiftUI 原生客户端，31 个生产路由。  
范围：操作状态、刷新语义、详情层级、网页风格视觉样板与 Liquid Glass 使用边界。

## 证据边界

- 代码与确定性测试证据：路由入口、主操作、上下文、状态保留、详情模式和失败恢复已由 `R7InteractionAuditCatalog` 覆盖 31/31。
- 既有离屏视觉证据：R1–R6 路由矩阵只证明固定场景渲染稳定，不能证明真实窗口中的焦点、滚动、Sheet 返回和动画手感。
- 真实运行证据：本 Goal 完成前必须在安装候选中逐项记录；若 macOS Accessibility 自动化仍被系统阻塞，保留为明确限制，不以 source gate 替代。

## 可复现问题基线

1. 从自选股切换到新闻再返回，自选股分组、排序和选择仅保存在临时 View 状态，路由重新创建后会丢失。
2. 新闻中心重新进入后，市场/个股范围、证券和主题筛选恢复不统一，选中的文章也无法返回原上下文。
3. 工具栏“刷新”通过重建整个路由触发，文案没有说明只刷新当前页，也没有承诺保留筛选和选择。
4. 公司研究使用共享证券，但非公司路由缺少统一的 per-route 选择存储，详情返回行为由各页面各自决定。
5. R6 页面视觉清晰但偏平；现有网页的浅灰画布、蓝色主操作、柔和大圆角卡片层次尚未形成原生共享组件。

## 设计取舍

- 网页端提供信息层次与品牌氛围；macOS 端继续使用系统控件、系统动态色、键盘路径和窗口模型。
- Liquid Glass 只用于 sidebar、toolbar、popover、sheet 和轻量浮动筛选 chrome。正文、表格与图表保持稳定内容表面。
- 动效默认可中断且克制；排序、路由、行情刷新和键盘导航保持即时。Reduce Motion 使用短 cross-fade，Reduce Transparency 使用实色表面。

## 分批验收

- R7.1：31 路由操作目录、每路由状态模型、当前页刷新语义、焦点返回。
- R7.2：总览、持仓、新闻、设置四类样板及网页风格共享组件。
- R7.3：三批路由推广、动效与辅助功能检查、全测试和本机应用替换。

## 实施与自动化结果

- 31/31 路由已接入统一窗口级 `RouteInteractionState`；自选股、新闻、公司研究、期权、AI 会话、交易日志及所有服务工作区已保存并恢复其关键上下文。
- 工具栏刷新改为“刷新当前页面”，重建数据模型但保留导航模型中的筛选和选择；服务工作区继续以 last-good payload 覆盖刷新与失败过程。
- AppShell 为全部生产路由注入网页风格环境：冷灰/淡蓝原生动态画布、蓝色主操作、连续圆角内容卡片、系统 toolbar/sidebar/filter chrome。Reduce Transparency 与 Increase Contrast 降级仍由共享组件承担。
- R7 视觉基线 10 张：总览、持仓、新闻、设置四类代表页面各含浅色/深色标准窗口，另含持仓窄窗紧凑与新闻宽窗深色。人工检查通过；`1578.T` 为 JPY，组合汇总为 USD。
- StockMonitorCore：36 passed；StockMonitorDesign：11 passed；StockMonitorFeatures：106 passed。
- arm64 Release Swift build：passed；R1–R7 串行门禁：passed。
- 已知编译警告仅来自既有 `GoalM4Models.swift` 两处 optional 字符串插值，本轮未改该模型。

## 本机安装验收

- Xcode Release 候选使用生产配置 `https://jialenb.com`，环境标记为 `production`。
- 候选与安装后的应用均通过 `verify-app-security.sh`：arm64、Hardened Runtime、App Sandbox、网络客户端权限和 Privacy Manifest 均符合门禁。
- 原应用已完整备份到 `apple/DerivedData/install-backups/20260910-144655-interaction-r7/`，再以同卷切换方式替换 `/Applications/Stock Monitor.app`。
- 候选与已安装可执行文件 SHA-256 均为 `4332f307ff6e461f62f33fb27212cfb3729929cc8eec795c890f637c9efecd45`。
- 已安装应用成功启动，进程路径来自 `/Applications/Stock Monitor.app/Contents/MacOS/Stock Monitor`；生产 `/api/client-capabilities` 返回 HTTP 200。
- 当前自动化环境仍不能驱动原生 macOS Accessibility 逐页操作，因此焦点返回、真实滚动位置和动画手感保留为人工运行验收项；未用离屏快照代替这部分结论。
