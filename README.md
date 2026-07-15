# 股票监控台

本地与单机 VPS 使用同一套 Docker Compose：FastAPI、Celery Worker/Beat、PostgreSQL、Redis、React/Nginx，以及提供 HTTPS 和 Basic Auth 的 Caddy。

## 本地启动

1. 安装 Docker Engine（Linux）或 Docker Desktop，并确认 `docker compose version` 可用。
2. 复制配置：`cp .env.example .env`。
3. 修改 `.env`：至少设置强数据库密码，并填写 `TAVILY_API_KEY`、`OPENAI_API_KEY`、`OPENAI_BASE_URL`。自定义 OpenAI-compatible 服务时，三个 `MODEL_*` 必须使用服务商实际支持的模型 ID。
4. 设置 `SITE_DOMAIN=localhost`、`AUTH_USER`，并使用 `docker run --rm caddy:2-alpine caddy hash-password --plaintext '你的密码'` 生成 `AUTH_PASSWORD_HASH`。写入 `.env` 时将哈希中的每个 `$` 写成 `$$`，避免 Compose 将其解释为变量。
5. 执行 `make up`，然后访问 `https://localhost`。本地自动签发的证书不受浏览器信任，需要手动确认。
6. 查看任务日志：`make logs`。停止：`make down`。

未配置搜索或模型密钥时，行情与自选股仍可使用；依赖这些服务的报告无法生成。

## VPS 迁移

1. 在 VPS 安装 Docker 与 Compose 插件，将整个 `stock-monitor` 目录复制到服务器，例如 `/opt/stock-monitor`。
2. 复制并编辑 `.env`，不要将真实 `.env` 提交到代码仓库；建议执行 `chmod 600 .env`。
3. 将 `SITE_DOMAIN` 设为已解析到 VPS 的域名；国际化域名建议填写 Punycode。设置 `AUTH_USER` 和经过转义的 `AUTH_PASSWORD_HASH`。
4. 在防火墙和云安全组开放 TCP 80、443；Caddy 会自动申请并续签 HTTPS 证书。
5. 执行 `docker compose config --quiet` 检查配置，再执行 `make up`。Compose 会自动运行数据库迁移，持久数据位于命名卷中。
6. 使用 `docker compose ps` 和 `docker compose logs --tail=200` 检查服务状态。

## 备份与恢复

- 备份：`make backup`
- 恢复：`make restore FILE=stock-monitor-YYYY-MM-DD-HHMM.sql.gz`
- 升级前应先备份数据库，再更新代码并执行 `make up`。

## 当前监控逻辑

- 美股常规交易时段每 5 分钟采集一次启用股票的行情。
- 按 20 分钟、1 小时和当日变化阈值触发警报；阈值可在网页中配置。
- 异动触发后每 20 分钟通过 Tavily 搜索一次，持续 2 小时，最终使用重要模型生成调查报告。
- 交易日盘前和盘后分别生成新闻报告，同一股票、日期、报告类型只生成一次。
- `yfinance` 是非官方低频数据源，适合当前原型，不适合作为交易执行或严格实时行情依据。

## 新闻中心与财报

- `finnhub-mcp` 作为内部服务运行（`cfdude/mcp-finnhub`，Streamable HTTP，端口 8125），不对公网开放；后端通过 `FINNHUB_MCP_URL` 内部访问。
- 默认每 15 分钟为启用股票聚合 Finnhub 与 Tavily 新闻，按来源 ID、规范化 URL 与标题指纹跨来源去重后入库，并追加到 `archive/<股票>/news/<日期>/raw.jsonl`。原始新闻永不被 AI 改写。
- 每日由 Luna（`MODEL_MEDIUM`）对当天原始新闻做去重筛选与事实归纳，生成 `daily.md` 定档；异动、盘前盘后、财报报告会引用当日定档。
- 新闻界面按股票切换，展示原始标题、来源、时间、图片与链接，并提供单条“AI 总结”按钮（Luna，结果按输入哈希幂等复用）。
- 财报区通过 Finnhub 同步每只股票最近四个已公布季度，缺失指标显示“数据不足”，超过四季度的受管记录与归档文件会被清理。
- 需在 `.env` 填写 `FINNHUB_API_KEY`；`ARCHIVE_DIR` 归档目录挂载到 `archive_data` 卷，随备份一并保留。

## 验证

- Python 语法：`python3 -m compileall -q backend/app backend/tests`
- 后端测试：`docker compose run --rm api pytest`
- 前端构建：`docker compose build frontend`
- 健康检查：`curl -u "$AUTH_USER:你的密码" https://$SITE_DOMAIN/api/health`
- Finnhub MCP：`docker compose exec api python -c "from app.services.finnhub_mcp import fetch_company_news; print(len(fetch_company_news('AAPL', 3)))"`；确认 8125 端口未映射到公网。
- 新闻与财报接口：`curl -u "$AUTH_USER:你的密码" "https://$SITE_DOMAIN/api/news?ticker=AAPL"` 与 `.../api/financials?ticker=AAPL`。
- 归档落盘：`docker compose exec worker ls /data/archive/AAPL/news`。
