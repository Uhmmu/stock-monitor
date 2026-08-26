# IBKR 只读集成测试

## 架构与边界

该模块是管理员专用的隔离测试入口：浏览器只访问 stock-monitor 的鉴权 API；FastAPI 只访问 VPS 本机受控 relay 后的 Client Portal Gateway；Gateway 与 Flex 的 IBKR 外联必须经宿主机 `socks5h://127.0.0.1:10808` 进入 Xray/VLESS TCP/NTT 出口。代理不可用即失败，不允许 direct fallback。官方 Gateway 因固定 wildcard 监听而被放入独立 Linux network namespace，宿主机只暴露 `127.0.0.1:5000` relay；5000 与 10808 均不得暴露公网。

本阶段只有健康、认证、session、账户、摘要、余额、持仓、未成交订单和当日成交的读取能力。没有下单、改单、撤单、订单确认回复或自动交易代码。正式持仓模块不依赖本测试模块。

选择 Client Portal Gateway 是因为个人 IBKR Pro 账户可通过官方 SRP 登录和 IB Key 建立 Web API 会话。stock-monitor 仅把自动登录用于只读测试模块，不启用交易接口。

## Gateway 与 Flex 双源同步

IBKR 板块（前端 `/ibkr`）有两个互相独立的手动同步来源，绝不互相 fallback 或隐式调用：

### Client Portal Gateway —— 当前仓位（current / near-real-time）

- 用途：读取当前账户与当前仓位，写入数据库 current-state 表 `ibkr_cp_positions`（迁移 `0074_ibkr_cp_positions`，含运行记录表 `ibkr_cp_sync_runs`）。
- 管线：`POST /api/ibkr/client-portal/sync` → Celery 任务 `sync_ibkr_client_portal_positions`（`ibkr` 队列，仅手动触发，无 beat 计划）→ `cp_sync.py`：认证检查 → 账户选择 → 分页拉取 `/portfolio/{accountId}/positions/{page}` → 规范化 → 单数据库事务内 upsert 当前仓位并把缺失仓位标记 `removed`（软删除保留历史）。
- 读取端点：`GET /api/ibkr/client-portal/status`（可选 `?live=1` 附带 Gateway 连通性探测）、`GET /api/ibkr/client-portal/positions`、`GET /api/ibkr/client-portal/sync/{id}`。
- 空仓位安全：只有会话已认证、账户经过 `/portfolio/accounts` 校验、请求成功且 IBKR 明确返回空集合时，才把当前仓位清空；任何上游失败都保留原有数据库仓位。
- 多账户：单账户自动选用；多账户必须在服务端设置 `IBKR_CP_ACCOUNT_ID`，否则同步显式失败，不做猜测。
- Gateway 同步不写 `portfolio_positions`，不传播 Portfolio 权威；Flex 仍是组合持仓权威来源。

### Flex —— 报表/历史/日终（reporting / statement / historical / EOD）

- 既有 `POST /api/ibkr/sync` 流程保持不变；数量、成本、币种等组合权威仍由 Flex 对账传播。

两者目前均为用户手动触发。

## 代理约定（所有 IBKR 连接）

所有 IBKR HTTP 客户端统一由 `backend/app/integrations/ibkr/http_transport.py` 构造：

- 任何非环回 IBKR 主机（Flex Web Service 及后续新增端点）强制 `socks5h` 代理（Xray/VLESS），代理缺失或不可用即 fail-closed，禁止 direct fallback；`trust_env` 恒为 false。
- 唯一例外是本机 Client Portal Gateway origin（`127.0.0.1` / `localhost` / `host.docker.internal` 的 5000 端口）：该跳不出 VPS，且 Gateway 进程自身被隔离在 `stock-monitor-ibkr` network namespace 中、其唯一出站路径就是 namespace SOCKS relay 到宿主机 `127.0.0.1:10808`；把容器域名的解析交给 socks5h 在技术上不可行。这与 headless Chromium 登录既有的 `--proxy-bypass-list` 先例一致。

## VPS 安装

使用 [deploy/ibkr/README.md](../../deploy/ibkr/README.md) 的脚本。安装程序在 Debian/Ubuntu 上检查 Java 17、unzip、curl、ca-certificates 和 proxychains4，验证下载文件为 ZIP，已有安装会先整体备份，且不修改防火墙或 Gateway 用户配置。专用 proxychains 配置使用 `strict_chain` 与 `proxy_dns`，确保域名经代理解析并在 10808 失效时 fail-closed。

```bash
sudo useradd --system --home /opt/stock-monitor/ibkr --shell /usr/sbin/nologin stock-monitor
sudo ./deploy/ibkr/install-client-portal-gateway.sh
sudo install -m 0644 deploy/ibkr/stock-monitor-ibkr-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stock-monitor-ibkr-network
sudo systemctl enable --now stock-monitor-ibkr-namespace-relays
sudo systemctl enable --now stock-monitor-ibkr-gateway
sudo systemctl enable --now stock-monitor-ibkr-docker-relays
sudo systemctl status stock-monitor-ibkr-gateway
journalctl -u stock-monitor-ibkr-gateway -f
```

上线或真实测试前必须运行 `deploy/ibkr/check-client-portal-gateway.sh`，并人工确认经代理的公网出口仍为预期的日本东京 AS2914 NTT。脚本不读取或输出 VLESS 订阅、UUID、密钥。

若 FastAPI 保持在普通 Docker bridge 中，容器内的 `127.0.0.1:5000` 不是宿主机。本项目提供 `stock-monitor-ibkr-docker-relays.service`：它动态读取 `stock-monitor_default` 的私有 bridge gateway，只在该私有地址绑定 5000/10808，再转发到宿主机 loopback。生产将 `IBKR_DOCKER_BRIDGE_GATEWAY` 设置为这个经过验证的私有地址，Compose 将 `host.docker.internal` 精确映射到它，绝不绑定 `0.0.0.0`。对应配置为 `IBKR_CP_BASE_URL=https://host.docker.internal:5000/v1/api` 与 `IBKR_PROXY_URL=socks5h://host.docker.internal:10808`。

## 浏览器登录和 IB Key

在个人电脑运行：

```bash
ssh -L 5000:127.0.0.1:5000 <user>@<vps-host>
```

在管理页输入用户名和密码，点击“登录并等待手机批准”。后端用无界面 Chromium 打开 VPS 本机 Gateway、代填并执行官方 SRP 登录；出现 IB Key 推送后在手机批准即可。勾选保存时，凭据使用 `IBKR_CREDENTIAL_ENCRYPTION_KEY` 加密后写入持久 Redis，页面只返回掩码；后续可点击“使用已保存凭据登录”。密码不会写入应用日志或 API 响应。

## 配置

复制 `.env.example` 中 `IBKR_*` 字段。`IBKR_CP_BASE_URL` 只允许本机 HTTPS 地址；`IBKR_CP_VERIFY_SSL=false` 仅作用于专用 Gateway client。Flex Token 和 Query ID 可留空，且永不返回前端。`IBKR_PROXY_URL` 必须保持 `socks5h://127.0.0.1:10808`。

Flex Query 需先在 Client Portal 手工创建，再填写 Token 与 Query ID。实现使用官方 v3 两阶段流程：`/SendRequest` 获取 ReferenceCode，随后有限轮询 `/GetStatement`。缺失 section 返回空数组与 warning，未知 XML 属性原样保留。Activity Statement 通常每日收盘后才更新，无需高频运行。

生产 Flex Query 的真实区块、字段和正式前端建议见 [IBKR Flex 真实返回总结](./ibkr-flex-live-summary.md)。

正式账户页 `/ibkr` 现支持只读手动 Flex 同步和账户分析。同步成功的定义包含 typed 导入、Portfolio 权威对账、现金传播、派生分析重建、缓存代次更新和 AI 上下文可见；任何阶段失败都不会返回 completed。数量与成本以 IBKR 为准，当前价格以项目行情系统为准。完整状态机、数据模型、API 与恢复方式见上述真实返回总结的“账户分析层与全项目权威同步”章节。

## 管理员测试顺序

1. 确认 Xray active、10808 loopback 监听、代理出口正确。
2. 启动 Gateway，打开 `/admin/integrations/ibkr`。
3. 手动点击“检查 Gateway”。
4. 建立 SSH 隧道并打开 `https://localhost:5000`。
5. 在 stock-monitor 管理页输入账号密码，点击登录并用手机完成 IB Key；需要时可加密保存。
6. 返回测试页，点击“检查认证状态”。
7. 仅在明确理解 competing session 风险后，手动确认初始化 Brokerage Session。初始化固定 `compete=false`。
8. 读取账户列表并显式选择账户，然后读取摘要、持仓、orders 或 trades。
9. 检查结构化结果、已清理的原始响应和请求信息。
10. 配置 Flex 后手动测试和运行 Query。

## 实际采用的 Client Portal endpoint

- `GET /sso/validate`
- `POST /iserver/auth/status`
- `POST /iserver/auth/ssodh/init`，固定 `publish=true, compete=false`
- `POST /tickle`
- `GET /portfolio/accounts`
- `GET /portfolio/{accountId}/summary`
- `GET /portfolio/{accountId}/ledger`
- `GET /portfolio/{accountId}/positions/{pageId}`
- `GET /iserver/account/orders`
- `GET /iserver/account/trades?days=1`

这些路径存在硬编码只读 allowlist；API 不接收任意 URL。账户路径使用的 ID 必须再次出现在当前 Gateway `/portfolio/accounts` 响应中。

## 常见错误

- `GATEWAY_UNAVAILABLE`：检查 systemd、`127.0.0.1:5000` 与容器到宿主机的安全通路。
- `AUTHENTICATION_REQUIRED`：重新建立隧道，在官方页面登录并完成 IB Key。
- `BROKERAGE_SESSION_NOT_CONNECTED`：手动检查后再决定是否初始化。
- `COMPETING_SESSION`：其他 IBKR 客户端占用会话；系统不会抢占，由用户自行处理或使用第二用户名。
- `FLEX_NOT_CONFIGURED`：填写后端环境变量并重新创建相关后端容器。
- 代理失败：检查 Xray 与 10808；禁止临时改成直连来“排障”。

## 手工验证与限制

自动化测试不使用真实账户。生产镜像会验证 Chromium 能加载 Gateway 登录控件；真实凭据和 IB Key 仍由管理员在页面触发。测试页原始响应只对项目管理员显示，Cookie、Authorization、Token、Query ID 等字段在返回前清理。
