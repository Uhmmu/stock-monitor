# 机会发现模型评估

## 当前结论

生产默认模型为 `openai/gpt-5.4`。2026-07-24 在 VPS 上使用相同的真实组合上下文和受控 `$0.50` 预算完成一次对照评测：两个模型都通过 JSON Schema，但 `openai/gpt-5.4-mini` 的 6 个唯一候选全部与当前持仓重复，只有 12 个有效财务字段；`openai/gpt-5.4` 返回 8 个不与持仓重复的候选和 69 个有效财务字段，因此低成本模型没有达到可用门槛。

| 模型 | 成本 | 延迟 | finance / web | 候选 | 持仓重复 | 有效财务字段 | 引用 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `openai/gpt-5.4-mini` | `$0.05985` | 61.3 秒 | 2 / 0 | 7（1 重复） | 6 | 12 | 13 |
| `openai/gpt-5.4` | `$0.27611` | 120.1 秒 | 6 / 1 | 8 | 0 | 69 | 23 |

本次对照总成本为 `$0.33596`。单次评测不足以衡量跨批次稳定性，候选本身仍需在应用的本地过滤与人工研究环节复核；但就本次结果而言，强模型是满足组合去重和财务覆盖要求的最低可用选择。

## 已验证（不产生费用）

- Agent 请求使用 `POST /v1/agent` 的响应结构，不读取 Chat Completions `choices`。
- `finance_search` 始终启用；`web_search` 只由主发现批次设置控制。
- JSON Schema 已内联，所有模型输出通过 Pydantic `stock-discovery-schema-v0.4` 校验。
- 原始 `finance_results` / `search_results`、模型名、token、工具次数和 `usage.cost` 均保留。
- 普通测试全部 mock/解析固定响应，不会调用真实 API。

## 显式真实评估

在 API 容器或具有后端依赖的环境中运行：

```bash
export PERPLEXITY_API_KEY='your-key'
export PERPLEXITY_LIVE_EVALUATION_ENABLED=true
export PERPLEXITY_EVALUATION_BUDGET_USD=2
PYTHONPATH=backend python backend/scripts/evaluate_stock_discovery.py \
  --live \
  --models openai/gpt-5.4-mini openai/gpt-5.4 \
  --repetitions 2 \
  --budget-usd 2 \
  --output stock-discovery-evaluation.json
```

脚本通过现有用户与默认组合数据访问层构建上下文，不把真实持仓硬编码进测试源文件。每次请求前使用保守成本估算检查剩余测试预算，并在响应后记录 Perplexity 报告的精确成本。

## 预期成本边界

精确成本以 Agent API 响应为准。本次 `openai/gpt-5.4` 实测为 `$0.27611`；若后续运行成本相近，默认每 3 天一次约为每月 10–11 次，即约 `$2.76–$3.04/月`。代码仍会在请求前检查单次 `$1` 上限和 `$10` 月度硬预算，达到预算后停止自动调用。
