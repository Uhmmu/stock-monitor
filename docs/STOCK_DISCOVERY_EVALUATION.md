# 机会发现成本与模型验证

## 当前架构

- 低成本模式调用独立 Search API，并由项目 important tier（默认 `gpt-5.6-sol`）分析。
- 深度 Agent 模式保留 `finance_search`、可选 `web_search` 与 `openai/gpt-5.4`。
- Search 查询覆盖新闻、公司事件、行业趋势、市场情绪、宏观变化与 Why now。
- 价格、估值、市值和财报数字只使用项目已持久化的 Yahoo、FMP、Finnhub 与 SEC 数据。
- 两种模式都会读取新闻中心保存的标题、供应商概要和 AI 概要。
- 普通测试全部使用 mock，不会调用真实 API。

## 显式真实评估

真实评估仍属于手动付费操作，必须同时提供 `--live` 与服务端评估开关：

```bash
export PERPLEXITY_API_KEY='your-key'
export OPENAI_API_KEY='your-key'
export PERPLEXITY_LIVE_EVALUATION_ENABLED=true
export PERPLEXITY_EVALUATION_BUDGET_USD=0.10
PYTHONPATH=backend python backend/scripts/evaluate_stock_discovery.py \
  --live \
  --repetitions 2 \
  --budget-usd 0.10 \
  --output stock-discovery-evaluation.json
```

报告记录 Search 成本、Perplexity 模型 token（必须为 0）、本地分析模型、token 数、
结构校验结果与候选代码。脚本不会比较或调用任何 Perplexity Agent 模型。
