# 更新日志

本文件从 v0.9.1 开始维护；更早版本请查看 [Git 标签](https://github.com/Uhmmu/stock-monitor/tags) 与提交记录。

## v0.9.2（2026-09-03）

### 亮点

- **加密资产研究与量化工作台**：新增统一加密资产身份、Binance 公共行情与 K 线管线、衍生品和基本面研究、技术分析、回测、信号及内部模拟交易页面；`/crypto` 现为独立入口。
- **安全的模拟执行链路**：新增隔离的 execution agent 与 TEST-only 控制面，带幂等、审计、风险限制和故障关闭；公开产品仅暴露内部 PAPER 模拟执行，不启用真实下单。
- **IBKR Gateway 持仓同步**：Client Portal Gateway 与 Flex 双来源独立展示；Gateway 手动同步成为当前数量的最高优先级来源，并修复 `1578` 与 `1578.T` 的已知映射。
- **实时行情自愈**：完善流式行情连接监督、陈旧检测和恢复逻辑，降低服务存活但报价停止刷新的风险。
- **macOS 原生开发环境**：本地开发改用 Homebrew、Python 3.12、Node 22、PostgreSQL 和 Redis 原生进程，提供 `make native-*`、安全本地 Celery beat、空库迁移引导和本机 Playwright 支持；Docker Compose 继续作为 Linux/VPS 生产路径。

### 变更范围

- 新增迁移 `0066_crypto_identity_assets` 至 `0080_internal_paper_engine`，覆盖加密资产、行情、研究、IBKR Gateway、量化回测/信号/模拟账本和 TEST-only 执行记录。
- 新增加密资产搜索、行情概览、UTC 多周期图表、衍生品研究、回测与模拟交易界面。
- 新增 Binance/CoinGecko/DefiLlama 固定夹具、行情精度回放、策略和执行安全测试。
- 修正 execution agent 协议兼容、部署主机记录、SQLite lease 更新和控制 URL 示例。
- 更新生产域名、IBKR 历史交接说明及本地开发文档，避免沿用过时主机和路径。

### 升级注意

- 升级前备份 PostgreSQL；本版本包含迁移 `0066`–`0080`。
- 后端、前端、Celery worker、`market-stream` 和队列配置均有变化，生产部署应按实际 Compose 拓扑重建相关服务。
- 量化信号、模拟交易、公共加密行情与 execution control 均由显式环境开关控制；默认保持关闭或暂停，不应在升级时自动启用。
- macOS 原生配置仅用于本地开发，不替代生产 Docker/Compose，也不会改变 IBKR 必须经 VPS `socks5h` 代理且 fail-closed 的约束。

## v0.9.1（2026-08-24）

### 亮点

- **Apple 设计成为桌面 Web 默认体验**：全新视觉体系（`apple-design.css`）、可折叠侧栏（悬停展开快捷入口）、导航气泡切换与图标过渡动效；经典布局仍可通过路由切换。
- **新增 Beta 市场工作台**：独立 `frontend-beta` 服务与 `/beta/` 入口，命令条式预览布局，与主前端共用同一套代码与 API。
- **管理员用户管理**：注册申请需管理员审核激活后才能登录；管理设置面板新增用户管理表格，支持创建账号、审核、备注与删除（迁移 `0065_admin_user_management`）。
- **客户端查询缓存与刷新进度条**：板块数据持久化到浏览器 IndexedDB，冷加载（刷新页面、再次进入）先渲染上次数据，后台刷新完成后自动切换为新数据（stale-while-revalidate）。缓存按登录用户隔离，退出登录或切换账号时整份清空；最长保留 7 天，超过 24MB 时从最旧开始淘汰。任何请求持续超过 800ms 时，页面顶部出现流动进度条，加载完成即消失，常规轮询不会打扰。

### 变更列表

| 提交 | 内容 |
|---|---|
| `48714d3` | Apple 设计前端体验（新视觉体系与路由） |
| `f085e46` | 可折叠 Apple 侧栏导航 |
| `33bbe14` | 折叠态侧栏细节重构 |
| `3f6c1db` | 导航气泡切换动效 |
| `e623c05` | 导航项过渡动画 |
| `e588194` | Apple 设计设为默认前端 |
| `3ac3b0d` | Beta 市场工作台（`/beta/` 服务与网关路由） |
| `4be4f67` | 管理员用户管理（审核/创建/删除/备注，迁移 0065） |
| `ccf5754` | 客户端查询缓存与全局刷新进度条 |

### 升级注意

- 含数据库迁移 `0065_admin_user_management`，API 启动时自动执行；升级前照常备份数据库。
- 本版本涉及前端与后端变更：`frontend`、`frontend-beta` 及共享 `backend` 上下文的 `api`、`worker`、`sec-worker`、`beat`、`market-stream` 均需重建。
- 客户端缓存无需配置；如需彻底清空，在浏览器中清除站点数据即可（或在应用内退出登录自动清空）。
